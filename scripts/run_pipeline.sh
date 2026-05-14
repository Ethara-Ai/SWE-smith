#!/bin/bash
# Usage: ./automation_script.sh <tasks.json> [--start-step N]
set -uo pipefail

MAX_PARALLEL=2
START_STEP=1
START_STEP_REPO_INDEX=-1
MODEL="bedrock/converse/arn:aws:bedrock:ap-south-1:426628337772:application-inference-profile/k15bb853wwgi"
MAX_BUGS=2000
N_WORKERS=1
VALIDATION_WORKERS=2
COMBINE_NUM_PATCHES=2
COMBINE_LIMIT_PER_FILE=15
COMBINE_MAX_COMBOS=100
COMBINE_MODULE_NUM_PATCHES=2
COMBINE_MODULE_LIMIT=20
COMBINE_MODULE_MAX_COMBOS=200
COMBINE_MODULE_DEPTH=2
LOG_DIR="logs"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

error_exit() {
    echo "[ERROR] $1" >&2
    exit 1
}

get_repo_id() {
    local repo="$1"
    local commit="$2"
    local owner="${repo%%/*}"
    local name="${repo##*/}"
    echo "${owner}__${name}.${commit:0:8}"
}

run_step() {
    local step_num="$1"
    local step_name="$2"
    local status_file="$3"
    local repo_id="$4"
    local start_step="$5"
    shift 5

    if [[ $step_num -lt $start_step ]]; then
        log "[$repo_id] Skipping Step ${step_num}: ${step_name} (start-step=$start_step)"
        echo "Step ${step_num}: ${step_name} - SKIPPED" >> "$status_file"
        return 0
    fi

    log "[$repo_id] === Step ${step_num}: ${step_name} ==="
    if "$@"; then
        echo "Step ${step_num}: ${step_name} - DONE" >> "$status_file"
        log "[$repo_id] Step ${step_num} completed successfully."
        return 0
    else
        echo "Step ${step_num}: ${step_name} - CRASHED (exit code: $?)" >> "$status_file"
        log "[$repo_id] Step ${step_num} FAILED."
        return 1
    fi
}

run_pipeline_for_repo() {
    local repo="$1"
    local commit="$2"
    local cwe_ids_json="$3"
    local start_step="${4:-1}"

    local repo_id
    repo_id=$(get_repo_id "$repo" "$commit")

    local log_file="${LOG_DIR}/pipeline_${repo_id}.log"
    local status_file="${SCRIPT_DIR}/pipeline_status_${repo_id}.log"
    mkdir -p "$LOG_DIR"

    {
        echo "=========================================="
        echo "Pipeline Status: ${repo_id}"
        echo "Repo: ${repo}"
        echo "Commit: ${commit}"
        echo "Start Step: ${start_step}"
        echo "Started: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "=========================================="
    } > "$status_file"

    log "[$repo_id] Starting pipeline from step $start_step (log: $log_file, status: $status_file)"

    {
        # --- Step 1: Generate CWE-specific single-site bugs ---
        if [[ $start_step -le 1 ]]; then
            local cwe_ids
            cwe_ids=$(echo "$cwe_ids_json" | jq -r '.[]')
            local step1_failed=0

            for cwe_id in $cwe_ids; do
                local config_file="configs/bug_gen/lm_modify_cwe${cwe_id}.yml"
                if [[ ! -f "$config_file" ]]; then
                    log "[$repo_id] WARNING: Config not found for CWE-${cwe_id} ($config_file), skipping."
                    continue
                fi

                log "[$repo_id] Running CWE-${cwe_id} bug generation..."
                if ! uv run python -m swesmith.bug_gen.llm.modify "$repo_id" \
                    --max_bugs "$MAX_BUGS" \
                    --model "$MODEL" \
                    --config_file "$config_file" \
                    --n_workers "$N_WORKERS"; then
                    step1_failed=1
                fi
                log "[$repo_id] CWE-${cwe_id} done."
            done

            if [[ $step1_failed -eq 1 ]]; then
                echo "Step 1: Generate CWE-specific single-site bugs - CRASHED" >> "$status_file"
                echo "=========================================="  >> "$status_file"
                echo "Pipeline ABORTED at Step 1 ($(date '+%Y-%m-%d %H:%M:%S'))" >> "$status_file"
                log "[$repo_id] Pipeline aborted at Step 1."
                return 1
            fi
            echo "Step 1: Generate CWE-specific single-site bugs - DONE" >> "$status_file"
        else
            log "[$repo_id] Skipping Step 1: Generate CWE-specific single-site bugs (start-step=$start_step)"
            echo "Step 1: Generate CWE-specific single-site bugs - SKIPPED" >> "$status_file"
        fi

        # --- Step 2: Collect single-site patches ---
        run_step 2 "Collect single-site patches" "$status_file" "$repo_id" "$start_step" \
            uv run python -m swesmith.bug_gen.collect_patches "logs/bug_gen/${repo_id}/" || {
            echo "Pipeline ABORTED at Step 2 ($(date '+%Y-%m-%d %H:%M:%S'))" >> "$status_file"
            return 1
        }

        # --- Step 3: Validate single-site patches ---
        run_step 3 "Validate single-site patches" "$status_file" "$repo_id" "$start_step" \
            uv run python -m swesmith.harness.valid "logs/bug_gen/${repo_id}_all_patches.json" --workers "$VALIDATION_WORKERS" || {
            echo "Pipeline ABORTED at Step 3 ($(date '+%Y-%m-%d %H:%M:%S'))" >> "$status_file"
            return 1
        }

        # --- Step 4: Gather validation results ---
        run_step 4 "Gather validation results" "$status_file" "$repo_id" "$start_step" \
            uv run python -m swesmith.harness.gather "logs/run_validation/${repo_id}" || {
            echo "Pipeline ABORTED at Step 4 ($(date '+%Y-%m-%d %H:%M:%S'))" >> "$status_file"
            return 1
        }

        # --- Step 5: Combine — same_file ---
        run_step 5 "Combine — same_file" "$status_file" "$repo_id" "$start_step" \
            uv run python -m swesmith.bug_gen.combine.same_file "logs/bug_gen/${repo_id}" \
            --num_patches "$COMBINE_NUM_PATCHES" \
            --limit_per_file "$COMBINE_LIMIT_PER_FILE" \
            --max_combos "$COMBINE_MAX_COMBOS" || {
            echo "Pipeline ABORTED at Step 5 ($(date '+%Y-%m-%d %H:%M:%S'))" >> "$status_file"
            return 1
        }

        # --- Step 6: Combine — same_module ---
        run_step 6 "Combine — same_module" "$status_file" "$repo_id" "$start_step" \
            uv run python -m swesmith.bug_gen.combine.same_module "logs/bug_gen/${repo_id}" \
            --num_patches "$COMBINE_MODULE_NUM_PATCHES" \
            --limit_per_module "$COMBINE_MODULE_LIMIT" \
            --max_combos "$COMBINE_MODULE_MAX_COMBOS" \
            --depth "$COMBINE_MODULE_DEPTH" || {
            echo "Pipeline ABORTED at Step 6 ($(date '+%Y-%m-%d %H:%M:%S'))" >> "$status_file"
            return 1
        }

        # --- Step 7: Collect combined patches ---
        run_step 7 "Collect combined patches" "$status_file" "$repo_id" "$start_step" \
            uv run python -m swesmith.bug_gen.collect_patches "logs/bug_gen/${repo_id}/" || {
            echo "Pipeline ABORTED at Step 7 ($(date '+%Y-%m-%d %H:%M:%S'))" >> "$status_file"
            return 1
        }

        # --- Step 8: Validate combined patches ---
        run_step 8 "Validate combined patches" "$status_file" "$repo_id" "$start_step" \
            uv run python -m swesmith.harness.valid "logs/bug_gen/${repo_id}_all_patches.json" --workers 8 || {
            echo "Pipeline ABORTED at Step 8 ($(date '+%Y-%m-%d %H:%M:%S'))" >> "$status_file"
            return 1
        }

        # --- Step 9: Gather final validation results ---
        run_step 9 "Gather final validation results" "$status_file" "$repo_id" "$start_step" \
            uv run python -m swesmith.harness.gather "logs/run_validation/${repo_id}" || {
            echo "Pipeline ABORTED at Step 9 ($(date '+%Y-%m-%d %H:%M:%S'))" >> "$status_file"
            return 1
        }

        # --- Step 10: Generate issue descriptions ---
        run_step 10 "Generate issue descriptions" "$status_file" "$repo_id" "$start_step" \
            uv run python -m swesmith.issue_gen.generate \
            --dataset_path "logs/task_insts/${repo_id}.json" \
            --config_file configs/issue_gen/ig_v2_bedrock.yaml || {
            echo "Pipeline ABORTED at Step 10 ($(date '+%Y-%m-%d %H:%M:%S'))" >> "$status_file"
            return 1
        }

        echo "==========================================" >> "$status_file"
        echo "Pipeline COMPLETED successfully ($(date '+%Y-%m-%d %H:%M:%S'))" >> "$status_file"
        log "[$repo_id] === Pipeline complete ==="

    } 2>&1 | tee "$log_file"
}

main() {
    local input_file=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --start-step)
                START_STEP="$2"
                shift 2
                ;;
            --repo-index)
                START_STEP_REPO_INDEX="$2"
                shift 2
                ;;
            -*)
                error_exit "Unknown option: $1"
                ;;
            *)
                input_file="$1"
                shift
                ;;
        esac
    done

    if [[ -z "$input_file" ]]; then
        error_exit "Usage: $0 <tasks.json> [--start-step N --repo-index I]"
    fi

    if [[ ! -f "$input_file" ]]; then
        error_exit "Input file not found: $input_file"
    fi

    if ! jq empty "$input_file" 2>/dev/null; then
        error_exit "Invalid JSON in $input_file"
    fi

    if [[ $START_STEP -lt 1 || $START_STEP -gt 10 ]]; then
        error_exit "--start-step must be between 1 and 10"
    fi

    local num_repos
    num_repos=$(jq length "$input_file")
    if [[ $START_STEP_REPO_INDEX -ne -1 ]]; then
        log "Found $num_repos repo(s) to process. Repo index $START_STEP_REPO_INDEX starts from step $START_STEP."
    else
        log "Found $num_repos repo(s) to process."
    fi

    local pids=()
    local failed=0

    for i in $(seq 0 $((num_repos - 1))); do
        local repo commit cwe_ids_json repo_start_step
        repo=$(jq -r ".[$i].repo" "$input_file")
        commit=$(jq -r ".[$i].commit" "$input_file")
        cwe_ids_json=$(jq -c ".[$i].cwe_ids" "$input_file")

        if [[ $i -eq $START_STEP_REPO_INDEX ]]; then
            repo_start_step=$START_STEP
        else
            repo_start_step=1
        fi

        log "Launching pipeline for $repo (commit: ${commit:0:8}, start-step: $repo_start_step) with CWEs: $cwe_ids_json"

        run_pipeline_for_repo "$repo" "$commit" "$cwe_ids_json" "$repo_start_step" &
        pids+=($!)

        # Throttle: only MAX_PARALLEL repos at a time
        if [[ ${#pids[@]} -ge $MAX_PARALLEL ]]; then
            for pid in "${pids[@]}"; do
                if ! wait "$pid"; then
                    log "WARNING: Process $pid failed."
                    ((failed++))
                fi
            done
            pids=()
        fi
    done

    for pid in "${pids[@]}"; do
        if ! wait "$pid"; then
            log "WARNING: Process $pid failed."
            ((failed++))
        fi
    done

    if [[ $failed -gt 0 ]]; then
        log "Pipeline finished with $failed failure(s) out of $num_repos repo(s)."
        exit 1
    else
        log "All $num_repos pipeline(s) completed successfully."
    fi
}

main "$@"

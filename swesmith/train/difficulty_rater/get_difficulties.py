"""
Purpose: Get difficulty ratings for different bugs

Usage:
python train/difficulty_rater/get_difficulties.py --dataset_path <dataset_path> --model <model>

Supports two modes:
1. --base_url <url>: Use an OpenAI-compatible API (e.g., sglang server)
2. --model <model>: Use any litellm-supported model (e.g., bedrock/converse/...)

NOTE:
For --base_url mode, make sure the sglang server for the difficulty rating model is running.
"""

import argparse
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import openai
from litellm import completion as litellm_completion
from swebench.harness.constants import KEY_INSTANCE_ID
from tqdm.auto import tqdm

from swesmith.train.difficulty_rater.create_datasets import (
    PROMPT_INSTANCE,
    PROMPT_SYSTEM,
)

DIFFICULTY_SCORE = {"medium": 5, "hard": 9, "easy": 1}


def process_instance_openai(client, model_name, instance):
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": PROMPT_SYSTEM},
                {"role": "user", "content": PROMPT_INSTANCE.format(**instance)},
            ],
            temperature=0,
            max_tokens=64,
        )
        difficulty = response.choices[0].message.content.strip().lower()
        return {
            KEY_INSTANCE_ID: instance[KEY_INSTANCE_ID],
            "difficulty": difficulty,
        }
    except Exception as e:
        print(f"Error processing {instance.get(KEY_INSTANCE_ID, '?')}: {e}")
        return None


def process_instance_litellm(model, instance):
    try:
        response = litellm_completion(
            model=model,
            messages=[
                {"role": "system", "content": PROMPT_SYSTEM},
                {"role": "user", "content": PROMPT_INSTANCE.format(**instance)},
            ],
            max_tokens=64,
            temperature=0,
        )
        difficulty = response.choices[0].message.content.strip().lower()
        return {
            KEY_INSTANCE_ID: instance[KEY_INSTANCE_ID],
            "difficulty": difficulty,
        }
    except Exception as e:
        print(f"Error processing {instance.get(KEY_INSTANCE_ID, '?')}: {e}")
        return None


def main(dataset_path, base_url=None, model=None, openai_model="gpt-4o", overwrite=False):
    if base_url and model:
        raise ValueError("Cannot provide both --base_url and --model")
    if not base_url and not model:
        raise ValueError("Must provide either --base_url or --model")

    client = None
    if base_url:
        client = openai.Client(base_url=f"{base_url}/v1", api_key="swesmith")

    if dataset_path.endswith(".json"):
        with open(dataset_path) as f:
            dataset = json.load(f)
    elif dataset_path.endswith(".jsonl"):
        with open(dataset_path) as f:
            dataset = [json.loads(line) for line in f.readlines()]
    else:
        raise ValueError(f"Unsupported file format: {dataset_path}")

    ext = ".json" if dataset_path.endswith(".json") else ".jsonl"
    difficulties_path = dataset_path.replace(ext, "_difficulties.jsonl")

    id_to_diff = {}
    completed = []
    mode = "w"
    if os.path.exists(difficulties_path) and not overwrite:
        with open(difficulties_path) as f:
            for line in f.readlines():
                line = json.loads(line)
                id_to_diff[line[KEY_INSTANCE_ID]] = line["difficulty"]
                completed.append(line[KEY_INSTANCE_ID])
        print(f"Skipping {len(completed)} completed instances")
        dataset = [x for x in dataset if x[KEY_INSTANCE_ID] not in completed]
        mode = "a"

    print(f"Rating {len(dataset)} instances (will write to {difficulties_path})")
    num_threads = 4
    with (
        ThreadPoolExecutor(max_workers=num_threads) as executor,
        open(difficulties_path, mode) as f,
    ):
        if base_url:
            future_to_instance = {
                executor.submit(process_instance_openai, client, openai_model, instance): instance
                for instance in dataset
            }
        else:
            future_to_instance = {
                executor.submit(process_instance_litellm, model, instance): instance
                for instance in dataset
            }

        for future in tqdm(as_completed(future_to_instance), total=len(dataset)):
            result = future.result()
            if result:
                f.write(json.dumps(result) + "\n")
                id_to_diff[result[KEY_INSTANCE_ID]] = result["difficulty"]

    print(f"Assessed difficulty for {len(id_to_diff)} instances")
    difficulty_dist = Counter(id_to_diff.values())
    print(difficulty_dist)
    for k in list(difficulty_dist.keys()):
        if k not in DIFFICULTY_SCORE:
            del difficulty_dist[k]
    if sum(difficulty_dist.values()) == 0:
        print("No valid difficulty ratings found")
        return
    difficulty_rating = round(
        sum(
            DIFFICULTY_SCORE[rating] * count
            for rating, count in difficulty_dist.items()
        )
        / sum(difficulty_dist.values()),
        3,
    )
    print(f"Difficulty score: {difficulty_rating}")
    print(f"Saved to {difficulties_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Get difficulty ratings for different bugs"
    )
    parser.add_argument(
        "--base_url",
        type=str,
        default=None,
        help="Base URL of an OpenAI-compatible API (e.g., sglang server)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="litellm model string (e.g., bedrock/converse/...)",
    )
    parser.add_argument(
        "--openai_model",
        type=str,
        default="gpt-4o",
        help="Model name to send in OpenAI API requests (default: gpt-4o)",
    )
    parser.add_argument(
        "--dataset_path", type=str, required=True, help="Path to the dataset"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Whether to overwrite existing difficulties",
    )
    args = parser.parse_args()
    main(**vars(args))

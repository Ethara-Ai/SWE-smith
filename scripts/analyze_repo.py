"""
Analyze a repository for SWE-smith bug generation.

This script performs the full analysis pipeline:
1. Checks if a profile exists → creates one if not
2. Counts code entity candidates
3. Identifies relevant CWE IDs via heuristics
4. Maps CWEs to target directories
5. Updates the profile with bug_gen_dirs_include

Usage:
    uv run python scripts/analyze_repo.py facebook/react
    uv run python scripts/analyze_repo.py facebook/react --commit abc123
    uv run python scripts/analyze_repo.py facebook/react --heuristic-only
    uv run python scripts/analyze_repo.py facebook/react --dry-run
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from swesmith.constants import CodeEntity, CodeProperty
from swesmith.profiles import registry
from swesmith.profiles.base import RepoProfile


LANGUAGE_EXTENSIONS = {
    "javascript": [".js", ".jsx", ".mjs", ".cjs"],
    "typescript": [".ts", ".tsx"],
    "python": [".py"],
    "java": [".java"],
    "go": [".go"],
    "rust": [".rs"],
    "c": [".c", ".h"],
    "cpp": [".cpp", ".cc", ".cxx", ".hpp", ".h"],
}

PROFILE_FILE_MAP = {
    "javascript": "javascript.py",
    "typescript": "typescript.py",
    "python": "python.py",
    "java": "java.py",
    "go": "golang.py",
    "rust": "rust.py",
    "c": "c.py",
    "cpp": "cpp.py",
}

CWE_HEURISTICS: dict[str, dict] = {
    "CWE-20": {
        "name": "Improper Input Validation",
        "tag_weights": {
            CodeProperty.HAS_IF: 1.0,
            CodeProperty.HAS_EXCEPTION: 2.0,
            CodeProperty.HAS_RETURN: 0.5,
        },
        "path_keywords": [
            "valid",
            "parse",
            "sanitiz",
            "input",
            "deserializ",
            "decode",
            "pipe",
            "guard",
            "filter",
            "check",
        ],
        "path_weight": 3.0,
    },
    "CWE-754": {
        "name": "Improper Check for Unusual or Exceptional Conditions",
        "tag_weights": {
            CodeProperty.HAS_EXCEPTION: 3.0,
            CodeProperty.HAS_IF: 0.5,
            CodeProperty.HAS_RETURN: 1.0,
        },
        "path_keywords": [
            "error",
            "exception",
            "handler",
            "middleware",
            "intercept",
            "fallback",
            "recovery",
        ],
        "path_weight": 3.0,
    },
    "CWE-670": {
        "name": "Always-Incorrect Control Flow Implementation",
        "tag_weights": {
            CodeProperty.HAS_LOOP: 1.5,
            CodeProperty.HAS_IF_ELSE: 2.0,
            CodeProperty.HAS_SWITCH: 2.5,
        },
        "path_keywords": [
            "router",
            "dispatch",
            "state",
            "workflow",
            "pipeline",
            "middleware",
            "handler",
            "controller",
            "reconciler",
            "scheduler",
            "fiber",
        ],
        "path_weight": 2.0,
    },
    "CWE-682": {
        "name": "Incorrect Calculation",
        "tag_weights": {
            CodeProperty.HAS_ARITHMETIC: 3.0,
            CodeProperty.HAS_BINARY_OP: 1.5,
        },
        "path_keywords": [
            "math",
            "calc",
            "compute",
            "score",
            "metric",
            "stat",
            "counter",
            "hash",
            "encode",
            "priority",
        ],
        "path_weight": 3.0,
    },
    "CWE-193": {
        "name": "Off-By-One Error",
        "tag_weights": {
            CodeProperty.HAS_OFF_BY_ONE: 5.0,
            CodeProperty.HAS_LIST_INDEXING: 2.0,
            CodeProperty.HAS_LOOP: 1.0,
        },
        "path_keywords": [
            "array",
            "buffer",
            "index",
            "slice",
            "range",
            "iterator",
            "cursor",
            "children",
        ],
        "path_weight": 2.0,
    },
    "CWE-835": {
        "name": "Loop with Unreachable Exit Condition (Infinite Loop)",
        "tag_weights": {CodeProperty.HAS_LOOP: 4.0},
        "path_keywords": [
            "loop",
            "iter",
            "stream",
            "poll",
            "watch",
            "retry",
            "worker",
            "scheduler",
        ],
        "path_weight": 2.5,
    },
    "CWE-1333": {
        "name": "Inefficient Regular Expression Complexity (ReDoS)",
        "tag_weights": {},
        "path_keywords": [
            "regex",
            "pattern",
            "match",
            "search",
            "highlight",
            "lexer",
            "tokeniz",
            "grammar",
        ],
        "path_weight": 5.0,
        "source_pattern": r"(?:new RegExp|/[^/]+/[gimsuvy]*|re\.compile|regex|regexp)",
    },
}

MIN_SCORE_THRESHOLD = 2.0
MIN_ENTITIES_PER_DIR = 3
MAX_DIRS_PER_CWE = 8


@dataclass
class RepoBuildInfo:
    """Build information detected from a cloned repository.

    Analyzes package.json, lockfiles, and config files to determine how to
    build and install dependencies for Docker image creation.
    """

    package_manager: str = "npm"
    pm_version: str | None = None
    has_build_script: bool = False
    has_lockfile: bool = False
    lockfile_name: str | None = None
    uses_corepack: bool = False
    node_version: str = "22"
    build_cmd: str | None = None
    extra_apt_deps: list[str] = field(default_factory=list)
    uses_workspaces: bool = False
    build_system: str | None = None
    cmake_test_option: str | None = None
    uses_wrapper: bool = False


def detect_repo_build_info(repo_root: str, language: str) -> RepoBuildInfo:
    """Analyze a cloned repo to detect package manager, build steps, and Docker requirements.

    Reads package.json, lockfiles, .nvmrc, and engine constraints to produce
    a RepoBuildInfo that drives Dockerfile generation. Falls back to sensible
    defaults when files are missing or unparseable.
    """
    info = RepoBuildInfo()

    if language in ("c", "cpp"):
        cmakelists = os.path.join(repo_root, "CMakeLists.txt")
        if os.path.exists(cmakelists):
            info.build_system = "cmake"
            try:
                with open(cmakelists, encoding="utf-8", errors="replace") as f:
                    cm = f.read()
                opt_match = re.search(
                    r"option\s*\(\s*([A-Z_][A-Z0-9_]*(?:TEST|TESTS|TESTING)[A-Z0-9_]*)\b",
                    cm,
                )
                if opt_match:
                    info.cmake_test_option = opt_match.group(1)
                elif re.search(r"\benable_testing\s*\(", cm) or re.search(
                    r"\bBUILD_TESTING\b", cm
                ):
                    info.cmake_test_option = "BUILD_TESTING"
            except OSError:
                pass
            return info

        autotools_markers = [
            "configure.ac",
            "configure.in",
            "configure",
            "Makefile.am",
            "autogen.sh",
        ]
        if any(os.path.exists(os.path.join(repo_root, m)) for m in autotools_markers):
            info.build_system = "autotools"
            return info

        if os.path.exists(os.path.join(repo_root, "Makefile")) or os.path.exists(
            os.path.join(repo_root, "makefile")
        ):
            info.build_system = "make"
            return info

        return info

    if language == "java":
        if os.path.exists(os.path.join(repo_root, "pom.xml")):
            info.build_system = "maven"
            if os.path.exists(os.path.join(repo_root, "mvnw")):
                info.uses_wrapper = True
            return info

        gradle_markers = [
            "build.gradle",
            "build.gradle.kts",
            "settings.gradle",
            "settings.gradle.kts",
        ]
        if any(os.path.exists(os.path.join(repo_root, m)) for m in gradle_markers):
            info.build_system = "gradle"
            if os.path.exists(os.path.join(repo_root, "gradlew")):
                info.uses_wrapper = True
            return info

        return info

    if language not in ("javascript", "typescript"):
        return info

    pkg_path = os.path.join(repo_root, "package.json")
    if not os.path.exists(pkg_path):
        return info

    try:
        with open(pkg_path) as f:
            pkg = json.load(f)
    except (json.JSONDecodeError, OSError):
        return info

    scripts = pkg.get("scripts", {})
    if "build" in scripts:
        info.has_build_script = True
        info.build_cmd = scripts["build"]

    pm_field = pkg.get("packageManager", "")
    if pm_field:
        info.uses_corepack = True
        if pm_field.startswith("yarn"):
            info.package_manager = "yarn"
            version_part = (
                pm_field.split("@")[-1].split("+")[0] if "@" in pm_field else None
            )
            if version_part:
                info.pm_version = version_part
        elif pm_field.startswith("pnpm"):
            info.package_manager = "pnpm"
            version_part = (
                pm_field.split("@")[-1].split("+")[0] if "@" in pm_field else None
            )
            if version_part:
                info.pm_version = version_part

    lockfiles = {
        "yarn.lock": "yarn",
        "pnpm-lock.yaml": "pnpm",
        "package-lock.json": "npm",
    }
    for lockfile, pm in lockfiles.items():
        if os.path.exists(os.path.join(repo_root, lockfile)):
            info.has_lockfile = True
            info.lockfile_name = lockfile
            if not info.uses_corepack:
                info.package_manager = pm
            break

    engines = pkg.get("engines", {})
    node_constraint = engines.get("node", "")
    if node_constraint:
        version_match = re.search(r"(\d+)", node_constraint)
        if version_match:
            major = int(version_match.group(1))
            if major >= 18:
                info.node_version = str(major)
            else:
                info.node_version = "18"

    nvmrc_path = os.path.join(repo_root, ".nvmrc")
    if os.path.exists(nvmrc_path):
        try:
            with open(nvmrc_path) as f:
                nv = f.read().strip().lstrip("v")
                major = nv.split(".")[0]
                if major.isdigit() and int(major) >= 16:
                    info.node_version = major
        except OSError:
            pass

    if pkg.get("workspaces"):
        info.uses_workspaces = True

    native_dep_keywords = ["node-gyp", "prebuild", "nan", "napi", "canvas", "sharp"]
    all_deps = {}
    all_deps.update(pkg.get("dependencies", {}))
    all_deps.update(pkg.get("devDependencies", {}))
    for dep_name in all_deps:
        if any(kw in dep_name for kw in native_dep_keywords):
            info.extra_apt_deps = ["build-essential", "python3"]
            break

    return info


def generate_dockerfile_lines(
    build_info: RepoBuildInfo,
    language: str,
) -> list[str]:
    """Generate Dockerfile lines based on detected build info.

    Follows conventions from existing SWE-smith profiles:
    - JS/TS: node:X-bullseye, git clone via mirror_url, npm/yarn/pnpm install
    - Go: golang base, go mod tidy
    - Rust: rust base, apt build-essential, cargo test || true
    - Python: handled separately by PythonProfile.build_image()
    """
    lines = []

    if language in ("javascript", "typescript"):
        lines.append(f'        return f"""FROM node:{build_info.node_version}-bullseye')
        apt_pkgs = ["git"] + build_info.extra_apt_deps
        lines.append(f"RUN apt update && apt install -y {' '.join(apt_pkgs)}")
        lines.append("RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}")
        lines.append("WORKDIR /{ENV_NAME}")

        if build_info.package_manager == "yarn":
            if build_info.uses_corepack:
                lines.append("RUN corepack enable && yarn install")
            else:
                if build_info.has_lockfile:
                    lines.append("RUN yarn install --frozen-lockfile")
                else:
                    lines.append("RUN yarn install")
        elif build_info.package_manager == "pnpm":
            pnpm_ver = build_info.pm_version or "latest"
            lines.append(f"RUN npm install -g pnpm@{pnpm_ver}")
            if build_info.has_build_script:
                lines.append("RUN pnpm install && pnpm run build")
            else:
                lines.append("RUN pnpm install")
        else:
            if build_info.has_lockfile:
                lines.append("RUN npm ci")
            else:
                lines.append("RUN npm install")

        if build_info.has_build_script and build_info.package_manager not in ("pnpm",):
            lines.append("RUN npm run build")

        lines.append('CMD [\\"/bin/bash\\"]')
        lines.append('"""')

    elif language == "go":
        lines.append('        return f"""FROM golang:1.24')
        lines.append("RUN git clone {self.mirror_url} /{ENV_NAME}")
        lines.append("WORKDIR /{ENV_NAME}")
        lines.append("RUN go mod tidy")
        lines.append("RUN go test -v -count=1 ./... || true")
        lines.append('CMD [\\"/bin/bash\\"]')
        lines.append('"""')

    elif language == "rust":
        lines.append('        return f"""FROM rust:latest')
        lines.append("ENV TZ=Etc/UTC")
        lines.append("")
        lines.append("RUN apt update && apt install -y wget git build-essential \\\\")
        lines.append("&& rm -rf /var/lib/apt/lists/*")
        lines.append("")
        lines.append("RUN git clone {self.mirror_url} /{ENV_NAME}")
        lines.append("WORKDIR /{ENV_NAME}")
        lines.append("RUN {self.test_cmd} || true")
        lines.append('CMD [\\"/bin/bash\\"]')
        lines.append('"""')

    elif language in ("c", "cpp"):
        if build_info.build_system == "cmake":
            test_opt = build_info.cmake_test_option or "BUILD_TESTING"
            lines.append('        return f"""FROM gcc:11')
            lines.append(
                "RUN apt-get update && apt-get install -y cmake git build-essential "
                "&& rm -rf /var/lib/apt/lists/*"
            )
            lines.append(
                "RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}"
            )
            lines.append("WORKDIR /{ENV_NAME}")
            lines.append("RUN git submodule update --init --recursive || true")
            lines.append(
                f"RUN mkdir build && cd build && "
                f"cmake -DCMAKE_BUILD_TYPE=Debug -D{test_opt}=ON .. && "
                "make -j$(nproc)"
            )
            lines.append('CMD [\\"/bin/bash\\"]')
            lines.append('"""')
        elif build_info.build_system == "autotools":
            lines.append('        return f"""FROM ubuntu:22.04')
            lines.append(
                "RUN apt-get update && apt-get install -y "
                "build-essential autoconf automake libtool pkg-config git "
                "&& rm -rf /var/lib/apt/lists/*"
            )
            lines.append(
                "RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}"
            )
            lines.append("WORKDIR /{ENV_NAME}")
            lines.append("RUN git submodule update --init --recursive || true")
            lines.append("RUN autoreconf -i && ./configure")
            lines.append("RUN make -j$(nproc)")
            lines.append('CMD [\\"/bin/bash\\"]')
            lines.append('"""')
        elif build_info.build_system == "make":
            lines.append('        return f"""FROM ubuntu:22.04')
            lines.append(
                "RUN apt-get update && apt-get install -y "
                "build-essential git "
                "&& rm -rf /var/lib/apt/lists/*"
            )
            lines.append(
                "RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}"
            )
            lines.append("WORKDIR /{ENV_NAME}")
            lines.append("RUN make -j$(nproc) || true")
            lines.append('CMD [\\"/bin/bash\\"]')
            lines.append('"""')
        else:
            lines.append('        return f"""FROM ubuntu:22.04')
            lines.append(
                "RUN apt-get update && apt-get install -y "
                "build-essential cmake autoconf automake libtool pkg-config git "
                "&& rm -rf /var/lib/apt/lists/*"
            )
            lines.append(
                "RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}"
            )
            lines.append("WORKDIR /{ENV_NAME}")
            lines.append('CMD [\\"/bin/bash\\"]')
            lines.append('"""')

    elif language == "java":
        if build_info.build_system == "maven":
            lines.append('        return f"""FROM maven:3.9.6-eclipse-temurin-11')
            lines.append(
                "RUN apt-get update && apt-get install -y git "
                "&& rm -rf /var/lib/apt/lists/*"
            )
            lines.append(
                "RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}"
            )
            lines.append("WORKDIR /{ENV_NAME}")
            lines.append('ENV JAVA_TOOL_OPTIONS=""')
            if build_info.uses_wrapper:
                lines.append("RUN ./mvnw clean install -B -q -DskipTests")
            else:
                lines.append("RUN mvn clean install -B -q -DskipTests")
            lines.append('CMD [\\"/bin/bash\\"]')
            lines.append('"""')
        elif build_info.build_system == "gradle":
            lines.append('        return f"""FROM eclipse-temurin:17-jdk')
            lines.append(
                "RUN apt-get update && apt-get install -y git "
                "&& rm -rf /var/lib/apt/lists/*"
            )
            lines.append(
                "RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}"
            )
            lines.append("WORKDIR /{ENV_NAME}")
            if build_info.uses_wrapper:
                lines.append(
                    "RUN ./gradlew --no-daemon --console=plain assemble -x test"
                )
            else:
                lines.append("RUN gradle --no-daemon --console=plain assemble -x test")
            lines.append('CMD [\\"/bin/bash\\"]')
            lines.append('"""')
        else:
            lines.append('        return f"""FROM eclipse-temurin:17-jdk')
            lines.append(
                "RUN apt-get update && apt-get install -y git maven "
                "&& rm -rf /var/lib/apt/lists/*"
            )
            lines.append(
                "RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}"
            )
            lines.append("WORKDIR /{ENV_NAME}")
            lines.append('CMD [\\"/bin/bash\\"]')
            lines.append('"""')

    return lines


def validate_dockerfile(build_info: RepoBuildInfo, language: str) -> list[str]:
    """Check generated Dockerfile for common issues against existing profile patterns.

    Returns a list of warnings. Empty list means all checks passed.
    """
    warnings = []

    if language in ("javascript", "typescript"):
        if build_info.package_manager == "yarn" and build_info.uses_corepack:
            major = (
                build_info.pm_version.split(".")[0] if build_info.pm_version else "0"
            )
            if major.isdigit() and int(major) >= 2:
                pass
            elif not build_info.pm_version:
                warnings.append(
                    "Corepack detected with yarn but no version found. "
                    "Verify yarn version compatibility."
                )

        if build_info.package_manager == "pnpm" and not build_info.pm_version:
            warnings.append(
                "pnpm detected but no version pinned. "
                "Consider setting a specific pnpm version (check packageManager field)."
            )

        if not build_info.has_lockfile:
            warnings.append(
                f"No lockfile found. Using '{build_info.package_manager} install' "
                "without lockfile may produce non-reproducible builds."
            )

        if build_info.extra_apt_deps:
            warnings.append(
                "Native dependencies detected (node-gyp/nan/napi). "
                "Added build-essential + python3. Verify if additional system libs needed."
            )

    if language == "python":
        warnings.append(
            "Python profiles use build_image() with conda environments instead of "
            "a simple Dockerfile property. Manual profile setup recommended."
        )

    if language in ("c", "cpp"):
        if build_info.build_system is None:
            warnings.append(
                "No C/C++ build system detected (no CMakeLists.txt, configure*, "
                "or Makefile). Generated Dockerfile will install build tools but "
                "will not compile the project. Manual profile setup recommended."
            )
        elif build_info.build_system == "cmake" and not build_info.cmake_test_option:
            warnings.append(
                "CMake project detected but no project-specific test option found. "
                "Falling back to -DBUILD_TESTING=ON; verify the project actually "
                "uses this flag (some projects use e.g. <NAME>_BUILD_TESTS)."
            )
        elif build_info.build_system == "make":
            warnings.append(
                "Plain Makefile detected (no CMake/autotools). 'make test' "
                "is assumed; adjust test_cmd if the project uses a different target."
            )

    if language == "java":
        if build_info.build_system is None:
            warnings.append(
                "No Java build system detected (no pom.xml or build.gradle*). "
                "Generated Dockerfile will install JDK and Maven but will not "
                "compile the project. Manual profile setup recommended."
            )
        elif build_info.build_system == "maven" and not build_info.uses_wrapper:
            warnings.append(
                "Maven project detected but no mvnw wrapper found. "
                "Image relies on system Maven; verify version compatibility."
            )
        elif build_info.build_system == "gradle" and not build_info.uses_wrapper:
            warnings.append(
                "Gradle project detected but no gradlew wrapper found. "
                "Image relies on system Gradle; verify version compatibility."
            )

    return warnings


EXCLUDED_DIR_PREFIXES = [
    "scripts/",
    "fixtures/",
    "docs/",
    "examples/",
    "benchmarks/",
    "test/",
    "tests/",
    "__tests__/",
    "spec/",
    "auxil/",
    "vendor/",
    "third_party/",
    "third-party/",
    "external/",
    "deps/",
    "contrib/",
    "submodules/",
]

EXCLUDED_DIR_PATTERNS = [
    "/npm/",
    "/npm",
    "/__mocks__/",
    "/__tests__/",
    "/__tests__",
    "/scripts/",
    "/scripts",
    "/fixtures/",
]


def get_latest_commit(owner: str, repo: str) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=1"
    headers = {"User-Agent": "swesmith-analyzer"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data[0]["sha"]


def detect_language(owner: str, repo: str) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}/languages"
    headers = {"User-Agent": "swesmith-analyzer"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        languages = json.loads(resp.read())

    lang_map = {
        "JavaScript": "javascript",
        "TypeScript": "typescript",
        "Python": "python",
        "Java": "java",
        "Go": "go",
        "Rust": "rust",
        "C": "c",
        "C++": "cpp",
    }

    for lang in languages:
        if lang in lang_map:
            return lang_map[lang]

    return "javascript"


def detect_test_command(
    owner: str, repo: str, commit: str, language: str = "javascript"
) -> str:
    if language in ("c", "cpp"):
        return "cd build && ctest --verbose --output-on-failure"
    if language == "java":
        return (
            "mvn test -B -T 1C -Dsurefire.useFile=false "
            "-Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
        )
    if language == "rust":
        return "cargo test --verbose"
    if language == "go":
        return "go test -v ./..."
    if language not in ("javascript", "typescript"):
        return ""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/package.json?ref={commit}"
    headers = {"User-Agent": "swesmith-analyzer"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        import base64

        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            content = base64.b64decode(data["content"]).decode()
            pkg = json.loads(content)
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                return "yarn test"
            return "npm test"
    except Exception:
        return "npm test"


def find_existing_profile(owner: str, repo: str) -> str | None:
    for key in registry.keys():
        parts = key.split("/")
        repo_part = parts[-1] if len(parts) > 1 else parts[0]
        name_parts = repo_part.split(".")
        if len(name_parts) >= 2:
            repo_id = name_parts[0]
            expected = f"{owner}__{repo}"
            if repo_id.lower() == expected.lower():
                return key
    return None


def generate_profile_class_name(repo: str, commit: str) -> str:
    """Generate a profile class name following existing conventions.

    Convention: capitalize repo name (strip special chars) + first 8 chars of commit.
    Examples: Nest3c6c2855, Commanderjs8247364d, Svelte d4c5a917
    """
    clean_name = re.sub(r"[^a-zA-Z0-9]", "", repo).capitalize()
    return f"{clean_name}{commit[:8]}"


def generate_profile_code(
    owner: str,
    repo: str,
    commit: str,
    language: str,
    test_cmd: str,
    bug_gen_dirs_include: dict[str, list[str]],
    build_info: RepoBuildInfo | None = None,
) -> str:
    profile_class_map = {
        "javascript": "JavaScriptProfile",
        "typescript": "TypeScriptProfile",
        "python": "PythonProfile",
        "java": "JavaProfile",
        "go": "GoProfile",
        "rust": "RustProfile",
        "c": "CProfile",
        "cpp": "CppProfile",
    }
    base_class = profile_class_map.get(language, "JavaScriptProfile")
    class_name = generate_profile_class_name(repo, commit)

    log_parser_map = {
        "javascript": "parse_log_jest",
        "typescript": "parse_log_jest",
        "python": "parse_log_pytest",
        "go": None,
        "rust": None,
        "java": "parse_log_maven_surefire",
        "c": "parse_log_ctest",
        "cpp": "parse_log_ctest",
    }
    log_parser_fn = log_parser_map.get(language)

    if build_info is None:
        build_info = RepoBuildInfo()

    if language in ("c", "cpp") and build_info.build_system == "autotools":
        log_parser_fn = "parse_log_autotools"

    if language == "java" and build_info.build_system == "gradle":
        log_parser_fn = "parse_log_gradle_junit_xml"

    lines = []
    lines.append("")
    lines.append("")
    lines.append("@dataclass")
    lines.append(f"class {class_name}({base_class}):")
    lines.append(f'    owner: str = "{owner}"')
    lines.append(f'    repo: str = "{repo}"')
    lines.append(f'    commit: str = "{commit}"')
    if test_cmd:
        lines.append(f'    test_cmd: str = "{test_cmd}"')

    if bug_gen_dirs_include:
        lines.append("    bug_gen_dirs_include: dict[str, list[str]] = field(")
        lines.append("        default_factory=lambda: {")
        for cwe_id, dirs in sorted(bug_gen_dirs_include.items()):
            lines.append(f'            "{cwe_id}": [')
            for d in dirs:
                lines.append(f'                "{d}",')
            lines.append("            ],")
        lines.append("        }")
        lines.append("    )")

    dockerfile_lines = generate_dockerfile_lines(build_info, language)
    if dockerfile_lines:
        lines.append("")
        lines.append("    @property")
        lines.append("    def dockerfile(self):")
        lines.extend(dockerfile_lines)

    if log_parser_fn:
        lines.append("")
        lines.append("    def log_parser(self, log: str) -> dict[str, str]:")
        lines.append(f"        return {log_parser_fn}(log)")

    return "\n".join(lines)


@dataclass
class DirProfile:
    path: str
    entities: list
    tag_counts: Counter
    total_entities: int
    has_regex: bool = False


def build_dir_profiles(entities: list, repo_root: str) -> dict[str, DirProfile]:
    dir_entities: dict[str, list] = defaultdict(list)

    for entity in entities:
        rel_path = os.path.relpath(entity.file_path, repo_root).replace(os.sep, "/")
        parts = rel_path.split("/")
        if len(parts) > 1:
            dir_key = "/".join(parts[: min(4, len(parts) - 1)])
        else:
            dir_key = "."
        dir_entities[dir_key].append(entity)

    profiles = {}
    for dir_path, ents in dir_entities.items():
        tag_counts = Counter()
        has_regex = False
        for ent in ents:
            for tag in ent._tags:
                tag_counts[tag] += 1
            if hasattr(ent, "src_code") and ent.src_code:
                src = (
                    ent.src_code if isinstance(ent.src_code, str) else str(ent.src_code)
                )
                if re.search(
                    r"(?:new RegExp|/[^/]+/[gimsuvy]*|re\.compile|regex|regexp)", src
                ):
                    has_regex = True

        profiles[dir_path] = DirProfile(
            path=dir_path,
            entities=ents,
            tag_counts=tag_counts,
            total_entities=len(ents),
            has_regex=has_regex,
        )

    return profiles


def score_directory_for_cwe(dir_profile: DirProfile, cwe_id: str) -> float:
    heuristic = CWE_HEURISTICS.get(cwe_id)
    if not heuristic:
        return 0.0

    score = 0.0

    tag_weights = heuristic.get("tag_weights", {})
    for tag, weight in tag_weights.items():
        count = dir_profile.tag_counts.get(tag, 0)
        if count > 0:
            density = count / max(dir_profile.total_entities, 1)
            score += min(density, 0.7) * weight

    path_lower = dir_profile.path.lower()
    path_keywords = heuristic.get("path_keywords", [])
    path_weight = heuristic.get("path_weight", 1.0)
    for keyword in path_keywords:
        if keyword in path_lower:
            score += path_weight
            break

    if cwe_id == "CWE-1333" and dir_profile.has_regex:
        score += 4.0

    return score


def select_relevant_cwes(entities: list, repo_root: str) -> list[str]:
    dir_profiles = build_dir_profiles(entities, repo_root)

    cwe_scores = {}
    for cwe_id in CWE_HEURISTICS:
        max_score = 0.0
        for profile in dir_profiles.values():
            if profile.total_entities >= MIN_ENTITIES_PER_DIR:
                s = score_directory_for_cwe(profile, cwe_id)
                max_score = max(max_score, s)
        cwe_scores[cwe_id] = max_score

    relevant = [
        (cwe, score)
        for cwe, score in cwe_scores.items()
        if score >= MIN_SCORE_THRESHOLD
    ]
    relevant.sort(key=lambda x: x[1], reverse=True)
    return [cwe for cwe, _ in relevant[:10]]


def _is_source_dir(dir_path: str) -> bool:
    if dir_path == ".":
        return False
    dir_lower = dir_path.lower() + "/"
    for prefix in EXCLUDED_DIR_PREFIXES:
        if dir_lower.startswith(prefix):
            return False
    for pattern in EXCLUDED_DIR_PATTERNS:
        if pattern in dir_lower:
            return False
    return True


def heuristic_mapping(
    entities: list,
    repo_root: str,
    cwe_ids: list[str],
) -> dict[str, list[str]]:
    dir_profiles = build_dir_profiles(entities, repo_root)
    dir_profiles = {
        k: v
        for k, v in dir_profiles.items()
        if v.total_entities >= MIN_ENTITIES_PER_DIR and _is_source_dir(k)
    }

    result: dict[str, list[str]] = {}

    for cwe_id in cwe_ids:
        if cwe_id not in CWE_HEURISTICS:
            continue

        scores = []
        for dir_path, profile in dir_profiles.items():
            s = score_directory_for_cwe(profile, cwe_id)
            if s >= MIN_SCORE_THRESHOLD:
                scores.append((dir_path, s))

        scores.sort(key=lambda x: x[1], reverse=True)
        top_dirs = [d for d, _ in scores[:MAX_DIRS_PER_CWE]]

        if top_dirs:
            result[cwe_id] = top_dirs

    return result


def llm_refine_mapping(
    heuristic_result: dict[str, list[str]],
    dir_profiles: dict[str, DirProfile],
    owner: str,
    repo: str,
    model: str = "claude-sonnet-4-20250514",
) -> dict[str, list[str]]:
    try:
        from litellm import completion
    except ImportError:
        print("  litellm not installed. Using heuristic-only results.")
        return heuristic_result

    dir_summaries = []
    for dir_path, profile in sorted(dir_profiles.items()):
        if profile.total_entities < MIN_ENTITIES_PER_DIR:
            continue
        top_tags = profile.tag_counts.most_common(5)
        tag_str = ", ".join(f"{t.value}={c}" for t, c in top_tags)
        dir_summaries.append(
            f"  {dir_path}/ ({profile.total_entities} entities): {tag_str}"
        )

    dir_text = "\n".join(dir_summaries[:60])

    cwe_descriptions = []
    for cwe_id in heuristic_result.keys():
        h = CWE_HEURISTICS.get(cwe_id, {})
        name = h.get("name", "Unknown")
        cwe_descriptions.append(f"  {cwe_id}: {name}")
    cwe_text = "\n".join(cwe_descriptions)

    heuristic_text = json.dumps(heuristic_result, indent=2)

    prompt = f"""Given this repository ({owner}/{repo}) directory structure with code property distributions, refine the CWE-to-directory mapping.

DIRECTORIES (path, entity count, top code properties):
{dir_text}

CWE IDs TO MAP:
{cwe_text}

INITIAL HEURISTIC MAPPING (may have false positives/negatives):
{heuristic_text}

TASK: Return a refined JSON mapping of CWE ID -> list of directories. Rules:
1. Remove directories that are unlikely targets for the given CWE
2. Add directories that the heuristic missed but are semantically relevant
3. Keep 3-8 directories per CWE (prefer quality over quantity)
4. Only include directories that appear in the DIRECTORIES list above
5. A directory can appear under multiple CWEs if genuinely relevant

Return ONLY a JSON object, no explanation:
{{"CWE-XX": ["dir1", "dir2"], ...}}"""

    try:
        response = completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2000,
        )
        content = response.choices[0].message.content.strip()
        json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", content, re.DOTALL)
        if json_match:
            refined = json.loads(json_match.group())
            valid_dirs = set(dir_profiles.keys())
            validated = {}
            for cwe_id, dirs in refined.items():
                valid = [d for d in dirs if d in valid_dirs]
                if valid:
                    validated[cwe_id] = valid
            return validated
        else:
            print("  Could not parse LLM response. Using heuristic results.")
            return heuristic_result
    except Exception as e:
        print(f"  LLM call failed: {e}")
        return heuristic_result


def insert_profile_into_file(
    profile_code: str,
    language: str,
    profiles_dir: Path,
) -> str:
    """Insert a new profile into the appropriate language file.

    Inserts the new profile class alphabetically (case-insensitive) among
    existing profile classes that subclass the language's base profile.
    Falls back to inserting before the registry.register_profile() block
    when no existing profile classes are found or the new class sorts
    after all of them.
    """
    filename = PROFILE_FILE_MAP.get(language, "javascript.py")
    filepath = profiles_dir / filename

    if not filepath.exists():
        raise FileNotFoundError(f"Profile file not found: {filepath}")

    content = filepath.read_text()

    class_match = re.search(r"class\s+(\w+)\s*\(", profile_code)
    new_class_name = class_match.group(1) if class_match else None

    if new_class_name and re.search(
        rf"\nclass\s+{re.escape(new_class_name)}\s*\(", content
    ):
        print(
            f"  Skipping insert: class {new_class_name} already exists in {filepath.name}"
        )
        return str(filepath)

    profile_class_map = {
        "javascript": "JavaScriptProfile",
        "typescript": "TypeScriptProfile",
        "python": "PythonProfile",
        "java": "JavaProfile",
        "go": "GoProfile",
        "rust": "RustProfile",
        "c": "CProfile",
        "cpp": "CppProfile",
    }
    base_class = profile_class_map.get(language, "JavaScriptProfile")

    insert_match = None
    if new_class_name:
        subclass_pattern = (
            rf"\n@dataclass\nclass\s+(\w+)\s*\(\s*{re.escape(base_class)}\s*\)\s*:"
        )
        for m in re.finditer(subclass_pattern, content):
            existing_name = m.group(1)
            if existing_name.lower() > new_class_name.lower():
                insert_match = m
                break

    if insert_match is not None:
        insert_pos = insert_match.start()
        new_content = (
            content[:insert_pos] + profile_code[1:] + "\n\n" + content[insert_pos:]
        )
    else:
        register_pattern = r"\n# Register all .+ profiles with the global registry\n"
        match = re.search(register_pattern, content)
        if match:
            insert_pos = match.start()
            new_content = (
                content[:insert_pos] + profile_code + "\n" + content[insert_pos:]
            )
        else:
            new_content = content + profile_code + "\n"

    filepath.write_text(new_content)
    return str(filepath)


def update_existing_profile_dirs_include(
    repo_id: str,
    bug_gen_dirs_include: dict[str, list[str]],
    profiles_dir: Path,
    language: str,
) -> str | None:
    """Update an existing profile's bug_gen_dirs_include field.

    Returns the file path if updated, None otherwise.
    """
    filename = PROFILE_FILE_MAP.get(language, "javascript.py")
    filepath = profiles_dir / filename
    content = filepath.read_text()

    owner_repo = repo_id.split(".")[0]
    parts = owner_repo.split("__")
    if len(parts) != 2:
        return None

    owner_pattern = f'owner: str = "{parts[0]}"'
    repo_pattern = f'repo: str = "{parts[1]}"'

    owner_idx = content.find(owner_pattern)
    if owner_idx == -1:
        return None

    repo_idx = content.find(repo_pattern, owner_idx)
    if repo_idx == -1 or repo_idx - owner_idx > 200:
        return None

    class_start = content.rfind("@dataclass\nclass ", 0, owner_idx)
    if class_start == -1:
        return None

    next_class = content.find("\n@dataclass\nclass ", owner_idx)
    next_register = content.find("\n# Register all", owner_idx)

    if next_class != -1:
        class_end = next_class
    elif next_register != -1:
        class_end = next_register
    else:
        class_end = len(content)

    class_block = content[class_start:class_end]

    if "bug_gen_dirs_include" in class_block:
        old_field_start = class_block.find("bug_gen_dirs_include")
        paren_depth = 0
        i = class_block.find("field(", old_field_start)
        if i == -1:
            return None
        for j in range(i, len(class_block)):
            if class_block[j] == "(":
                paren_depth += 1
            elif class_block[j] == ")":
                paren_depth -= 1
                if paren_depth == 0:
                    old_field_end = j + 1
                    break
        else:
            return None

        field_line_start = class_block.rfind("\n", 0, old_field_start) + 1
        old_field_text = class_block[field_line_start:old_field_end]
        new_field_text = format_dirs_include_field(bug_gen_dirs_include)
        new_content = (
            content[: class_start + field_line_start]
            + new_field_text
            + content[class_start + old_field_end :]
        )
    else:
        last_field_match = None
        for m in re.finditer(r"\n    \w+:.*=.*\n", class_block):
            last_field_match = m

        if last_field_match:
            insert_pos = class_start + last_field_match.end()
        else:
            insert_pos = class_start + len(class_block)

        new_field = format_dirs_include_field(bug_gen_dirs_include)
        new_content = content[:insert_pos] + new_field + "\n" + content[insert_pos:]

    filepath.write_text(new_content)
    return str(filepath)


def format_dirs_include_field(bug_gen_dirs_include: dict[str, list[str]]) -> str:
    lines = ["    bug_gen_dirs_include: dict[str, list[str]] = field("]
    lines.append("        default_factory=lambda: {")
    for cwe_id, dirs in sorted(bug_gen_dirs_include.items()):
        lines.append(f'            "{cwe_id}": [')
        for d in dirs:
            lines.append(f'                "{d}",')
        lines.append("            ],")
    lines.append("        }")
    lines.append("    )")
    return "\n".join(lines)


def _create_temp_profile(
    owner: str, repo: str, commit: str, test_cmd: str, language: str
):
    """Create a temporary profile for entity extraction when no registered profile exists.

    Dynamically selects the correct language-specific base class and creates a concrete
    subclass with log_parser implemented, since RepoProfile.log_parser is abstract.
    """
    from swesmith.profiles.javascript import JavaScriptProfile

    base_classes: dict[str, type] = {"javascript": JavaScriptProfile}

    try:
        from swesmith.profiles.typescript import TypeScriptProfile

        base_classes["typescript"] = TypeScriptProfile
    except ImportError:
        pass

    try:
        from swesmith.profiles.c import CProfile

        base_classes["c"] = CProfile
    except ImportError:
        pass

    try:
        from swesmith.profiles.cpp import CppProfile

        base_classes["cpp"] = CppProfile
    except ImportError:
        pass

    try:
        from swesmith.profiles.java import JavaProfile

        base_classes["java"] = JavaProfile
    except ImportError:
        pass

    try:
        from swesmith.profiles.rust import RustProfile

        base_classes["rust"] = RustProfile
    except ImportError:
        pass

    try:
        from swesmith.profiles.golang import GoProfile

        base_classes["go"] = GoProfile
    except ImportError:
        pass

    try:
        from swesmith.profiles.python import PythonProfile

        base_classes["python"] = PythonProfile
    except ImportError:
        pass

    base = base_classes.get(language, JavaScriptProfile)

    cls = dataclass(
        type(
            "TempProfile",
            (base,),
            {
                "__annotations__": {
                    "owner": str,
                    "repo": str,
                    "commit": str,
                    "test_cmd": str,
                },
                "owner": owner,
                "repo": repo,
                "commit": commit,
                "test_cmd": test_cmd,
                "log_parser": lambda self, log: {},
            },
        )
    )
    return cls()


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a repository for SWE-smith bug generation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "repo_spec",
        type=str,
        help="Repository in owner/repo format (e.g., facebook/react)",
    )
    parser.add_argument(
        "--commit",
        type=str,
        default=None,
        help="Specific commit hash (default: latest from main branch)",
    )
    parser.add_argument(
        "--language",
        type=str,
        default=None,
        help="Override language detection (javascript, typescript, python, etc.)",
    )
    parser.add_argument(
        "--test-cmd",
        type=str,
        default=None,
        help="Override test command detection",
    )
    parser.add_argument(
        "--heuristic-only",
        action="store_true",
        help="Skip LLM refinement for CWE mapping",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="claude-sonnet-4-20250514",
        help="LLM model for CWE refinement",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results without modifying profile files",
    )
    parser.add_argument(
        "--cwes",
        nargs="+",
        type=str,
        default=None,
        help="Specify CWE IDs to map (default: auto-detect)",
    )
    parser.add_argument(
        "--refined-json",
        type=str,
        default=None,
        help="Path to refined CWE->dirs JSON file from LLM (skips litellm call)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed scoring breakdown",
    )
    args = parser.parse_args()

    if "/" not in args.repo_spec:
        print("Error: repo_spec must be in owner/repo format (e.g., facebook/react)")
        sys.exit(1)

    owner, repo = args.repo_spec.split("/", 1)
    print(f"{'=' * 60}")
    print(f"  Analyzing: {owner}/{repo}")
    print(f"{'=' * 60}")

    if args.commit:
        commit = args.commit
    else:
        print("\n[1/6] Fetching latest commit...")
        commit = get_latest_commit(owner, repo)
    print(f"  Commit: {commit}")
    print(f"  Short: {commit[:8]}")

    if args.language:
        language = args.language
    else:
        print("\n[2/6] Detecting language...")
        language = detect_language(owner, repo)
    print(f"  Language: {language}")

    print("\n[3/6] Checking for existing profile...")
    repo_id = f"{owner}__{repo}.{commit[:8]}"
    existing_key = find_existing_profile(owner, repo)
    test_cmd: str = ""

    if existing_key:
        print(f"  Found existing profile: {existing_key}")
        rp = registry.get(existing_key)
        repo_id = existing_key.split("/")[-1] if "/" in existing_key else existing_key
    else:
        print(f"  No existing profile found.")
        print(f"  Will create: {repo_id}")

        if args.test_cmd:
            test_cmd = args.test_cmd
        else:
            test_cmd = detect_test_command(owner, repo, commit, language)
        print(f"  Test command: {test_cmd}")

        rp = _create_temp_profile(owner, repo, commit, test_cmd, language)

    print("\n[4/6] Cloning and extracting entities...")
    rp.create_mirror()
    repo_root, _ = rp.clone()
    print(f"  Cloned to: {repo_root}")

    print("\n[5/6] Detecting build configuration...")
    build_info = detect_repo_build_info(repo_root, language)
    if language in ("c", "cpp"):
        print(f"  Build system: {build_info.build_system or 'none detected'}")
        if build_info.cmake_test_option:
            print(f"  CMake test option: {build_info.cmake_test_option}")
        if not args.test_cmd and not existing_key:
            if build_info.build_system == "cmake":
                opt = build_info.cmake_test_option or "BUILD_TESTING"
                refined = (
                    "cd build && cmake -D" + opt + "=ON .. && "
                    "make -j$(nproc) && "
                    "ctest --verbose --output-on-failure"
                )
            elif build_info.build_system == "autotools":
                refined = "make check"
            elif build_info.build_system == "make":
                refined = "make test"
            else:
                refined = test_cmd
            if refined and refined != test_cmd:
                print(f"  Refined test command: {refined}")
                test_cmd = refined
                rp.test_cmd = refined
    elif language == "java":
        print(f"  Build system: {build_info.build_system or 'none detected'}")
        print(f"  Uses wrapper: {build_info.uses_wrapper}")
        if not args.test_cmd and not existing_key:
            if build_info.build_system == "maven" and build_info.uses_wrapper:
                refined = test_cmd.replace("mvn ", "./mvnw ", 1)
            elif build_info.build_system == "gradle":
                runner = "./gradlew" if build_info.uses_wrapper else "gradle"
                refined = (
                    f"{runner} test --rerun-tasks --continue "
                    "--no-daemon --console=plain "
                    "|| true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
                )
            else:
                refined = test_cmd
            if refined and refined != test_cmd:
                print(f"  Refined test command: {refined}")
                test_cmd = refined
                rp.test_cmd = refined
    elif language in ("javascript", "typescript"):
        print(f"  Package manager: {build_info.package_manager}")
        if build_info.pm_version:
            print(f"  PM version: {build_info.pm_version}")
        print(f"  Lockfile: {build_info.lockfile_name or 'none'}")
        print(f"  Has build script: {build_info.has_build_script}")
        print(f"  Corepack: {build_info.uses_corepack}")
        print(f"  Node version: {build_info.node_version}")
        if build_info.uses_workspaces:
            print(f"  Workspaces: yes")
        if build_info.extra_apt_deps:
            print(f"  Extra apt deps: {', '.join(build_info.extra_apt_deps)}")
    elif language == "rust":
        rust_version = getattr(rp, "rust_version", "unknown")
        print(f"  Toolchain: cargo (rust {rust_version})")
    elif language == "go":
        print(f"  Toolchain: go modules")
    elif language == "python":
        python_version = getattr(rp, "python_version", "unknown")
        print(f"  Toolchain: conda + pip (python {python_version})")

    docker_warnings = validate_dockerfile(build_info, language)
    if docker_warnings:
        print(f"\n  ⚠ Dockerfile warnings:")
        for w in docker_warnings:
            print(f"    - {w}")

    if not existing_key:
        print(
            "\n  Adding bare profile (empty bug_gen_dirs_include) to language file..."
        )
        profiles_dir = Path(__file__).resolve().parent.parent / "swesmith" / "profiles"
        bare_profile_code = generate_profile_code(
            owner,
            repo,
            commit,
            language,
            test_cmd,
            bug_gen_dirs_include={},
            build_info=build_info,
        )
        bare_path = insert_profile_into_file(bare_profile_code, language, profiles_dir)
        print(f"  Added bare profile in: {bare_path}")

    entities = rp.extract_entities(dirs_exclude=rp.bug_gen_dirs_exclude)
    print(f"\n  Total candidates: {len(entities)}")

    if not entities:
        print("\n  ERROR: No entities found. Cannot proceed.")
        sys.exit(1)

    if args.verbose:
        ext_counts = Counter(Path(e.file_path).suffix for e in entities)
        print(f"\n  By extension:")
        for ext, count in ext_counts.most_common(10):
            print(f"    {ext}: {count}")

        func_count = sum(1 for e in entities if CodeProperty.IS_FUNCTION in e._tags)
        class_count = sum(1 for e in entities if CodeProperty.IS_CLASS in e._tags)
        print(f"\n  By type:")
        print(f"    Functions: {func_count}")
        print(f"    Classes: {class_count}")

    print("\n[6/6] Mapping CWEs to directories...")

    if args.cwes:
        cwe_ids = args.cwes
    else:
        cwe_ids = select_relevant_cwes(entities, repo_root)

    print(f"  Relevant CWEs: {', '.join(cwe_ids)}")

    if not cwe_ids:
        print("  No relevant CWEs found.")
        bug_gen_dirs_include = {}
    else:
        bug_gen_dirs_include = heuristic_mapping(entities, repo_root, cwe_ids)

        if args.verbose:
            dir_profiles = build_dir_profiles(entities, repo_root)
            for cwe_id in cwe_ids:
                if cwe_id not in CWE_HEURISTICS:
                    continue
                print(f"\n  {cwe_id} ({CWE_HEURISTICS[cwe_id]['name']}):")
                scores = []
                for dir_path, profile in dir_profiles.items():
                    if profile.total_entities >= MIN_ENTITIES_PER_DIR:
                        s = score_directory_for_cwe(profile, cwe_id)
                        if s > 0:
                            scores.append((dir_path, s))
                scores.sort(key=lambda x: x[1], reverse=True)
                for dir_path, s in scores[:10]:
                    marker = "✓" if s >= MIN_SCORE_THRESHOLD else "·"
                    print(f"    {marker} {dir_path}: {s:.2f}")

        if args.refined_json:
            print(f"\n  Loading refined mapping from: {args.refined_json}")
            with open(args.refined_json) as f:
                bug_gen_dirs_include = json.load(f)
        elif not args.heuristic_only and bug_gen_dirs_include:
            print("\n  Refining with LLM...")
            dir_profiles = build_dir_profiles(entities, repo_root)
            bug_gen_dirs_include = llm_refine_mapping(
                bug_gen_dirs_include, dir_profiles, owner, repo, model=args.model
            )

    print(f"\n{'=' * 60}")
    print("  RESULTS")
    print(f"{'=' * 60}")
    print(f"\n  Repository: {owner}/{repo}")
    print(f"  Commit: {commit[:8]}")
    print(f"  Language: {language}")
    print(f"  Total candidates: {len(entities)}")
    print(f"  CWEs mapped: {len(bug_gen_dirs_include)}")
    total_dirs = sum(len(v) for v in bug_gen_dirs_include.values())
    print(f"  Total directory entries: {total_dirs}")

    if bug_gen_dirs_include:
        print(f"\n  CWE → Directory Mapping:")
        for cwe_id, dirs in sorted(bug_gen_dirs_include.items()):
            name = CWE_HEURISTICS.get(cwe_id, {}).get("name", "Unknown")
            print(f"\n    {cwe_id} ({name}):")
            for d in dirs:
                print(f"      - {d}")

    if args.dry_run:
        if not existing_key:
            print(
                f"\n  Bare profile already added above. bug_gen_dirs_include NOT written (--dry-run)."
            )
        else:
            print(f"\n  [DRY RUN] No files modified.")
    else:
        profiles_dir = Path(__file__).resolve().parent.parent / "swesmith" / "profiles"

        if bug_gen_dirs_include:
            result_path = update_existing_profile_dirs_include(
                repo_id, bug_gen_dirs_include, profiles_dir, language
            )
            if result_path:
                print(f"\n  Updated profile in: {result_path}")
            else:
                print(f"\n  Could not auto-update profile. Manual update needed.")
                print(f"  Paste this into the profile class:")
                print(format_dirs_include_field(bug_gen_dirs_include))
        else:
            print(f"\n  No CWE mapping to write.")

    import shutil

    if os.path.isdir(repo_root) and repo_root != ".":
        shutil.rmtree(repo_root, ignore_errors=True)

    print(f"\n{'=' * 60}")
    print("  Done!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

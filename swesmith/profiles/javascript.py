import os
import re
import shutil

from dataclasses import dataclass, field
from swebench.harness.constants import (
    FAIL_TO_PASS,
    PASS_TO_PASS,
    KEY_INSTANCE_ID,
    TestStatus,
)
from swesmith.constants import ENV_NAME, KEY_PATCH
from swesmith.profiles.base import RepoProfile, registry
from swesmith.profiles.utils import X11_DEPS
from unidiff import PatchSet


@dataclass
class JavaScriptProfile(RepoProfile):
    """
    Profile for JavaScript repositories.
    """

    exts: list[str] = field(default_factory=lambda: [".js"])
    _test_name_to_files_cache: dict[str, set[str]] = field(
        default=None, init=False, repr=False
    )

    @classmethod
    def _dockerfile_env_groups(cls) -> list[str]:
        return ["node"]

    _JS_TEST_EXTS: tuple[str, ...] = (
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".mjs",
        ".cjs",
    )

    @staticmethod
    def _is_js_test_file(root: str, fname: str) -> bool:
        """Return True if the file looks like a JS/TS test file."""
        parts = root.split(os.sep)
        in_test_dir = any(
            p in ("test", "tests", "__tests__", "spec", "specs") for p in parts
        )
        is_test_named = any(
            x in fname
            for x in (".test.", ".spec.", "_test.", "_spec.", "test.", "spec.")
        )
        return in_test_dir or is_test_named

    def _build_test_name_to_files_map(self) -> dict[str, set[str]]:
        """Build a mapping from test description strings to the files that contain them."""
        dest, cloned = self.clone()
        test_name_to_files: dict[str, set[str]] = {}

        # Match it('...'), it("..."), it(`...`), test('...'), test("..."), test(`...`)
        # Also handle .only and .skip variants
        test_call_re = re.compile(
            r"""(?:it|test)(?:\.only|\.skip)?\s*\(\s*(['"`])(.+?)\1"""
        )

        for dirpath, _, filenames in os.walk(dest):
            # Skip node_modules
            if "node_modules" in dirpath.split(os.sep):
                continue
            for fname in filenames:
                if not fname.endswith(self._JS_TEST_EXTS):
                    continue
                if not self._is_js_test_file(dirpath, fname):
                    continue

                full_path = os.path.join(dirpath, fname)
                relative_path = os.path.relpath(full_path, dest)

                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except (OSError, UnicodeDecodeError):
                    continue

                for match in test_call_re.finditer(content):
                    test_name = match.group(2)
                    test_name_to_files.setdefault(test_name, set()).add(relative_path)

        if cloned:
            shutil.rmtree(dest)
        return test_name_to_files

    def get_test_files(self, instance: dict) -> tuple[list[str], list[str]]:
        assert FAIL_TO_PASS in instance and PASS_TO_PASS in instance, (
            f"Instance {instance[KEY_INSTANCE_ID]} missing required keys {FAIL_TO_PASS} or {PASS_TO_PASS}"
        )

        # Lazy load the cache if needed
        if self._test_name_to_files_cache is None:
            with self._lock:
                if self._test_name_to_files_cache is None:
                    self._test_name_to_files_cache = (
                        self._build_test_name_to_files_map()
                    )

        f2p_files: set[str] = set()
        for test_name in instance[FAIL_TO_PASS]:
            # File-path test names (e.g. Svelte vitest)
            if test_name.endswith(self._JS_TEST_EXTS):
                f2p_files.add(test_name)
            elif test_name in self._test_name_to_files_cache:
                f2p_files.update(self._test_name_to_files_cache[test_name])

        p2p_files: set[str] = set()
        for test_name in instance[PASS_TO_PASS]:
            if test_name.endswith(self._JS_TEST_EXTS):
                p2p_files.add(test_name)
            elif test_name in self._test_name_to_files_cache:
                p2p_files.update(self._test_name_to_files_cache[test_name])

        return list(f2p_files), list(p2p_files)

    def extract_entities(
        self,
        dirs_exclude: list[str] = None,
        dirs_include: list[str] = [],
        exclude_tests: bool = True,
        max_entities: int = -1,
    ) -> list:
        """
        Override to exclude JavaScript build artifacts by default.

        JavaScript projects often have build/dist directories that contain
        transpiled/bundled code. We should only analyze source files.
        """
        if dirs_exclude is None:
            # Default exclusions for JavaScript projects
            dirs_exclude = [
                "dist",
                "build",
                "node_modules",
                "coverage",
                ".next",
                "out",
                "examples",
                "docs",
                "bin",
            ]

        return super().extract_entities(
            dirs_exclude=dirs_exclude,
            dirs_include=dirs_include,
            exclude_tests=exclude_tests,
            max_entities=max_entities,
        )


def default_npm_install_dockerfile(mirror_url: str, node_version: str = "18") -> str:
    return f"""FROM node:{node_version}-bullseye
RUN apt update && apt install -y git
RUN git clone {mirror_url} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
"""


def parse_log_jest(log: str) -> dict[str, str]:
    """
    Parser for test logs generated with Jest. Assumes --verbose flag.

    Args:
        log (str): log content
    Returns:
        dict: test case to test status mapping
    """
    test_status_map = {}

    pattern = r"^\s*(✓|✕|○)\s(.+?)(?:\s\((\d+\s*m?s)\))?$"

    for line in log.split("\n"):
        match = re.match(pattern, line.strip())
        if match:
            status_symbol, test_name, _duration = match.groups()
            if status_symbol == "✓":
                test_status_map[test_name] = TestStatus.PASSED.value
            elif status_symbol == "✕":
                test_status_map[test_name] = TestStatus.FAILED.value
            elif status_symbol == "○":
                test_status_map[test_name] = TestStatus.SKIPPED.value
    return test_status_map


def parse_log_mocha(log: str) -> dict[str, str]:
    test_status_map = {}
    # Pattern for checkmark/x/dash style output
    # Note: Match both ✓ (U+2713) and ✔ (U+2714) checkmarks as different Mocha versions use different symbols
    pattern = r"^\s*([✓✔]|[✖✘]|-)\s(.+?)(?:\s\((\d+\s*m?s)\))?$"
    # Pattern for numbered failures like "1) test name" or "1) should solve..."
    fail_pattern = r"^\s*\d+\)\s+(.+?)(?:\s\((\d+\s*m?s)\))?$"
    for line in log.split("\n"):
        match = re.match(pattern, line.strip())
        if match:
            status_symbol, test_name, _duration = match.groups()
            if status_symbol in ("✓", "✔"):
                test_status_map[test_name] = TestStatus.PASSED.value
            elif status_symbol in ("✖", "✘"):
                test_status_map[test_name] = TestStatus.FAILED.value
            elif status_symbol == "-":
                test_status_map[test_name] = TestStatus.SKIPPED.value
        else:
            # Try numbered failure pattern
            fail_match = re.match(fail_pattern, line.strip())
            if fail_match:
                test_name = fail_match.group(1)
                test_status_map[test_name] = TestStatus.FAILED.value
    return test_status_map


def parse_log_vitest(log: str) -> dict[str, str]:
    test_status_map = {}
    patterns = [
        # Vitest uses ✓ for passing test files and ❯ for test files with failures
        (r"^✓\s+(.+?)(?:\s+\([\.\d]+ms\))?$", TestStatus.PASSED.value),
        (r"^❯\s+(.+?)(?:\s+\(.*?\))?$", TestStatus.FAILED.value),  # Failed test files
        (r"^[✗×]\s+(.+?)(?:\s+\([\.\d]+ms\))?$", TestStatus.FAILED.value),
        (r"^○\s+(.+?)(?:\s+\([\.\d]+ms\))?$", TestStatus.SKIPPED.value),
        (r"^✓\s+(.+?)$", TestStatus.PASSED.value),
        (r"^[✗×]\s+(.+?)$", TestStatus.FAILED.value),
        (r"^○\s+(.+?)$", TestStatus.SKIPPED.value),
    ]
    for line in log.split("\n"):
        for pattern, status in patterns:
            match = re.match(pattern, line.strip())
            if match:
                test_name = match.group(1).strip()
                # Normalize test file names: extract just the file path before parentheses
                # e.g., "test/foo.test.js (9 tests)" -> "test/foo.test.js"
                # or "test/foo.test.js (9 tests | 5 failed) 22ms" -> "test/foo.test.js"
                if "(" in test_name:
                    test_name = test_name.split("(")[0].strip()
                test_status_map[test_name] = status
                break

    return test_status_map


def parse_log_karma(log: str) -> dict[str, str]:
    """
    Parser for test logs generated by Karma (commonly used with Jasmine/Mocha).
    Since Karma doesn't output individual test names in a parseable way,
    we generate generic test entries based on the summary counts.
    """
    test_status_map = {}

    # Pattern for Karma final summary
    success_pattern = r"Executed\s+(\d+)\s+of\s+\d+\s+SUCCESS"
    failed_pattern = r"Executed\s+\d+\s+of\s+\d+\s+\((\d+)\s+FAILED\)"
    skipped_pattern = r"Executed\s+\d+\s+of\s+(\d+)\s+\((\d+)\s+skipped\)"

    passed_count = 0
    failed_count = 0
    skipped_count = 0

    for line in log.split("\n"):
        success_match = re.search(success_pattern, line)
        if success_match:
            passed_count = max(passed_count, int(success_match.group(1)))

        failed_match = re.search(failed_pattern, line)
        if failed_match:
            failed_count = max(failed_count, int(failed_match.group(1)))

        skipped_match = re.search(skipped_pattern, line)
        if skipped_match:
            skipped_count = max(skipped_count, int(skipped_match.group(2)))

    # Generate test entries
    for i in range(passed_count):
        test_status_map[f"karma_unit_test_{i + 1}"] = TestStatus.PASSED.value

    for i in range(failed_count):
        test_status_map[f"karma_unit_test_failed_{i + 1}"] = TestStatus.FAILED.value

    for i in range(skipped_count):
        test_status_map[f"karma_unit_test_skipped_{i + 1}"] = TestStatus.SKIPPED.value

    return test_status_map


def parse_log_jasmine(log: str) -> dict[str, str]:
    """
    Parser for standalone Jasmine CLI output.
    Format: "426 specs, 0 failures, 3 pending specs"
    """
    test_status_map = {}

    # Pattern for Jasmine summary: "X specs, Y failures, Z pending specs"
    pattern = r"(\d+)\s+specs?,\s+(\d+)\s+failures?(?:,\s+(\d+)\s+pending\s+specs?)?"

    for line in log.split("\n"):
        match = re.search(pattern, line)
        if match:
            total_specs = int(match.group(1))
            failures = int(match.group(2))
            pending = int(match.group(3)) if match.group(3) else 0

            passed = total_specs - failures - pending

            # Generate test entries
            for i in range(passed):
                test_status_map[f"jasmine_spec_{i + 1}"] = TestStatus.PASSED.value

            for i in range(failures):
                test_status_map[f"jasmine_spec_failed_{i + 1}"] = (
                    TestStatus.FAILED.value
                )

            for i in range(pending):
                test_status_map[f"jasmine_spec_pending_{i + 1}"] = (
                    TestStatus.SKIPPED.value
                )

            break  # Only process the first summary line

    return test_status_map


def parse_log_qunit(log: str) -> dict[str, str]:
    """
    Parser for QUnit test output. Supports two formats:
    1. TAP format (QUnit CLI): "ok N test name" / "not ok N test name"
    2. jtr format (jquery-test-runner): summary line "X failed. Y passed. Z skipped."
    """
    test_status_map = {}

    # First try TAP format (QUnit CLI direct)
    tap_pattern = r"^(ok|not ok)\s+(\d+)\s*(?:-\s+)?([^#]*?)?\s*(?:#\s*(SKIP|TODO).*?)?\s*$"
    for line in log.split("\n"):
        match = re.match(tap_pattern, line.strip())
        if match:
            status, _num, test_name, directive = match.groups()
            test_name = (test_name or "").strip()
            if not test_name:
                test_name = f"test_{_num}"

            if directive in ("SKIP", "TODO"):
                test_status_map[test_name] = TestStatus.SKIPPED.value
            elif status == "ok":
                test_status_map[test_name] = TestStatus.PASSED.value
            else:
                test_status_map[test_name] = TestStatus.FAILED.value

    if test_status_map:
        return test_status_map

    # Fallback: jtr summary format "X failed. Y passed. Z skipped."
    summary_pattern = r"(\d+)\s+failed\.\s+(\d+)\s+passed\.\s+(\d+)\s+skipped\."
    for line in log.split("\n"):
        match = re.search(summary_pattern, line.strip())
        if match:
            failed = int(match.group(1))
            passed = int(match.group(2))
            skipped = int(match.group(3))

            for i in range(passed):
                test_status_map[f"qunit_test_{i + 1}"] = TestStatus.PASSED.value
            for i in range(failed):
                test_status_map[f"qunit_test_failed_{i + 1}"] = TestStatus.FAILED.value
            for i in range(skipped):
                test_status_map[f"qunit_test_skipped_{i + 1}"] = TestStatus.SKIPPED.value
            return test_status_map

    return test_status_map


def parse_log_tap(log: str) -> dict[str, str]:
    """
    Parser for TAP (Test Anything Protocol) format output.
    Used by tape, node-tap, and other TAP-compatible runners.
    Format: "ok N test name" / "not ok N test name"
    """
    test_status_map = {}
    pattern = r"^(ok|not ok)\s+(\d+)\s*(?:-\s+)?([^#]*?)?\s*(?:#\s*(SKIP|TODO).*?)?\s*$"

    for line in log.split("\n"):
        match = re.match(pattern, line.strip())
        if match:
            status, _num, test_name, directive = match.groups()
            test_name = (test_name or "").strip()
            if not test_name:
                test_name = f"test_{_num}"

            if directive in ("SKIP", "TODO"):
                test_status_map[test_name] = TestStatus.SKIPPED.value
            elif status == "ok":
                test_status_map[test_name] = TestStatus.PASSED.value
            else:
                test_status_map[test_name] = TestStatus.FAILED.value

    return test_status_map


@dataclass
class Reactpdfd41a8207(JavaScriptProfile):
    owner: str = "diegomura"
    repo: str = "react-pdf"
    commit: str = "d41a8207fb06a56e60fcb53ac0e18ce27e7d32d6"
    test_cmd: str = "./node_modules/.bin/vitest --no-color --reporter verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-bullseye
RUN apt update && apt install -y pkg-config build-essential libpixman-1-0 libpixman-1-dev libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN yarn install
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        test_status_map = {}
        for line in log.split("\n"):
            for pattern, status in [
                (r"^\s*✓\s(.*)\s\d+ms", TestStatus.PASSED.value),
                (r"^\s*✗\s(.*)\s\d+ms", TestStatus.FAILED.value),
                (r"^\s*✖\s(.*)", TestStatus.FAILED.value),
                (r"^\s*✓\s(.*)", TestStatus.PASSED.value),
            ]:
                match = re.match(pattern, line)
                if match:
                    test_name = match.group(1).strip()
                    test_status_map[test_name] = status
                    break
        return test_status_map


@dataclass
class Marked69257e45(JavaScriptProfile):
    owner: str = "markedjs"
    repo: str = "marked"
    commit: str = "69257e455e599e9c9ddedcaf913569279b12c20c"
    test_cmd: str = "NO_COLOR=1 node --test"

    @property
    def dockerfile(self):
        return f"""FROM node:24-bullseye
RUN apt update && apt install -y git {X11_DEPS}
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm ci
RUN npm run build
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        test_status_map = {}
        fail_pattern = r"^\s*✖\s(.*?)\s\([\.\d]+ms\)"
        pass_pattern = r"^\s*✔\s(.*?)\s\([\.\d]+ms\)"
        for line in log.split("\n"):
            fail_match = re.match(fail_pattern, line)
            if fail_match:
                test = fail_match.group(1)
                test_status_map[test.strip()] = TestStatus.FAILED.value
            else:
                pass_match = re.match(pass_pattern, line)
                if pass_match:
                    test = pass_match.group(1)
                    test_status_map[test.strip()] = TestStatus.PASSED.value
        return test_status_map


@dataclass
class Babelb79f64a1(JavaScriptProfile):
    owner: str = "babel"
    repo: str = "babel"
    commit: str = "b79f64a144c2db466d09770298b4ece0adca34bf"
    test_cmd: str = "yarn jest --verbose"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )

    @property
    def dockerfile(self):
        return f"""FROM node:20-bullseye
RUN apt update && apt install -y git
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN make bootstrap
RUN make build
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)

    def get_test_cmd(self, instance: dict, f2p_only: bool = False):
        if KEY_PATCH not in instance:
            return self.test_cmd, []
        test_folders = []
        for f in PatchSet(instance[KEY_PATCH]):
            parts = f.path.split("/")
            if len(parts) >= 2 and parts[0] == "packages":
                test_folders.append("/".join(parts[:2]))
        return f"{self.test_cmd} {' '.join(test_folders)}", test_folders


@dataclass
class Githubreadmestats5df91f9b(JavaScriptProfile):
    owner: str = "anuraghazra"
    repo: str = "github-readme-stats"
    commit: str = "5df91f9bfa89c356a55cbb3c2bbc164fdbf94a86"
    test_cmd: str = "npm test -- --verbose"

    @property
    def dockerfile(self):
        return default_npm_install_dockerfile(self.mirror_url)

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Mongoose2b7bb96c(JavaScriptProfile):
    owner: str = "Automattic"
    repo: str = "mongoose"
    commit: str = "2b7bb96c517d7ce0e6a2c386a894149959efbe38"
    test_cmd: str = "npm test -- --verbose"

    @property
    def dockerfile(self):
        return default_npm_install_dockerfile(self.mirror_url)

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Axios23fd0a6a(JavaScriptProfile):
    owner: str = "axios"
    repo: str = "axios"
    commit: str = "23fd0a6a16a4879bc2601c867db0caa2ce178824"
    test_cmd: str = "npm run test:mocha -- --verbose"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )

    @property
    def dockerfile(self):
        return default_npm_install_dockerfile(self.mirror_url)

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Async03fbed25(JavaScriptProfile):
    owner: str = "caolan"
    repo: str = "async"
    commit: str = "03fbed25c728e78b503df4f21e946948d9459cc9"
    test_cmd: str = "npm run mocha-node-test -- --verbose"

    @property
    def dockerfile(self):
        return default_npm_install_dockerfile(self.mirror_url)

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Expressf873ac23(JavaScriptProfile):
    owner: str = "expressjs"
    repo: str = "express"
    commit: str = "f873ac23124ffcff8c040b4bd257b32c29828d53"
    test_cmd: str = "npm test -- --verbose"

    @property
    def dockerfile(self):
        return default_npm_install_dockerfile(self.mirror_url)

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Dayjsb84592fe(JavaScriptProfile):
    owner: str = "iamkun"
    repo: str = "dayjs"
    commit: str = "b84592fe4e89abb23749de9a772454d5d2e65f19"
    test_cmd: str = "npm test -- --verbose"

    @property
    def dockerfile(self):
        return default_npm_install_dockerfile(self.mirror_url)

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Svelted4c5a917(JavaScriptProfile):
    owner: str = "sveltejs"
    repo: str = "svelte"
    commit: str = "d4c5a917356a4ef0905681bdd98113c84707db42"
    test_cmd: str = "pnpm test -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-bullseye
RUN apt update && apt install -y git
RUN npm install -g pnpm@10.4.0
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN pnpm install
RUN pnpm playwright install chromium
RUN pnpm exec playwright install-deps
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Commanderjs8247364d(JavaScriptProfile):
    owner: str = "tj"
    repo: str = "commander.js"
    commit: str = "8247364da749736570161e95682b07fc2d72497b"
    test_cmd: str = "npm test -- --verbose"

    @property
    def dockerfile(self):
        return default_npm_install_dockerfile(self.mirror_url, node_version="20")

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Wretch0b90bc4a(JavaScriptProfile):
    owner: str = "elbywan"
    repo: str = "wretch"
    commit: str = "0b90bc4a71f60e113167a83e716142d43fa1c4f7"
    test_cmd: str = "npm run test -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:22-bullseye
RUN apt update && apt install -y git
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
RUN npm run build
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Html5boilerplate31357fdb(JavaScriptProfile):
    owner: str = "h5bp"
    repo: str = "html5-boilerplate"
    commit: str = "31357fdb7c4c4da60a7c910e95440444c2ca7a6d"
    test_cmd: str = "npm run test -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:22-bullseye
RUN apt update && apt install -y git
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm ci
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class HighlightJS5697ae51(JavaScriptProfile):
    owner: str = "highlightjs"
    repo: str = "highlight.js"
    commit: str = "5697ae5187746c24732e62cd625f3f83004a44ce"
    test_cmd: str = "npm run test -- --verbose"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multimodal"}
    )

    @property
    def dockerfile(self):
        return f"""FROM node:22-bullseye
RUN apt update && apt install -y git
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
RUN npm run build
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Prismded4a65b(JavaScriptProfile):
    owner: str = "PrismJS"
    repo: str = "prism"
    commit: str = "ded4a65b75a246b4dbc6c5a84e584db1078529aa"
    test_cmd: str = "npm run test"
    eval_sets: set[str] = field(
        default_factory=lambda: {
            "SWE-bench/SWE-bench_Multilingual",
            "SWE-bench/SWE-bench_Multimodal",
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM node:22-bullseye
RUN apt update && apt install -y git
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
RUN npm run build
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Chromajs87058d62(JavaScriptProfile):
    owner: str = "gka"
    repo: str = "chroma.js"
    commit: str = "87058d62a50c1de02043bd2c15aa6a30e4256b0a"
    test_cmd: str = "npm run test -- --run"

    @property
    def dockerfile(self):
        return f"""FROM node:22-bullseye
RUN apt update && apt install -y git
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
RUN npm run build
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Color4fda9a3e(JavaScriptProfile):
    owner: str = "Qix-"
    repo: str = "color"
    commit: str = "4fda9a3edf1a966070e4cd9ed91e47b500df2110"
    test_cmd: str = "npm run test -- --verbose"

    @property
    def image_name(self) -> str:
        # Note: "-" followed by a "_" is not allowed in Docker image names
        return f"{self.org_dh}/swesmith.{self.arch}.{self.owner.replace('-', '_')}_1776_{self.repo}.{self.commit[:8]}".lower()

    @property
    def dockerfile(self):
        return default_npm_install_dockerfile(self.mirror_url, node_version="22")

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Qd180f4a0(JavaScriptProfile):
    owner: str = "kriskowal"
    repo: str = "q"
    commit: str = "d180f4a0b22499607ac750b56766c8829d6bff43"
    test_cmd: str = "npm run test -- --verbose --reporter spec"

    @property
    def dockerfile(self):
        return default_npm_install_dockerfile(self.mirror_url, node_version="22")

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Immutablejs9acd11a8(JavaScriptProfile):
    owner: str = "immutable-js"
    repo: str = "immutable-js"
    commit: str = "9acd11a87e1c628f08639f9ae0539073f4ee46d8"
    test_cmd: str = "npm run test -- --verbose"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )

    @property
    def dockerfile(self):
        return default_npm_install_dockerfile(self.mirror_url, node_version="22")

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Threejs9bc5f5cc(JavaScriptProfile):
    owner: str = "mrdoob"
    repo: str = "three.js"
    commit: str = "9bc5f5ccdbffd1797ce44f29fa510a96da2f94c3"
    test_cmd: str = "npm run test -- --verbose"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )

    @property
    def dockerfile(self):
        return default_npm_install_dockerfile(self.mirror_url, node_version="22")

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Echartsd6a812f8(JavaScriptProfile):
    owner: str = "apache"
    repo: str = "echarts"
    commit: str = "d6a812f8482f23933692ce3ab99d8bf73131835f"
    test_cmd: str = "npm run test -- --verbose"

    @property
    def dockerfile(self):
        return default_npm_install_dockerfile(self.mirror_url, node_version="22")

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Draggable8a1eed57(JavaScriptProfile):
    owner: str = "Shopify"
    repo: str = "draggable"
    commit: str = "8a1eed57f3ab2dff9371e8ce60fb39ac85871e8d"
    test_cmd: str = "yarn test --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Reactslick97442318(JavaScriptProfile):
    owner: str = "akiran"
    repo: str = "react-slick"
    commit: str = "97442318e9a442bd4a84eb25133ef62087f98232"
    test_cmd: str = "npm test -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

# Install system dependencies
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies
RUN npm install

# Set the default command
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Pdfmake700b4fa9(JavaScriptProfile):
    owner: str = "bpampuch"
    repo: str = "pdfmake"
    commit: str = "700b4fa9f71af1e6fec7c55373386ed711ae397b"
    test_cmd: str = "npm run test"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies
RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Multer368c8a10(JavaScriptProfile):
    owner: str = "expressjs"
    repo: str = "multer"
    commit: str = "368c8a10cca11854cf17c24029fefd1eafb1c059"
    test_cmd: str = "npm test -- --reporter spec"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Pdfkit224971a3(JavaScriptProfile):
    owner: str = "foliojs"
    repo: str = "pdfkit"
    commit: str = "224971a3c23c2bb3b722fa175b558f59bff1b386"
    test_cmd: str = "yarn test --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    libcairo2-dev \
    libpango1.0-dev \
    libjpeg-dev \
    libgif-dev \
    librsvg2-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /{ENV_NAME}

# Enable corepack to use the yarn version specified in package.json
RUN corepack enable

# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies
RUN yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Mathjsef44f12a(JavaScriptProfile):
    owner: str = "josdejong"
    repo: str = "mathjs"
    commit: str = "ef44f12a37f6a227a37aef94c78cd6c62b241ea9"
    test_cmd: str = "npm run test:src -- --reporter spec"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

# Install git and other system dependencies if needed
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies
RUN npm install

# Build the project (as it seems to have a build step that generates lib/ which might be needed for tests)
RUN npm run build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)  # Default fallback


@dataclass
class Jqueryd31238e7(JavaScriptProfile):
    owner: str = "jquery"
    repo: str = "jquery"
    commit: str = "d31238e7899d61b0777ecea93e97442e55ad278c"
    test_cmd: str = "npm run test:browserless -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies
RUN npm install

# Default command
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_qunit(log)


@dataclass
class Koae0ba8ef3(JavaScriptProfile):
    owner: str = "koajs"
    repo: str = "koa"
    commit: str = "e0ba8ef39d27fe5dae5492f9fe753d155124f994"
    test_cmd: str = "node --test"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Layui349b924f(JavaScriptProfile):
    owner: str = "layui"
    repo: str = "layui"
    commit: str = "349b924fc61a336e8775b8324bb766c9104bebce"
    test_cmd: str = "npm test -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

# Install git
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies
RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Mocha441c32aa(JavaScriptProfile):
    owner: str = "mochajs"
    repo: str = "mocha"
    commit: str = "441c32aa076f2b0e1c1ba39d67f267c46c1dee4b"
    test_cmd: str = "npm run test-node:unit"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

# Install git
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies
RUN npm install

# Set the default command
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Reactnativeweba9de220b(JavaScriptProfile):
    owner: str = "necolas"
    repo: str = "react-native-web"
    commit: str = "a9de220ba9e65bdea540fb5322ffb1da2b0bf442"
    test_cmd: str = "npm run unit:dom -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory

# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies
RUN npm install

# Set default command
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Piskela6b9c02d(JavaScriptProfile):
    owner: str = "piskelapp"
    repo: str = "piskel"
    commit: str = "a6b9c02daefceb10093f71e92d52d16920ccb16e"
    test_cmd: str = "npm run unit-tests"

    @property
    def dockerfile(self):
        return f"""FROM node:18-bullseye-slim

# Install system dependencies for Playwright and Puppeteer
RUN apt-get update && apt-get install -y \
    git \
    libnss3 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libx11-6 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies
RUN npm install

# Install Playwright browsers and their dependencies
RUN npx playwright install --with-deps chromium

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_karma(log)


@dataclass
class Reduxsagaa4ace10d(JavaScriptProfile):
    owner: str = "redux-saga"
    repo: str = "redux-saga"
    commit: str = "a4ace10dc3ff182828cd3ee7469f6667e08ceb62"
    test_cmd: str = "yarn test --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

# Install git for cloning and patching
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies using yarn (yarn.lock is present)
RUN yarn install --frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Riotde59df6f(JavaScriptProfile):
    owner: str = "riot"
    repo: str = "riot"
    commit: str = "de59df6f8129c7e13d2c2559ec69de286d78345a"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y \
    git \
    make \
    procps \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Svgo581fe687(JavaScriptProfile):
    owner: str = "svg"
    repo: str = "svgo"
    commit: str = "581fe687825740e425012bbdf6491ee4bbc9dc65"
    test_cmd: str = "yarn cross-env NODE_OPTIONS=--experimental-vm-modules jest --maxWorkers=4 --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

# Install git for cloning the repository
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Enable corepack to use the yarn version specified in package.json and install dependencies
RUN corepack enable && yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Brunod39d5ef5(JavaScriptProfile):
    owner: str = "usebruno"
    repo: str = "bruno"
    commit: str = "d39d5ef5750a98e983a45c85aa7b1378b4525004"
    test_cmd: str = "npm test --workspaces --if-present -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm run setup

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Webtorrent02bfbc52(JavaScriptProfile):
    owner: str = "webtorrent"
    repo: str = "webtorrent"
    commit: str = "02bfbc529af17371894af77eecb205e781552fe4"
    test_cmd: str = "npx tape test/*.js test/node/*.js"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

# Install system dependencies for native modules
RUN apt-get update && apt-get install -y \
    python3 \
    make \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies
RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_tap(log)


@dataclass
class Whydidyourender3ec3512d(JavaScriptProfile):
    owner: str = "welldone-software"
    repo: str = "why-did-you-render"
    commit: str = "3ec3512d750c49448fe2241e26d05db9e42f0c21"
    test_cmd: str = "yarn test --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies
RUN yarn install

# Keep the container running
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Eleventy29a22aa0(JavaScriptProfile):
    owner: str = "11ty"
    repo: str = "eleventy"
    commit: str = "29a22aa0c431c169d5434d50d86d4e72637d60d5"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install

CMD ["npm", "test"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Workbox62b9d8ba(JavaScriptProfile):
    owner: str = "GoogleChrome"
    repo: str = "workbox"
    commit: str = "62b9d8ba8eb3c1a2ab8aac9d84c90cda7865d6a3"
    test_cmd: str = "npm run test_node -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

# Install system dependencies required for building some native modules and git for cloning
RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies and build the project (required for tests to find built modules)
RUN npm ci && npm run build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Habitica1178da3a(JavaScriptProfile):
    owner: str = "HabitRPG"
    repo: str = "habitica"
    commit: str = "1178da3a26466be153e31d916c3461060204313d"
    test_cmd: str = "npm run test:api:unit -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# The postinstall script in package.json handles:
# 1. gulp build
# 2. cd website/client && npm install
# We need to ensure dependencies for the main app are installed first.
# Also, Habitica expects a config.json file.
RUN cp config.json.example config.json
RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Modernizrbab42e37(JavaScriptProfile):
    owner: str = "Modernizr"
    repo: str = "Modernizr"
    commit: str = "bab42e37f8f2951a5fedffa010cb01c481b14348"
    test_cmd: str = "npm test -- --verbose --reporter spec"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

# Install system dependencies including git and chromium for puppeteer/mocha-headless-chrome
RUN apt-get update && apt-get install -y \
    git \
    wget \
    gnupg \
    ca-certificates \
    chromium \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies, skipping puppeteer browser download since we use system chromium
ENV PUPPETEER_SKIP_DOWNLOAD=true
ENV CHROME_PATH=/usr/bin/chromium
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
RUN npm install

# Set CMD
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Falcor39d64776(JavaScriptProfile):
    owner: str = "Netflix"
    repo: str = "falcor"
    commit: str = "39d64776cf9d87781b2791615dcbae73b2bcd2e1"
    test_cmd: str = "npm run test:only -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install --legacy-peer-deps

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Pm2ba62cae9(JavaScriptProfile):
    owner: str = "Unitech"
    repo: str = "pm2"
    commit: str = "ba62cae9b9b7116ee758b70f538919a52515fa26"
    test_cmd: str = "npm run test:unit -- --reporter spec"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git procps bc python3 && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Audiobookshelf47ea6b50(JavaScriptProfile):
    owner: str = "advplyr"
    repo: str = "audiobookshelf"
    commit: str = "47ea6b50922e310acf523dbfaa4abd2f43d61940"
    test_cmd: str = "npm test -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-bullseye-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install root dependencies
RUN npm ci

# Install client dependencies and build client
RUN cd client && npm ci && npm run generate

# Ensure we are back in root
WORKDIR /{ENV_NAME}

CMD ["npm", "start"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Sailsfd71efbd(JavaScriptProfile):
    owner: str = "balderdashy"
    repo: str = "sails"
    commit: str = "fd71efbd4f13a31525d9fa936560d3c99efe3da6"
    test_cmd: str = "npm run custom-tests -- --reporter spec"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Vuebootstrapvue9a246f45(JavaScriptProfile):
    owner: str = "bootstrap-vue"
    repo: str = "bootstrap-vue"
    commit: str = "9a246f45fc813f161df291fc7d6197febf8afaf4"
    test_cmd: str = "yarn jest --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-bullseye-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN chmod u+x scripts/build.sh
RUN yarn install --frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Nodepostgres341cb60b(JavaScriptProfile):
    owner: str = "brianc"
    repo: str = "node-postgres"
    commit: str = "341cb60b0f4579382c7f65be97815c3fe4621064"
    test_cmd: str = "service postgresql start && sleep 5 && sudo -u postgres psql -c \"ALTER USER postgres WITH PASSWORD 'postgres';\" && export PGPASSWORD=postgres && export PGUSER=postgres && export PGHOST=localhost && yarn test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y \
    git \
    make \
    python3 \
    g++ \
    build-essential \
    libpq-dev \
    postgresql \
    postgresql-contrib \
    sudo \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN yarn install
RUN yarn build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Claudecodetemplates63298a5f(JavaScriptProfile):
    owner: str = "davila7"
    repo: str = "claude-code-templates"
    commit: str = "63298a5f286905e4f79e2bf8fadb23e4d5a7bbe5"
    test_cmd: str = "cd api && npm test -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install && \
    cd cli-tool && npm install && \
    cd ../api && npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Jsemotionb882bcba(JavaScriptProfile):
    owner: str = "emotion-js"
    repo: str = "emotion"
    commit: str = "b882bcba85132554992e4bd49e94c95939bbf810"
    test_cmd: str = "yarn jest --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*

RUN corepack enable


RUN git clone --depth 1 https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Enzyme61e1b47c(JavaScriptProfile):
    owner: str = "enzymejs"
    repo: str = "enzyme"
    commit: str = "61e1b47c4bdc4509b2ac286c0d3ae3df172d26f0"
    test_cmd: str = "npm run react 16 && npm run test:only -- --reporter spec"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

ENV NODE_OPTIONS="--max-old-space-size=4096"
RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Recoilc1b97f3a(JavaScriptProfile):
    owner: str = "facebookexperimental"
    repo: str = "Recoil"
    commit: str = "c1b97f3a0117cad76cbc6ab3cb06d89a9ce717af"
    test_cmd: str = "yarn test"

    @property
    def dockerfile(self):
        return f"""FROM node:18

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Superagent3ef36761(JavaScriptProfile):
    owner: str = "forwardemail"
    repo: str = "superagent"
    commit: str = "3ef367619fbb2a8d07082238892ae12dafe4b0b0"
    test_cmd: str = "./node_modules/.bin/mocha --require should --trace-warnings --throw-deprecation --reporter spec --slow 2000 --timeout 5000 --exit test/*.js test/node/*.js"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git build-essential python3 && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install

RUN npm run build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Supertestd7997513(JavaScriptProfile):
    owner: str = "forwardemail"
    repo: str = "supertest"
    commit: str = "d7997513dcfb2f918e617f48ea4d56006aa0c3c3"
    test_cmd: str = "npm test -- --reporter spec"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
CMD ["npm", "test"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Revealjs76dc9006(JavaScriptProfile):
    owner: str = "hakimel"
    repo: str = "reveal.js"
    commit: str = "76dc90065968d4ead13692489c2c4e506c50e382"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

# Install system dependencies for git and Puppeteer
RUN apt-get update && apt-get install -y \
    git \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libc6 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libgcc1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libstdc++6 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    lsb-release \
    wget \
    xdg-utils \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies
RUN npm install

# Build the project (some tests might depend on built assets)
RUN npm run build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Handsontable51a9db2a(JavaScriptProfile):
    owner: str = "handsontable"
    repo: str = "handsontable"
    commit: str = "51a9db2a6c8b584434bcffd97bdef2a0de362845"
    test_cmd: str = "pnpm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@10.12.2


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN pnpm install && pnpm run build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Joi048fe05b(JavaScriptProfile):
    owner: str = "hapijs"
    repo: str = "joi"
    commit: str = "048fe05b82355f445c5aab7881d836b2e9811296"
    test_cmd: str = "npx lab -t 100 -a @hapi/code -L -Y -v"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Impressjsc9f6c674(JavaScriptProfile):
    owner: str = "impress"
    repo: str = "impress.js"
    commit: str = "c9f6c67457ceee5a011e554f67c447113640777d"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:18

RUN apt-get update && apt-get install -y \
    git \
    wget \
    gnupg \
    ca-certificates \
    libgconf-2-4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libgdk-pixbuf2.0-0 \
    libgtk-3-0 \
    libgbm-dev \
    libnss3 \
    libxss1 \
    libasound2 \
    libxtst6 \
    xfonts-75dpi \
    xfonts-base \
    fonts-liberation \
    libappindicator3-1 \
    lsb-release \
    xdg-utils \
    libx11-xcb1 \
    libxcb-dri3-0 \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install

RUN npm run build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jasmine(log)


@dataclass
class Htmlwebpackpluginfdef1b4e(JavaScriptProfile):
    owner: str = "jantimon"
    repo: str = "html-webpack-plugin"
    commit: str = "fdef1b4e7847413e67f7826120073ea282bfe927"
    test_cmd: str = "npm run test:only -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install --legacy-peer-deps

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Backbonecbeb7e31(JavaScriptProfile):
    owner: str = "jashkenas"
    repo: str = "backbone"
    commit: str = "cbeb7e31d95f64dbe92f2202c1131858f905280e"
    test_cmd: str = "npx karma start --browsers ChromeHeadlessNoSandbox --single-run"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git chromium && rm -rf /var/lib/apt/lists/*

ENV CHROME_BIN=/usr/bin/chromium


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install && npm install karma-chrome-launcher --save-dev

# Add ChromeHeadlessNoSandbox launcher to karma.conf.js
RUN sed -i "s/customLaunchers: {{/customLaunchers: {{\\n        ChromeHeadlessNoSandbox: {{\\n            base: 'ChromeHeadless',\\n            flags: ['--no-sandbox']\\n        }},/" karma.conf.js

# Build debug-info.js which is required by tests
RUN npm run build-debug

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_karma(log)


@dataclass
class Hyperapp5a113fa0(JavaScriptProfile):
    owner: str = "jorgebucaran"
    repo: str = "hyperapp"
    commit: str = "5a113fa00450302be9234e0a74ee634ed5574243"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Jsoneditoreebd07cb(JavaScriptProfile):
    owner: str = "josdejong"
    repo: str = "jsoneditor"
    commit: str = "eebd07cb8b8d89259dc9aeabd3174aa16fb415e3"
    test_cmd: str = "npm test -- --reporter spec"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Uptimekumad60feb90(JavaScriptProfile):
    owner: str = "louislam"
    repo: str = "uptime-kuma"
    commit: str = "d60feb909cc3c9f2003db162c226e37b9079d9f5"
    test_cmd: str = "npm run test-backend"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    python3 \
    build-essential \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies
RUN npm install

# Build the frontend
RUN npm run build

# Default command
CMD ["npm", "start"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Markoc4980211(JavaScriptProfile):
    owner: str = "marko-js"
    repo: str = "marko"
    commit: str = "c4980211fa5d26118fbc3c66eb7a3b6b8893d53a"
    test_cmd: str = "env MARKO_DEBUG=1 ./node_modules/.bin/mocha --reporter spec"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install && npm run build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Mdx1b31316e(JavaScriptProfile):
    owner: str = "mdx-js"
    repo: str = "mdx"
    commit: str = "1b31316e2a60005fec14b2dec2219b59cd81f449"
    test_cmd: str = "npm run test-api --workspaces --if-present"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install

RUN npm run build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class PapaParsecc8c801f(JavaScriptProfile):
    owner: str = "mholt"
    repo: str = "PapaParse"
    commit: str = "cc8c801f83fa2bdbf4baab5048e79b0911d9aa58"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y \
    git \
    chromium \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
RUN sed -i "s/'-f'/'-a', '[\"--no-sandbox\"]', '-f'/" tests/test.js

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Materialuibbcd5eae(JavaScriptProfile):
    owner: str = "mui"
    repo: str = "material-ui"
    commit: str = "bbcd5eae5077ce8dece3a1480e299ac4665186f8"
    test_cmd: str = "pnpm test:node run"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@10.25.0


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Nightwatch646fc9cd(JavaScriptProfile):
    owner: str = "nightwatchjs"
    repo: str = "nightwatch"
    commit: str = "646fc9cd846d7db699d525eb9939dbc5cd59aa59"
    test_cmd: str = "npm test -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install --ignore-scripts

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Nock215cd2a8(JavaScriptProfile):
    owner: str = "nock"
    repo: str = "nock"
    commit: str = "215cd2a8f1780960e5984fdcd1ea84cd42df463d"
    test_cmd: str = "npm test -- --reporter spec"

    @property
    def dockerfile(self):
        return f"""FROM node:20

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class NoVNC8e1ebdff(JavaScriptProfile):
    owner: str = "novnc"
    repo: str = "noVNC"
    commit: str = "8e1ebdffba02e651c399dacef841f8941f6ad6e4"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    chromium \
    ca-certificates \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# Create a wrapper for chromium to always include --no-sandbox
RUN mv /usr/bin/chromium /usr/bin/chromium-orig && \
    echo -e '#!/bin/bash\\n/usr/bin/chromium-orig --no-sandbox "$@"' > /usr/bin/chromium && \
    chmod +x /usr/bin/chromium

# Set environment variables
ENV CHROME_BIN=/usr/bin/chromium
ENV TEST_BROWSER_NAME=ChromeHeadless


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install dependencies
RUN npm install

# Command to keep container running
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class JsPDFbfeae27a(JavaScriptProfile):
    owner: str = "parallax"
    repo: str = "jsPDF"
    commit: str = "bfeae27a27087f9a3279031959086cb7ff7bcaee"
    test_cmd: str = "npm run test-node"

    @property
    def dockerfile(self):
        return rf"""FROM node:18

RUN apt-get update && apt-get install -y \
    git \
    libnss3 \
    libatk-bridge2.0-0 \
    libx11-xcb1 \
    libxcb-dri3-0 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxtst6 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libgcc1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libstdc++6 \
    libv4l-0 \
    libxkbcommon0 \
    libasound2 \
    wget \
    gnupg \
    --no-install-recommends \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list' \
    && apt-get update \
    && apt-get install -y google-chrome-stable --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_BIN=/usr/bin/google-chrome-stable


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install

# Inject custom launcher into karma.conf.js
RUN sed -i "s/browsers: \\['Chrome'\\]/browsers: ['ChromeHeadlessNoSandbox']/" test/unit/karma.conf.js && \
    sed -i "/reporters: \\[/i     customLaunchers: {{\\n      ChromeHeadlessNoSandbox: {{\\n        base: 'ChromeHeadless',\\n        flags: ['--no-sandbox', '--disable-setuid-sandbox']\\n      }}\\n    }}," test/unit/karma.conf.js

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Filepond3107602c(JavaScriptProfile):
    owner: str = "pqina"
    repo: str = "filepond"
    commit: str = "3107602c21555108d5c60def540cd58617c84192"
    test_cmd: str = "npm test -- --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Reacttransitiongroup2989b5b8(JavaScriptProfile):
    owner: str = "reactjs"
    repo: str = "react-transition-group"
    commit: str = "2989b5b87b4b4d1001f21c8efa503049ffb4fe8d"
    test_cmd: str = "npm run testonly"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install --legacy-peer-deps

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Reactmarkdownfda7fa56(JavaScriptProfile):
    owner: str = "remarkjs"
    repo: str = "react-markdown"
    commit: str = "fda7fa560bec901a6103e195f9b1979dab543b17"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Nodemonfd5c1130(JavaScriptProfile):
    owner: str = "remy"
    repo: str = "nodemon"
    commit: str = "fd5c11309c0eb4618af4d6b932d600bdb442774c"
    test_cmd: str = "for FILE in test/**/*.test.js; do echo $FILE; TEST=1 ./node_modules/.bin/mocha --exit --timeout 30000 $FILE || true; sleep 1; done"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Evergreen9b774aee(JavaScriptProfile):
    owner: str = "segmentio"
    repo: str = "evergreen"
    commit: str = "9b774aee2d794f6cf2f73a054bd33066ca5898a9"
    test_cmd: str = "yarn jest --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN yarn install --frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Serverless2d2cff12(JavaScriptProfile):
    owner: str = "serverless"
    repo: str = "serverless"
    commit: str = "2d2cff12200dc62970d3ec5c430d848180a29042"
    test_cmd: str = "npm test -- --reporter spec"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Jssqljs52e5649f(JavaScriptProfile):
    owner: str = "sql-js"
    repo: str = "sql.js"
    owner: str = "sql-js"
    repo: str = "sql.js"
    commit: str = "52e5649f3a3a2a46aa4ad58a79d118c22f56cf30"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM emscripten/emsdk:latest

RUN apt-get update && apt-get install -y git make python3 unzip curl libdigest-sha3-perl && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN npm install
RUN npm run build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Jsonserver89a34a44(JavaScriptProfile):
    owner: str = "typicode"
    repo: str = "json-server"
    commit: str = "89a34a44b7a6a5311dc84f3b8a1b8b45c0905aea"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
CMD ["npm", "start"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Webpackead3dc97(JavaScriptProfile):
    owner: str = "webpack"
    repo: str = "webpack"
    commit: str = "ead3dc97fee131d4bfe62127ee824b1d7854e537"
    test_cmd: str = (
        "yarn test:base --verbose --testMatch '<rootDir>/test/*.basictest.js'"
    )

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}

RUN yarn install && yarn setup

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Ws84392554(JavaScriptProfile):
    owner: str = "websockets"
    repo: str = "ws"
    commit: str = "843925544e2f4cffe445e0179947f56d6c5b608f"
    test_cmd: str = "npm test -- --reporter spec"
    timeout: int = 300

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


# Register all JavaScript profiles with the global registry
for name, obj in list(globals().items()):
    if (
        isinstance(obj, type)
        and issubclass(obj, JavaScriptProfile)
        and obj.__name__ != "JavaScriptProfile"
    ):
        registry.register_profile(obj)

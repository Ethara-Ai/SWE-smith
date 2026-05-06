import json
import re
from dataclasses import dataclass, field

from swesmith.constants import ENV_NAME
from swebench.harness.constants import TestStatus
from swesmith.profiles.base import RepoProfile, registry


def parse_log_rspec_json(log: str) -> dict[str, str]:
    """Parse RSpec JSON output (from --format json) into a test status map.

    Extracts the JSON object from the log (which may contain other output
    before/after) and maps each example's full_description to PASSED/FAILED.
    """
    # Find the start of the RSpec JSON — look for {"version" or {"examples"
    match = re.search(r"\{\"(?:version|examples)", log)
    if not match:
        return {}
    start = match.start()
    # Find the last closing brace and try to parse from start to there.
    # RSpec JSON can be very large (10MB+), so avoid character-by-character walks.
    end = log.rfind("}")
    if end < start:
        return {}

    try:
        data = json.loads(log[start : end + 1])
    except json.JSONDecodeError:
        return {}

    test_status_map = {}
    for example in data.get("examples", []):
        desc = example.get("full_description", "").strip()
        if not desc:
            continue
        status = example.get("status", "")
        if status == "passed":
            test_status_map[desc] = TestStatus.PASSED.value
        elif status == "failed":
            test_status_map[desc] = TestStatus.FAILED.value
    return test_status_map


def parse_log_ruby_test(log: str) -> dict[str, str]:
    """Parse Ruby test output in either Minitest or test-unit verbose format.

    Minitest verbose:
        TestClass#test_name = X.XX s = .

    test-unit verbose (--verbose):
        TestClassName:
          test_name:     .: (0.001234)
          test_other:    F: (0.002345)
    """
    test_status_map = {}
    current_class = None
    for line in log.splitlines():
        stripped = line.strip()
        # Minitest verbose: "TestClass#test_name = X.XX s = ."
        if "#test_" in stripped and " = " in stripped:
            parts = stripped.rsplit(" = ", 1)
            if len(parts) == 2:
                status_char = parts[1].strip()
                test_name = parts[0].rsplit(" = ", 1)[0].strip()
                if status_char == ".":
                    test_status_map[test_name] = TestStatus.PASSED.value
                elif status_char == "F":
                    test_status_map[test_name] = TestStatus.FAILED.value
                elif status_char == "E":
                    test_status_map[test_name] = TestStatus.ERROR.value
            continue
        # test-unit: class header line like "TestClassName:"
        if stripped.endswith(":") and stripped[0].isupper() and " " not in stripped:
            current_class = stripped[:-1]
            continue
        # test-unit verbose: "  test_name:   .: (0.001234)"
        if current_class and (
            ".: (" in stripped or "F: (" in stripped or "E: (" in stripped
        ):
            match = re.match(r"^(\S+):\s+([.FE]):\s+\(", stripped)
            if match:
                test_name = f"{current_class}#{match.group(1)}"
                status_char = match.group(2)
                if status_char == ".":
                    test_status_map[test_name] = TestStatus.PASSED.value
                elif status_char == "F":
                    test_status_map[test_name] = TestStatus.FAILED.value
                elif status_char == "E":
                    test_status_map[test_name] = TestStatus.ERROR.value
    return test_status_map


@dataclass
class RubyProfile(RepoProfile):
    """Profile for Ruby repositories."""

    test_cmd: str = "bundle exec rake test"
    exts: list[str] = field(default_factory=lambda: [".rb"])
    ruby_version: str = "3.3"

    def extract_entities(
        self,
        dirs_exclude: list[str] | None = None,
        dirs_include: list[str] = [],
        exclude_tests: bool = True,
        max_entities: int = -1,
    ) -> list:
        """Override to exclude Ruby-specific vendored/generated directories."""
        if dirs_exclude is None:
            dirs_exclude = [
                "vendor",
                ".bundle",
                "tmp",
                "pkg",
                "doc",
                "coverage",
            ]

        return super().extract_entities(
            dirs_exclude=dirs_exclude,
            dirs_include=dirs_include,
            exclude_tests=exclude_tests,
            max_entities=max_entities,
        )

    def _is_test_path(self, root: str, file: str) -> bool:
        if super()._is_test_path(root, file):
            return True
        dirs = root.split("/")
        if "spec" in dirs:
            return True
        if file.endswith("_spec.rb"):
            return True
        return False

    def log_parser(self, log: str):
        # Try RSpec JSON first (repos using --format json)
        result = parse_log_rspec_json(log)
        if result:
            return result
        # Fall back to Minitest/test-unit verbose format
        return parse_log_ruby_test(log)

    @property
    def dockerfile(self):
        return f"""FROM ruby:{self.ruby_version}
ENV TZ=Etc/UTC

RUN apt update && apt install -y wget git build-essential \
&& rm -rf /var/lib/apt/lists/*

RUN git clone {self.mirror_url} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN bundle install || true
RUN {self.test_cmd} || true
CMD ["/bin/bash"]
"""


# SWE-bench_Multilingual repos


@dataclass
class Faker73fe1745(RubyProfile):
    owner: str = "faker-ruby"
    repo: str = "faker"
    commit: str = "73fe17456a75b0f30a78436b6bea44a1a90ec3df"
    test_cmd: str = "bundle exec rake test TESTOPTS='--verbose'"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )


@dataclass
class Rubocop7af083d7(RubyProfile):
    owner: str = "rubocop"
    repo: str = "rubocop"
    commit: str = "7af083d724ad0249af2cc753a47b0cfa8f2b43cf"
    test_cmd: str = "bundle exec rspec --format json"
    timeout: int = 180
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )


@dataclass
class Jekyll202df571(RubyProfile):
    owner: str = "jekyll"
    repo: str = "jekyll"
    commit: str = "202df571314ba1d18e9fccd81d12aaad4a703c38"
    test_cmd: str = "bundle exec rake test"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )


@dataclass
class Fluentd7a7e9fe8(RubyProfile):
    owner: str = "fluent"
    repo: str = "fluentd"
    commit: str = "7a7e9fe8ca9e2672d471b157e446067d6dd63381"
    test_cmd: str = "bundle exec rake test TESTOPTS='--verbose'"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )

    @property
    def dockerfile(self):
        return f"""FROM ruby:{self.ruby_version}
ENV TZ=Etc/UTC

RUN apt update && apt install -y wget git build-essential \
    libyajl-dev libev-dev \
&& rm -rf /var/lib/apt/lists/*

RUN git clone {self.mirror_url} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN bundle install || true
RUN {self.test_cmd} || true
CMD ["/bin/bash"]
"""


@dataclass
class Fastlane618633c6(RubyProfile):
    owner: str = "fastlane"
    repo: str = "fastlane"
    commit: str = "618633c640bce40ececc86beee1dfbc828d803e4"
    test_cmd: str = "bundle exec rspec --format json"
    timeout: int = 300
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )


@dataclass
class Fpmf51ba16f(RubyProfile):
    owner: str = "jordansissel"
    repo: str = "fpm"
    commit: str = "f51ba16fe8659cf2a4996a8e2b2e6a142bbc5b99"
    test_cmd: str = "bundle exec rspec --format json"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )

    @property
    def dockerfile(self):
        return f"""FROM ruby:{self.ruby_version}
ENV TZ=Etc/UTC

RUN apt update && apt install -y wget git build-essential \
    rpm squashfs-tools \
&& rm -rf /var/lib/apt/lists/*

RUN git clone {self.mirror_url} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN bundle install || true
RUN {self.test_cmd} || true
CMD ["/bin/bash"]
"""


# Additional repos (alphabetical by repo name)


@dataclass
class Brakeman565e7a7b(RubyProfile):
    owner: str = "presidentbeef"
    repo: str = "brakeman"
    commit: str = "565e7a7b1dfc654d086519c0735bcaf884d9f13c"
    test_cmd: str = "bundle exec rake test TESTOPTS='--verbose'"
    timeout: int = 180


@dataclass
class Concurrentruby9b2dbf71(RubyProfile):
    owner: str = "ruby-concurrency"
    repo: str = "concurrent-ruby"
    commit: str = "9b2dbf712896a638a73d2fa221206961c8d6484d"
    test_cmd: str = "bundle exec rspec --format json"


@dataclass
class Csv79eb55ab(RubyProfile):
    owner: str = "ruby"
    repo: str = "csv"
    commit: str = "79eb55aba206c2e3f2ebccdb83d86f7487604800"
    test_cmd: str = "bundle exec rake test"


@dataclass
class Devise7ca7ed9c(RubyProfile):
    owner: str = "heartcombo"
    repo: str = "devise"
    commit: str = "7ca7ed9c174525a4d36167441b35af4a0991b6af"
    test_cmd: str = "bundle exec rake test TESTOPTS='--verbose'"

    @property
    def dockerfile(self):
        return f"""FROM ruby:{self.ruby_version}
ENV TZ=Etc/UTC

RUN apt update && apt install -y wget git build-essential \
    libsqlite3-dev \
&& rm -rf /var/lib/apt/lists/*

RUN git clone {self.mirror_url} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN bundle install || true
RUN {self.test_cmd} || true
CMD ["/bin/bash"]
"""


@dataclass
class Dryvalidation817f125b(RubyProfile):
    owner: str = "dry-rb"
    repo: str = "dry-validation"
    commit: str = "817f125b1f31039c9240c13cfecb7097ea5cc625"
    test_cmd: str = "bundle exec rspec --format json"


@dataclass
class Factorybot5d399535(RubyProfile):
    owner: str = "thoughtbot"
    repo: str = "factory_bot"
    commit: str = "5d399535578de5d1c32a76d6d91a8f816ec01965"
    test_cmd: str = "bundle exec rspec --format json"

    @property
    def dockerfile(self):
        return f"""FROM ruby:{self.ruby_version}
ENV TZ=Etc/UTC

RUN apt update && apt install -y wget git build-essential \
    libsqlite3-dev \
&& rm -rf /var/lib/apt/lists/*

RUN git clone {self.mirror_url} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN bundle install || true
RUN {self.test_cmd} || true
CMD ["/bin/bash"]
"""


@dataclass
class Foremanf65ddba8(RubyProfile):
    owner: str = "ddollar"
    repo: str = "foreman"
    commit: str = "f65ddba83932bd4670e014389d6e27ea1e20b469"
    test_cmd: str = "bundle exec rspec --format json"


@dataclass
class Grapec464ffad(RubyProfile):
    owner: str = "ruby-grape"
    repo: str = "grape"
    commit: str = "c464ffad4fb703c11d89f1004ec6901be681be19"
    test_cmd: str = "bundle exec rspec --format json"
    timeout: int = 180


@dataclass
class Hashie3988742e(RubyProfile):
    owner: str = "hashie"
    repo: str = "hashie"
    commit: str = "3988742ebc7edb0500c67c4463ce54cd318d7af9"
    test_cmd: str = "bundle exec rspec --format json"


@dataclass
class Liquid1954a265(RubyProfile):
    owner: str = "Shopify"
    repo: str = "liquid"
    commit: str = "1954a2655cf4d427b6c9169354832638740f2db5"
    test_cmd: str = "bundle exec rake test TESTOPTS='--verbose'"
    timeout: int = 180


@dataclass
class Pry13564026(RubyProfile):
    owner: str = "pry"
    repo: str = "pry"
    commit: str = "135640262879544c6bfecbf3e78511289bfe956c"
    test_cmd: str = "bundle exec rspec --format json"


@dataclass
class Pundit06318683(RubyProfile):
    owner: str = "varvet"
    repo: str = "pundit"
    commit: str = "06318683c960066a2e499341cb372e0ff4540334"
    test_cmd: str = "bundle exec rspec --format json"


@dataclass
class Rack1551230b(RubyProfile):
    owner: str = "rack"
    repo: str = "rack"
    commit: str = "1551230b9868c5981d8614e487646dd634a0eb41"
    test_cmd: str = "bundle exec rake test TESTOPTS='--verbose'"


@dataclass
class Simplecovea9e9213(RubyProfile):
    owner: str = "simplecov-ruby"
    repo: str = "simplecov"
    commit: str = "ea9e92134ad2844a721c93ce8eaa63104a65e4fc"
    test_cmd: str = "bundle exec rspec --format json"


@dataclass
class Sinatra5236d345(RubyProfile):
    owner: str = "sinatra"
    repo: str = "sinatra"
    commit: str = "5236d3459b8b9015e5ce21ddd0c6beb0db4081d4"
    test_cmd: str = "bundle exec rake test TESTOPTS='--verbose'"
    timeout: int = 180

    @property
    def dockerfile(self):
        return f"""FROM ruby:{self.ruby_version}
ENV TZ=Etc/UTC

RUN apt update && apt install -y wget git build-essential \
    libxml2-dev libxslt-dev \
&& rm -rf /var/lib/apt/lists/*

RUN git clone {self.mirror_url} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN bundle install || true
RUN {self.test_cmd} || true
CMD ["/bin/bash"]
"""


@dataclass
class Vcr6f376c11(RubyProfile):
    owner: str = "vcr"
    repo: str = "vcr"
    commit: str = "6f376c11c23eee7fd029f7735ac40ade2855fcd0"
    test_cmd: str = "bundle exec rspec --format json"

    @property
    def dockerfile(self):
        return f"""FROM ruby:{self.ruby_version}
ENV TZ=Etc/UTC

RUN apt update && apt install -y wget git build-essential \
    libcurl4-openssl-dev \
&& rm -rf /var/lib/apt/lists/*

RUN git clone {self.mirror_url} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN bundle install || true
RUN {self.test_cmd} || true
CMD ["/bin/bash"]
"""


# Register all Ruby profiles with the global registry
for name, obj in list(globals().items()):
    if (
        isinstance(obj, type)
        and issubclass(obj, RubyProfile)
        and obj.__name__ != "RubyProfile"
    ):
        registry.register_profile(obj)

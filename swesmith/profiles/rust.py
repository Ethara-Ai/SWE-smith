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
from swesmith.constants import ENV_NAME
from swesmith.profiles.base import RepoProfile, registry


@dataclass
class RustProfile(RepoProfile):
    """
    Profile for Rust repositories.
    """

    test_cmd: str = "cargo test --verbose"
    exts: list[str] = field(default_factory=lambda: [".rs"])
    rust_version: str = "1.88"
    _test_name_to_files_cache: dict[str, set[str]] = field(
        default=None, init=False, repr=False
    )

    @staticmethod
    def _extract_test_fn_name(test_name: str) -> tuple[str, str | None]:
        """Extract the function name (and optional file path) from a Rust test name.

        Returns (fn_name, file_path | None). file_path is only set for doc tests.

        Handles these formats:
        - Bare function: "test_foo" -> ("test_foo", None)
        - Module-qualified: "module::sub::test_foo" -> ("test_foo", None)
        - Should-panic: "module::test_foo - should panic" -> ("test_foo", None)
        - Doc test: "src/lib.rs - Foo::bar (line 42)" -> ("src/lib.rs", "src/lib.rs")
        """
        if " - " in test_name:
            before, _after = test_name.split(" - ", 1)
            if ".rs" in before:
                # Doc test — the file path is the part before " - "
                return before.strip(), before.strip()
            else:
                # Should-panic or similar suffix — strip it, then extract fn name
                test_name = before.strip()

        # Take last :: segment (or entire string if no ::)
        if "::" in test_name:
            return test_name.rsplit("::", 1)[1], None
        return test_name, None

    def _build_test_name_to_files_map(self) -> dict[str, set[str]]:
        """Build a mapping from test function names to the files that contain them."""
        dest, cloned = self.clone()
        test_name_to_files: dict[str, set[str]] = {}

        # Regex to match #[test] and common async test attributes
        test_attr_re = re.compile(r"^\s*#\[(?:\w+::)*test")
        fn_re = re.compile(r"^\s*(?:pub(?:\s*\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)")
        # Attributes, blank lines, or comments that can appear between #[test] and fn
        intervening_re = re.compile(r"^\s*(?:#\[|//|$)")

        for dirpath, _, filenames in os.walk(dest):
            for fname in filenames:
                if not fname.endswith(".rs"):
                    continue

                full_path = os.path.join(dirpath, fname)
                relative_path = os.path.relpath(full_path, dest)

                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                except (OSError, UnicodeDecodeError):
                    continue

                expecting_fn = False
                for line in lines:
                    if test_attr_re.match(line):
                        expecting_fn = True
                        continue

                    if expecting_fn:
                        fn_match = fn_re.match(line)
                        if fn_match:
                            fn_name = fn_match.group(1)
                            test_name_to_files.setdefault(fn_name, set()).add(
                                relative_path
                            )
                            expecting_fn = False
                        elif not intervening_re.match(line):
                            # Not an attribute/comment/blank — stop expecting
                            expecting_fn = False

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
            fn_name, file_path = self._extract_test_fn_name(test_name)
            if file_path is not None:
                # Doc test — use the embedded file path directly
                f2p_files.add(file_path)
            elif fn_name in self._test_name_to_files_cache:
                f2p_files.update(self._test_name_to_files_cache[fn_name])

        p2p_files: set[str] = set()
        for test_name in instance[PASS_TO_PASS]:
            fn_name, file_path = self._extract_test_fn_name(test_name)
            if file_path is not None:
                p2p_files.add(file_path)
            elif fn_name in self._test_name_to_files_cache:
                p2p_files.update(self._test_name_to_files_cache[fn_name])

        return list(f2p_files), list(p2p_files)

    def log_parser(self, log: str):
        test_status_map = {}
        for line in log.splitlines():
            line = line.removeprefix("test ")
            if "... ok" in line:
                test_name = line.rsplit(" ... ", 1)[0].strip()
                test_status_map[test_name] = TestStatus.PASSED.value
            elif "... FAILED" in line:
                test_name = line.rsplit(" ... ", 1)[0].strip()
                test_status_map[test_name] = TestStatus.FAILED.value
        return test_status_map

    @property
    def dockerfile(self):
        return f"""FROM rust:{self.rust_version}
ENV TZ=Etc/UTC

RUN apt update && apt install -y wget git build-essential \
&& rm -rf /var/lib/apt/lists/*

RUN git clone {self.mirror_url} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN {self.test_cmd} || true
CMD ["/bin/bash"]
"""


@dataclass
class Rustbase6413f4fe86(RustProfile):
    owner: str = "marshallpierce"
    repo: str = "rust-base64"
    commit: str = "13f4fe86e565b3a8ed9402d3b8b1bcf83ab9817c"


@dataclass
class Clapd142d8f9(RustProfile):
    owner: str = "clap-rs"
    repo: str = "clap"
    commit: str = "d142d8f96650c49302aeab87814d5bf352dbf4db"
    test_cmd: str = "make test-full ARGS=--verbose"


@dataclass
class Hyper99f24345(RustProfile):
    owner: str = "hyperium"
    repo: str = "hyper"
    commit: str = "99f243450268cfc8125ff232e0b7de016a1dce5b"
    test_cmd: str = "cargo test --verbose --features full"


@dataclass
class Itertools5707384b(RustProfile):
    owner: str = "rust-itertools"
    repo: str = "itertools"
    commit: str = "5707384b6a3a675c65e12b96e71335e9ce857b16"
    test_cmd: str = "cargo test --verbose --all-features"


@dataclass
class Jsondc8003a8(RustProfile):
    owner: str = "serde-rs"
    repo: str = "json"
    commit: str = "dc8003a88e7142529cf4a7429c4778af31dadf50"


@dataclass
class Log67bc7e32(RustProfile):
    owner: str = "rust-lang"
    repo: str = "log"
    commit: str = "67bc7e32c68a4a8908d1016693418f12b43bab90"


@dataclass
class Semver7625c7aa(RustProfile):
    owner: str = "dtolnay"
    repo: str = "semver"
    commit: str = "7625c7aa3f0e8ba21e099d1765bcebcb72aa8816"


@dataclass
class Tokio02ff0833(RustProfile):
    owner: str = "tokio-rs"
    repo: str = "tokio"
    commit: str = "02ff0833e00adeb8cd451420f586f968deb70f78"
    test_cmd: str = "cargo test --verbose --features full -- --skip try_exists"
    timeout: int = 180
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )


@dataclass
class Uuidca0c85fe(RustProfile):
    owner: str = "uuid-rs"
    repo: str = "uuid"
    commit: str = "ca0c85fe2172e82e9d0c76e659f5c57ceb86d9a4"
    test_cmd: str = "cargo test --verbose --all-features"


@dataclass
class MdBook9190b5d0(RustProfile):
    owner: str = "rust-lang"
    repo: str = "mdBook"
    commit: str = "9190b5d0933188c6fae6e1962e70e941b014d814"
    test_cmd: str = "cargo test --workspace --verbose"


@dataclass
class Rustcsv4a3997e9(RustProfile):
    owner: str = "BurntSushi"
    repo: str = "rust-csv"
    commit: str = "4a3997e91d668ea1d8595bdef15625a77cf2308a"


@dataclass
class Html5ever201534ee(RustProfile):
    owner: str = "servo"
    repo: str = "html5ever"
    commit: str = "201534ee4f4c3db10dc558869555768d864278bf"

    @property
    def dockerfile(self):
        return f"""FROM rust:1.88
ENV TZ=Etc/UTC

RUN apt update && apt install -y wget git build-essential \
&& rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init
CMD ["/bin/bash"]
"""


@dataclass
class Byteorder5a82625f(RustProfile):
    owner: str = "BurntSushi"
    repo: str = "byteorder"
    commit: str = "5a82625fae462e8ba64cec8146b24a372b4d75c6"


@dataclass
class Chronoc6063e6f(RustProfile):
    owner: str = "chronotope"
    repo: str = "chrono"
    commit: str = "c6063e6f5a03a48c6feeac3eb5b51ab4cb902759"


@dataclass
class Rpds348d7ab6(RustProfile):
    owner: str = "orium"
    repo: str = "rpds"
    commit: str = "348d7ab6851b74aeca3f9d8f4aa12df2ddbb0a1c"


@dataclass
class Ripgrep4519153e(RustProfile):
    owner: str = "BurntSushi"
    repo: str = "ripgrep"
    commit: str = "4519153e5e461527f4bca45b042fff45c4ec6fb9"
    test_cmd: str = "cargo test --all --verbose"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "crates/searcher/src",
                "crates/regex/src",
                "crates/globset/src",
                "crates/core",
                "crates/core/flags",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM rust:1.88
ENV TZ=Etc/UTC

RUN apt update && apt install -y wget git build-essential \
&& rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN cargo build --release
CMD ["/bin/bash"]
"""



@dataclass
class Rustclippy98098dfe(RustProfile):
    owner: str = "rust-lang"
    repo: str = "rust-clippy"
    commit: str = "98098dfe6bb203425dece84610cbcff61771a9a6"


@dataclass
class Hexyl6ecc29b9(RustProfile):
    owner: str = "sharkdp"
    repo: str = "hexyl"
    commit: str = "6ecc29b9c8c84d08a7e860f7f69c22b113b480ea"


@dataclass
class Ohad07ff6bc(RustProfile):
    owner: str = "hatoo"
    repo: str = "oha"
    commit: str = "d07ff6bcde762d5cf6ef738509109824bce291af"


@dataclass
class Indicatifd65c4f06(RustProfile):
    owner: str = "console-rs"
    repo: str = "indicatif"
    commit: str = "d65c4f067464556ae0430d9903e6ff11174bb2b7"


@dataclass
class Melodyf4af9b48(RustProfile):
    owner: str = "yoav-lavi"
    repo: str = "melody"
    commit: str = "f4af9b4829555fedb687eb5f6f5755ce3c5ef738"


@dataclass
class RustOwl655bc5c3(RustProfile):
    owner: str = "cordx56"
    repo: str = "rust-owl"
    commit: str = "655bc5c37e59156954fa9af3e6466602e7dfa814"


@dataclass
class Quinnc9b40f10(RustProfile):
    owner: str = "quinn-rs"
    repo: str = "quinn"
    commit: str = "c9b40f1096a3301d699a0118359f5b176dde38d1"


@dataclass
class Shellharden1e629728(RustProfile):
    owner: str = "anordal"
    repo: str = "shellharden"
    commit: str = "1e629728e37d2e78dd3a06ed69cd54e2f66b87b0"


@dataclass
class Grex99cc3477(RustProfile):
    owner: str = "pemistahl"
    repo: str = "grex"
    commit: str = "99cc347707375e00514f938b76d885a201dfc110"


@dataclass
class Htmlq6e31bc81(RustProfile):
    owner: str = "mgdm"
    repo: str = "htmlq"
    commit: str = "6e31bc814332b2521f0316d0ed9bf0a1c521b6e6"


@dataclass
class Xh54387b5c(RustProfile):
    owner: str = "ducaale"
    repo: str = "xh"
    commit: str = "54387b5cfee5d7f97730d74230f311262527ba45"


@dataclass
class Lightningcssdf63db2c(RustProfile):
    owner: str = "parcel-bundler"
    repo: str = "lightningcss"
    commit: str = "df63db2c51c49a6a82f795f3a8988a3cd08ea03a"


@dataclass
class Miniserve02b3bbe7(RustProfile):
    owner: str = "svenstaro"
    repo: str = "miniserve"
    commit: str = "02b3bbe738bb2ed029185ab5c0b70865a72da234"


@dataclass
class Tailpsin6278437c(RustProfile):
    owner: str = "bensadeh"
    repo: str = "tailpsin"
    commit: str = "6278437c3d28f2e95201f3b0c8a471b8668eed5b"


@dataclass
class Sccachec0db872c(RustProfile):
    owner: str = "mozilla"
    repo: str = "sccache"
    commit: str = "c0db872c953f20fde2d45ab68ddc74d5100febbc"


@dataclass
class Boacee71775(RustProfile):
    owner: str = "boa-dev"
    repo: str = "boa"
    commit: str = "cee717758041349be02561a0676b78362aee69c7"


@dataclass
class Pastel01d4252a(RustProfile):
    owner: str = "sharkdp"
    repo: str = "pastel"
    commit: str = "01d4252aa794f1331834948f133e75c64532be46"


@dataclass
class Anyhow841522b2(RustProfile):
    owner: str = "dtolnay"
    repo: str = "anyhow"
    commit: str = "841522b2aa09732fecee40804440d2c35c68c480"


@dataclass
class Cxx0cbbf15e(RustProfile):
    owner: str = "dtolnay"
    repo: str = "cxx"
    commit: str = "0cbbf15ec43439e51b99d895e1f72162de81cd30"


@dataclass
class Rustfmtef22670a(RustProfile):
    owner: str = "rust-lang"
    repo: str = "rustfmt"
    commit: str = "ef22670aa4859d8dfd2d7a005bbf18450c9de798"


@dataclass
class Tealdeer1252261d(RustProfile):
    owner: str = "tealdeer-rs"
    repo: str = "tealdeer"
    commit: str = "1252261d662fcedecce229f08bf23277da8bf51e"


@dataclass
class Imagef12ba2bb(RustProfile):
    owner: str = "image-rs"
    repo: str = "image"
    commit: str = "f12ba2bbd3f5988e7094d48bb4f69e2d6219316a"


@dataclass
class Duacli19df299c(RustProfile):
    owner: str = "Byron"
    repo: str = "dua-cli"
    commit: str = "19df299c07d83b6dbe48edd7e7cdf7e9d1afdc51"


@dataclass
class Serenityf84addf5(RustProfile):
    owner: str = "serenity-rs"
    repo: str = "serenity"
    commit: str = "f84addf529bbaadf192c02041fedaf06ce16cf89"


@dataclass
class Tideb32f680d(RustProfile):
    owner: str = "http-rs"
    repo: str = "tide"
    commit: str = "b32f680d5bd14bc2ce7c81bef9ce99859028b20f"


@dataclass
class Rhai43d2e69b(RustProfile):
    owner: str = "rhaiscript"
    repo: str = "rhai"
    commit: str = "43d2e69b59f3ec4ca20919a3731a70d3c30cbd4d"


@dataclass
class Rayonc4dac9f8(RustProfile):
    owner: str = "rayon-rs"
    repo: str = "rayon"
    commit: str = "c4dac9f82ee03f61e855075b668229a9e4d759ad"


@dataclass
class Broot0cca9c16(RustProfile):
    owner: str = "Canop"
    repo: str = "broot"
    commit: str = "0cca9c1687a7b2d44d07e8f670d3bca430b67635"


@dataclass
class Onefetch6d881792(RustProfile):
    owner: str = "o2sh"
    repo: str = "onefetch"
    commit: str = "6d8817928d8209f9f1d13462490307ff53bb2f6f"


@dataclass
class Reqwest4b813a89(RustProfile):
    owner: str = "seanmonstar"
    repo: str = "reqwest"
    commit: str = "4b813a89dcd97a4b283fda02bd458d44339850c7"


@dataclass
class Dust93fe6585(RustProfile):
    owner: str = "bootandy"
    repo: str = "dust"
    commit: str = "93fe658574b1677052fba8b042283174b0fdef49"


@dataclass
class Bore00a735a8(RustProfile):
    owner: str = "ekzhang"
    repo: str = "bore"
    commit: str = "00a735a89917642df62d84336a90d9476fa175b5"


@dataclass
class Warp707866ca(RustProfile):
    owner: str = "seanmonstar"
    repo: str = "warp"
    commit: str = "707866ca367dd7e40082c31fbce88624f7059df0"


@dataclass
class Gpingd9a4e49f(RustProfile):
    owner: str = "orf"
    repo: str = "gping"
    commit: str = "d9a4e49fb3a7ed1667838d07687a701841bcca81"


@dataclass
class Tokenizers22d54d37(RustProfile):
    owner: str = "huggingface"
    repo: str = "tokenizers"
    commit: str = "22d54d37621f2d9f35cf9420d6ed8658372a6c5d"
    test_cmd: str = f"cd ~/{ENV_NAME}/tokenizers && cargo test --verbose"

    @property
    def dockerfile(self):
        return f"""FROM rust:{self.rust_version}
ENV TZ=Etc/UTC

RUN apt update && apt install -y wget git build-essential \
&& rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN {self.test_cmd} || true
CMD ["/bin/bash"]
"""


# Register all Rust profiles with the global registry
for name, obj in list(globals().items()):
    if (
        isinstance(obj, type)
        and issubclass(obj, RustProfile)
        and obj.__name__ != "RustProfile"
    ):
        registry.register_profile(obj)

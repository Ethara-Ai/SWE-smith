import re

from dataclasses import dataclass, field
from swebench.harness.constants import TestStatus
from swesmith.constants import ENV_NAME
from swesmith.profiles.base import RepoProfile, registry
from swesmith.profiles.cpp import parse_log_ctest


@dataclass
class CProfile(RepoProfile):
    """
    Profile for C repositories.
    """

    exts: list[str] = field(default_factory=lambda: [".c"])


@dataclass
class Jq9761ceb7(CProfile):
    owner: str = "jqlang"
    repo: str = "jq"
    commit: str = "9761ceb7d6cc48c16b25f0ab1baaef0e701927e4"
    test_cmd: str = "make check"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )

    @property
    def dockerfile(self):
        return f"""FROM ubuntu:22.04
RUN apt-get update \
    && apt-get install -y build-essential autoconf libtool git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
ENV CFLAGS="-fsanitize=address,undefined -fno-omit-frame-pointer" \
    LDFLAGS="-fsanitize=address,undefined"
RUN autoreconf -i \
    && ./configure \
    --disable-docs \
    --with-oniguruma=builtin \
    --enable-static \
    --enable-all-static \
    --prefix=/usr/local
RUN make clean
RUN touch src/parser.y src/lexer.l
RUN make -j$(nproc)

CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        test_status_map = {}
        pattern = r"^\s*(PASS|FAIL):\s(.+)$"
        for line in log.split("\n"):
            match = re.match(pattern, line.strip())
            if match:
                status, test_name = match.groups()
                if status == "PASS":
                    test_status_map[test_name] = TestStatus.PASSED.value
                elif status == "FAIL":
                    test_status_map[test_name] = TestStatus.FAILED.value
        return test_status_map


@dataclass
class Valkeyc5959266(CProfile):
    owner: str = "valkey-io"
    repo: str = "valkey"
    commit: str = "c5959266f1f94dfd976e6af0f4c65d400ef3904d"
    test_cmd: str = "TERM=dumb ./runtest --durable"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )

    @property
    def dockerfile(self):
        return f"""FROM ubuntu:22.04
ENV TZ=Etc/UTC
RUN sed -i 's/^# deb-src/deb-src/' /etc/apt/sources.list
RUN apt update && \
    apt install -y pkg-config wget git build-essential libtool automake autoconf tcl bison flex cmake python3 python3-pip python3-venv python-is-python3 && \
    rm -rf /var/lib/apt/lists/*
RUN adduser --disabled-password --gecos 'dog' nonroot
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN cd deps/jemalloc && ./autogen.sh
RUN make distclean
RUN make
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        test_status_map = {}
        pattern = r"^\[(ok|err|skip|ignore)\]:\s(.+?)(?:\s\((\d+\s*m?s)\))?$"
        for line in log.split("\n"):
            match = re.match(pattern, line.strip())
            if match:
                status, test_name, _duration = match.groups()
                if status == "ok":
                    test_status_map[test_name] = TestStatus.PASSED.value
                elif status == "err":
                    # Strip out file path information from failed test names
                    test_name = re.sub(r"\s+in\s+\S+$", "", test_name)
                    test_status_map[test_name] = TestStatus.FAILED.value
                elif status == "skip" or status == "ignore":
                    test_status_map[test_name] = TestStatus.SKIPPED.value
        return test_status_map


@dataclass
class FFmpeg17734f69(CProfile):
    owner: str = "FFmpeg"
    repo: str = "FFmpeg"
    commit: str = "17734f696752e996a37f80077c2bf116444ad340"
    test_cmd: str = "make fate -j$(nproc) -k"

    @property
    def dockerfile(self):
        return f"""FROM ubuntu:22.04
ENV TZ=Etc/UTC
RUN apt-get update && apt-get install -y \
    build-essential git nasm yasm pkg-config texinfo \
    && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
ENV CFLAGS="-fsanitize=address,undefined -fno-omit-frame-pointer" \
    LDFLAGS="-fsanitize=address,undefined"
RUN ./configure --disable-doc --disable-debug
RUN make -j$(nproc)
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        test_status_map = {}
        tested = set()
        failed = set()
        for line in log.split("\n"):
            match = re.match(r"^TEST\s+(.+)$", line.strip())
            if match:
                tested.add(match.group(1).strip())
                continue
            match = re.match(r"^Test (.+?) failed\.", line.strip())
            if match:
                failed.add(match.group(1).strip())
        for name in tested:
            if name in failed:
                test_status_map[name] = TestStatus.FAILED.value
            else:
                test_status_map[name] = TestStatus.PASSED.value
        for name in failed:
            if name not in test_status_map:
                test_status_map[name] = TestStatus.FAILED.value
        return test_status_map


@dataclass
class Hdf586bdc783(CProfile):
    owner: str = "HDFGroup"
    repo: str = "hdf5"
    commit: str = "86bdc78365c483b660dc0026f0288f200e555abf"
    test_cmd: str = "cd build && ctest --verbose --output-on-failure --rerun-failed --repeat until-pass:1 -j$(nproc)"
    timeout: int = 900
    bug_gen_dirs_exclude: list[str] = field(
        default_factory=lambda: [
            "c++",
            "fortran",
            "java",
            "hl",
            "tools",
            "utils",
            "HDF5Examples",
            "config",
            "bin",
            "release_docs",
            "testpar",
        ]
    )

    @property
    def dockerfile(self):
        return f"""FROM ubuntu:24.04
RUN apt-get update && apt-get install -y build-essential cmake git zlib1g-dev pkg-config && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mkdir build && cd build && cmake .. -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON -DHDF5_BUILD_CPP_LIB=OFF -DHDF5_BUILD_FORTRAN=OFF -DHDF5_BUILD_JAVA=OFF -DHDF5_BUILD_HL_LIB=ON -DHDF5_BUILD_TOOLS=OFF -DHDF5_BUILD_EXAMPLES=OFF -DHDF5_ENABLE_ZLIB_SUPPORT=ON && make -j$(nproc)
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_ctest(log)


@dataclass
class Openssl5b9f03c0(CProfile):
    owner: str = "openssl"
    repo: str = "openssl"
    commit: str = "5b9f03c0f4a6121c64f3129ce20c171f0862dd09"
    test_cmd: str = "make test HARNESS_JOBS=$(nproc)"
    timeout: int = 1200
    bug_gen_dirs_exclude: list[str] = field(
        default_factory=lambda: [
            "Configurations",
            "apps",
            "demos",
            "doc",
            "engines",
            "fuzz",
            "pyca-cryptography",
            "krb5",
            "gost-engine",
            "wycheproof",
            "tlsfuzzer",
            "python-ecdsa",
            "tlslite-ng",
            "oqs-provider",
            "cloudflare-quiche",
            "pkcs11-provider",
            "VMS",
            "external",
            "util",
        ]
    )

    @property
    def dockerfile(self):
        return f"""FROM ubuntu:22.04
RUN apt-get update && apt-get install -y build-essential git perl && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./Configure no-docs no-shared && make -j$(nproc)
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        test_status_map = {}
        for line in log.split("\n"):
            # prove/Test::Harness format: "ok N - test_name" or "not ok N - test_name"
            match = re.match(r"^(ok|not ok)\s+\d+\s+-\s+(.+)$", line.strip())
            if match:
                status, test_name = match.groups()
                if status == "ok":
                    test_status_map[test_name] = TestStatus.PASSED.value
                else:
                    test_status_map[test_name] = TestStatus.FAILED.value
                continue
            # .t file result lines: "ok 1 - some_test.t" at top-level prove output
            match = re.match(r"^(.+\.t)\s+\.+\s+(ok|FAILED)", line.strip())
            if match:
                test_name, status = match.groups()
                if status == "ok":
                    test_status_map[test_name] = TestStatus.PASSED.value
                else:
                    test_status_map[test_name] = TestStatus.FAILED.value
        return test_status_map


@dataclass
class Nghttp2c06ac6a0(CProfile):
    owner: str = "nghttp2"
    repo: str = "nghttp2"
    commit: str = "c06ac6a0d2fd713f566f5c48e1ecf3a3ed3d899c"
    test_cmd: str = "cd build && make main && ./tests/main"
    timeout: int = 600
    bug_gen_dirs_exclude: list[str] = field(
        default_factory=lambda: [
            "src",
            "third-party",
            "examples",
            "contrib",
            "doc",
            "docker",
            "bpf",
            "integration-tests",
            "fuzz",
            "fedora",
        ]
    )

    @property
    def dockerfile(self):
        return f"""FROM ubuntu:22.04
RUN apt-get update && apt-get install -y build-essential cmake git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN mkdir build && cd build && cmake .. -DENABLE_LIB_ONLY=ON -DBUILD_STATIC_LIBS=ON -DBUILD_TESTING=ON && make -j$(nproc)
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        test_status_map = {}
        for line in log.split("\n"):
            match = re.match(r"^(\S+)\s+\[\s*(OK|FAIL|SKIP|ERROR)\s*\]", line.strip())
            if match:
                test_name, status = match.groups()
                if status == "OK":
                    test_status_map[test_name] = TestStatus.PASSED.value
                elif status == "FAIL" or status == "ERROR":
                    test_status_map[test_name] = TestStatus.FAILED.value
                elif status == "SKIP":
                    test_status_map[test_name] = TestStatus.SKIPPED.value
        return test_status_map


# Register all C profiles with the global registry
for name, obj in list(globals().items()):
    if (
        isinstance(obj, type)
        and issubclass(obj, CProfile)
        and obj.__name__ != "CProfile"
    ):
        registry.register_profile(obj)

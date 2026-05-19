import os
import re
import shutil
import xml.etree.ElementTree as ET

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
class JavaProfile(RepoProfile):
    """
    Profile for Java repositories.
    """

    exts: list[str] = field(default_factory=lambda: [".java"])
    _test_name_to_files_cache: dict[str, set[str]] = field(
        default=None, init=False, repr=False
    )

    @classmethod
    def _dockerfile_env_groups(cls) -> list[str]:
        return ["java"]

    @staticmethod
    def _extract_test_class_name(test_name: str) -> str | None:
        """Extract the Java class name from a fully-qualified test name.

        Returns the simple class name (outer class for nested classes), or None
        if no valid class name can be identified.

        Handles these formats:
        - FQN with parens: "pkg.Class.method()" -> "Class"
        - FQN no parens: "pkg.Class.method" -> "Class"
        - Parameterized: "pkg.Class.method[display]" -> "Class"
        - Nested class: "pkg.Outer$Inner.method()" -> "Outer"
        - Repetition: "pkg.Class.repetition 1 of 100" -> "Class"
        - Simple: "Class.method()" -> "Class"
        """
        # Strip parameterized suffix [...]
        name = re.sub(r"\[.*$", "", test_name)
        # Strip method signature/parens (...)
        name = re.sub(r"\(.*$", "", name)
        # Strip trailing dots and whitespace
        name = name.rstrip(". ")

        if not name:
            return None

        # Split by dot, find rightmost valid Java class name (starts with uppercase)
        parts = name.split(".")
        for i in range(len(parts) - 1, -1, -1):
            part = parts[i]
            # Handle nested classes: Outer$Inner -> use Outer
            outer = part.split("$")[0]
            if outer and outer[0].isupper() and outer.isidentifier():
                return outer
        return None

    def _build_test_name_to_files_map(self) -> dict[str, set[str]]:
        """Build a mapping from Java class names to their source file paths.

        Uses filename-based mapping since Java enforces that the public class
        name matches the filename (e.g. FooTest.java contains class FooTest).
        """
        dest, cloned = self.clone()
        class_to_files: dict[str, set[str]] = {}

        for dirpath, _, filenames in os.walk(dest):
            for fname in filenames:
                if not fname.endswith(".java"):
                    continue

                class_name = fname[:-5]  # Strip .java
                full_path = os.path.join(dirpath, fname)
                relative_path = os.path.relpath(full_path, dest)
                class_to_files.setdefault(class_name, set()).add(relative_path)

        if cloned:
            shutil.rmtree(dest)
        return class_to_files

    def get_test_files(self, instance: dict) -> tuple[list[str], list[str]]:
        assert FAIL_TO_PASS in instance and PASS_TO_PASS in instance, (
            f"Instance {instance[KEY_INSTANCE_ID]} missing required keys {FAIL_TO_PASS} or {PASS_TO_PASS}"
        )

        if self._test_name_to_files_cache is None:
            with self._lock:
                if self._test_name_to_files_cache is None:
                    self._test_name_to_files_cache = (
                        self._build_test_name_to_files_map()
                    )

        f2p_files: set[str] = set()
        for test_name in instance[FAIL_TO_PASS]:
            class_name = self._extract_test_class_name(test_name)
            if class_name and class_name in self._test_name_to_files_cache:
                f2p_files.update(self._test_name_to_files_cache[class_name])

        p2p_files: set[str] = set()
        for test_name in instance[PASS_TO_PASS]:
            class_name = self._extract_test_class_name(test_name)
            if class_name and class_name in self._test_name_to_files_cache:
                p2p_files.update(self._test_name_to_files_cache[class_name])

        return list(f2p_files), list(p2p_files)


def parse_log_maven_surefire(log: str) -> dict[str, str]:
    """
    Parse Maven Surefire text output with per-method granularity.

    Handles two formats:
    1. With [INFO]/[ERROR] prefix: [INFO] testMethodName -- Time elapsed: 0.001 s
    2. Without prefix: testMethodName(className)  Time elapsed: 0.001 sec

    Used with: mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain

    Args:
        log (str): log content from Maven Surefire
    Returns:
        dict: test case to test status mapping
    """
    test_status_map = {}

    # Pattern 1: [INFO] testMethodName -- Time elapsed: 0.001 s
    # Pattern 2: [ERROR] testMethodName -- Time elapsed: 0.001 s <<< FAILURE!
    pattern_with_prefix = r"^\[(INFO|ERROR)\]\s+(.*?)\s+--\s+Time elapsed:\s+([\d.]+)\s"

    # Pattern 3: testMethodName(className)  Time elapsed: 0.001 sec
    # Pattern 4: testMethodName(className)  Time elapsed: 0 sec
    pattern_no_prefix = (
        r"^([a-zA-Z0-9_]+)\(([a-zA-Z0-9_.]+)\)\s+Time elapsed:\s+([\d.]+)\s+sec"
    )

    for line in log.split("\n"):
        line = line.strip()

        # Try pattern with [INFO]/[ERROR] prefix first
        if line.startswith("["):
            if line.endswith("<<< FAILURE!") and line.startswith("[ERROR]"):
                test_name = re.match(pattern_with_prefix, line)
                if test_name:
                    test_status_map[test_name.group(2)] = TestStatus.FAILED.value
            elif "Time elapsed:" in line:
                test_name = re.match(pattern_with_prefix, line)
                if test_name:
                    test_status_map[test_name.group(2)] = TestStatus.PASSED.value

        # Try pattern without prefix
        elif "Time elapsed:" in line and "(" in line:
            match = re.match(pattern_no_prefix, line)
            if match:
                test_method = match.group(1)
                test_class = match.group(2)
                test_name = f"{test_class}.{test_method}"
                test_status_map[test_name] = TestStatus.PASSED.value

    return test_status_map


def parse_log_gradle_junit_xml(log: str) -> dict[str, str]:
    """
    Parse JUnit XML test results from Gradle output.

    Parses XML testsuite elements from Gradle test output when using:
    ./gradlew test ... || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;

    Args:
        log (str): log content containing JUnit XML test results
    Returns:
        dict: test case to test status mapping
    """
    test_status_map = {}
    xml_matches = re.findall(r"<\?xml version.*?</testsuite>", log, re.DOTALL)

    for xml_content in xml_matches:
        try:
            root = ET.fromstring(xml_content)
            suite_classname = root.get("name", "")

            for testcase in root.findall(".//testcase"):
                classname = testcase.get("classname", suite_classname)
                methodname = testcase.get("name", "")
                test_name = f"{classname}.{methodname}"

                if (
                    testcase.find("failure") is not None
                    or testcase.find("error") is not None
                ):
                    test_status_map[test_name] = TestStatus.FAILED.value
                elif testcase.find("skipped") is not None:
                    test_status_map[test_name] = TestStatus.SKIPPED.value
                else:
                    test_status_map[test_name] = TestStatus.PASSED.value
        except ET.ParseError:
            continue

    return test_status_map


@dataclass
class Gson8260eddf(JavaProfile):
    owner: str = "google"
    repo: str = "gson"
    commit: str = "8260eddffe413c132b3a38e68446da6bd083220d"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )

    @property
    def dockerfile(self):
        return f"""FROM ubuntu:22.04
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
RUN apt-get update && apt-get install -y git openjdk-11-jdk
RUN apt-get install -y maven
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -pl gson -DskipTests -am
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_maven_surefire(log)


@dataclass
class Mindustryf3ad7b85(JavaProfile):
    owner: str = "Anuken"
    repo: str = "Mindustry"
    commit: str = "f3ad7b85705d0a215f71f15c703bf8a72fcef5b1"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew --no-daemon --console=plain assemble -x test

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Asynchttpclient1ab1ea31(JavaProfile):
    owner: str = "AsyncHttpClient"
    repo: str = "async-http-client"
    commit: str = "1ab1ea31fcaa0b016130d9f08cd5334feb2d1d93"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.8.8-eclipse-temurin-11

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -DskipTests -Dgpg.skip
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Recaf34802966(JavaProfile):
    owner: str = "Col-E"
    repo: str = "Recaf"
    commit: str = "34802966f991ec6082e4512770621f98cf97a262"
    test_cmd: str = "./gradlew :recaf-core:test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} +"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:22-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew :recaf-core:build -x test --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class HMCLf146040f(JavaProfile):
    owner: str = "HMCL-dev"
    repo: str = "HMCL"
    commit: str = "f146040ff33212979493a209a248724875e59b0f"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew --no-daemon --console=plain assemble -x test

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Web3jbd6cc3b3(JavaProfile):
    owner: str = "LFDT-web3j"
    repo: str = "web3j"
    commit: str = "bd6cc3b3d370717f3b6ce71385dc636924289b66"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:21-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew assemble --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Disruptorc871ca49(JavaProfile):
    owner: str = "LMAX-Exchange"
    repo: str = "disruptor"
    commit: str = "c871ca49826a6be7ada6957f6fbafcfecf7b1f87"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew assemble --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class MycatServer243539fb(JavaProfile):
    owner: str = "MyCATApache"
    repo: str = "Mycat-Server"
    commit: str = "243539fb74bbdcb9819fecc7e7b50ccf0899e671"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.8-openjdk-8-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Eureka8227a727(JavaProfile):
    owner: str = "Netflix"
    repo: str = "eureka"
    commit: str = "8227a727534338909ef8c3b5ee3dca7641921f62"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:8-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew build -x test --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Paperb4682bfe(JavaProfile):
    owner: str = "PaperMC"
    repo: str = "Paper"
    commit: str = "b4682bfef616ac62e73cc96046dacdf4a6f53eeb"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} +"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:21-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Paper uses a complex build system that often requires initializing submodules or running setup scripts.
# We run gradlew help to trigger wrapper download and basic initialization.
RUN ./gradlew --no-daemon --console=plain help

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class MPAndroidChart9c7275a0(JavaProfile):
    owner: str = "PhilJay"
    repo: str = "MPAndroidChart"
    commit: str = "9c7275a0596a7ac0e50ca566e680f7f9d73607af"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM runmymind/docker-android-sdk:latest

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew assembleDebug --no-daemon --console=plain
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class RxAndroidd5e0e399(JavaProfile):
    owner: str = "ReactiveX"
    repo: str = "RxAndroid"
    commit: str = "d5e0e39926b71fe7646315c4e7974c8eced61f9c"
    test_cmd: str = "./gradlew :rxandroid:test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM debian:bullseye-slim

RUN apt-get update && apt-get install -y \
    openjdk-11-jdk-headless \
    git \
    wget \
    unzip \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

ENV ANDROID_SDK_ROOT=/opt/android-sdk
RUN mkdir -p ${{ANDROID_SDK_ROOT}}/cmdline-tools && \
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-7583922_latest.zip -O /tmp/tools.zip && \
    unzip -q /tmp/tools.zip -d ${{ANDROID_SDK_ROOT}}/cmdline-tools && \
    mv ${{ANDROID_SDK_ROOT}}/cmdline-tools/cmdline-tools ${{ANDROID_SDK_ROOT}}/cmdline-tools/latest && \
    rm /tmp/tools.zip

ENV PATH=${{PATH}}:${{ANDROID_SDK_ROOT}}/cmdline-tools/latest/bin:${{ANDROID_SDK_ROOT}}/platform-tools

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN yes | sdkmanager --licenses && \
    sdkmanager "platforms;android-31" "build-tools;31.0.0"

# Only build the library module to avoid AAPT2 issues with the sample app on ARM
RUN ./gradlew :rxandroid:assembleDebug --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class GoGoGode0d5961(JavaProfile):
    owner: str = "ZCShou"
    repo: str = "GoGoGo"
    commit: str = "de0d596190c57b8ca71481f60ce6b9e50af5107f"
    test_cmd: str = "./gradlew testDebugUnitTest --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM --platform=linux/amd64 eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git wget unzip && rm -rf /var/lib/apt/lists/*

ENV ANDROID_SDK_ROOT=/opt/android-sdk
RUN mkdir -p $ANDROID_SDK_ROOT/cmdline-tools && \
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-9477386_latest.zip -O /tmp/tools.zip && \
    unzip -q /tmp/tools.zip -d $ANDROID_SDK_ROOT/cmdline-tools && \
    mv $ANDROID_SDK_ROOT/cmdline-tools/cmdline-tools $ANDROID_SDK_ROOT/cmdline-tools/latest && \
    rm /tmp/tools.zip

ENV PATH=$PATH:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$ANDROID_SDK_ROOT/platform-tools

RUN yes | sdkmanager --licenses
RUN sdkmanager "platforms;android-32" "platform-tools"

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN sed -i 's/..\\\\keystore\\\\GoGoGo.jks/..\\/keystore\\/GoGoGo.jks/g' app/build.gradle
RUN echo "MAPS_API_KEY=unused" > local.properties && echo "MAPS_SAFE_CODE=unused" >> local.properties

RUN sed -i 's/locationOption.setIgnoreCacheException(true);//g' app/src/main/java/com/zcshou/gogogo/MainActivity.java

RUN chmod +x gradlew && ./gradlew assembleDebug --no-daemon --console=plain || true

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Austinf2d1fb28(JavaProfile):
    owner: str = "ZhongFuCheng3y"
    repo: str = "austin"
    commit: str = "f2d1fb28315e868ecb6991e475ee0e41dc04a5a7"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -pl '!austin-data-house'"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:8-jdk

RUN apt-get update && apt-get install -y git maven && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests -pl '!austin-data-house'

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Mapper1978fac5(JavaProfile):
    owner: str = "abel533"
    repo: str = "Mapper"
    commit: str = "1978fac567760399eb5dbadd46291be920aa13eb"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9-eclipse-temurin-17

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class QLExpressd5f60c4f(JavaProfile):
    owner: str = "alibaba"
    repo: str = "QLExpress"
    commit: str = "d5f60c4f77973a05959dd41fc3a47efd953f1dd4"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:8-jdk

RUN apt-get update && apt-get install -y git maven && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Druid2790bd78(JavaProfile):
    owner: str = "alibaba"
    repo: str = "druid"
    commit: str = "2790bd782191a4824e1deea418ff92ecdcef41e9"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.8-openjdk-8-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Otter7544d051(JavaProfile):
    owner: str = "alibaba"
    repo: str = "otter"
    commit: str = "7544d0515e832b188736cc6d882d5a7da0558a55"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -Denv=release -Dmaven.test.skip=false"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.8.8-eclipse-temurin-8

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN cd lib && bash install.sh
RUN mvn clean install -B -q -DskipTests -Denv=release
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Hbaseb61d47f1(JavaProfile):
    owner: str = "apache"
    repo: str = "hbase"
    commit: str = "b61d47f1654e9f0f5796d650b5d5c1dbaf7905cd"
    test_cmd: str = "mvn test -B -pl hbase-common -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-17

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Use -pl hbase-common to limit the scope because HBase is massive and might timeout/fail on a full build in some environments
# We will install hbase-common and its dependencies
RUN mvn clean install -B -q -DskipTests -pl hbase-common -am

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Jmeter170647bd(JavaProfile):
    owner: str = "apache"
    repo: str = "jmeter"
    commit: str = "170647bdeadfec6a903b7ac653a5bd4480989d9d"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew help --no-daemon --console=plain
# Note: Full build/install of JMeter can be very heavy. 
# We'll use classes to ensure dependencies are downloaded.
RUN ./gradlew classes --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Pulsar64e0e0f1(JavaProfile):
    owner: str = "apache"
    repo: str = "pulsar"
    commit: str = "64e0e0f15992323df0405d215a18739c38b8f7d1"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -pl pulsar-common"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-17

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Pulsar is a massive project. We install a subset (pulsar-common) to ensure the Dockerfile is manageable and builds reliably.
RUN mvn clean install -B -q -DskipTests -pl pulsar-common -am

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Rocketmqc6fc39ab(JavaProfile):
    owner: str = "apache"
    repo: str = "rocketmq"
    commit: str = "c6fc39ab5f1661cab5e2d6ff0c215c0add9c6d1d"
    test_cmd: str = "mvn test -B -pl common,namesrv,srvutil -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:11-jdk

RUN apt-get update && apt-get install -y git maven && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Build only a subset of core modules to stay within time limits
RUN mvn clean install -B -q -DskipTests -pl common,namesrv,srvutil -am

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Seatunnel646eabde(JavaProfile):
    owner: str = "apache"
    repo: str = "seatunnel"
    commit: str = "646eabde3c9b98ff6947903c58d197632ad5f40d"
    test_cmd: str = "mvn test -B -pl seatunnel-common,seatunnel-api -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.8.7-eclipse-temurin-11

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests -pl seatunnel-common,seatunnel-api -am
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Shardingsphere968719af(JavaProfile):
    owner: str = "apache"
    repo: str = "shardingsphere"
    commit: str = "968719afe4198d009ed8527faa93e2a3370483ae"
    test_cmd: str = "mvn test -B -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -pl infra/common"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:8-jdk

RUN apt-get update && apt-get install -y git maven && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Build required modules for infra-common
RUN mvn clean install -B -q -DskipTests -pl infra/common -am

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Shenyu73b580d3(JavaProfile):
    owner: str = "apache"
    repo: str = "shenyu"
    commit: str = "73b580d3c07c74904d2d72ce3dc2b3a3aee44d2a"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.8.5-openjdk-17-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Mybatisplus856acc1b(JavaProfile):
    owner: str = "baomidou"
    repo: str = "mybatis-plus"
    commit: str = "856acc1b0f28588dde87279f416221e0fb0aba92"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:21-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew build -x test --no-daemon --console=plain
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Bazel8cb7f793(JavaProfile):
    owner: str = "bazelbuild"
    repo: str = "bazel"
    commit: str = "8cb7f793027aad0f31777ad55085b496b17c1c69"
    test_cmd: str = 'bazel test //src/test/java/com/google/devtools/build/lib/util:UtilTests --test_output=all --noshow_progress --show_result=10 --test_summary=detailed || true; find bazel-testlogs -name "test.xml" -exec cat {} +'
    timeout: int = 300

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:21-jdk

RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    python3 \
    unzip \
    zip \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Bazelisk
RUN curl -L https://github.com/bazelbuild/bazelisk/releases/download/v1.19.0/bazelisk-linux-amd64 -o /usr/local/bin/bazel && \
    chmod +x /usr/local/bin/bazel


# Shallow clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Pre-fetch dependencies
RUN bazel fetch //src:bazel

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class HikariCPbba167f0(JavaProfile):
    owner: str = "brettwooldridge"
    repo: str = "HikariCP"
    commit: str = "bba167f0a28905e8e63083cd7b5cbf479263271a"
    test_cmd: str = "mvn test -Ddocker.skip=true -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-11

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests -Ddocker.skip=true
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class YCSBd9faaac8(JavaProfile):
    owner: str = "brianfrankcooper"
    repo: str = "YCSB"
    commit: str = "d9faaac85a95acd4c650a3436ac41eeaeb49c365"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -pl core"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:8-jdk

RUN apt-get update && apt-get install -y git maven && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests -pl core -am

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Btracea837fe6f(JavaProfile):
    owner: str = "btraceio"
    repo: str = "btrace"
    commit: str = "a837fe6f80792f954fbff2bdd6575a6ee5d66fe8"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git openjdk-8-jdk openjdk-11-jdk && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew assemble --no-daemon --console=plain
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Hutool34bebfd6(JavaProfile):
    owner: str = "chinabugotech"
    repo: str = "hutool"
    commit: str = "34bebfd6f32cdc5eaf223327a3f9751360907923"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-8

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Thumbnailatore31168ca(JavaProfile):
    owner: str = "coobird"
    repo: str = "thumbnailator"
    commit: str = "e31168ca792b549966db090c51d4d671e393b2ab"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9-eclipse-temurin-8

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Spotless9aeda7bb(JavaProfile):
    owner: str = "diffplug"
    repo: str = "spotless"
    commit: str = "9aeda7bb219c408cfdc76ed66d1776576b686102"
    test_cmd: str = "./gradlew :lib:test :testlib:test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew :lib:build :testlib:build -x test --no-daemon --console=plain
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Dropwizard9df28807(JavaProfile):
    owner: str = "dropwizard"
    repo: str = "dropwizard"
    commit: str = "9df28807a868c59493eb7055961a74f7fb44af1e"
    test_cmd: str = "./mvnw test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./mvnw clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Metrics53740cd3(JavaProfile):
    owner: str = "dropwizard"
    repo: str = "metrics"
    commit: str = "53740cd3348d4926d3f4ca495c6c37c5b8526e90"
    test_cmd: str = "./mvnw test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk-jammy

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./mvnw clean install -B -q -DskipTests
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Flowableengine0b6067fc(JavaProfile):
    owner: str = "flowable"
    repo: str = "flowable-engine"
    commit: str = "0b6067fc6ee2123e5143400d453b01769fce907e"
    test_cmd: str = "mvn test -B -pl modules/flowable-bpmn-model -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-17


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests -pl modules/flowable-bpmn-model -am

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Gephi53c9936d(JavaProfile):
    owner: str = "gephi"
    repo: str = "gephi"
    commit: str = "53c9936dda37218d5a192f1561f7685de559449d"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -PenableTests"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9-eclipse-temurin-17

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Googlejavaformat35ed64a0(JavaProfile):
    owner: str = "google"
    repo: str = "google-java-format"
    commit: str = "35ed64a039a1a1a8683c962bfb320bf25d647cba"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9-eclipse-temurin-21

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Guice55a2b68e(JavaProfile):
    owner: str = "google"
    repo: str = "guice"
    commit: str = "55a2b68ebe445b8dca3795bd3cdfc5c09d566e74"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-17

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Hibernateorm21d67589(JavaProfile):
    owner: str = "hibernate"
    repo: str = "hibernate-orm"
    commit: str = "21d6758921b748aa9f8a1b267e652d7face0d18f"
    test_cmd: str = "./gradlew :hibernate-core:test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -path '*/test-results/*/TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:25-jdk-noble

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Use -x test to skip tests during installation phase
RUN ./gradlew help --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Apktool02a9d202(JavaProfile):
    owner: str = "iBotPeaches"
    repo: str = "Apktool"
    commit: str = "02a9d202f3252eb01c372196b3952e495f750d22"
    test_cmd: str = './gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name "TEST-*.xml" -exec cat {} +'
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:11-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew assemble --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Jetlinkscommunitya8141080(JavaProfile):
    owner: str = "jetlinks"
    repo: str = "jetlinks-community"
    commit: str = "a814108090884501758737a41c3bf3b9d0f00c23"
    test_cmd: str = "./mvnw test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./mvnw clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Jsonschema2pojo1c6b7664(JavaProfile):
    owner: str = "joelittlejohn"
    repo: str = "jsonschema2pojo"
    commit: str = "1c6b7664e453c62265c5e60a630f52f1fd47452a"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.9-eclipse-temurin-17

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Zxingandroidembeddedd09b7c76(JavaProfile):
    owner: str = "journeyapps"
    repo: str = "zxing-android-embedded"
    commit: str = "d09b7c76c3124fbfbd096a65d60b1997f37ff90f"
    test_cmd: str = "./gradlew :zxing-android-embedded:test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {}+"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:11-jdk

RUN apt-get update && apt-get install -y git wget unzip libstdc++6 && rm -rf /var/lib/apt/lists/*

ENV ANDROID_SDK_ROOT=/opt/android-sdk
RUN mkdir -p $ANDROID_SDK_ROOT/cmdline-tools && \
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-7583922_latest.zip -O cmdline-tools.zip && \
    unzip -q cmdline-tools.zip -d $ANDROID_SDK_ROOT/cmdline-tools && \
    mv $ANDROID_SDK_ROOT/cmdline-tools/cmdline-tools $ANDROID_SDK_ROOT/cmdline-tools/latest && \
    rm cmdline-tools.zip

ENV PATH=$PATH:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$ANDROID_SDK_ROOT/platform-tools

RUN unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy && \
    yes | sdkmanager --licenses && \
    sdkmanager "platform-tools" "platforms;android-30" "build-tools;30.0.3"

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew :zxing-android-embedded:assembleDebug --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class JsonPath62a4c9f0(JavaProfile):
    owner: str = "json-path"
    repo: str = "JsonPath"
    commit: str = "62a4c9f0f65ba3f625aa0867d64c528ba72d09ec"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:11-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew assemble --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class JustAuth694bbf1b(JavaProfile):
    owner: str = "justauth"
    repo: str = "JustAuth"
    commit: str = "694bbf1b010d93404e3bfb4824d90e9ddfaebebb"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:8-jdk

RUN apt-get update && apt-get install -y git maven && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Aviatorscript2cdc53dc(JavaProfile):
    owner: str = "killme2008"
    repo: str = "aviatorscript"
    commit: str = "2cdc53dcbb5f3d1d72f4838197004dd0a85a29e1"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-8

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Langchain4j7ef2747c(JavaProfile):
    owner: str = "langchain4j"
    repo: str = "langchain4j"
    commit: str = "7ef2747cb1237047977d342ec55d03974d3dce01"
    test_cmd: str = "./mvnw test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -pl langchain4j-core,langchain4j-open-ai,langchain4j"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Build only core and open-ai modules to keep it manageable and stable
RUN ./mvnw clean install -B -q -DskipTests -pl langchain4j-core,langchain4j-open-ai,langchain4j -am

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Usbserialforandroid32c2905e(JavaProfile):
    owner: str = "mik3y"
    repo: str = "usb-serial-for-android"
    commit: str = "32c2905e444266a9bcdc92df8dc3d7092c81ed01"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM runmymind/docker-android-sdk:latest

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew assembleDebug --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class OsmAnd2ddccee7(JavaProfile):
    owner: str = "osmandapp"
    repo: str = "OsmAnd"
    commit: str = "2ddccee792ad6c5fe8eb75f191d8730107d8a9a2"
    test_cmd: str = "./gradlew :OsmAnd-java:test --rerun-tasks --continue --no-daemon --console=plain --tests 'net.osmand.ReShaperTest' --tests 'net.osmand.util.GeoPointParserUtilTest' --tests 'net.osmand.util.GeoPolylineParserUtilTest' --tests 'net.osmand.util.ParseLengthTest' || true; find OsmAnd-java/build/test-results -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk-focal

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Increase memory for Gradle and Java compiler
ENV GRADLE_OPTS="-Xmx2048m -Dorg.gradle.jvmargs='-Xmx2048m -XX:MaxMetaspaceSize=512m'"

RUN ./gradlew :OsmAnd-java:assemble --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Miaoshae5801765(JavaProfile):
    owner: str = "qiurunze123"
    repo: str = "miaosha"
    commit: str = "e58017658e549b63fc4db2160d2325ccd7f8435b"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -Dspring-boot.repackage.skip=true -pl miaosha-order/miaosha-order-provider,miaosha-rpc/dubbo-api -am"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:8-jdk

RUN apt-get update && apt-get install -y git maven && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN sed -i 's/<packaging>war<\\/packaging>/<packaging>jar<\\/packaging>/g' miaosha-admin/miaosha-admin-service/pom.xml
RUN mvn clean install -B -q -Dmaven.test.skip=true -Dspring-boot.repackage.skip=true

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Quarkus7dc1708c(JavaProfile):
    owner: str = "quarkusio"
    repo: str = "quarkus"
    commit: str = "7dc1708c7e5f48943eb29acdfba7c00ba306c828"
    test_cmd: str = "mvn test -B -pl independent-projects/arc/runtime -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-17

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Remove Maven 4/Extension configs
RUN rm -f .mvn/extensions.xml .mvn/maven.config

# Build a simpler module to avoid complex dependency and configuration issues
RUN mvn clean install -B -q -am -pl independent-projects/arc/runtime -DskipTests -Denforcer.skip=true
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Questdb87355210(JavaProfile):
    owner: str = "questdb"
    repo: str = "questdb"
    commit: str = "873552107838f6d2d7fe1fbfd73bba58dbb0e012"
    test_cmd: str = "mvn test -B -pl core -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -Dtest=io.questdb.test.std.FilesTest,io.questdb.test.std.IntHashSetTest"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk-focal

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    cmake \
    build-essential \
    maven \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${{PATH}}"


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Install dependencies and build native components
# We use the recommended build profile and skip tests during installation
RUN mvn clean install -B -q -DskipTests -P build-web-console

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Bytebuddy81c8c56f(JavaProfile):
    owner: str = "raphw"
    repo: str = "byte-buddy"
    commit: str = "81c8c56ff78dd8437d63a706feb17a5680f66b07"
    test_cmd: str = "./mvnw test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./mvnw clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Reactorcore83ce2fa7(JavaProfile):
    owner: str = "reactor"
    repo: str = "reactor-core"
    commit: str = "83ce2fa72ba27152d540e201d9ec595292c5f689"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:21-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew classes --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Jedise1412f1e(JavaProfile):
    owner: str = "redis"
    repo: str = "jedis"
    commit: str = "e1412f1e38f28a81847303e78b56a5613696e8d0"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git maven && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Restassured2cdc2587(JavaProfile):
    owner: str = "rest-assured"
    repo: str = "rest-assured"
    commit: str = "2cdc25872f945f7d3978f73f2c4fb679302ac593"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-17

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class TelegramBotsad003baa(JavaProfile):
    owner: str = "rubenlagus"
    repo: str = "TelegramBots"
    commit: str = "ad003baae370529e2f99c72236ff52ba4382c0c2"
    test_cmd: str = "./mvnw test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -Dgpg.skip"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./mvnw clean install -B -q -DskipTests -Dgpg.skip
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class SmartRefreshLayout224db48f(JavaProfile):
    owner: str = "scwang90"
    repo: str = "SmartRefreshLayout"
    commit: str = "224db48f8af897a930b810a6b6fc55af8cef0d57"
    test_cmd: str = "./gradlew :refresh-layout-kernel:test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git wget unzip libncurses6 && rm -rf /var/lib/apt/lists/*

# Install Android SDK
ENV ANDROID_HOME=/opt/android-sdk
RUN mkdir -p ${{ANDROID_HOME}}/cmdline-tools && \
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-9477386_latest.zip -O cmdline-tools.zip && \
    unzip -q cmdline-tools.zip -d ${{ANDROID_HOME}}/cmdline-tools && \
    mv ${{ANDROID_HOME}}/cmdline-tools/cmdline-tools ${{ANDROID_HOME}}/cmdline-tools/latest && \
    rm cmdline-tools.zip

ENV PATH=${{PATH}}:${{ANDROID_HOME}}/cmdline-tools/latest/bin:${{ANDROID_HOME}}/platform-tools

# Accept licenses
RUN yes | sdkmanager --licenses

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN chmod +x gradlew

# Download dependencies using help task to avoid architecture-specific build failures (AAPT2) during build time
RUN ./gradlew help --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class SignalServer9c6ec78a(JavaProfile):
    owner: str = "signalapp"
    repo: str = "Signal-Server"
    commit: str = "9c6ec78a4e3d9424a90bd1f65d6bb70d0e0a1ace"
    test_cmd: str = "./mvnw test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:24-jdk-noble

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./mvnw clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Jadxbce6611a(JavaProfile):
    owner: str = "skylot"
    repo: str = "jadx"
    commit: str = "bce6611aaf32ac16b8ef27bccd7a8646a368a0bd"
    test_cmd: str = "./gradlew :jadx-core:test --tests jadx.core.utils.TypeUtilsTest --rerun-tasks --continue -Dorg.gradle.jvmargs=\"-Xmx1024m\" --no-daemon --console=plain || true; find jadx-core/build/test-results/test -type f -name 'TEST-*.xml' -exec cat {} +"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:21-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Build specific modules using full task paths to avoid memory issues
RUN ./gradlew :jadx-core:jar :jadx-cli:jar -Dorg.gradle.jvmargs="-Xmx1536m" --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Socketioclientjavaeb438de0(JavaProfile):
    owner: str = "socketio"
    repo: str = "socket.io-client-java"
    commit: str = "eb438de0f7038a075db4c7eff53fd0e7f13116ce"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -Dgpg.skip"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:8-jdk

RUN apt-get update && \
    apt-get install -y git maven curl && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn install -B -q -DskipTests -Dgpg.skip
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Strimzikafkaoperator2208be4e(JavaProfile):
    owner: str = "strimzi"
    repo: str = "strimzi-kafka-operator"
    commit: str = "2208be4e2284e69be49f1e50ccc9e492a68d2ae0"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:21-jdk

RUN apt-get update && apt-get install -y git maven wget && \
    wget https://github.com/mikefarah/yq/releases/latest/download/yq_linux_$( [ $(uname -m) = "aarch64" ] && echo "arm64" || echo "amd64" ) -O /usr/bin/yq && \
    chmod +x /usr/bin/yq && \
    rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -DskipTests -q

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Traccar9484ae82(JavaProfile):
    owner: str = "traccar"
    repo: str = "traccar"
    commit: str = "9484ae82151e2771b4f0b55695b6d7cbe8b724e7"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk-jammy

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew assemble --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Motan4c18b71e(JavaProfile):
    owner: str = "weibocom"
    repo: str = "motan"
    commit: str = "4c18b71e4491200c5cc4317d42556d337f96f11b"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.8.7-eclipse-temurin-8

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Zxing62a33ca7(JavaProfile):
    owner: str = "zxing"
    repo: str = "zxing"
    commit: str = "62a33ca7a328907dee602798043692ff1f83b0c0"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "core/src/main/java",
                "zxing.appspot.com/src/main/java",
                "zxingorg/src/main/java",
                "javase/src/main/java",
                "android-core/src/main/java",
                "android/src/com/google",
            ],
            "CWE-193": [
                "core/src/main/java",
                "javase/src/main/java",
                "zxingorg/src/main/java",
                "android/src/com/google",
                "zxing.appspot.com/src/main/java",
                "android-core/src/main/java",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM maven:3.8-openjdk-8

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Fragmentation0394930a(JavaProfile):
    owner: str = "YoKeyword"
    repo: str = "Fragmentation"
    commit: str = "0394930a3e2368f210df31f2632fb89b9c44e121"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} +"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM --platform=linux/amd64 eclipse-temurin:8-jdk-jammy

RUN apt-get update && apt-get install -y git wget unzip libncurses5 && rm -rf /var/lib/apt/lists/*

ENV ANDROID_SDK_ROOT=/opt/android-sdk
ENV ANDROID_HOME=/opt/android-sdk

RUN mkdir -p $ANDROID_SDK_ROOT/cmdline-tools && \\
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-6858069_latest.zip -O cmdline-tools.zip && \\
    unzip -q cmdline-tools.zip -d $ANDROID_SDK_ROOT/cmdline-tools && \\
    mv $ANDROID_SDK_ROOT/cmdline-tools/cmdline-tools $ANDROID_SDK_ROOT/cmdline-tools/latest && \\
    rm cmdline-tools.zip

ENV PATH=$PATH:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$ANDROID_SDK_ROOT/platform-tools

RUN yes | sdkmanager --licenses && \\
    sdkmanager "platform-tools" "platforms;android-28" "build-tools;28.0.3"

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN echo "sdk.dir=$ANDROID_SDK_ROOT" > local.properties

# Android Gradle Plugin 3.2.1/Gradle 4.6 might need this for modern environments
RUN ./gradlew assembleDebug --no-daemon --console=plain -Pandroid.enableAapt2=false || ./gradlew assembleDebug --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Sentinel38b4619a(JavaProfile):
    owner: str = "alibaba"
    repo: str = "Sentinel"
    commit: str = "38b4619a8c4aa4b170d97b9ff6bb83dd58b3ca16"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-17

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Canalcf97b2ae(JavaProfile):
    owner: str = "alibaba"
    repo: str = "canal"
    commit: str = "cf97b2ae3189a8d0d88bfcf151a8181dc2c40deb"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -Dgpg.skip"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.8-openjdk-8

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests -Dgpg.skip
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Fastjsonc942c834(JavaProfile):
    owner: str = "alibaba"
    repo: str = "fastjson"
    commit: str = "c942c83443117b73af5ad278cc780270998ba3e1"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-8

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Jvmsandboxc01c28ab(JavaProfile):
    owner: str = "alibaba"
    repo: str = "jvm-sandbox"
    commit: str = "c01c28ab5d7d97a64071a2aca261804c47a5347e"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:8-jdk

RUN apt-get update && apt-get install -y git maven && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Nacosb57b8e82(JavaProfile):
    owner: str = "alibaba"
    repo: str = "nacos"
    commit: str = "b57b8e829c51cd9616678256598a59a6b0256cda"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.8.7-eclipse-temurin-17

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests -Drat.skip=true
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Calcitecf4ffc1f(JavaProfile):
    owner: str = "apache"
    repo: str = "calcite"
    commit: str = "cf4ffc1fdf9b6d971bc703fb31ec97be9b2f42de"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Use gradle wrapper to install dependencies. 
# We run help to trigger wrapper download and then build -x test to install deps.
RUN ./gradlew --no-daemon --console=plain help
RUN ./gradlew --no-daemon --console=plain build -x test --continue || true

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Cassandra93949918(JavaProfile):
    owner: str = "apache"
    repo: str = "cassandra"
    commit: str = "939499185382af3e8a0143ebb772ea5d7173714d"
    test_cmd: str = "ant test -Dtest.name=StorageServiceTest -Dtest.methods=testBinaryArchive || true; find build/test/output -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:11-jdk

RUN apt-get update && apt-get install -y git ant ant-optional python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Cassandra build can be heavy, we'll run 'ant jar' to download dependencies and build the core
RUN ant jar

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Dubbo3dbba260(JavaProfile):
    owner: str = "apache"
    repo: str = "dubbo"
    commit: str = "3dbba260caee92e3adc63fd2e982c4bbd60e4861"
    test_cmd: str = "./mvnw test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -pl dubbo-common,dubbo-remoting,dubbo-rpc,dubbo-cluster,dubbo-registry,dubbo-config"
    timeout: int = 400

    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "dubbo-compatible/src/main/java",
                "dubbo-registry/dubbo-registry-multiple/src/main",
                "dubbo-registry/dubbo-registry-nacos/src/main",
                "dubbo-registry/dubbo-registry-api/src/main",
                "dubbo-configcenter/dubbo-configcenter-apollo/src/main",
                "dubbo-plugin/dubbo-mcp/src/main",
                "dubbo-metadata/dubbo-metadata-definition-protobuf/src/main",
                "dubbo-metrics/dubbo-metrics-api/src/main",
            ],
            "CWE-20": [
                "dubbo-plugin/dubbo-filter-validation/src/main",
                "dubbo-plugin/dubbo-filter-cache/src/main",
                "dubbo-rpc/dubbo-rpc-injvm/src/main",
                "dubbo-remoting/dubbo-remoting-zookeeper-curator5/src/main",
                "dubbo-plugin/dubbo-mcp/src/main",
                "dubbo-configcenter/dubbo-configcenter-nacos/src/main",
                "dubbo-metadata/dubbo-metadata-definition-protobuf/src/main",
            ],
            "CWE-682": [
                "dubbo-metrics/dubbo-metrics-config-center/src/main",
                "dubbo-metrics/dubbo-metrics-default/src/main",
                "dubbo-metrics/dubbo-metrics-api/src/main",
                "dubbo-metrics/dubbo-metrics-event/src/main",
                "dubbo-registry/dubbo-registry-api/src/main",
                "dubbo-metrics/dubbo-metrics-registry/src/main",
                "dubbo-plugin/dubbo-filter-cache/src/main",
            ],
            "CWE-754": [
                "dubbo-plugin/dubbo-filter-validation/src/main",
                "dubbo-remoting/dubbo-remoting-zookeeper-curator5/src/main",
                "dubbo-plugin/dubbo-spring-security/src/main",
                "dubbo-plugin/dubbo-mcp/src/main",
                "dubbo-metadata/dubbo-metadata-definition-protobuf/src/main",
                "dubbo-rpc/dubbo-rpc-injvm/src/main",
                "dubbo-configcenter/dubbo-configcenter-nacos/src/main",
                "dubbo-metadata/dubbo-metadata-report-nacos/src/main",
            ],
            "CWE-835": [
                "dubbo-configcenter/dubbo-configcenter-file/src/main",
                "dubbo-metrics/dubbo-metrics-api/src/main",
                "dubbo-registry/dubbo-registry-api/src/main",
            ],
        }
    )
    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:8-jdk-focal
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
ENV JAVA_TOOL_OPTIONS=""
RUN ./mvnw clean install -B -q -DskipTests -pl dubbo-common,dubbo-remoting,dubbo-rpc,dubbo-cluster,dubbo-registry,dubbo-config -am
CMD ["/bin/bash"]"""
    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_maven_surefire(log)


@dataclass
class Flinkcdc24ab5486(JavaProfile):
    owner: str = "apache"
    repo: str = "flink-cdc"
    commit: str = "24ab54868d6915cd93fca81957d71bd6c2665cf1"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -pl flink-cdc-common,flink-cdc-pipeline-model,flink-cdc-runtime"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:11-jdk

RUN apt-get update && apt-get install -y git maven && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Use -pl flink-cdc-common -am to keep the build manageable if needed, 
# but let's try building the core modules.
RUN mvn clean install -B -q -DskipTests -pl flink-cdc-common,flink-cdc-pipeline-model,flink-cdc-runtime -am

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Hadoop3e657602(JavaProfile):
    owner: str = "apache"
    repo: str = "hadoop"
    commit: str = "3e657602a259ea62cf33b84120477c4cc9014e97"
    test_cmd: str = "mvn test -B -pl hadoop-common-project/hadoop-common -Dtest=TestConfiguration,TestCommonConfigurationKeys -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y \\
    git \\
    maven \\
    build-essential \\
    autoconf \\
    automake \\
    libtool \\
    cmake \\
    zlib1g-dev \\
    pkg-config \\
    libssl-dev \\
    libsasl2-dev \\
    && rm -rf /var/lib/apt/lists/*


# Clone the repository
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Build specific modules to save time and ensure stability in a container environment
# We focus on hadoop-common as it's the core.
RUN mvn clean install -B -q -DskipTests -pl hadoop-common-project/hadoop-common -am

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Iceberg0bae0503(JavaProfile):
    owner: str = "apache"
    repo: str = "iceberg"
    commit: str = "0bae0503bcec99e5b725da18430458f38749888c"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Use assemble to avoid running integration tests during build
RUN ./gradlew assemble --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Incubatorkiedrools34a5f65b(JavaProfile):
    owner: str = "apache"
    repo: str = "incubator-kie-drools"
    commit: str = "34a5f65be26bbaacbf28285cdcf8242b7de754ee"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -Denforcer.skip=true -pl drools-core,drools-compiler"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git wget curl && rm -rf /var/lib/apt/lists/*

ARG MAVEN_VERSION=3.9.9
RUN wget https://archive.apache.org/dist/maven/maven-3/${{MAVEN_VERSION}}/binaries/apache-maven-${{MAVEN_VERSION}}-bin.tar.gz && \\
    tar -xzf apache-maven-${{MAVEN_VERSION}}-bin.tar.gz -C /opt && \\
    ln -s /opt/apache-maven-${{MAVEN_VERSION}}/bin/mvn /usr/bin/mvn && \\
    rm apache-maven-${{MAVEN_VERSION}}-bin.tar.gz

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests -Denforcer.skip=true -pl drools-core,drools-compiler -am
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Iotdbcee5fbb9(JavaProfile):
    owner: str = "apache"
    repo: str = "iotdb"
    commit: str = "cee5fbb958feaab8c4a6e6ccaa1321094992801a"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -pl iotdb-core/node-commons"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:11-jdk-focal

RUN apt-get update && apt-get install -y git maven thrift-compiler && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests -am -pl iotdb-api/udf-api,iotdb-api/trigger-api,iotdb-core/node-commons

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Nifi749b702d(JavaProfile):
    owner: str = "apache"
    repo: str = "nifi"
    commit: str = "749b702dc69d5797ccbd0a52bb57ee68941affa1"
    test_cmd: str = "./mvnw test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -pl nifi-commons/nifi-utils"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:21-jdk

RUN apt-get update && apt-get install -y git maven && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./mvnw clean install -B -q -DskipTests -pl nifi-commons/nifi-utils -am

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Stormff68a422(JavaProfile):
    owner: str = "apache"
    repo: str = "storm"
    commit: str = "ff68a4228f28dd6bd9eb97b8b83c950d1cc6bffd"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -pl storm-client -Dlicense.skip=true -Dcheckstyle.skip -Drat.skip=true"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk-focal

RUN apt-get update && apt-get install -y git maven python3 python2 build-essential && \\
    rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/bin/python

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Use -DskipTests to only install dependencies.
# The multilang modules are needed as dependencies for storm-client
RUN mvn clean install -B -q -DskipTests -Dlicense.skip=true -Dcheckstyle.skip -Drat.skip=true -Denforcer.skip=true

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Dynamicdatasourcebd423122(JavaProfile):
    owner: str = "baomidou"
    repo: str = "dynamic-datasource"
    commit: str = "bd423122ce07048ad3db7212eb88e571805e8202"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk-focal

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew build -x test --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Bisq32c825a3(JavaProfile):
    owner: str = "bisq-network"
    repo: str = "bisq"
    commit: str = "32c825a393de64a1f34ecffd5bfcdb69398bfa12"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain -Dorg.gradle.dependency.verification=off || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:11-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew build -x test --no-daemon --console=plain -Dorg.gradle.dependency.verification=off

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Tcctransaction874cb910(JavaProfile):
    owner: str = "changmingxie"
    repo: str = "tcc-transaction"
    commit: str = "874cb9105601f0a142f6c428c8fdc4cead851049"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.8.5-openjdk-8-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Cate815e74d(JavaProfile):
    owner: str = "dianping"
    repo: str = "cat"
    commit: str = "e815e74d4c2dd74edac831241f1253fcc7d25381"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.8-openjdk-8

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Guava5f7d0c2a(JavaProfile):
    owner: str = "google"
    repo: str = "guava"
    commit: str = "5f7d0c2ad63a110ce940c777077a0f37dfe6712a"
    test_cmd: str = "./mvnw test -B -pl guava-tests -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:11-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./mvnw clean install -B -q -DskipTests -pl guava,guava-tests -am
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Tsunamisecurityscannerf29c42aa(JavaProfile):
    owner: str = "google"
    repo: str = "tsunami-security-scanner"
    commit: str = "f29c42aa5bc0c865d5aa15cb55c7c11072af641c"
    test_cmd: str = "gradle test --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM gradle:8.5-jdk21

USER root
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN gradle classes --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Hswebframework5e8f7358(JavaProfile):
    owner: str = "hs-web"
    repo: str = "hsweb-framework"
    commit: str = "5e8f7358954d5d9606e553c0ccc194532fa4cc1c"
    test_cmd: str = "./mvnw test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./mvnw clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class CalendarViewf5479ea3(JavaProfile):
    owner: str = "huanghaibin-dev"
    repo: str = "CalendarView"
    commit: str = "f5479ea3baefdbba2453cea19a208eca83baeb9e"
    test_cmd: str = "gradle test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} +"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:11-jdk-focal

# Configure multi-arch for AAPT2 (AMD64) on ARM64 host
RUN dpkg --add-architecture amd64 && \\
    sed -i 's/http:\\/\\/ports.ubuntu.com\\/ubuntu-ports/http:\\/\\/archive.ubuntu.com\\/ubuntu/g' /etc/apt/sources.list && \\
    echo "deb [arch=arm64] http://ports.ubuntu.com/ubuntu-ports focal main universe restricted multiverse" > /etc/apt/sources.list.d/arm64.list && \\
    echo "deb [arch=arm64] http://ports.ubuntu.com/ubuntu-ports focal-updates main universe restricted multiverse" >> /etc/apt/sources.list.d/arm64.list && \\
    echo "deb [arch=arm64] http://ports.ubuntu.com/ubuntu-ports focal-security main universe restricted multiverse" >> /etc/apt/sources.list.d/arm64.list && \\
    sed -i 's/^deb /deb [arch=amd64] /' /etc/apt/sources.list && \\
    apt-get update && \\
    apt-get install -y git wget unzip libc6:amd64 libstdc++6:amd64 zlib1g:amd64 && \\
    rm -rf /var/lib/apt/lists/*

# Install Gradle 5.6.4
RUN wget -q https://services.gradle.org/distributions/gradle-5.6.4-bin.zip -O /tmp/gradle.zip && \\
    unzip -q /tmp/gradle.zip -d /opt && \\
    rm /tmp/gradle.zip
ENV GRADLE_HOME=/opt/gradle-5.6.4
ENV PATH=$PATH:$GRADLE_HOME/bin

# Install Android SDK
ENV ANDROID_SDK_ROOT=/opt/android-sdk
RUN mkdir -p $ANDROID_SDK_ROOT/cmdline-tools && \\
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-9477386_latest.zip -O /tmp/tools.zip && \\
    unzip -q /tmp/tools.zip -d $ANDROID_SDK_ROOT/cmdline-tools && \\
    mv $ANDROID_SDK_ROOT/cmdline-tools/cmdline-tools $ANDROID_SDK_ROOT/cmdline-tools/latest && \\
    rm /tmp/tools.zip

ENV PATH=$PATH:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$ANDROID_SDK_ROOT/platform-tools

RUN yes | sdkmanager --licenses && \\
    sdkmanager "platform-tools" "platforms;android-28" "build-tools;28.0.3"

# Fix XML validation error in SDK
RUN find $ANDROID_SDK_ROOT -name "package.xml" -exec sed -i '/<base-extension/,/<\\/base-extension>/d' {{}} +

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Fix build scripts and JCenter issues
RUN find . -name "*.gradle" -exec sed -i 's/jcenter()/mavenCentral()/g' {{}} + && \\
    find . -name "*.gradle" -exec sed -i '/com.jfrog.bintray.gradle/d' {{}} + && \\
    find . -name "*.gradle" -exec sed -i "/apply plugin: 'com.jfrog.bintray'/d" {{}} + && \\
    find . -name "*.gradle" -exec sed -i "s/apply from: '..\\/script\\/gradle-jcenter-push.gradle'/\\/\\/ bypassed/g" {{}} + && \\
    echo "sdk.dir=/opt/android-sdk" > local.properties

# Build the project
RUN gradle assembleDebug --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Analysisikb72b9d4a(JavaProfile):
    owner: str = "infinilabs"
    repo: str = "analysis-ik"
    commit: str = "b72b9d4ac20f4fc2bd05786c452d4cd6b4e66796"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-21

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Mapdb8721c0e8(JavaProfile):
    owner: str = "jankotek"
    repo: str = "mapdb"
    commit: str = "8721c0e824d8d546ecc76639c05ccbc618279511"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:8-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew assemble --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Keycloakc5eacd47(JavaProfile):
    owner: str = "keycloak"
    repo: str = "keycloak"
    commit: str = "c5eacd473ed392691a2e07d92d94c610e7082d78"
    test_cmd: str = "./mvnw test -B -pl core -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Build only the 'core' module and its dependencies to keep the build manageable
RUN ./mvnw clean install -B -q -DskipTests -pl core -am

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Killbill5d5ccbb5(JavaProfile):
    owner: str = "killbill"
    repo: str = "killbill"
    commit: str = "5d5ccbb50202b2001f2897e78e780324c4ed97c4"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-11

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Generatora3a976b1(JavaProfile):
    owner: str = "mybatis"
    repo: str = "generator"
    commit: str = "a3a976b1caced7bac15f8c49c6f8d25a69117cb7"
    test_cmd: str = "./mvnw test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}/core
RUN ./mvnw clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Mybatis3159066860(JavaProfile):
    owner: str = "mybatis"
    repo: str = "mybatis-3"
    commit: str = "159066860c6773ce63662168d67c30a03bc25e04"
    test_cmd: str = "./mvnw test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./mvnw clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class MybatisPageHelper1399246d(JavaProfile):
    owner: str = "pagehelper-org"
    repo: str = "Mybatis-PageHelper"
    commit: str = "1399246da98c7b6d027c4f25e8ebdd8e503cf609"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9-eclipse-temurin-17

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Plantumlacc489b9(JavaProfile):
    owner: str = "plantuml"
    repo: str = "plantuml"
    commit: str = "acc489b9b908197237187d4f60616090d6b4c367"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git graphviz && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew --no-daemon --console=plain classes
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Lettucea464c7e3(JavaProfile):
    owner: str = "redis"
    repo: str = "lettuce"
    commit: str = "a464c7e3b203c04b6e8799125a74b00820702976"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM --platform=linux/amd64 maven:3.9.6-eclipse-temurin-17

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class Picocli2bcadb5d(JavaProfile):
    owner: str = "remkop"
    repo: str = "picocli"
    commit: str = "2bcadb5d0ff466b7ca6321de10e6f97f55fa6619"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} +"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:11-jdk-focal

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew assemble --no-daemon --console=plain
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Runelite8b312880(JavaProfile):
    owner: str = "runelite"
    repo: str = "runelite"
    commit: str = "8b312880e5c58937381074efd05f8601fe145ff0"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Use multiple retries for the initial gradle run to ensure the wrapper and dependencies are downloaded
RUN (./gradlew assemble -x test -x javadoc -x checkstyleMain -x checkstyleTest --no-daemon --console=plain || \\
     ./gradlew assemble -x test -x javadoc -x checkstyleMain -x checkstyleTest --no-daemon --console=plain || \\
     ./gradlew assemble -x test -x javadoc -x checkstyleMain -x checkstyleTest --no-daemon --console=plain)
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Springauthorizationserverb90fb093(JavaProfile):
    owner: str = "spring-projects"
    repo: str = "spring-authorization-server"
    commit: str = "b90fb09362aae9eb6ee64e536d0ad7d589af917f"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew classes --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Springboot23bcc680(JavaProfile):
    owner: str = "spring-projects"
    repo: str = "spring-boot"
    commit: str = "23bcc680d5c49b1eec85fb34d8cebb0c546ddabd"
    test_cmd: str = "./gradlew :core:spring-boot:test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} +"
    timeout: int = 300

    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "buildpack/spring-boot-buildpack-platform/src/main",
                "core/spring-boot-docker-compose/src/main",
                "core/spring-boot/src/main",
                "module/spring-boot-actuator/src/main",
                "module/spring-boot-devtools/src/main",
                "loader/spring-boot-loader/src/main",
                "module/spring-boot-http-client/src/main",
                "module/spring-boot-security/src/main",
            ],
            "CWE-20": [
                "module/spring-boot-validation/src/main",
                "core/spring-boot/src/main",
                "module/spring-boot-actuator/src/main",
                "module/spring-boot-web-server/src/main",
                "module/spring-boot-security/src/main",
                "buildpack/spring-boot-buildpack-platform/src/main",
            ],
            "CWE-682": [
                "module/spring-boot-micrometer-metrics/src/main",
                "loader/spring-boot-loader/src/main",
                "module/spring-boot-actuator/src/main",
                "buildpack/spring-boot-buildpack-platform/src/main",
                "core/spring-boot/src/main",
            ],
        }
    )
    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:25-jdk
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew :core:spring-boot:assemble -x javadoc --no-daemon --console=plain
CMD ["/bin/bash"]"""
    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_gradle_junit_xml(log)


@dataclass
class Javapoetb9017a95(JavaProfile):
    owner: str = "square"
    repo: str = "javapoet"
    commit: str = "b9017a9503b76e11b4ad4c1a9f050e2d29112cb0"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.8-eclipse-temurin-8

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN mvn clean install -B -q -DskipTests
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class CoreNLP1b7edd19(JavaProfile):
    owner: str = "stanfordnlp"
    repo: str = "CoreNLP"
    commit: str = "1b7edd19c4d0d7b1f13a2591425b9b60a0b1af7a"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain"
    timeout: int = 400  # Maven tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-17

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*


RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
# Use compile instead of install to avoid trying to move the missing models JAR to the local repo
RUN mvn clean compile -B -q -DskipTests

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse Maven Surefire text output with per-method granularity.

        Parses individual test methods from Maven Surefire output when using:
        mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain
        """
        return parse_log_maven_surefire(log)


@dataclass
class CloudReader10640f28(JavaProfile):
    owner: str = "youlookwhat"
    repo: str = "CloudReader"
    commit: str = "10640f2870fd3ff8c04a33b369c113b7a8b5d5fe"
    test_cmd: str = "./gradlew test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} \\;"
    timeout: int = 300  # Gradle tests can be slow

    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:17-jdk-jammy

RUN apt-get update && apt-get install -y git wget unzip && rm -rf /var/lib/apt/lists/*

ENV ANDROID_SDK_ROOT=/opt/android-sdk
RUN mkdir -p $ANDROID_SDK_ROOT/cmdline-tools && \\
    wget -q https://dl.google.com/android/repository/commandlinetools-linux-9477386_latest.zip -O /tmp/tools.zip && \\
    unzip -q /tmp/tools.zip -d $ANDROID_SDK_ROOT/cmdline-tools && \\
    mv $ANDROID_SDK_ROOT/cmdline-tools/cmdline-tools $ANDROID_SDK_ROOT/cmdline-tools/latest && \\
    rm /tmp/tools.zip

ENV PATH=$PATH:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$ANDROID_SDK_ROOT/platform-tools

RUN yes | sdkmanager --licenses && \\
    sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN sed -i 's|distributionUrl=.*|distributionUrl=https\\\\://services.gradle.org/distributions/gradle-8.0-bin.zip|' gradle/wrapper/gradle-wrapper.properties

RUN echo "sdk.dir=/opt/android-sdk" > local.properties

# Verify installation by running dependencies task (skips aapt2)
RUN ./gradlew dependencies --no-daemon --console=plain

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        """Parse JUnit XML test results from Gradle output."""
        return parse_log_gradle_junit_xml(log)


@dataclass
class Nettyb2d2137c(JavaProfile):
    owner: str = "netty"
    repo: str = "netty"
    commit: str = "b2d2137c4404af425bf9d5d601a62576f5c06925"
    test_cmd: str = "mvn test -B -T 1C -Dsurefire.useFile=false -Dsurefire.printSummary=true -Dsurefire.reportFormat=plain -pl transport,codec,common"
    timeout: int = 400
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "handler/src/main/java",
                "codec-http/src/main/java",
                "common/src/main/java",
                "resolver/src/main/java",
                "resolver-dns/src/main/java",
            ],
            "CWE-193": [
                "buffer/src/main/java",
                "common/src/main/java",
                "codec-compression/src/main/java",
                "codec-http3/src/main/java",
                "transport-native-unix-common/src/main/java",
            ],
            "CWE-670": [
                "handler-ssl-ocsp/src/main/java",
                "handler/src/main/java",
                "handler-proxy/src/main/java",
            ],
            "CWE-754": [
                "handler-ssl-ocsp/src/main/java",
                "handler/src/main/java",
                "handler-proxy/src/main/java",
            ],
            "CWE-835": [
                "transport-classes-epoll/src/main/java",
                "common/src/main/java",
                "codec-compression/src/main/java",
                "resolver-dns/src/main/java",
                "resolver-dns-classes-macos/src/main/java",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM maven:3.9.6-eclipse-temurin-11

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
ENV JAVA_TOOL_OPTIONS=""
RUN mvn clean install -B -q -DskipTests -pl transport,codec,common -am

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_maven_surefire(log)





@dataclass
class Springframework0c25d817(JavaProfile):
    owner: str = "spring-projects"
    repo: str = "spring-framework"
    commit: str = "0c25d817bdd7959f17a225cfdc92d6403284f13d"
    test_cmd: str = "./gradlew :spring-core:test --rerun-tasks --continue --no-daemon --console=plain || true; find . -type f -name 'TEST-*.xml' -exec cat {} +"
    timeout: int = 400

    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "spring-webflux/src/main/java",
                "spring-messaging/src/main/java",
                "spring-expression/src/main/java",
                "spring-core/src/main/java",
                "spring-beans/src/main/java",
                "spring-aop/src/main/java",
            ],
            "CWE-193": [
                "spring-context-indexer/src/main/java",
                "spring-expression/src/main/java",
                "spring-core/src/main/java",
                "spring-beans/src/main/java",
                "spring-aop/src/main/java",
                "spring-jdbc/src/main/java",
                "spring-r2dbc/src/main/java",
            ],
        }
    )
    @property
    def dockerfile(self):
        return f"""FROM eclipse-temurin:25-jdk
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN ./gradlew :spring-core:assemble -x javadoc --no-daemon --console=plain
CMD ["/bin/bash"]"""
    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_gradle_junit_xml(log)








for name, obj in list(globals().items()):
    if (
        isinstance(obj, type)
        and issubclass(obj, JavaProfile)
        and obj.__name__ != "JavaProfile"
    ):
        registry.register_profile(obj)

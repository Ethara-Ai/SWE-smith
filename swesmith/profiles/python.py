import re
import subprocess

from dataclasses import dataclass, field
from pathlib import Path
from swebench.harness.constants import (
    FAIL_TO_PASS,
    PASS_TO_PASS,
    KEY_INSTANCE_ID,
    TestStatus,
)
from swebench.harness.dockerfiles import get_dockerfile_env
from swesmith.constants import LOG_DIR_ENV, ENV_NAME, INSTANCE_REF, ORG_NAME_DH
from swesmith.profiles.base import (
    RepoProfile,
    registry,
    _strip_platform_from_dockerfile,
    _build_with_buildx,
)
from swesmith.profiles.utils import INSTALL_BAZEL, INSTALL_CMAKE


@dataclass
class PythonProfile(RepoProfile):
    """
    Profile for Python repositories.

    This class provides Python-specific defaults and functionality for
    repository profiles, including Python version management and common
    Python installation/test patterns.
    """

    python_version: str = "3.10"
    install_cmds: list[str] = field(
        default_factory=lambda: ["python -m pip install -e ."]
    )
    test_cmd: str = (
        "source /opt/miniconda3/bin/activate; "
        f"conda activate {ENV_NAME}; "
        "pytest --disable-warnings --color=no --tb=no --verbose"
    )
    exts: list[str] = field(default_factory=lambda: [".py"])

    @classmethod
    def _dockerfile_env_groups(cls) -> list[str]:
        return ["python"]

    def get_test_files(self, instance: dict) -> tuple[list[str], list[str]]:
        assert FAIL_TO_PASS in instance and PASS_TO_PASS in instance, (
            f"Instance {instance[KEY_INSTANCE_ID]} missing required keys {FAIL_TO_PASS} or {PASS_TO_PASS}"
        )
        _helper = lambda tests: sorted(list(set([x.split("::", 1)[0] for x in tests])))
        return _helper(instance[FAIL_TO_PASS]), _helper(instance[PASS_TO_PASS])

    def build_image(self, platform: str | None = None, output_tar: Path | None = None):
        platforms = [p.strip() for p in platform.split(",")] if platform else []
        is_multi = len(platforms) > 1
        base_suffix = "base" if is_multi else self.arch
        BASE_IMAGE_KEY = self._ensure_base_image_local(base_suffix)
        HEREDOC_DELIMITER = "EOF_59812759871"
        PATH_TO_REQS = "swesmith_environment.yml"

        with open(self._env_yml) as f:
            reqs = f.read()

        setup_commands = [
            "#!/bin/bash",
            "set -euxo pipefail",
            f"git clone -o origin {self.mirror_url} /{ENV_NAME}",
            f"cd /{ENV_NAME}",
            "source /opt/miniconda3/bin/activate",
            f"cat <<'{HEREDOC_DELIMITER}' > {PATH_TO_REQS}\n{reqs}\n{HEREDOC_DELIMITER}",
            f"conda env create --file {PATH_TO_REQS}",
            f"conda activate {ENV_NAME} && conda install python={self.python_version} -y",
            f"rm {PATH_TO_REQS}",
            f"conda activate {ENV_NAME}",
            'echo "Current environment: $CONDA_DEFAULT_ENV"',
        ] + self.install_cmds

        dockerfile = get_dockerfile_env(
            self.pltf, self.arch, "py", base_image_key=BASE_IMAGE_KEY
        )
        dockerfile = self._prepare_dockerfile(dockerfile)
        if platform:
            dockerfile = _strip_platform_from_dockerfile(dockerfile)

        env_dir = LOG_DIR_ENV / self.repo_name
        env_dir.mkdir(parents=True, exist_ok=True)
        with open(env_dir / "setup_env.sh", "w") as f:
            f.write("\n".join(setup_commands) + "\n")
        with open(env_dir / "Dockerfile", "w") as f:
            f.write(dockerfile)

        if platform:
            _build_with_buildx(
                workdir=str(env_dir),
                dockerfile_name="Dockerfile",
                image_name=self.image_name,
                platform_str=platform,
                ssh_arg=self._docker_ssh_arg,
                proxy_args=self._get_proxy_build_args(),
                output_tar=output_tar,
            )
        else:
            build_cmd = (
                f"docker build --platform {self.pltf} --no-cache"
                f" {self._docker_ssh_arg} {self._get_proxy_build_args()}"
                f" -t {self.image_name} {env_dir}"
            )
            with open(env_dir / "build_image.log", "w") as log_file:
                subprocess.run(
                    build_cmd,
                    check=True,
                    shell=True,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )

    def log_parser(self, log: str) -> dict[str, str]:
        """Parser for test logs generated with PyTest framework"""
        test_status_map = {}
        for line in log.split("\n"):
            for status in TestStatus:
                is_match = re.match(rf"^(\S+)(\s+){status.value}", line)
                if is_match:
                    test_status_map[is_match.group(1)] = status.value
                    continue
        return test_status_map

    @property
    def _env_yml(self) -> Path:
        return LOG_DIR_ENV / self.repo_name / f"sweenv_{self.repo_name}.yml"


### MARK: Repository Profile Classes ###


@dataclass
class Addict75284f95(PythonProfile):
    owner: str = "mewwts"
    repo: str = "addict"
    commit: str = "75284f9593dfb929cadd900aff9e35e7c7aec54b"


@dataclass
class Aliveprogress69d9bf0a(PythonProfile):
    owner: str = "rsalmei"
    repo: str = "alive-progress"
    commit: str = "69d9bf0aba6276e2434a3a595cceca55040d64d7"


@dataclass
class Apispec89c262ea(PythonProfile):
    owner: str = "marshmallow-code"
    repo: str = "apispec"
    commit: str = "89c262eaf7876922b48bd9a93431e52bb5f186dc"
    install_cmds: list = field(default_factory=lambda: ["pip install -e .[dev]"])


@dataclass
class Arrow2224255c(PythonProfile):
    owner: str = "arrow-py"
    repo: str = "arrow"
    commit: str = "2224255c4acc594d734cef0bbc83360452a67983"


@dataclass
class Astroid3b4b7d43(PythonProfile):
    owner: str = "pylint-dev"
    repo: str = "astroid"
    commit: str = "3b4b7d437074f55ea0595ca3035d185e8704bb75"


@dataclass
class Asynctimeout7dc0022f(PythonProfile):
    owner: str = "aio-libs"
    repo: str = "async-timeout"
    commit: str = "7dc0022fb8160e3d7905cefa279e034e37063814"


@dataclass
class Autogradcefd3d92(PythonProfile):
    owner: str = "HIPS"
    repo: str = "autograd"
    commit: str = "cefd3d9229eca22d569f58639770f3e15d190a5c"
    install_cmds: list = field(
        default_factory=lambda: ["pip install -e '.[scipy,test]'"]
    )

    def log_parser(self, log: str) -> dict[str, str]:
        test_status_map = {}
        for line in log.split("\n"):
            for status in TestStatus:
                is_match = re.match(rf"^\[gw\d\]\s{status.value}\s(\S+)", line)
                if is_match:
                    test_status_map[is_match.group(1)] = status.value
                    continue
        return test_status_map


@dataclass
class Bleach913ab759(PythonProfile):
    owner: str = "mozilla"
    repo: str = "bleach"
    commit: str = "913ab75992b845e2c9c060c41f24d46921db4693"


@dataclass
class Boltons207651ee(PythonProfile):
    owner: str = "mahmoud"
    repo: str = "boltons"
    commit: str = "207651ee6055aabd0d9cdeac2e00140cdc208d44"


@dataclass
class Bottle2a743a30(PythonProfile):
    owner: str = "bottlepy"
    repo: str = "bottle"
    commit: str = "2a743a302a71460bfe4c0b8b7cb99a306b0328c6"


@dataclass
class Cantools0da98f9b(PythonProfile):
    owner: str = "cantools"
    repo: str = "cantools"
    commit: str = "0da98f9b538f661d7829c9f4f4b76af77b165ae8"
    install_cmds: list = field(default_factory=lambda: ["pip install -e .[dev,plot]"])


@dataclass
class Channels4188a656(PythonProfile):
    owner: str = "django"
    repo: str = "channels"
    commit: str = "4188a65617f8a3ab84e43f25969ceebae5dc3361"
    install_cmds: list = field(
        default_factory=lambda: ["pip install -e .[tests,daphne]"]
    )


@dataclass
class Chardetb5b2aa5f(PythonProfile):
    owner: str = "chardet"
    repo: str = "chardet"
    commit: str = "b5b2aa5ff41b17b63b04dfe6a803dbebe820c8ad"


@dataclass
class Charsetnormalizer49cf8d32(PythonProfile):
    owner: str = "jawah"
    repo: str = "charset_normalizer"
    commit: str = "49cf8d328c991b4af62b21b0472bede962112cd6"


@dataclass
class Click73e15500(PythonProfile):
    owner: str = "pallets"
    repo: str = "click"
    commit: str = "73e155006526575548d143ef519995f540547e52"


@dataclass
class Cloudpicklef5199fe2(PythonProfile):
    owner: str = "cloudpipe"
    repo: str = "cloudpickle"
    commit: str = "f5199fe2bc102a5ee070c743336699fc885ca966"


@dataclass
class Pythoncolorlog68b10149(PythonProfile):
    owner: str = "borntyping"
    repo: str = "python-colorlog"
    commit: str = "68b10149ffdaf3e4f7798d8050cc66c3da53c8e0"


@dataclass
class Cookiecutterc88fbe92(PythonProfile):
    owner: str = "cookiecutter"
    repo: str = "cookiecutter"
    commit: str = "c88fbe921c97c58b65f1883ba90a0ab53cc91b34"


@dataclass
class Daphnefef65a75(PythonProfile):
    owner: str = "django"
    repo: str = "daphne"
    commit: str = "fef65a75130989bb4c6b5e7f30a6d738d5b1a9e9"


@dataclass
class Datasetdb592cc0(PythonProfile):
    owner: str = "pudo"
    repo: str = "dataset"
    commit: str = "db592cc041014762bba55fd544e982170831f227"
    install_cmds: list = field(default_factory=lambda: ["python setup.py install"])


@dataclass
class Deepdiff2db8427f(PythonProfile):
    owner: str = "seperman"
    repo: str = "deepdiff"
    commit: str = "2db8427faf5b38d4df548b74e60f825bbc6ec47a"
    install_cmds: list = field(
        default_factory=lambda: [
            "pip install -r requirements-dev.txt",
            "pip install -e .",
        ]
    )


@dataclass
class Djangomoney72b99755(PythonProfile):
    owner: str = "django-money"
    repo: str = "django-money"
    commit: str = "72b99755ef9da91e67917e95701485454728b0a1"
    install_cmds: list = field(
        default_factory=lambda: ["pip install -e .[test,exchange]"]
    )


@dataclass
class Dominate208eb1d4(PythonProfile):
    owner: str = "Knio"
    repo: str = "dominate"
    commit: str = "208eb1d415f1d2a18425f603700d839d538eca46"


@dataclass
class Pythondotenvbca6644d(PythonProfile):
    owner: str = "theskumar"
    repo: str = "python-dotenv"
    commit: str = "bca6644d9aedbe287b792b756b3ae3d650cd0d3a"


@dataclass
class Drfnestedroutersbabd4a9c(PythonProfile):
    owner: str = "alanjds"
    repo: str = "drf-nested-routers"
    commit: str = "babd4a9c7cee13c13508838a35fc4db03e6b51e0"
    install_cmds: list = field(
        default_factory=lambda: ["pip install -r requirements.txt", "pip install -e ."]
    )


@dataclass
class Environs5e5ec7d0(PythonProfile):
    owner: str = "sloria"
    repo: str = "environs"
    commit: str = "5e5ec7d0f3eafc761b219844dca2fcfea0bec782"
    install_cmds: list = field(default_factory=lambda: ["pip install -e .[dev]"])


@dataclass
class Exceptiongroup0c6cfbf6(PythonProfile):
    owner: str = "agronholm"
    repo: str = "exceptiongroup"
    commit: str = "0c6cfbf677f6b50df17311cfdad01e9ff17310aa"


@dataclass
class Fakere7d5cf2e(PythonProfile):
    owner: str = "joke2k"
    repo: str = "faker"
    commit: str = "e7d5cf2ee9c90058b56d393e40a91dc58506e4f7"


@dataclass
class Feedparser0fc1e958(PythonProfile):
    owner: str = "kurtmckee"
    repo: str = "feedparser"
    commit: str = "0fc1e9587feb78ab8a07e5b45e9f4bc4c876268a"


@dataclass
class Flake848f2ca8b(PythonProfile):
    owner: str = "PyCQA"
    repo: str = "flake8"
    commit: str = "48f2ca8bf7c15a2b8ff8be9463182e1e7c5e0c48"


@dataclass
class Flashtextf4927445(PythonProfile):
    owner: str = "vi3k6i5"
    repo: str = "flashtext"
    commit: str = "f49274459bc9879789c6e6bb64bf05af755de0b3"


@dataclass
class Flask7374c85d(PythonProfile):
    owner: str = "pallets"
    repo: str = "flask"
    commit: str = "7374c85ddefc3f4b177a698ab9f0cbb6a5c0b392"
    eval_sets: set[str] = field(
        default_factory=lambda: {
            "SWE-bench/SWE-bench",
            "SWE-bench/SWE-bench_Lite",
            "SWE-bench/SWE-bench_Verified",
        }
    )


@dataclass
class Freezegun92d61b3f(PythonProfile):
    owner: str = "spulec"
    repo: str = "freezegun"
    commit: str = "92d61b3f5c31942a1039713574487bdcfcdbbfff"


@dataclass
class Funcy9eb04473(PythonProfile):
    owner: str = "Suor"
    repo: str = "funcy"
    commit: str = "9eb04473e31b6b60bd459e4dda24f6b1db5a3773"


@dataclass
class Furl46d9ea79(PythonProfile):
    owner: str = "gruns"
    repo: str = "furl"
    commit: str = "46d9ea79c98bb14b970a199fb924705d024f29ad"


@dataclass
class Fvcorec0fa8c4e(PythonProfile):
    owner: str = "facebookresearch"
    repo: str = "fvcore"
    commit: str = "c0fa8c4effa446a63855a3730965d9361db0ec04"
    install_cmds: list = field(
        default_factory=lambda: [
            "pip install torch shapely",
            "rm tests/test_focal_loss.py",
            "pip install -e .",
        ]
    )


@dataclass
class Glomc1b2d387(PythonProfile):
    owner: str = "mahmoud"
    repo: str = "glom"
    commit: str = "c1b2d387548fd3bb736453a6dbd6f749cf329faa"


@dataclass
class Gpxpy09fc46b3(PythonProfile):
    owner: str = "tkrajina"
    repo: str = "gpxpy"
    commit: str = "09fc46b3cad16b5bf49edf8e7ae873794a959620"
    test_cmd: str = (
        "source /opt/miniconda3/bin/activate; "
        f"conda activate {ENV_NAME}; "
        "pytest test.py --verbose --color=no --tb=no --disable-warnings"
    )


@dataclass
class Grafanaliba79ef6ea(PythonProfile):
    owner: str = "weaveworks"
    repo: str = "grafanalib"
    commit: str = "a79ef6eaf143ae1fb0fedb8f655a2e9aa7c1c5d1"


@dataclass
class Graphene82903263(PythonProfile):
    owner: str = "graphql-python"
    repo: str = "graphene"
    commit: str = "82903263080b3b7f22c2ad84319584d7a3b1a1f6"


@dataclass
class Gspread5e2b628d(PythonProfile):
    owner: str = "burnash"
    repo: str = "gspread"
    commit: str = "5e2b628da598151a5a4122d3cf7ba2704041643c"


@dataclass
class GTTS0f73323b(PythonProfile):
    owner: str = "pndurette"
    repo: str = "gTTS"
    commit: str = "0f73323bc7a50cb379ed9236b275b9a4d7b19146"


@dataclass
class Gunicorn9bc5891b(PythonProfile):
    owner: str = "benoitc"
    repo: str = "gunicorn"
    commit: str = "9bc5891b4b06f25a8ce0e707053dcb2fb9bf638c"


@dataclass
class H1162c5068c(PythonProfile):
    owner: str = "python-hyper"
    repo: str = "h11"
    commit: str = "62c5068c971579d61fa1b55373390e12f25fd856"


@dataclass
class Icecreamf5132dee(PythonProfile):
    owner: str = "gruns"
    repo: str = "icecream"
    commit: str = "f5132deee6e921c4cfafacf762af6be66c26d516"


@dataclass
class Inflect262a247d(PythonProfile):
    owner: str = "jaraco"
    repo: str = "inflect"
    commit: str = "262a247d2d99a47a520cdb2d46adb90df88b4326"


@dataclass
class Iniconfig77db208a(PythonProfile):
    owner: str = "pytest-dev"
    repo: str = "iniconfig"
    commit: str = "77db208ab4ae0cd2061d909fe222a1db72867850"


@dataclass
class Isodate17cb25eb(PythonProfile):
    owner: str = "gweis"
    repo: str = "isodate"
    commit: str = "17cb25eb7bc3556a68f3f7b241313e9bb8b23760"


@dataclass
class Jinja5ef70112(PythonProfile):
    owner: str = "pallets"
    repo: str = "jinja"
    commit: str = "5ef70112a1ff19c05324ff889dd30405b1002044"


@dataclass
class Jsonschema7aa8fe1c(PythonProfile):
    owner: str = "python-jsonschema"
    repo: str = "jsonschema"
    commit: str = "7aa8fe1c1c4cf0fa7d6443ec6cffb4589740ae8a"


@dataclass
class Langdetect50718717(PythonProfile):
    owner: str = "Mimino666"
    repo: str = "langdetect"
    commit: str = "5071871742170034557c0e6ec8d6e410f3d9652f"


@dataclass
class Lineprofilera5ec7fd8(PythonProfile):
    owner: str = "pyutils"
    repo: str = "line_profiler"
    commit: str = "a5ec7fd8a4de2912ae54c870e00c2460f2df0d7f"


@dataclass
class Pythonmarkdownifyadd391a6(PythonProfile):
    owner: str = "matthewwithanm"
    repo: str = "python-markdownify"
    commit: str = "add391a6235cbc66af30ec0202cb00cb0ff0eb4c"


@dataclass
class Markupsafeb2e4d9c7(PythonProfile):
    owner: str = "pallets"
    repo: str = "markupsafe"
    commit: str = "b2e4d9c7687be25695fffbe93a37622302b24fb1"


@dataclass
class Marshmallowd646fb3b(PythonProfile):
    owner: str = "marshmallow-code"
    repo: str = "marshmallow"
    commit: str = "d646fb3bf4c236fabe3b4f49c48fd0c93a43f281"


@dataclass
class Mido53c5eaab(PythonProfile):
    owner: str = "mido"
    repo: str = "mido"
    commit: str = "53c5eaab5764cf1a2053542b57c04fe854b47fdd"
    test_cmd: str = (
        "source /opt/miniconda3/bin/activate; "
        f"conda activate {ENV_NAME}; "
        "pytest --disable-warnings --color=no --tb=no --verbose -rs -c /dev/null"
    )

    def get_test_files(self, instance: dict) -> list[str]:
        f2p_files, p2p_files = super().get_test_files(instance)
        prefix = "../dev/"
        _helper = lambda test_file: (
            test_file[len(prefix) :] if test_file.startswith(prefix) else test_file
        )
        remove_prefix = lambda test_files: sorted(list(set(map(_helper, test_files))))
        return remove_prefix(f2p_files), remove_prefix(p2p_files)


@dataclass
class Mistune067f9086(PythonProfile):
    owner: str = "lepture"
    repo: str = "mistune"
    commit: str = "067f90861088a496942f5eb43236135352b85d39"


@dataclass
class Nikola0a3f5e92(PythonProfile):
    owner: str = "getnikola"
    repo: str = "nikola"
    commit: str = "0a3f5e923b35e9884207faee645512d1ef5df4f6"
    install_cmds: list = field(
        default_factory=lambda: ["pip install -e '.[extras,tests]'"]
    )


@dataclass
class Oauthlibb3f9edff(PythonProfile):
    owner: str = "oauthlib"
    repo: str = "oauthlib"
    commit: str = "b3f9edffed6b370e3eb92721cea0da22ec7e18b9"


@dataclass
class Paramiko86971581(PythonProfile):
    owner: str = "paramiko"
    repo: str = "paramiko"
    commit: str = "8697158113a3eab25ed1d1d541ebe2cad10169a7"
    test_cmd: str = (
        "source /opt/miniconda3/bin/activate; "
        f"conda activate {ENV_NAME}; "
        "pytest -rA --color=no --disable-warnings"
    )

    def log_parser(self, log: str) -> dict[str, str]:
        test_status_map = {}
        for line in log.split("\n"):
            for status in TestStatus:
                is_match = re.match(rf"^{status.value}\s(\S+)", line)
                if is_match:
                    test_status_map[is_match.group(1)] = status.value
                    continue
        return test_status_map


@dataclass
class Parse71b443f4(PythonProfile):
    owner: str = "r1chardj0n3s"
    repo: str = "parse"
    commit: str = "71b443f4de2e9c82e117f935e347a1ab7fefdee1"


@dataclass
class Parsimoniouseb796398(PythonProfile):
    owner: str = "erikrose"
    repo: str = "parsimonious"
    commit: str = "eb79639859a9697a86c0992a045174a8856b5fb0"


@dataclass
class Parsobfe30584(PythonProfile):
    owner: str = "davidhalter"
    repo: str = "parso"
    commit: str = "bfe30584415cde2e5a686512c2b109e1d06da3b6"
    install_cmds: list = field(default_factory=lambda: ["python setup.py install"])


@dataclass
class Patsy7c7b4ecc(PythonProfile):
    owner: str = "pydata"
    repo: str = "patsy"
    commit: str = "7c7b4ecc9b5a14d89bb8af671cbf8b68fb1ea758"
    install_cmds: list = field(default_factory=lambda: ["pip install -e .[test]"])


@dataclass
class Pdfminersixa18de2a9(PythonProfile):
    owner: str = "pdfminer"
    repo: str = "pdfminer.six"
    commit: str = "a18de2a9c479b4c847538500017b449ddaec177e"


@dataclass
class Pdfplumber98041536(PythonProfile):
    owner: str = "jsvine"
    repo: str = "pdfplumber"
    commit: str = "98041536932ce85d18a1fba80d9db0686b831d9d"
    install_cmds: list = field(
        default_factory=lambda: [
            "apt-get update && apt-get install ghostscript -y",
            "pip install -e .",
        ]
    )


@dataclass
class Pipdeptree1833e00d(PythonProfile):
    owner: str = "tox-dev"
    repo: str = "pipdeptree"
    commit: str = "1833e00d203bf7bb050d8929bb40bf71c320c2d8"
    install_cmds: list = field(
        default_factory=lambda: [
            "apt-get update && apt-get install graphviz -y",
            "pip install -e .[test,graphviz]",
        ]
    )


@dataclass
class Prettytable2fe26d39(PythonProfile):
    owner: str = "prettytable"
    repo: str = "prettytable"
    commit: str = "2fe26d39f2d3ab811def02bc3bb64587c1927f24"


@dataclass
class Ptyprocess97f068c8(PythonProfile):
    owner: str = "pexpect"
    repo: str = "ptyprocess"
    commit: str = "97f068c80952c702873d801d2c8b262b79685d38"


@dataclass
class Pyasn1907afbf7(PythonProfile):
    owner: str = "pyasn1"
    repo: str = "pyasn1"
    commit: str = "907afbf7098352c56e98382660a6c7976e98fe50"


@dataclass
class Pydicom489dbbe6(PythonProfile):
    owner: str = "pydicom"
    repo: str = "pydicom"
    commit: str = "489dbbe6dea50ca27b203f8a0c78ca2b7af6e6ba"
    python_version: str = "3.11"


@dataclass
class Pyfiglete7590f2b(PythonProfile):
    owner: str = "pwaller"
    repo: str = "pyfiglet"
    commit: str = "e7590f2b80a403db9605750df8a51198759757ee"


@dataclass
class Pygments98aa2560(PythonProfile):
    owner: str = "pygments"
    repo: str = "pygments"
    commit: str = "98aa256034403c29cf49d8ec5d190002e0fc1c85"


@dataclass
class Pyopenssl23208870(PythonProfile):
    owner: str = "pyca"
    repo: str = "pyopenssl"
    commit: str = "23208870fab95ba33ab897e5b7d66ceb38ce56f7"


@dataclass
class Pyparsing4f52ba7e(PythonProfile):
    owner: str = "pyparsing"
    repo: str = "pyparsing"
    commit: str = "4f52ba7e9daa4845fd94dd4a1999fc42204207fe"


@dataclass
class Pypika5e800d83(PythonProfile):
    owner: str = "kayak"
    repo: str = "pypika"
    commit: str = "5e800d83a0f0ae14210410c02fd97e51e2e3f1d5"


@dataclass
class Pyqueryce3ad507(PythonProfile):
    owner: str = "gawel"
    repo: str = "pyquery"
    commit: str = "ce3ad507fd89c581bdd7aa086e96590e1f124277"


@dataclass
class PySnooperf82c4607(PythonProfile):
    owner: str = "cool-RR"
    repo: str = "PySnooper"
    commit: str = "f82c4607c5f9e82eb1b1f94686f85be0e8a231ab"


@dataclass
class Pythondocxe4545460(PythonProfile):
    owner: str = "python-openxml"
    repo: str = "python-docx"
    commit: str = "e45454602b53e8e572b179ccf1c91093ec9f4ed7"


@dataclass
class Pythonjsonloggerbe42d82e(PythonProfile):
    owner: str = "madzak"
    repo: str = "python-json-logger"
    commit: str = "be42d82ebd1b3276b739a314545f7a3f518ff222"


@dataclass
class Pythonpinyin8595294b(PythonProfile):
    owner: str = "mozillazg"
    repo: str = "python-pinyin"
    commit: str = "8595294b1a97845e30f11ecfdb3caa4e61ac3988"


@dataclass
class PythonPptx278b47b1(PythonProfile):
    owner: str = "scanny"
    repo: str = "python-pptx"
    commit: str = "278b47b1dedd5b46ee84c286e77cdfb0bf4594be"


@dataclass
class Pythonqrcodef92c0074(PythonProfile):
    owner: str = "lincolnloop"
    repo: str = "python-qrcode"
    commit: str = "f92c007498d796e4825638b7d50c14ea51e5457a"


@dataclass
class Pythonreadability701833cc(PythonProfile):
    owner: str = "buriy"
    repo: str = "python-readability"
    commit: str = "701833ccb24f9a15b463434f78229e4d6daf1c79"


@dataclass
class Pythonslugify7b6d5d96(PythonProfile):
    owner: str = "un33k"
    repo: str = "python-slugify"
    commit: str = "7b6d5d96c1995e6dccb39a19a13ba78d7d0a3ee4"
    test_cmd: str = (
        "source /opt/miniconda3/bin/activate; "
        f"conda activate {ENV_NAME}; "
        "python test.py --verbose"
    )

    def get_test_files(self, instance: dict) -> list[str]:
        return ["test.py"], ["test.py"]

    def log_parser(self, log: str) -> dict[str, str]:
        test_status_map = {}
        pattern = r"^([a-zA-Z0-9_\-,\.\s\(\)']+)\s\.{3}\s"
        for line in log.split("\n"):
            is_match = re.match(f"{pattern}ok$", line)
            if is_match:
                test_status_map[is_match.group(1)] = TestStatus.PASSED.value
                continue
            for keyword, status in {
                "FAIL": TestStatus.FAILED,
                "ERROR": TestStatus.ERROR,
            }.items():
                is_match = re.match(f"{pattern}{keyword}$", line)
                if is_match:
                    test_status_map[is_match.group(1)] = status.value
                    continue
        return test_status_map


@dataclass
class Radon54b88e58(PythonProfile):
    owner: str = "rubik"
    repo: str = "radon"
    commit: str = "54b88e5878b2724bf4d77f97349588b811abdff2"


@dataclass
class Recordsea427369(PythonProfile):
    owner: str = "kennethreitz"
    repo: str = "records"
    commit: str = "ea4273695cee6da42edf1cb294d1f2a4505470fc"


@dataclass
class RedDiscordBot169d0eed(PythonProfile):
    owner: str = "Cog-Creators"
    repo: str = "Red-DiscordBot"
    commit: str = "169d0eed493755e8b9fe7752b2a49b76028caeee"


@dataclass
class Result0b855e1e(PythonProfile):
    owner: str = "rustedpy"
    repo: str = "result"
    commit: str = "0b855e1e38a08d6f0a4b0138b10c127c01e54ab4"


@dataclass
class Safety5049dbf3(PythonProfile):
    owner: str = "pyupio"
    repo: str = "safety"
    commit: str = "5049dbf325e5de0c43f731b1670e3815029aac6a"


@dataclass
class Scrapy5223dbe3(PythonProfile):
    owner: str = "scrapy"
    repo: str = "scrapy"
    commit: str = "5223dbe3fdf801a8a3e7877e271f54519ff73f0a"
    install_cmds: list = field(
        default_factory=lambda: [
            "apt-get update && apt-get install -y libxml2-dev libxslt-dev libjpeg-dev",
            "python -m pip install -e .",
            "rm tests/test_feedexport.py",
            "rm tests/test_pipeline_files.py",
        ]
    )
    min_testing: bool = True


@dataclass
class Schedule82a43db1(PythonProfile):
    owner: str = "dbader"
    repo: str = "schedule"
    commit: str = "82a43db1b938d8fdf60103bd41f329e06c8d3651"


@dataclass
class Schema340d3f05(PythonProfile):
    owner: str = "keleshev"
    repo: str = "schema"
    commit: str = "340d3f0596b985db9e7c81a1233f784648d7c101"


@dataclass
class Soupsieve3a661b23(PythonProfile):
    owner: str = "facelessuser"
    repo: str = "soupsieve"
    commit: str = "3a661b23b20e92b49b4683f0227c26c9d765267f"


@dataclass
class Sqlfluff39b5a606(PythonProfile):
    owner: str = "sqlfluff"
    repo: str = "sqlfluff"
    commit: str = "39b5a6069a9a7d040df0beed6e2b687190be587f"
    min_testing: bool = True


@dataclass
class Sqlglotfd35d740(PythonProfile):
    owner: str = "tobymao"
    repo: str = "sqlglot"
    commit: str = "fd35d740cec4dc918a932c66a71ee8e05e49c1d9"
    install_cmds: list = field(default_factory=lambda: ['pip install -e ".[dev]"'])
    min_testing: bool = True


@dataclass
class Sqlparse897eb2df(PythonProfile):
    owner: str = "andialbrecht"
    repo: str = "sqlparse"
    commit: str = "897eb2df8c0608b9ee4682e9728f669adf13595e"


@dataclass
class Stackprinter7a07a51a(PythonProfile):
    owner: str = "cknd"
    repo: str = "stackprinter"
    commit: str = "7a07a51a806e70c273a96071c87d19289bc0c69e"


@dataclass
class Starlette7793b925(PythonProfile):
    owner: str = "encode"
    repo: str = "starlette"
    commit: str = "7793b925a88ed98f3482325b0eca00b433123030"


@dataclass
class PythonStringSimilarity115acaac(PythonProfile):
    owner: str = "luozhouyang"
    repo: str = "python-string-similarity"
    commit: str = "115acaacf926b41a15664bd34e763d074682bda3"


@dataclass
class Sunpyd9f78349(PythonProfile):
    owner: str = "sunpy"
    repo: str = "sunpy"
    commit: str = "d9f78349356ae4347c9cb7e4d692e84b71ea634d"
    python_version: str = "3.11"
    install_cmds: list = field(default_factory=lambda: ['pip install -e ".[dev]"'])
    min_testing: bool = True


@dataclass
class Dspyfaa99d1f(PythonProfile):
    owner: str = "stanfordnlp"
    repo: str = "dspy"
    commit: str = "faa99d1f784a5d34cd0d0a5af5725ace9dae21d8"


@dataclass
class Sympya377b8a9(PythonProfile):
    owner: str = "sympy"
    repo: str = "sympy"
    commit: str = "a377b8a9c67fb39f0af3009d9cf451c6088f74d4"
    min_testing: bool = True
    min_pregold: bool = True
    eval_sets: set[str] = field(
        default_factory=lambda: {
            "SWE-bench/SWE-bench",
            "SWE-bench/SWE-bench_Lite",
            "SWE-bench/SWE-bench_Verified",
        }
    )


@dataclass
class Tenacity8779333a(PythonProfile):
    owner: str = "jd"
    repo: str = "tenacity"
    commit: str = "8779333a4759e56427b5d7ba23cacd3fe6054d61"


@dataclass
class Termcolor32f0020b(PythonProfile):
    owner: str = "termcolor"
    repo: str = "termcolor"
    commit: str = "32f0020b5095a4bce1dfdbdbaaec4867070dc978"


@dataclass
class Textdistanced6a68d61(PythonProfile):
    owner: str = "life4"
    repo: str = "textdistance"
    commit: str = "d6a68d61088a40eef5c88191ccf79323dbf34850"
    install_cmds: list = field(
        default_factory=lambda: ['pip install -e ".[benchmark,test]"']
    )


@dataclass
class Textfsmf80bbb45(PythonProfile):
    owner: str = "google"
    repo: str = "textfsm"
    commit: str = "f80bbb459c55ff5f21651e48d2529722d667af97"


@dataclass
class Thefuzz1ba86f33(PythonProfile):
    owner: str = "seatgeek"
    repo: str = "thefuzz"
    commit: str = "1ba86f33a19deedcf886b74cf6efffd79495a50f"


@dataclass
class Tinydb2283a2b5(PythonProfile):
    owner: str = "msiemens"
    repo: str = "tinydb"
    commit: str = "2283a2b556d5ef361b61bae8ed89c0ce0730d7c8"


@dataclass
class Tldextractf06eec7f(PythonProfile):
    owner: str = "john-kurkowski"
    repo: str = "tldextract"
    commit: str = "f06eec7f1c86322554bcb4031b72a74699f04cf6"
    install_cmds: list = field(default_factory=lambda: ["pip install -e .[testing]"])


@dataclass
class Tomli5a77b12a(PythonProfile):
    owner: str = "hukkin"
    repo: str = "tomli"
    commit: str = "5a77b12a7a9f052ce5a20c335d2825658f6aea52"


@dataclass
class Tornado0ca3c5f8(PythonProfile):
    owner: str = "tornadoweb"
    repo: str = "tornado"
    commit: str = "0ca3c5f8279d402b245718d16522bc18a8f5d958"
    test_cmd: str = (
        "source /opt/miniconda3/bin/activate; "
        f"conda activate {ENV_NAME}; "
        "python -m tornado.test --verbose"
    )

    def get_test_files(self, instance: dict) -> list[str]:
        f2p_files = set()
        p2p_files = set()
        for i, j in (
            (PASS_TO_PASS, p2p_files),
            (FAIL_TO_PASS, f2p_files),
        ):
            for test_name in instance[i]:
                is_match = re.search(r"\s\((.*)\)", test_name)
                if is_match:
                    test_path = is_match.group(1)
                    j.add("/".join(test_path.split(".")[:-1]) + ".py")
        return list(f2p_files), list(p2p_files)

    def log_parser(self, log: str) -> dict[str, str]:
        test_status_map = {}
        for line in log.split("\n"):
            if line.endswith("... ok"):
                test_case = line.split(" ... ")[0]
                test_status_map[test_case] = TestStatus.PASSED.value
            elif " ... skipped " in line:
                test_case = line.split(" ... ")[0]
                test_status_map[test_case] = TestStatus.SKIPPED.value
            elif any([line.startswith(x) for x in ["ERROR:", "FAIL:"]]):
                test_case = " ".join(line.split()[1:3])
                test_status_map[test_case] = TestStatus.FAILED.value
        return test_status_map


@dataclass
class Trio4d55cd50(PythonProfile):
    owner: str = "python-trio"
    repo: str = "trio"
    commit: str = "4d55cd50b3db330e4aedcec62e5a19d7ecfbc847"


@dataclass
class Tweepyc05ba988(PythonProfile):
    owner: str = "tweepy"
    repo: str = "tweepy"
    commit: str = "c05ba988177219f1591b3bf03b8896b427c8b233"
    install_cmds: list = field(
        default_factory=lambda: ["pip install -e '.[dev,test,async]'"]
    )


@dataclass
class Typeguardeb77bac7(PythonProfile):
    owner: str = "agronholm"
    repo: str = "typeguard"
    commit: str = "eb77bac7efadeb58934998dc52b01c3b50efac91"
    install_cmds: list = field(default_factory=lambda: ["pip install -e .[test,doc]"])


@dataclass
class Usaddressaa7699b5(PythonProfile):
    owner: str = "datamade"
    repo: str = "usaddress"
    commit: str = "aa7699b53a0843fc443f9e87285b88cbd9eaf50a"
    install_cmds: list = field(default_factory=lambda: ["pip install -e .[dev]"])


@dataclass
class Voluptuous87825d6d(PythonProfile):
    owner: str = "alecthomas"
    repo: str = "voluptuous"
    commit: str = "87825d6dbdab8830fcc6d559ecb3b88bdf68af6d"


@dataclass
class Webargsfbc2b0bd(PythonProfile):
    owner: str = "marshmallow-code"
    repo: str = "webargs"
    commit: str = "fbc2b0bdce906449794e1da695339f69b17292db"


@dataclass
class Wordcloud93c5e4cd(PythonProfile):
    owner: str = "amueller"
    repo: str = "word_cloud"
    commit: str = "93c5e4cd50c5f2c56ec7eb624a620790dab5df6c"


@dataclass
class Xmltodict77b55aa1(PythonProfile):
    owner: str = "martinblech"
    repo: str = "xmltodict"
    commit: str = "77b55aa159add632bafdf721f61d86f06210f235"


@dataclass
class Yamllint30a25fe0(PythonProfile):
    owner: str = "adrienverge"
    repo: str = "yamllint"
    commit: str = "30a25fe087e31d0345be0ffed4360e4651a44b6e"


@dataclass
class Moto6b3cf8df(PythonProfile):
    owner: str = "getmoto"
    repo: str = "moto"
    commit: str = "6b3cf8df811c548de5637261a882bd1fc7f2236d"
    python_version = "3.12"
    install_cmds: list = field(default_factory=lambda: ["make init"])
    min_testing: bool = True


@dataclass
class Mypyc9a8c748(PythonProfile):
    owner: str = "python"
    repo: str = "mypy"
    commit: str = "c9a8c748957f0e9857a2b60ed0fd6cbe4b1735f7"
    python_version = "3.12"
    install_cmds: list = field(
        default_factory=lambda: [
            "git submodule update --init mypy/typeshed || true",
            "python -m pip install -r test-requirements.txt",
            "python -m pip install -e .",
            "hash -r",
        ]
    )
    test_cmd: str = (
        "source /opt/miniconda3/bin/activate; "
        f"conda activate {ENV_NAME}; "
        "pytest --color=no -rA -k"
    )
    min_testing: bool = True

    def get_test_cmd(self, instance: str, f2p_only: bool = False) -> tuple[str, list]:
        test_keys = []
        if f2p_only and FAIL_TO_PASS in instance:
            test_keys = [x.rsplit("::", 1)[-1] for x in instance[FAIL_TO_PASS]]
        elif INSTANCE_REF in instance and "test_patch" in instance[INSTANCE_REF]:
            test_keys = re.findall(
                r"\[case ([^\]]+)\]", instance[INSTANCE_REF]["test_patch"]
            )
        if len(test_keys) > 1:
            combined = " or ".join(test_keys)
            return f'{self.test_cmd} "{combined}"', test_keys
        return self.test_cmd, test_keys

    def log_parser(self, log: str) -> dict[str, str]:
        test_status_map = {}
        for line in log.split("\n"):
            for status in [
                TestStatus.PASSED.value,
                TestStatus.FAILED.value,
            ]:
                if status in line:
                    test_case = line.split()[-1]
                    test_status_map[test_case] = status
                    break
        return test_status_map


@dataclass
class MONAI862f3a63(PythonProfile):
    owner: str = "Project-MONAI"
    repo: str = "MONAI"
    commit: str = "862f3a63881b3b3f2f6859554adb784d58db7356"
    python_version = "3.12"
    install_cmds: list = field(
        default_factory=lambda: [
            r"sed -i '/^git+https:\/\/github.com\/Project-MONAI\//d' requirements-dev.txt",
            "python -m pip install -U -r requirements-dev.txt",
            "python -m pip install -e .",
        ]
    )
    test_cmd: str = (
        "source /opt/miniconda3/bin/activate; "
        f"conda activate {ENV_NAME}; "
        "pytest --disable-warnings --color=no --tb=no --verbose"
    )
    min_pregold: bool = True
    min_testing: bool = True


@dataclass
class Dvc06ff81cd(PythonProfile):
    owner: str = "iterative"
    repo: str = "dvc"
    commit: str = "06ff81cd7f622d06d23cf61bb73e116dade8730b"
    install_cmds: list = field(default_factory=lambda: ['pip install -e ".[dev]"'])
    min_testing: bool = True


@dataclass
class Hydrabb680e51(PythonProfile):
    owner: str = "facebookresearch"
    repo: str = "hydra"
    commit: str = "bb680e516c9e9ea5799336a36b1adcedc4dd6f4e"
    install_cmds: list = field(
        default_factory=lambda: [
            "apt-get update && apt-get install -y openjdk-17-jdk openjdk-17-jre",
            "pip install -e .",
        ]
    )


@dataclass
class Daskaf302b23(PythonProfile):
    owner: str = "dask"
    repo: str = "dask"
    commit: str = "af302b233315e7568e089cce279a233cebf4578b"
    install_cmds: list = field(
        default_factory=lambda: [
            "python -m pip install graphviz",
            "python -m pip install -e .",
        ]
    )
    min_testing: bool = True


@dataclass
class Modin7ca200b0(PythonProfile):
    owner: str = "modin-project"
    repo: str = "modin"
    commit: str = "7ca200b08597ed6ecfd2db2d08bd322f83c2cec1"
    install_cmds: list = field(default_factory=lambda: ['pip install -e ".[all]"'])
    min_pregold: bool = True
    min_testing: bool = True


@dataclass
class Pydantic7a369fb5(PythonProfile):
    owner: str = "pydantic"
    repo: str = "pydantic"
    commit: str = "7a369fb502a473b1e387905359bdb3070ee7534a"
    install_cmds: list = field(
        default_factory=lambda: [
            "apt-get update && apt-get install -y locales pipx",
            "pipx install uv",
            "pipx install pre-commit",
            'export PATH="$HOME/.local/bin:$PATH"',
            "make install",
        ]
    )
    test_cmd: str = (
        "/root/.local/bin/uv run pytest --disable-warnings --color=no --tb=no --verbose"
    )


@dataclass
class Conan0698765f(PythonProfile):
    owner: str = "conan-io"
    repo: str = "conan"
    commit: str = "0698765f54f78c9385ef1322b53547dc555e1bb0"
    install_cmds = (
        INSTALL_CMAKE
        + INSTALL_BAZEL
        + [
            "apt-get -y update && apt-get -y upgrade && apt-get install -y build-essential cmake automake autoconf pkg-config meson ninja-build",
            "python -m pip install -r conans/requirements.txt",
            "python -m pip install -r conans/requirements_server.txt",
            "python -m pip install -r conans/requirements_dev.txt",
            "python -m pip install -e .",
        ]
    )
    min_testing: bool = True


@dataclass
class Pandas757fa840(PythonProfile):
    owner: str = "pandas-dev"
    repo: str = "pandas"
    commit: str = "757fa8409671ef39541a023917252c34d8154839"
    install_cmds: list = field(
        default_factory=lambda: [
            "git remote add upstream https://github.com/pandas-dev/pandas.git",
            "git fetch upstream --tags",
            "python -m pip install -ve . --no-build-isolation -Ceditable-verbose=true",
            """sed -i 's/__version__="[^"]*"/__version__="3.0.0.dev0+1992.g95280573e1"/' build/cp310/_version_meson.py""",
        ]
    )
    min_pregold: bool = True
    min_testing: bool = True


@dataclass
class MonkeyType15e7bca6(PythonProfile):
    owner: str = "Instagram"
    repo: str = "MonkeyType"
    commit: str = "15e7bca60146a7afbde46ee8782a0c650f781c74"


@dataclass
class String2string38e181e2(PythonProfile):
    owner: str = "stanfordnlp"
    repo: str = "string2string"
    commit: str = "38e181e2048c3d5dac64c0418b80e65b5d27597b"
    install_cmds: list = field(
        default_factory=lambda: [
            "pip install -r docs/requirements.txt",
            "pip install -e .",
            "pip install pytest",
        ]
    )


### Security repos (CWE-targeted) ###


@dataclass
class Glances82cd190c(PythonProfile):
    owner: str = "nicolargo"
    repo: str = "glances"
    commit: str = "82cd190cf482f4a08aa5ddb291f54cc356c9276c"
    install_cmds: list = field(
        default_factory=lambda: ["pip install -e .[test]"]
    )


@dataclass
class Ray88a939b6(PythonProfile):
    owner: str = "ray-project"
    repo: str = "ray"
    commit: str = "88a939b6d00671e90b6b85f5e68dcb110e248218"
    python_version: str = "3.11"
    timeout: int = 300
    timeout_ref: int = 3600
    install_cmds: list = field(
        default_factory=lambda: [
            "pip install -e '.[default]'",
        ]
    )


@dataclass
class GitPython5a294a6f(PythonProfile):
    owner: str = "gitpython-developers"
    repo: str = "GitPython"
    commit: str = "5a294a6fc7ed5dc0946d4b576257bf926178f269"
    install_cmds: list = field(
        default_factory=lambda: [
            "pip install -e .[test]",
        ]
    )


@dataclass
class Dagster3a8263af(PythonProfile):
    owner: str = "dagster-io"
    repo: str = "dagster"
    commit: str = "3a8263af65dc1a2ce6bf24749adcbab463184072"
    python_version: str = "3.11"
    timeout: int = 180
    timeout_ref: int = 1800
    install_cmds: list = field(
        default_factory=lambda: [
            "pip install -e python_modules/dagster",
            "pip install -e python_modules/dagster-pipes",
        ]
    )

@dataclass
class Langchain992c613b(PythonProfile):
    owner: str = "langchain-ai"
    repo: str = "langchain"
    commit: str = "992c613b51fb40213dc1e0156ce0d66db6771055"
    python_version: str = "3.11"
    install_cmds: list = field(
        default_factory=lambda: [
            "pip install -e libs/core",
            "pip install -e libs/langchain",
            "pip install pytest pytest-asyncio",
        ]
    )
    min_testing: bool = True
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "libs/text-splitters/langchain_text_splitters",
                "libs/core/langchain_core",
                "libs/core/langchain_core/language_models",
                "libs/core/langchain_core/messages",
                "libs/core/langchain_core/utils",
            ],
            "CWE-193": [
                "libs/text-splitters/langchain_text_splitters",
                "libs/core/langchain_core/indexing",
                "libs/langchain_v1/langchain/agents",
                "libs/standard-tests/langchain_tests/utils",
                "libs/partners/openrouter/langchain_openrouter",
                "libs/partners/mistralai/langchain_mistralai",
                "libs/langchain/langchain_classic/indexes",
            ],
            "CWE-20": [
                "libs/core/langchain_core/output_parsers",
                "libs/langchain/langchain_classic/output_parsers",
                "libs/langchain/langchain_classic/_api",
                "libs/model-profiles/langchain_model_profiles",
            ],
            "CWE-670": [
                "libs/partners/openrouter/langchain_openrouter",
                "libs/standard-tests/langchain_tests",
                "libs/langchain_v1/langchain/agents",
                "libs/partners/mistralai/langchain_mistralai",
                "libs/text-splitters/langchain_text_splitters",
            ],
            "CWE-682": [
                "libs/partners/qdrant/langchain_qdrant",
                "libs/partners/chroma/langchain_chroma",
                "libs/partners/ollama/langchain_ollama",
                "libs/langchain_v1/langchain/agents",
            ],
            "CWE-754": [
                "libs/langchain/langchain_classic/_api",
                "libs/model-profiles/langchain_model_profiles",
                "libs/standard-tests/langchain_tests/utils",
            ],
            "CWE-835": [
                "libs/text-splitters/langchain_text_splitters",
                "libs/partners/openrouter/langchain_openrouter",
                "libs/partners/mistralai/langchain_mistralai",
                "libs/core/langchain_core/language_models",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM python:{self.python_version}
RUN git clone https://github.com/{self.owner}/{self.repo}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN pip install -e libs/core
RUN pip install -e libs/langchain
RUN pip install pytest pytest-asyncio
CMD ["/bin/bash"]
"""

@dataclass
class Ckan5b25321e(PythonProfile):
    owner: str = "ckan"
    repo: str = "ckan"
    commit: str = "5b25321eec79747c5212ce58827e8b62611ba1e7"
    install_cmds: list = field(
        default_factory=lambda: [
            "pip install -e '.[requirements,dev]'",
        ]
    )


# Register all Python profiles with the global registry
for name, obj in list(globals().items()):
    if (
        isinstance(obj, type)
        and issubclass(obj, PythonProfile)
        and obj.__name__ != "PythonProfile"
    ):
        registry.register_profile(obj)

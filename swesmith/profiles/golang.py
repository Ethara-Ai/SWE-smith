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
class GoProfile(RepoProfile):
    """
    Profile for Golang repositories.

    This class provides Golang-specific defaults and functionality for
    repository profiles.
    """

    exts: list[str] = field(default_factory=lambda: [".go"])
    test_cmd: str = "go test -v ./..."
    _test_name_to_files_cache: dict[str, set[str]] = field(
        default=None, init=False, repr=False
    )

    @classmethod
    def _dockerfile_env_groups(cls) -> list[str]:
        return ["go"]

    @property
    def dockerfile(self):
        return f"""FROM golang:1.24
RUN git clone {self.mirror_url} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""

    def _build_test_name_to_files_map(self) -> dict[str, set[str]]:
        """Build a mapping from test names to the files that contain them."""
        dest, cloned = self.clone()
        test_name_to_files = {}

        # Scan all test files once
        for dirpath, _, filenames in os.walk(dest):
            for fname in filenames:
                if not fname.endswith("_test.go"):
                    continue

                full_path = os.path.join(dirpath, fname)
                # Convert to relative path from repository root
                relative_path = os.path.relpath(full_path, dest)

                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        for line in f:
                            # Look for function definitions that are tests
                            match = re.match(r"^\s*func\s+(\w+)\b", line.strip())
                            if match:
                                test_name = match.group(1)
                                if test_name not in test_name_to_files:
                                    test_name_to_files[test_name] = set()
                                test_name_to_files[test_name].add(relative_path)
                except (OSError, UnicodeDecodeError):
                    # skip files we can't read
                    continue

        if cloned:
            shutil.rmtree(dest)
        return test_name_to_files

    def get_test_files(self, instance: dict) -> tuple[list[str], list[str]]:
        assert FAIL_TO_PASS in instance and PASS_TO_PASS in instance, (
            f"Instance {instance[KEY_INSTANCE_ID]} missing required keys {FAIL_TO_PASS} or {PASS_TO_PASS}"
        )

        # Lazy load the cache if needed
        if self._test_name_to_files_cache is None:
            with self._lock:  # Only one process enters this block at a time
                if self._test_name_to_files_cache is None:  # Double-check pattern
                    self._test_name_to_files_cache = (
                        self._build_test_name_to_files_map()
                    )

        # Look up each test name in the cache
        f2p_files = set()
        for test_name in instance[FAIL_TO_PASS]:
            if test_name in self._test_name_to_files_cache:
                f2p_files.update(self._test_name_to_files_cache[test_name])

        p2p_files = set()
        for test_name in instance[PASS_TO_PASS]:
            if test_name in self._test_name_to_files_cache:
                p2p_files.update(self._test_name_to_files_cache[test_name])

        return list(f2p_files), list(p2p_files)

    def log_parser(self, log: str) -> dict[str, str]:
        """Parser for test logs generated with 'go test'"""
        test_status_map = {}

        pattern_status_map = [
            (re.compile(r"--- PASS: (\S+)"), TestStatus.PASSED.value),
            (re.compile(r"--- FAIL: (\S+)"), TestStatus.FAILED.value),
            (re.compile(r"FAIL:?\s?(.+?)\s"), TestStatus.FAILED.value),
            (re.compile(r"--- SKIP: (\S+)"), TestStatus.SKIPPED.value),
        ]
        for line in log.split("\n"):
            for pattern, status in pattern_status_map:
                match = pattern.match(line.strip())
                if match:
                    test_name = match.group(1)
                    test_status_map[test_name] = status
                    break

        return test_status_map


@dataclass
class Gind3ffc998(GoProfile):
    owner: str = "gin-gonic"
    repo: str = "gin"
    commit: str = "d3ffc9985281dcf4d3bef604cce4e662b1a327a6"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )


@dataclass
class Fzf263eb473(GoProfile):
    owner: str = "junegunn"
    repo: str = "fzf"
    commit: str = "263eb4732fc6268f9fb35cffb634903ea8e2a26b"


@dataclass
class Caddyc7c9f310(GoProfile):
    owner: str = "caddyserver"
    repo: str = "caddy"
    commit: str = "c7c9f3108a4200a8099ae41175b8aa356b14109f"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )


@dataclass
class Frp8666e364(GoProfile):
    owner: str = "fatedier"
    repo: str = "frp"
    commit: str = "8666e3643f4e8cc3ec65780c48e20c8904b17856"
    eval_sets: set[str] = field(
        default_factory=lambda: {"SWE-bench/SWE-bench_Multilingual"}
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
RUN git clone {self.mirror_url} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Gorm40cd2afd(GoProfile):
    owner: str = "go-gorm"
    repo: str = "gorm"
    commit: str = "40cd2afdadf291075944a50b7d816db2f28c3c86"


@dataclass
class Echo7d1fed05(GoProfile):
    owner: str = "labstack"
    repo: str = "echo"
    commit: str = "7d1fed0542fc7f4189adc2b92cc1e0eda4640f06"


@dataclass
class Natsserver86ecd078(GoProfile):
    owner: str = "nats-io"
    repo: str = "nats-server"
    commit: str = "86ecd078f4850ca34d89170f7862b8bdf2e2c419"
    timeout: int = 120


@dataclass
class Address89fd2c05(GoProfile):
    owner: str = "bojanz"
    repo: str = "address"
    commit: str = "89fd2c051e3f000f2f4c72ba64d912462f223a21"


@dataclass
class Goatcounterb0e4d1f8(GoProfile):
    owner: str = "arp242"
    repo: str = "goatcounter"
    commit: str = "b0e4d1f842360709f32854fc6c4d439d3f3672c1"


@dataclass
class Gotests2a672c52(GoProfile):
    owner: str = "cweill"
    repo: str = "gotests"
    commit: str = "2a672c523b4cb46a6dc7d04ab05fa0f4be72aade"


@dataclass
class Aferob81ba176(GoProfile):
    owner: str = "spf13"
    repo: str = "afero"
    commit: str = "b81ba1760d32980ab59f5660918e57d1f4db7804"


@dataclass
class Colord232e114(GoProfile):
    owner: str = "gookit"
    repo: str = "color"
    commit: str = "d232e114aa3d6d7b66dd5edc442d89e48bf366ae"


@dataclass
class Goprompt82a91227(GoProfile):
    owner: str = "c-bata"
    repo: str = "go-prompt"
    commit: str = "82a912274504477990ecf7c852eebb7c85291772"


@dataclass
class Accounting(GoProfile):
    owner: str = "leekchan"
    repo: str = "accounting"
    commit: str = "2e09117338f81558182056c197506abceadc83e0"


@dataclass
class Mpbcf7d4dce(GoProfile):
    owner: str = "vbauerster"
    repo: str = "mpb"
    commit: str = "cf7d4dcef21068ca314a4323315acc48738c0022"


@dataclass
class Bubbletea640d8793(GoProfile):
    owner: str = "charmbracelet"
    repo: str = "bubbletea"
    commit: str = "640d8793966c506842bb31af23bdb9c672fae3ab"


@dataclass
class Fxd9f75a1a(GoProfile):
    owner: str = "antonmedv"
    repo: str = "fx"
    commit: str = "d9f75a1acd7ecc58ce0b3e0bfe149a4d7067ecf0"


@dataclass
class UIProgress(GoProfile):
    owner: str = "gosuri"
    repo: str = "uiprogress"
    commit: str = "484b9f69ea000422e1873db136dbb80e30b5de3c"


@dataclass
class Cobraad460ea8(GoProfile):
    owner: str = "spf13"
    repo: str = "cobra"
    commit: str = "ad460ea8f249db69c943a365fb84f3a59042d54e"


@dataclass
class GoFlags(GoProfile):
    owner: str = "jessevdk"
    repo: str = "go-flags"
    commit: str = "8eae68f0a7870eec41bc8061c2194040048cdf59"


@dataclass
class Pflag18450ea2(GoProfile):
    owner: str = "spf13"
    repo: str = "pflag"
    commit: str = "18450ea2f1d4209b15df2915d762da99171ebb67"


@dataclass
class Liner(GoProfile):
    owner: str = "peterh"
    repo: str = "liner"
    commit: str = "58a158787cd552b11ce4a45f589a5452072c1fc0"


@dataclass
class Enva72d89a8(GoProfile):
    owner: str = "caarlos0"
    repo: str = "env"
    commit: str = "a72d89a8930fc800372a6a338a1acf33e5cc3a56"


@dataclass
class Godotenva2be92d1(GoProfile):
    owner: str = "joho"
    repo: str = "godotenv"
    commit: str = "a2be92d182fc04da33b365bf47c17fe0f4808aea"


@dataclass
class Hjsongo23908b1b(GoProfile):
    owner: str = "hjson"
    repo: str = "hjson-go"
    commit: str = "23908b1b28ce317b3f79151c7769cf5c2fa0f4ab"


@dataclass
class Sonic4ddcd087(GoProfile):
    owner: str = "bytedance"
    repo: str = "sonic"
    commit: str = "4ddcd087571ae4cf27c80a9ed21d7bf3c53010cd"


@dataclass
class Muffetdfc0f959(GoProfile):
    owner: str = "raviqqe"
    repo: str = "muffet"
    commit: str = "dfc0f9597550d5cd75c03246ff2d22fa2e1d02c4"


@dataclass
class Omniparser(GoProfile):
    owner: str = "jf-tech"
    repo: str = "omniparser"
    commit: str = "d4371ab77afacd626b21d925e0e5b7989298e847"


@dataclass
class Roaring6d3d113b(GoProfile):
    owner: str = "RoaringBitmap"
    repo: str = "roaring"
    commit: str = "6d3d113bca4606cb11e7458914c2bb595e5ac0e9"


@dataclass
class Bitset3c5210ae(GoProfile):
    owner: str = "bits-and-blooms"
    repo: str = "bitset"
    commit: str = "3c5210ae3543cc1337dc99b0fe702a2d50789687"


@dataclass
class BoomFilters53813c36(GoProfile):
    owner: str = "tylertreat"
    repo: str = "BoomFilters"
    commit: str = "53813c36cc1bd85a398068ecd9e4d47112dfc5fb"

    @property
    def dockerfile(self):
        return f"""FROM golang:1.24
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod init github.com/tylertreat/BoomFilters
RUN go mod tidy
CMD ["/bin/bash"]
"""


@dataclass
class Ini89efed65(GoProfile):
    owner: str = "go-ini"
    repo: str = "ini"
    commit: str = "89efed656251568a673d69d9f8d8ba0d1481363b"

    @property
    def dockerfile(self):
        return f"""FROM golang:1.24
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod init github.com/go-ini/ini
RUN go mod tidy
CMD ["/bin/bash"]
"""


@dataclass
class Godatastructures89d15fac(GoProfile):
    owner: str = "Workiva"
    repo: str = "go-datastructures"
    commit: str = "89d15facb2e3d7ae0c819fa43b66a2153e77196f"


@dataclass
class Gods(GoProfile):
    owner: str = "emirpasic"
    repo: str = "gods"
    commit: str = "1d83d5ae39fbb0de45a60365791ff1c8b9bae953"


@dataclass
class Gota(GoProfile):
    owner: str = "go-gota"
    repo: str = "gota"
    commit: str = "f70540952827cfc8abfa1257391fd33284300b24"


@dataclass
class Golangset8bc9a608(GoProfile):
    owner: str = "deckarep"
    repo: str = "golang-set"
    commit: str = "8bc9a608bc94c55847fb3d4314981cf2986b6786"


@dataclass
class Blevef7e4c923(GoProfile):
    owner: str = "blevesearch"
    repo: str = "bleve"
    commit: str = "f7e4c923ae4318baa92a442eb64dea09cac370ad"
    timeout: int = 120
    timeout_ref: int = 120


@dataclass
class Goadaptiveradixtreebdbea33d(GoProfile):
    owner: str = "plar"
    repo: str = "go-adaptive-radix-tree"
    commit: str = "bdbea33ddf359a660e4f7739e09ed4d003bb6814"


@dataclass
class Triebf829281(GoProfile):
    owner: str = "derekparker"
    repo: str = "trie"
    commit: str = "bf82928180827570bb22fa82bcde0d08ddac12c6"


@dataclass
class Bigcache532eb641(GoProfile):
    owner: str = "allegro"
    repo: str = "bigcache"
    commit: str = "532eb6410aefb749509084c74f56b8313e200f4a"


@dataclass
class Cache2go(GoProfile):
    owner: str = "muesli"
    repo: str = "cache2go"
    commit: str = "518229cd8021d8568e4c6c13743bb050dc1f3a05"


@dataclass
class Fastcachecef9ae95(GoProfile):
    owner: str = "VictoriaMetrics"
    repo: str = "fastcache"
    commit: str = "cef9ae9584294a46c74e5b9ba7563a0aa292931e"


@dataclass
class Gcache(GoProfile):
    owner: str = "bluele"
    repo: str = "gcache"
    commit: str = "d8b7e051c564c174fea6ef60d180abf601099015"


@dataclass
class Groupcache(GoProfile):
    owner: str = "golang"
    repo: str = "groupcache"
    commit: str = "2c02b8208cf8c02a3e358cb1d9b60950647543fc"


@dataclass
class Otter8c526307(GoProfile):
    owner: str = "maypok86"
    repo: str = "otter"
    commit: str = "8c526307556486ea0337280a4211135720bc29cc"


@dataclass
class Ristretto402101df(GoProfile):
    owner: str = "hypermodeinc"
    repo: str = "ristretto"
    commit: str = "402101df6c698ed1253bb305ce9cda71bc83ad1d"


@dataclass
class Sturdyc(GoProfile):
    owner: str = "viccon"
    repo: str = "sturdyc"
    commit: str = "97fc006bbf4a7f1f09922fa77a9444e5ce3a20ad"


@dataclass
class Ttlcachedb85e4f6(GoProfile):
    owner: str = "jellydator"
    repo: str = "ttlcache"
    commit: str = "db85e4f64251c73b33ba055e3fe07d70870992ce"


@dataclass
class Ledisdb(GoProfile):
    owner: str = "ledisdb"
    repo: str = "ledisdb"
    commit: str = "d35789ec47e667726160e227e7c05e09627a6d6c"


@dataclass
class Buntdb(GoProfile):
    owner: str = "tidwall"
    repo: str = "buntdb"
    commit: str = "3daff4e1233584685027938bde39971cc239f2b2"


@dataclass
class Diskv(GoProfile):
    owner: str = "peterbourgon"
    repo: str = "diskv"
    commit: str = "2566386005f64f58f34e1ff32907800a64537e6a"


@dataclass
class Eliasdb(GoProfile):
    owner: str = "krotik"
    repo: str = "eliasdb"
    commit: str = "88a1da66df9527aa97e8781dfc91cb9feb08125c"


@dataclass
class Godisf13d9cb9(GoProfile):
    owner: str = "HDT3213"
    repo: str = "godis"
    commit: str = "f13d9cb9d679daa590c79ebed6f1121887152fcb"


@dataclass
class Moss(GoProfile):
    owner: str = "couchbase"
    repo: str = "moss"
    commit: str = "bf10bab20a24b43c15d23b530fc848e7bb580cad"


@dataclass
class Pogrebb86080d0(GoProfile):
    owner: str = "akrylysov"
    repo: str = "pogreb"
    commit: str = "b86080d06267f8d12067cd432ffd9e5b6916d354"


@dataclass
class Redkad3c353f0(GoProfile):
    owner: str = "nalgeon"
    repo: str = "redka"
    commit: str = "d3c353f024704f99c87049251bb987beba62915e"


@dataclass
class Rosedbbcb43052(GoProfile):
    owner: str = "rosedblabs"
    repo: str = "rosedb"
    commit: str = "bcb43052ada686ec6d1345328e8299f502d3ef01"


@dataclass
class Atlasdf198801(GoProfile):
    owner: str = "ariga"
    repo: str = "atlas"
    commit: str = "df19880124d46a91d5d9f351130b90cb46b8f567"


@dataclass
class Avroafbafcb0(GoProfile):
    owner: str = "hamba"
    repo: str = "avro"
    commit: str = "afbafcb0b218ec431940d4866cc141ce2ef51172"


@dataclass
class Skeema9a2b471b(GoProfile):
    owner: str = "skeema"
    repo: str = "skeema"
    commit: str = "9a2b471b4aeceac44a4798fb223a681262df13d1"


@dataclass
class Chproxy77a99f12(GoProfile):
    owner: str = "ContentSquare"
    repo: str = "chproxy"
    commit: str = "77a99f12be3bfa57717bac03765c15995d71acc7"


@dataclass
class ClickhouseBulk(GoProfile):
    owner: str = "nikepan"
    repo: str = "clickhouse-bulk"
    commit: str = "cdc261cb029f4d493fa825a6edffe3f2f1b81f1e"


@dataclass
class Prestb62662d2(GoProfile):
    owner: str = "prest"
    repo: str = "prest"
    commit: str = "b62662d2642ba3fd1c3c3ab83f4dbf2cc8509a63"


@dataclass
class Rdb7ebe18a1(GoProfile):
    owner: str = "HDT3213"
    repo: str = "rdb"
    commit: str = "7ebe18a1ebef31cbcf1bd07744b47cd5d25fe7de"


@dataclass
class Goqu(GoProfile):
    owner: str = "doug-martin"
    repo: str = "goqu"
    commit: str = "21b6e6d1cb1befe839044764d8ad6b1c6f0b5ef4"


@dataclass
class Squirrel(GoProfile):
    owner: str = "Masterminds"
    repo: str = "squirrel"
    commit: str = "1ded5784535dcffa4e175d4efbd1ca2706927758"


@dataclass
class Sqlingo99a6d5b3(GoProfile):
    owner: str = "lqs"
    repo: str = "sqlingo"
    commit: str = "99a6d5b37a1a5762a9c4a5a71253b07ef064211c"

    @property
    def dockerfile(self):
        return f"""FROM golang:1.24
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod init github.com/lqs/sqlingo
RUN go mod tidy
CMD ["/bin/bash"]
"""


@dataclass
class Dotsql(GoProfile):
    owner: str = "qustavo"
    repo: str = "dotsql"
    commit: str = "5d06b8903af8416d86b205c175b22ee903d869c8"


@dataclass
class GoMssqldb(GoProfile):
    owner: str = "denisenkom"
    repo: str = "go-mssqldb"
    commit: str = "103f0369fa02aac21aae282e4f7f81c903aba6be"


@dataclass
class Mysqla065b60a(GoProfile):
    owner: str = "go-sql-driver"
    repo: str = "mysql"
    commit: str = "a065b60ab6d0c8e15468e7709c7f76acf4431647"


@dataclass
class Gosqlite320826e87(GoProfile):
    owner: str = "mattn"
    repo: str = "go-sqlite3"
    commit: str = "20826e87d8f061d0a7266562f43950ee06e2e9c0"


@dataclass
class Godror66765086(GoProfile):
    owner: str = "godror"
    repo: str = "godror"
    commit: str = "66765086d7947269c80c96b170b007b1c86cf487"


@dataclass
class Ksql2f80a222(GoProfile):
    owner: str = "VinGarcia"
    repo: str = "ksql"
    commit: str = "2f80a222570639cbf7ca207f157f1823d421d1a4"


@dataclass
class Richgoa351793e(GoProfile):
    owner: str = "kyoh86"
    repo: str = "richgo"
    commit: str = "a351793e36402c3883985b1ce3ac2d4235dbdea4"


@dataclass
class Goimportsreviserfa5587e5(GoProfile):
    owner: str = "incu6us"
    repo: str = "goimports-reviser"
    commit: str = "fa5587e51ba33c58734984cb41370a5b2582d5b7"


@dataclass
class Wrapcheckc058da10(GoProfile):
    owner: str = "tomarrell"
    repo: str = "wrapcheck"
    commit: str = "c058da1005e26566820d7eb858899c280d87eab9"


@dataclass
class Todocheck97440d05(GoProfile):
    owner: str = "presmihaylov"
    repo: str = "todocheck"
    commit: str = "97440d0590ea875d0931c71f6c5924bfc0e6a3c3"


@dataclass
class Revive9a886b16(GoProfile):
    owner: str = "mgechev"
    repo: str = "revive"
    commit: str = "9a886b1625361e32687ed60d044db99d8eeec822"


@dataclass
class Errcheck961568ff(GoProfile):
    owner: str = "kisielk"
    repo: str = "errcheck"
    commit: str = "961568ffb3cbedf5f1e8daac50e778981285ca9b"


@dataclass
class Dupl8836f5c0(GoProfile):
    owner: str = "mibk"
    repo: str = "dupl"
    commit: str = "8836f5c0e8eacdc5233911754b94e70917cf0dba"


@dataclass
class Gocritic9aea378c(GoProfile):
    owner: str = "go-critic"
    repo: str = "go-critic"
    commit: str = "9aea378c4dccd6f4394196ad8f0873b3e84678c8"


@dataclass
class GoModOutdated(GoProfile):
    owner: str = "psampaz"
    repo: str = "go-mod-outdated"
    commit: str = "bb79367d102a05221196613dde574f1a0b81b556"


@dataclass
class Xpathafd4762c(GoProfile):
    owner: str = "antchfx"
    repo: str = "xpath"
    commit: str = "afd4762cc342af56345a3fb4002a59281fcab494"


@dataclass
class Bone(GoProfile):
    owner: str = "go-zoo"
    repo: str = "bone"
    commit: str = "31c3a0bb520c6d7a63dbb942459a3067787a975e"


@dataclass
class Chia54874f0(GoProfile):
    owner: str = "go-chi"
    repo: str = "chi"
    commit: str = "a54874f0e2f12647a19e82ee70dfa8185014100c"


@dataclass
class Httprouter(GoProfile):
    owner: str = "julienschmidt"
    repo: str = "httprouter"
    commit: str = "484018016424d215c0b87c42f4c9b57d980fbd00"


@dataclass
class Httptreemux(GoProfile):
    owner: str = "dimfeld"
    repo: str = "httptreemux"
    commit: str = "53a6a09954e8593e66a0c372335c0e96b318b920"


### Security repos (CWE-targeted) ###


@dataclass
class Etcd36e2dbd5(GoProfile):
    owner: str = "etcd-io"
    repo: str = "etcd"
    commit: str = "36e2dbd502b2acab083d8901574d7d4cc66109fd"
    timeout: int = 180
    timeout_ref: int = 1800


@dataclass
class Mobyee3e21b7(GoProfile):
    owner: str = "moby"
    repo: str = "moby"
    commit: str = "ee3e21b70457f90d537640613d59340db1f0178c"
    timeout: int = 180
    timeout_ref: int = 1800

    @property
    def dockerfile(self):
        return f"""FROM golang:1.24
RUN apt-get update && apt-get install -y libseccomp-dev libbtrfs-dev libdevmapper-dev
RUN git clone {self.mirror_url} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Runceb7eaf19(GoProfile):
    owner: str = "opencontainers"
    repo: str = "runc"
    commit: str = "eb7eaf19b6eec5d1143b257057899e4a7b738c81"
    timeout: int = 120

    @property
    def dockerfile(self):
        return f"""FROM golang:1.24
RUN apt-get update && apt-get install -y libseccomp-dev pkg-config
RUN git clone {self.mirror_url} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Vaultd8868300(GoProfile):
    owner: str = "hashicorp"
    repo: str = "vault"
    commit: str = "d88683008114a35ec9fe6d6ed88838aae937531d"
    timeout: int = 180
    timeout_ref: int = 1800


@dataclass
class Consulb37270d7(GoProfile):
    owner: str = "hashicorp"
    repo: str = "consul"
    commit: str = "b37270d7a35664fceeeda151074e2570714e6f83"
    timeout: int = 180
    timeout_ref: int = 1800


@dataclass
class God5ebe810(GoProfile):
    owner: str = "golang"
    repo: str = "go"
    commit: str = "d5ebe8100deba2dd6cf26a70727b271e0f077f66"
    timeout: int = 300
    timeout_ref: int = 3600

    @property
    def dockerfile(self):
        return f"""FROM golang:1.24
RUN git clone {self.mirror_url} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Ciliume99150f8(GoProfile):
    owner: str = "cilium"
    repo: str = "cilium"
    commit: str = "e99150f8d8f403eca51ed82138d4ae20a265c8f3"
    timeout: int = 180
    timeout_ref: int = 1800


@dataclass
class CsiDriverNfsea222a77(GoProfile):
    owner: str = "kubernetes-csi"
    repo: str = "csi-driver-nfs"
    commit: str = "ea222a77e900a367092d1b2f93df7731c7b3b4ec"


@dataclass
class Gogit9bca9e01(GoProfile):
    owner: str = "go-git"
    repo: str = "go-git"
    commit: str = "9bca9e0108fbb5db38ac4016546606fed4010688"
    timeout: int = 120


@dataclass
class ArgoWorkflows80dc102f(GoProfile):
    owner: str = "argoproj"
    repo: str = "argo-workflows"
    commit: str = "80dc102f42b0867019e3464e9a341bc3e6bfa310"
    timeout: int = 180
    timeout_ref: int = 1800


@dataclass
class Traefikedd7d2eb(GoProfile):
    owner: str = "traefik"
    repo: str = "traefik"
    commit: str = "edd7d2eb333cb4aa25e525824f60968eba403d03"
    timeout: int = 120


@dataclass
class Grafanaf07c37c6(GoProfile):
    owner: str = "grafana"
    repo: str = "grafana"
    commit: str = "f07c37c693b0a33c7bf35275c1fe3b96de7d0294"
    timeout: int = 180
    timeout_ref: int = 1800


@dataclass
class Minio7aac2a2c(GoProfile):
    owner: str = "minio"
    repo: str = "minio"
    commit: str = "7aac2a2c5b7c882e68c1ce017d8256be2feea27f"
    timeout: int = 120


# Register all Go profiles with the global registry
for name, obj in list(globals().items()):
    if (
        isinstance(obj, type)
        and issubclass(obj, GoProfile)
        and obj.__name__ != "GoProfile"
    ):
        registry.register_profile(obj)

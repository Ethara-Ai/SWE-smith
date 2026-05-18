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
class Bubbleteac60f0c53(GoProfile):
    owner: str = "charmbracelet"
    repo: str = "bubbletea"
    commit: str = "c60f0c53042238305ec13b486326588f12aea0ec"
    timeout: int = 120
    timeout_ref: int = 1800
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "build/tools/gen-cockroachdb-metrics",
                "pkg/cmd/generate-ash-inventory",
                "pkg/cmd/roachprod-microbench",
            ],
            "CWE-193": [
                "pkg/util/trigram",
                "pkg/util/stringencoding",
                "pkg/util/bitarray",
                "pkg/sql/lex",
                "pkg/cmd/generate-ash-inventory",
            ],
            "CWE-20": [
                "pkg/sql/decodeusername",
                "pkg/sql/paramparse",
                "pkg/cmd/urlcheck",
                "pkg/sql/parserutils",
                "pkg/server/privchecker",
                "pkg/sql/parser",
                "pkg/workload/tpccchecks",
            ],
            "CWE-670": [
                "pkg/spanconfig/spanconfigreconciler",
                "pkg/cmd/cmp-protocol",
                "pkg/sql/colencoding",
                "pkg/util/schedulerlatency",
                "pkg/util/binfetcher",
                "pkg/cmd/generate-distdir",
                "pkg/cmd/cmp-sql",
            ],
            "CWE-682": [
                "pkg/sql/stats",
                "pkg/sql/appstatspb",
                "pkg/server/status",
                "pkg/jobs/metricspoller",
                "pkg/util/arith",
            ],
            "CWE-754": [
                "pkg/cli/clierrorplus",
                "pkg/util/errorutil",
                "pkg/cli/clierror",
                "pkg/sql/sqlerrors",
                "pkg/roachprod/errors",
                "pkg/server/srverrors",
                "pkg/sql/colexecerror",
            ],
            "CWE-835": [
                "pkg/util/iterutil",
                "pkg/jobs/metricspoller",
                "pkg/util/schedulerlatency",
                "pkg/util/trigram",
                "pkg/cli/syncbench",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/charmbracelet/bubbletea.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


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
class Etcd053fc705(GoProfile):
    owner: str = "etcd-io"
    repo: str = "etcd"
    commit: str = "053fc705d99824509fb0313036dc8a18e0ff4b86"
    timeout: int = 300
    timeout_ref: int = 3600
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-193": [
                "tools/rw-heatmaps/pkg",
                "tools/benchmark/cmd",
                "tools/etcd-dump-metrics",
                "tools/etcd-dump-logs",
                "tools/testgrid-analysis/cmd",
                "pkg/netutil",
                "server/verify",
                "client/v3/mirror",
            ],
            "CWE-20": [
                "pkg/netutil",
                "tools/proto-annotations/cmd",
                "pkg/pbutil",
                "tools/check-grpc-experimental",
                "client/pkg/tlsutil",
            ],
            "CWE-682": [
                "pkg/idutil",
                "pkg/netutil",
                "server/etcdserver/txn",
                "tools/etcd-dump-metrics",
                "tools/etcd-dump-logs",
                "tools/rw-heatmaps/pkg",
                "tools/benchmark/cmd",
            ],
            "CWE-835": [
                "tools/testgrid-analysis/cmd",
                "client/pkg/tlsutil",
                "server/proxy/tcpproxy",
                "tools/benchmark/cmd",
                "client/v3/leasing",
                "tools/etcd-dump-logs",
                "tools/local-tester/bridge",
                "client/v3/mirror",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN apt-get update && apt-get install -y build-essential
RUN git clone https://github.com/etcd-io/etcd.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


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
    timeout: int = 180
    timeout_ref: int = 1800
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-193": [
                "pkg/config/kv",
                "internal",
                "pkg/provider/ecs",
                "pkg/middlewares/encodedcharacters",
                "pkg/middlewares/compress",
                "pkg/middlewares/stripprefixregex",
                "pkg/middlewares/forwardedheaders",
            ],
            "CWE-20": [
                "pkg/healthcheck",
                "pkg/ip",
                "pkg/provider/nomad",
                "pkg/config/kv",
                "pkg/cli",
            ],
            "CWE-670": [
                "pkg/middlewares/stripprefixregex",
                "pkg/middlewares/headers",
                "pkg/middlewares/stripprefix",
                "pkg/middlewares/accesslog",
                "pkg/middlewares/compress",
                "pkg/middlewares/ingressnginx",
                "pkg/middlewares/passtlsclientcert",
                "pkg/server/router",
            ],
            "CWE-682": [
                "pkg/middlewares/metrics",
                "pkg/config/static",
                "pkg/observability/metrics",
                "pkg/collector",
                "pkg/provider/http",
                "pkg/tls/generate",
            ],
            "CWE-754": [
                "pkg/middlewares/tcp",
                "pkg/middlewares/snicheck",
                "pkg/middlewares/ratelimiter",
                "pkg/middlewares/replacepathregex",
                "pkg/middlewares/auth",
                "pkg/server/middleware",
                "pkg/middlewares/ingressnginx",
                "pkg/middlewares/stripprefix",
            ],
            "CWE-835": [
                "pkg/provider/tailscale",
                "pkg/provider/docker",
                "pkg/provider/ecs",
                "pkg/provider/consulcatalog",
                "pkg/healthcheck",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/traefik/traefik.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


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


@dataclass
class Act123167dc(GoProfile):
    owner: str = "nektos"
    repo: str = "act"
    commit: str = "123167dcaf6ec2c6a7e391ba21afadb55e4fadb5"
    timeout: int = 180
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-20": [
                "pkg/exprparser",
                "pkg/model",
                "pkg/schema",
                "pkg/artifactcache",
                "pkg/container",
                "pkg/common/git",
                "cmd",
            ],
            "CWE-670": [
                "pkg/workflowpattern",
                "pkg/exprparser",
                "pkg/schema",
                "pkg/model",
                "cmd",
                "pkg/runner",
                "pkg/common",
                "pkg/container",
            ],
            "CWE-835": [
                "pkg/schema",
                "pkg/common",
                "pkg/container",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
ENV GOPROXY=https://proxy.golang.org,direct
ENV GOFLAGS=-mod=mod
RUN git clone https://github.com/nektos/act.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN for i in 1 2 3 4 5; do go mod download -x && break || (echo "download retry $i" && sleep 15); done
RUN for i in 1 2 3 4 5; do go mod tidy && break || (echo "tidy retry $i" && sleep 15); done
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Prometheuse793b267(GoProfile):
    owner: str = "prometheus"
    repo: str = "prometheus"
    commit: str = "e793b26713cc7052c7558ae6ceffaa66c2a5b39f"
    timeout: int = 300
    timeout_ref: int = 3600
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-193": [
                "tsdb/index",
                "storage/remote/otlptranslator",
                "model/histogram",
                "util/convertnhcb",
                "util/strutil",
            ],
            "CWE-20": [
                "model/textparse",
                "promql/parser",
                "model/rulefmt",
                "tsdb/compression",
                "cmd/promtool",
                "model/relabel",
            ],
            "CWE-670": [
                "storage/remote/otlptranslator",
                "discovery/refresh",
                "util/treecache",
                "util/testrecord",
                "util/strutil",
                "model/histogram",
                "util/pool",
                "util/fmtutil",
            ],
            "CWE-682": [
                "util/stats",
                "util/pool",
                "discovery/refresh",
                "util/testrecord",
                "storage/remote/otlptranslator",
                "cmd/promtool",
                "model/relabel",
                "web",
            ],
            "CWE-835": [
                "util/treecache",
                "cmd/prometheus",
                "cmd/promtool",
                "util/httputil",
                "tsdb/index",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/prometheus/prometheus.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Goethereumda34eb59(GoProfile):
    owner: str = "ethereum"
    repo: str = "go-ethereum"
    commit: str = "da34eb59fdee4b0d12e3cf0b8a5e5b3546cb0632"
    timeout: int = 300
    timeout_ref: int = 3600
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-193": [
                "eth/gasprice",
                "beacon/light/sync",
                "miner/stress",
                "cmd/workload",
                "core/filtermaps",
                "core/txpool/blobpool",
                "common/bitutil",
                "eth/tracers/internal",
            ],
            "CWE-20": [
                "eth/filters",
                "core/filtermaps",
                "common/math",
                "ethstats",
                "cmd/geth",
                "cmd/devp2p",
            ],
            "CWE-670": [
                "eth/gasprice",
                "core/state/snapshot",
                "core/state/pruner",
                "core/stateless",
                "core/state",
                "miner/stress",
                "beacon/light/sync",
                "cmd/rlpdump",
            ],
            "CWE-682": [
                "metrics/influxdb",
                "triedb/hashdb",
                "core/state/pruner",
                "core/stateless",
                "core/state/snapshot",
                "ethstats",
                "common/math",
                "consensus/ethash",
            ],
            "CWE-835": [
                "eth/gasprice",
                "miner/stress",
                "core/txpool",
                "eth/fetcher",
                "internal/shutdowncheck",
                "beacon/light/sync",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN apt-get update && apt-get install -y build-essential libsnappy-dev
RUN git clone https://github.com/ethereum/go-ethereum.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Memos638e4f39(GoProfile):
    owner: str = "usememos"
    repo: str = "memos"
    commit: str = "638e4f398e90c556f70af150a79538312c8fc760"
    timeout: int = 180
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "internal/motionphoto",
                "internal/base",
                "server/router/api/v1",
                "server/router/fileserver",
                "server/router/rss",
            ],
            "CWE-193": [
                "internal/motionphoto",
                "internal/ai/audio",
                "internal/version",
                "internal/markdown/renderer",
                "server/router/rss",
            ],
            "CWE-20": [
                "internal/filter",
                "internal/markdown/parser",
                "server/router/api/v1",
                "internal/idp/oauth2",
                "internal/httpgetter",
            ],
            "CWE-670": [
                "internal/scheduler",
                "server/router/rss",
                "server/router/mcp",
                "server/router/api/v1",
                "server/router/fileserver",
                "server/router/frontend",
            ],
            "CWE-835": [
                "internal/scheduler",
                "internal/webhook",
                "internal/httpgetter",
                "server/runner/s3presign",
                "server/runner/memopayload",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN apt-get update && apt-get install -y build-essential
RUN git clone https://github.com/usememos/memos.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Rclonee95b64be(GoProfile):
    owner: str = "rclone"
    repo: str = "rclone"
    commit: str = "e95b64be086bf685b2778a84797a2cae8663c53e"
    timeout: int = 300
    timeout_ref: int = 3600
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "cmd",
                "cmd/selfupdate",
                "backend/webdav/api",
                "fs/filter",
                "fs/fspath",
                "fs/config/configstruct",
            ],
            "CWE-193": [
                "lib/ranges",
                "lib/encoder/filename",
                "cmd/listremotes",
                "cmd/rc",
                "cmd/ncdu",
                "backend/hidrive/hidrivehash",
            ],
            "CWE-20": [
                "fs/filter",
                "cmd/cryptdecode",
                "cmd/check",
            ],
            "CWE-670": [
                "cmd/listremotes",
                "fs/config/configflags",
                "fs/config/configstruct",
            ],
            "CWE-682": [
                "lib/encoder/filename",
                "backend/hasher",
                "fs/hash",
                "backend/hidrive/hidrivehash",
                "backend/mailru/mrhash",
                "lib/encoder",
                "backend/dropbox/dbhash",
                "backend/onedrive/quickxorhash",
            ],
            "CWE-754": [
                "fs/fserrors",
                "fs/march",
                "fs/walk",
                "backend/union/upstream",
                "fs/dirtree",
                "lib/batcher",
            ],
            "CWE-835": [
                "fs/dirtree",
                "cmd/listremotes",
                "fs/walk",
                "fs/march",
                "lib/encoder/filename",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/rclone/rclone.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Gitea2450127c(GoProfile):
    owner: str = "go-gitea"
    repo: str = "gitea"
    commit: str = "2450127c56ff36e0494e796918e99aa451c6b944"
    timeout: int = 300
    timeout_ref: int = 3600
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "modules/markup",
                "modules/markup/common",
                "modules/regexplru",
                "modules/validation",
                "modules/references",
                "routers/web/admin",
                "routers/web/user",
            ],
            "CWE-193": [
                "modules/git/languagestats",
                "modules/packages/rpm",
                "modules/packages/swift",
                "modules/packages/nuget",
                "modules/indexer/code",
                "services/repository/gitgraph",
                "build",
            ],
            "CWE-20": [
                "modules/validation",
                "modules/updatechecker",
                "modules/actions/jobparser",
                "modules/git/pipeline",
            ],
            "CWE-670": [
                "routers/web/explore",
                "routers/web/user",
                "routers/web/repo",
                "routers/web/shared",
                "routers/api/packages",
                "routers/common",
                "routers/web/admin",
            ],
            "CWE-682": [
                "modules/git/languagestats",
                "modules/commitstatus",
                "modules/indexer/stats",
                "modules/metrics",
                "services/repository/commitstatus",
            ],
            "CWE-754": [
                "modules/web/middleware",
                "modules/packages/alpine",
                "modules/proxy",
            ],
            "CWE-835": [
                "modules/packages/nuget",
                "modules/packages/cran",
                "services/mailer/incoming",
                "build",
                "models/migrations/v1_6",
                "modules/util/rotatingfilewriter",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN apt-get update && apt-get install -y build-essential git
RUN git clone https://github.com/go-gitea/gitea.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Terraform93b0eae7(GoProfile):
    owner: str = "hashicorp"
    repo: str = "terraform"
    commit: str = "93b0eae7368ff4b4c2cfad8c3c92401c4bc26afb"
    timeout: int = 300
    timeout_ref: int = 3600
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "internal/getmodules/moduleaddrs",
                "internal/states/statefile",
                "internal/configs/configschema",
                "internal/backend/remote-state",
            ],
            "CWE-193": [
                "internal/ipaddr",
                "internal/command/jsonconfig",
                "internal/command/jsonplan",
                "internal/command/format",
                "internal/command/junit",
            ],
            "CWE-20": [
                "internal/command/jsonplan",
                "internal/command/jsonstate",
                "internal/modsdir",
                "internal/getmodules/moduleaddrs",
                "internal/configs/hcl2shim",
                "internal/providers/testing",
                "internal/stacks/stackplan",
            ],
            "CWE-670": [
                "internal/command/jsonstate",
                "internal/states/statefile",
                "internal/command/jsonplan",
                "internal/command/jsonconfig",
                "internal/command/format",
                "internal/backend/remote-state",
                "internal/states",
            ],
            "CWE-682": [
                "internal/states/statefile",
                "internal/backend/remote-state",
                "internal/states/statemgr",
            ],
            "CWE-835": [
                "internal/ipaddr",
                "internal/command/jsonconfig",
                "internal/command/jsonstate",
                "internal/command/jsonplan",
                "internal/configs/configschema",
                "internal/command/format",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/hashicorp/terraform.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Alist527ad893(GoProfile):
    owner: str = "AlistGo"
    repo: str = "alist"
    commit: str = "527ad89362a8f3d51a35c5e4b6672cf05c983a5b"
    timeout: int = 180
    timeout_ref: int = 1800
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "drivers/onedrive_sharelink",
                "drivers/doubao_share",
                "drivers/streamtape",
                "drivers/chunker",
                "server/handles",
                "drivers/azure_blob",
                "drivers/yunpan360",
            ],
            "CWE-193": [
                "drivers/chunker",
                "server/webdav/internal",
                "pkg/sign",
                "drivers/doubao_share",
                "internal/net",
                "pkg/http_range",
                "pkg/singleflight",
            ],
            "CWE-20": [
                "pkg/gowebdav/cmd",
                "server/handles",
                "drivers/webdav/odrvcookie",
                "drivers/bitqiu",
                "drivers/chaoxing",
                "drivers/quqi",
            ],
            "CWE-670": [
                "server/webdav",
                "drivers/139",
                "drivers/bitqiu",
                "internal/archive/tool",
                "server/webdav/internal",
                "internal/bootstrap/data",
                "internal/device",
                "server/static",
            ],
            "CWE-682": [
                "pkg/utils/hash",
                "internal/setting",
                "pkg/gowebdav/cmd",
                "pkg/qbittorrent",
                "drivers/guangyapan",
                "server/handles",
                "internal/bootstrap",
            ],
            "CWE-754": [
                "drivers/yunpan360",
                "drivers/aliyundrive_open",
                "drivers/chaoxing",
                "pkg/qbittorrent",
                "drivers/quqi",
                "drivers/azure_blob",
                "server/middlewares",
                "drivers/alias",
            ],
            "CWE-835": [
                "internal/archive/tool",
                "drivers/bitqiu",
                "internal/net",
                "internal/archive/rardecode",
                "internal/search",
                "server/webdav/internal",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/AlistGo/alist.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Lazydocker7e7aadc2(GoProfile):
    owner: str = "jesseduffield"
    repo: str = "lazydocker"
    commit: str = "7e7aadc2071d58031bf2daafca1fbd4093efc23f"
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-193": [
                "pkg/utils",
                "pkg/gui",
                "pkg/commands",
                "pkg/gui/presentation",
            ],
            "CWE-754": [
                "pkg/log",
                "pkg/commands/ssh",
                "pkg/config",
                "pkg/commands",
                "pkg/gui",
                "pkg/cheatsheet",
            ],
            "CWE-835": [
                "pkg/tasks",
                "pkg/gui",
                "pkg/commands/ssh",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/jesseduffield/lazydocker.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Gogsd7571322(GoProfile):
    owner: str = "gogs"
    repo: str = "gogs"
    commit: str = "d7571322a04a29476d4241406ed50bf7eef0a5b7"
    timeout: int = 180
    timeout_ref: int = 1800
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "internal/lazyregexp",
                "internal/database",
                "internal/form",
                "internal/gitx",
                "internal/context",
                "internal/markup",
                "internal/route/repo",
            ],
            "CWE-193": [
                "internal/strx",
                "cmd/gogs",
                "internal/route/repo",
                "internal/markup",
                "internal/route/user",
            ],
            "CWE-670": [
                "internal/dbx",
                "internal/ssh",
                "internal/route/org",
                "internal/route/admin",
                "internal/markup",
                "cmd/gogs",
                "internal/route/user",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/gogs/gogs.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Cli2b7e7767(GoProfile):
    owner: str = "cli"
    repo: str = "cli"
    commit: str = "2b7e77674884953ac8bb904cd0272107a882caf7"
    timeout: int = 180
    timeout_ref: int = 1800
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "pkg/search",
                "internal/update",
                "pkg/cmd/api",
                "pkg/cmd/release",
                "pkg/cmd/attestation",
                "pkg/cmd/run",
                "pkg/githubtemplate",
            ],
            "CWE-193": [
                "pkg/jsoncolor",
                "pkg/cmd/api",
                "pkg/cmd/ssh-key",
                "pkg/cmd/skills",
                "pkg/cmd/release",
                "pkg/cmd/gist",
            ],
            "CWE-670": [
                "pkg/cmd/workflow",
                "pkg/cmd/api",
                "pkg/jsoncolor",
                "pkg/cmd/search",
                "pkg/cmd/issue",
                "pkg/cmd/status",
                "pkg/cmd/run",
            ],
            "CWE-682": [
                "pkg/cmd/status",
                "pkg/cmd/attestation",
                "pkg/cmd/ssh-key",
                "pkg/cmd/skills",
            ],
            "CWE-835": [
                "pkg/cmd/skills",
                "pkg/cmd/api",
                "pkg/cmd/run",
                "pkg/cmd/ruleset",
                "pkg/cmd/release",
                "pkg/cmd/status",
                "pkg/cmd/issue",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/cli/cli.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Localai8af963bd(GoProfile):
    owner: str = "mudler"
    repo: str = "LocalAI"
    commit: str = "8af963bdd92ea1208eadb93101b662b5a22f0aa5"
    timeout: int = 300
    timeout_ref: int = 3600
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "pkg/functions/grammars",
                "core/config",
                "pkg/functions",
                "pkg/functions/peg",
                "pkg/utils",
                "core/backend",
            ],
            "CWE-193": [
                "core/trace",
                "pkg/xsysinfo",
                "pkg/functions",
                "pkg/functions/peg",
                "core/config/gen_inference_defaults",
                "pkg/sound",
                "core/gallery/importers",
            ],
            "CWE-20": [
                "backend/go/piper",
                "backend/go/whisper",
                "backend/go/sam3-cpp",
                "backend/go/vibevoice-cpp",
                "core/cli/worker",
                "pkg/xsysinfo",
                "core/services/skills",
            ],
            "CWE-670": [
                "core/http/middleware",
                "backend/go/acestep-cpp",
                "backend/go/localvqe",
                "core/cli",
                "core/schema",
                "backend/go/vibevoice-cpp",
            ],
            "CWE-754": [
                "core/http/middleware",
                "pkg/oci",
                "core/cli/worker",
                "core/services/skills",
                "core/backend",
                "core/services/modeladmin",
                "backend/go/vibevoice-cpp",
            ],
            "CWE-835": [
                "core/services/worker",
                "core/cli/worker",
                "core/cli/workerregistry",
                "cmd/launcher/internal",
                "backend/go/local-store",
                "core/explorer",
                "core/cli",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.26
ENV GOTOOLCHAIN=auto
RUN apt-get update && apt-get install -y --no-install-recommends \\
        unzip make curl build-essential ca-certificates git && \\
    rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/mudler/LocalAI.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN make protogen-go
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"sh"]
"""


@dataclass
class Milvuse36613c7(GoProfile):
    owner: str = "milvus-io"
    repo: str = "milvus"
    commit: str = "e36613c7eaa9edb0452e7198fc751f53c52b38c7"
    timeout: int = 300
    timeout_ref: int = 3600
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-193": [
                "client/row",
                "internal/datanode/index",
                "pkg/util/merr",
                "internal/parser/planparserv2",
            ],
            "CWE-20": [
                "internal/querynodev2/pipeline",
                "internal/util/indexparamcheck",
                "internal/parser/planparserv2",
                "internal/querycoordv2/checkers",
                "client/ruleguard",
                "internal/flushcommon/pipeline",
            ],
            "CWE-670": [
                "internal/querynodev2/pipeline",
                "internal/cdc/controller",
                "pkg/mq/msgdispatcher",
                "cmd/tools/config",
                "internal/flushcommon/pipeline",
                "client/row",
                "internal/util/pipeline",
                "internal/util/clustering",
            ],
            "CWE-682": [
                "internal/util/metrics",
                "pkg/util/metricsinfo",
                "pkg/metrics",
                "internal/storagev2",
                "internal/util/clustering",
                "pkg/util/timestamptz",
            ],
            "CWE-754": [
                "pkg/util/interceptor",
                "pkg/objectstorage/gcp",
                "internal/distributed/utils",
                "internal/storagev2",
                "internal/proxy/replicate",
                "pkg/util/timestamptz",
                "pkg/util/externalspec",
                "pkg/util/requestutil",
            ],
            "CWE-835": [
                "internal/streamingcoord/server",
                "internal/streamingcoord/client",
                "internal/streamingnode/client",
                "internal/distributed/streaming",
                "internal/streamingnode/server",
                "pkg/streaming/util",
                "internal/util/streamingutil",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/milvus-io/milvus.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN go mod download
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""



@dataclass
class Fabric6a9b55a0(GoProfile):
    owner: str = "danielmiessler"
    repo: str = "Fabric"
    commit: str = "6a9b55a096361d368368fa8119f7dd3b8bf2673b"
    timeout: int = 180
    timeout_ref: int = 1800
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "cmd/generate_changelog/internal",
                "internal/tools/spotify",
                "internal/tools/youtube",
            ],
            "CWE-193": [
                "cmd/code2context",
                "cmd/generate_changelog/internal",
                "internal/tools/youtube",
                "internal/cli",
                "internal/domain",
            ],
            "CWE-670": [
                "internal/core",
                "cmd/to_pdf",
                "internal/cli",
                "cmd/generate_changelog/internal",
                "internal/plugins/ai",
            ],
            "CWE-835": [
                "internal/core",
                "cmd/generate_changelog/internal",
                "internal/tools/youtube",
                "internal/plugins/ai",
                "internal/cli",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/danielmiessler/Fabric.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Istio98c4a24a(GoProfile):
    owner: str = "istio"
    repo: str = "istio"
    commit: str = "98c4a24a9faeeed620e4be0de56fed913161f94f"
    timeout: int = 300
    timeout_ref: int = 3600
    # Scoped to bug_gen_dirs_include parents. Skips cni/*, tests/binary,
    # tools/istio-{ip,nf}tables/pkg/capture, tools/istio-iptables/pkg/dependencies
    # which blank-import unshare-go/netns (init() needs CAP_SYS_ADMIN, exits silently).
    test_cmd: str = (
        "go test -v "
        "./tools/docker-builder/... ./tools/bug-report/pkg/... "
        "./tools/istio-iptables/pkg/builder/... "
        "./tools/istio-iptables/pkg/validation/... "
        "./pkg/config/... ./pkg/util/... ./pkg/slices/... "
        "./pkg/jwt/... ./pkg/filewatcher/... ./pkg/webhooks/... "
        "./pkg/kube/controllers/... ./pkg/kube/watcher/... "
        "./istioctl/pkg/metrics/... ./istioctl/pkg/validate/... "
        "./istioctl/pkg/checkinject/... ./istioctl/pkg/precheck/... "
        "./pilot/pkg/controllers/... ./pilot/pkg/status/... "
        "./operator/pkg/install/..."
    )
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "tools/docker-builder",
                "tools/istio-iptables/pkg",
                "tools/bug-report/pkg",
                "pkg/config/labels",
                "pkg/config/validation",
            ],
            "CWE-193": [
                "pkg/util/strcase",
                "pkg/slices",
                "pkg/config/labels",
                "istioctl/pkg/metrics",
                "pkg/config/crd",
            ],
            "CWE-20": [
                "istioctl/pkg/validate",
                "istioctl/pkg/checkinject",
                "pkg/config/validation",
                "istioctl/pkg/precheck",
                "pkg/webhooks/validation",
            ],
            "CWE-670": [
                "pilot/pkg/controllers",
                "istioctl/pkg/checkinject",
                "pkg/jwt",
                "pkg/kube/controllers",
            ],
            "CWE-682": [
                "istioctl/pkg/metrics",
                "pilot/pkg/status",
                "pkg/util/hash",
            ],
            "CWE-835": [
                "pkg/filewatcher",
                "pkg/config/crd",
                "operator/pkg/install",
                "pkg/kube/watcher",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/istio/istio.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN go mod tidy
RUN go test -v -count=1 ./pkg/config/... || true
CMD ["/bin/bash"]
"""


@dataclass
class Xraycore1bdb488c(GoProfile):
    owner: str = "XTLS"
    repo: str = "Xray-core"
    commit: str = "1bdb488c9ec09ea51e6899697d5b7437f3cf6eb2"
    timeout: int = 180
    timeout_ref: int = 1800
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "common/geodata/strmatcher",
                "infra/vprotogen",
                "infra/conf",
                "transport/internet",
            ],
            "CWE-193": [
                "common/crypto/internal",
                "common/bytespool",
                "proxy/tun/icmp",
                "common/protocol/bittorrent",
                "proxy/vless/encryption",
                "common/protocol/http",
                "common/uuid",
                "proxy",
            ],
            "CWE-20": [
                "proxy/wireguard",
                "proxy/wireguard/gvisortun",
                "transport/pipe",
            ],
            "CWE-670": [
                "proxy/tun/icmp",
                "app/router",
                "app/dispatcher",
                "proxy",
                "app/router/command",
            ],
            "CWE-682": [
                "transport/internet/stat",
                "app/stats/command",
                "app/stats",
            ],
            "CWE-754": [
                "common/errors",
                "common/retry",
                "common/ocsp",
                "proxy/wireguard",
                "app/dispatcher",
            ],
            "CWE-835": [
                "common/retry",
                "common/crypto/internal",
                "common/bytespool",
                "common/protocol/http",
                "proxy",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/XTLS/Xray-core.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN go mod tidy
RUN go test -v -count=1 ./common/... || true
CMD ["/bin/bash"]
"""


@dataclass
class Photoprismf6a5dc84(GoProfile):
    owner: str = "photoprism"
    repo: str = "photoprism"
    commit: str = "f6a5dc8412a7bb5bd2736231a98b7be396b6e39b"
    timeout: int = 300
    timeout_ref: int = 3600
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "internal/config",
                "internal/meta",
                "internal/entity",
                "pkg/txt",
                "pkg/clean",
                "pkg/http/header",
                "pkg/http/dns",
            ],
            "CWE-193": [
                "pkg/txt/clip",
                "pkg/txt",
                "pkg/http/dns",
                "pkg/vector/alg",
                "internal/photoprism/backup",
                "internal/auth/jwt",
            ],
            "CWE-20": [
                "internal/form",
                "pkg/http/safe",
                "pkg/clean",
                "pkg/time/tz",
            ],
            "CWE-670": [
                "pkg/dsn",
                "internal/photoprism/backup",
                "internal/thumb/avatar",
            ],
            "CWE-682": [
                "internal/ffmpeg/encode",
                "internal/thumb/crop",
                "pkg/vector/alg",
                "pkg/geo",
            ],
            "CWE-835": [
                "internal/workers",
                "internal/workers/auto",
                "pkg/vector/alg",
                "internal/auth/jwt",
                "internal/api",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN apt-get update && apt-get install -y build-essential libheif-dev libvips-dev ffmpeg curl ca-certificates
RUN git clone https://github.com/photoprism/photoprism.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN bash scripts/dist/install-tensorflow.sh /usr && ldconfig
RUN go mod tidy
RUN go test -v -count=1 ./pkg/... || true
CMD ["/bin/bash"]
"""


@dataclass
class Xui3af45c14(GoProfile):
    owner: str = "MHSanaei"
    repo: str = "3x-ui"
    commit: str = "3af45c14622c65e5b815b1ae4399c96d32f3a737"
    timeout: int = 180
    timeout_ref: int = 1800
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "web/controller",
                "web/job",
                "util/netsafe",
                "web/service",
                "xray",
                "web/global",
            ],
            "CWE-193": [
                "sub",
                "web/job",
                "util/random",
            ],
            "CWE-670": [
                "web/middleware",
                "web/controller",
                "sub",
            ],
            "CWE-754": [
                "web/middleware",
                "config",
                "database",
                "web/locale",
                "web/session",
                "web/network",
                "util/sys",
            ],
            "CWE-835": [
                "util/common",
                "util/sys",
                "web/websocket",
                "web/service",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN apt-get update && apt-get install -y build-essential
RUN git clone https://github.com/MHSanaei/3x-ui.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Fiber33b7fd47(GoProfile):
    owner: str = "gofiber"
    repo: str = "fiber"
    commit: str = "33b7fd4718f7d94e05214f424ed8d44bdd601836"
    timeout: int = 180
    timeout_ref: int = 1800
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                ".",
                "middleware/rewrite",
                "middleware/redirect",
            ],
            "CWE-193": [
                "middleware/redirect",
                "middleware/static",
                "middleware/etag",
                "addon/retry",
                "middleware/rewrite",
                "middleware/keyauth",
                "middleware/cors",
                "internal/memory",
            ],
            "CWE-20": [
                "middleware/static",
                "extractors",
                "middleware/cors",
                "middleware/basicauth",
                "middleware/keyauth",
            ],
            "CWE-670": [
                "middleware/keyauth",
                "middleware/static",
                "middleware/idempotency",
                "middleware/cors",
                "middleware/cache",
                "middleware/logger",
                "middleware/rewrite",
                "middleware/basicauth",
            ],
            "CWE-682": [
                "middleware/static",
                "middleware/rewrite",
                "middleware/favicon",
                "middleware/redirect",
                "middleware/etag",
                "addon/retry",
                "middleware/limiter",
            ],
            "CWE-754": [
                "middleware/compress",
                "middleware/timeout",
                "middleware/favicon",
                "middleware/static",
                "middleware/keyauth",
                "middleware/etag",
                "middleware/idempotency",
                "middleware/encryptcookie",
            ],
            "CWE-835": [
                "addon/retry",
                "internal/logtemplate",
                "middleware/cache",
                "middleware/rewrite",
                "middleware/redirect",
                "middleware/keyauth",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/gofiber/fiber.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN go mod tidy
RUN go test -v -count=1 ./... || true
CMD ["/bin/bash"]
"""


@dataclass
class Compose659b269e(GoProfile):
    owner: str = "docker"
    repo: str = "compose"
    commit: str = "659b269e5291dcc3078a4e00804a07d8fa4bea6d"
    timeout: int = 180
    timeout_ref: int = 1800
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-193": [
                "pkg/compose/transform",
                "cmd/display",
                "cmd/compatibility",
                "pkg/utils",
            ],
            "CWE-835": [
                "pkg/watch",
                "pkg/compose/transform",
                "pkg/compose",
                "pkg/utils",
                "cmd/display",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/docker/compose.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN go mod tidy
RUN go test -v -count=1 ./pkg/compose/... || true
CMD ["/bin/bash"]
"""


@dataclass
class Esbuild6a794dff(GoProfile):
    owner: str = "evanw"
    repo: str = "esbuild"
    commit: str = "6a794dff68e6a43539f6da671e3080efdf11ca70"
    timeout: int = 180
    timeout_ref: int = 1800
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-1333": [
                "cmd/esbuild",
                "internal/config",
                "internal/js_parser",
                "internal/resolver",
                "pkg/api",
            ],
            "CWE-193": [
                "internal/sourcemap",
                "internal/css_printer",
                "internal/css_lexer",
                "internal/bundler",
                "internal/linker",
                "internal/logger",
                "internal/css_parser",
                "internal/js_lexer",
            ],
            "CWE-20": [
                "internal/js_parser",
                "internal/css_parser",
                "pkg/api",
                "pkg/cli",
                "internal/bundler",
                "internal/resolver",
            ],
            "CWE-670": [
                "internal/css_printer",
                "internal/bundler",
                "internal/sourcemap",
                "internal/linker",
                "internal/js_parser",
            ],
            "CWE-682": [
                "internal/xxhash",
                "internal/sourcemap",
                "internal/css_parser",
                "internal/js_parser",
                "internal/js_printer",
            ],
            "CWE-835": [
                "internal/sourcemap",
                "internal/linker",
                "internal/css_printer",
                "internal/bundler",
                "internal/css_lexer",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM golang:1.25
ENV GOTOOLCHAIN=auto
RUN git clone https://github.com/evanw/esbuild.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git checkout {self.commit}
RUN go mod tidy
RUN go test -v -count=1 ./internal/... || true
CMD ["/bin/bash"]
"""



# Register all Go profiles with the global registry
for name, obj in list(globals().items()):
    if (
        isinstance(obj, type)
        and issubclass(obj, GoProfile)
        and obj.__name__ != "GoProfile"
    ):
        registry.register_profile(obj)

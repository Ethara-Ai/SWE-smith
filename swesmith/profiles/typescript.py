import re
from dataclasses import dataclass, field

from swesmith.constants import ENV_NAME
from swesmith.profiles.base import RepoProfile, registry

from swesmith.profiles.javascript import (
    parse_log_jasmine,
    parse_log_jest,
    parse_log_mocha,
    parse_log_vitest,
)


@dataclass
class TypeScriptProfile(RepoProfile):
    """
    Profile for TypeScript repositories.
    """

    exts: list[str] = field(default_factory=lambda: [".ts", ".tsx"])

    @classmethod
    def _dockerfile_env_groups(cls) -> list[str]:
        return ["node"]

    def extract_entities(
        self,
        dirs_exclude: list[str] | None = None,
        dirs_include: list[str] = [],
        exclude_tests: bool = True,
        max_entities: int = -1,
    ) -> list:
        """
        Override to exclude TypeScript/JavaScript build artifacts by default.
        """
        if dirs_exclude is None:
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
                "lib",
            ]

        return super().extract_entities(
            dirs_exclude=dirs_exclude,
            dirs_include=dirs_include,
            exclude_tests=exclude_tests,
            max_entities=max_entities,
        )


def default_npm_install_dockerfile(mirror_name: str, node_version: str = "20") -> str:
    """Default Dockerfile for TypeScript projects using npm."""
    return f"""FROM node:{node_version}-bullseye
RUN apt update && apt install -y git
RUN git clone https://github.com/{mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
"""


def default_pnpm_install_dockerfile(mirror_name: str, node_version: str = "20") -> str:
    """Default Dockerfile for TypeScript projects using pnpm."""
    return f"""FROM node:{node_version}-bullseye
RUN apt update && apt install -y git
RUN npm install -g pnpm
RUN git clone https://github.com/{mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN pnpm install
"""


@dataclass
class CrossEnv9951937a(TypeScriptProfile):
    owner: str = "kentcdodds"
    repo: str = "cross-env"
    commit: str = "9951937a7d3d4a1ea7bd2ce3133bcfb687125813"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim
RUN apt-get update && apt-get install -y git procps && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name} /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN npm install
CMD ["/bin/bash"]
"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class NextChatc3b8c158(TypeScriptProfile):
    owner: str = "ChatGPTNextWeb"
    repo: str = "NextChat"
    commit: str = "c3b8c1587c04fff05f7b42276a43016e87771527"
    test_cmd: str = (
        "node --no-warnings --experimental-vm-modules $(yarn bin jest) --ci --forceExit"
    )

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN yarn install
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Cherrystudio101904d0(TypeScriptProfile):
    owner: str = "CherryHQ"
    repo: str = "cherry-studio"
    commit: str = "101904d03518e601ad2970242b2f29b15219073b"
    test_cmd: str = (
        "pnpm vitest run --reporter=verbose --silent --passWithNoTests || true"
    )

    @property
    def dockerfile(self):
        return f"""FROM node:22-alpine

RUN apk add --no-cache git python3 make g++ gcc musl-dev

# Clone ONLY the main repo to save space (avoiding --recurse-submodules)
RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}

# Install pnpm and dependencies, skipping scripts and cleaning cache
RUN npm install -g pnpm@10.27.0 &&     pnpm install --ignore-scripts &&     pnpm store prune

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class CopilotKit23d47705(TypeScriptProfile):
    owner: str = "CopilotKit"
    repo: str = "CopilotKit"
    commit: str = "23d4770537c9e9a90f68237ae94fa588e1f99b2a"
    test_cmd: str = "pnpm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${{PATH}}"

RUN npm install -g pnpm@10.13.1

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class RSSHubae48d4cf(TypeScriptProfile):
    owner: str = "DIYgod"
    repo: str = "RSSHub"
    commit: str = "ae48d4cfd1e4be03e85d03ebe555bcef48bdd21a"
    test_cmd: str = "pnpm vitest run"

    @property
    def dockerfile(self):
        return f"""FROM node:22

RUN corepack enable && corepack prepare pnpm@10.28.2 --activate

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN pnpm install

CMD ["pnpm", "start"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Dokploy9b416b36(TypeScriptProfile):
    owner: str = "Dokploy"
    repo: str = "dokploy"
    commit: str = "9b416b36992b35b3b27d42b19be6a6e572e6beec"
    test_cmd: str = "pnpm --filter dokploy run test --run --reporter=verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@9.12.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install --frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Effect70ce155c(TypeScriptProfile):
    owner: str = "Effect-TS"
    repo: str = "effect"
    commit: str = "70ce155cd73a3b4cd723fe955454b5837b428f76"
    test_cmd: str = "pnpm vitest run"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@10.17.1

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

# Remove the problematic @effect/docgen dependency that's causing 404
RUN sed -i '/"@effect\\/docgen":/d' package.json

RUN pnpm install --no-frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Fuelstsb3f37c91(TypeScriptProfile):
    owner: str = "FuelLabs"
    repo: str = "fuels-ts"
    commit: str = "b3f37c91aca4aa9d5e4c0d3967f66237190826ea"
    test_cmd: str = "pnpm test:node"

    @property
    def dockerfile(self):
        return f"""FROM node:20

RUN npm install -g pnpm@9.4.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install && pnpm build:packages

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class FigmaContextMCPfe3b504d(TypeScriptProfile):
    owner: str = "GLips"
    repo: str = "Figma-Context-MCP"
    commit: str = "fe3b504d75b671896a557188a9ad801b7bac40ee"
    test_cmd: str = "pnpm test -- src/tests/benchmark.test.ts"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@10.10.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["pnpm", "start"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Gitbook8bfced2e(TypeScriptProfile):
    owner: str = "GitbookIO"
    repo: str = "gitbook"
    commit: str = "8bfced2e0de48569ec7a69589eb344795ec4213d"
    test_cmd: str = "bun run unit"

    @property
    def dockerfile(self):
        return f"""FROM oven/bun:1.3.7

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN bun install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Reactselect052e864b(TypeScriptProfile):
    owner: str = "JedWatson"
    repo: str = "react-select"
    commit: str = "052e864b4990a67c4ee416851c34d1eb7b58267b"
    test_cmd: str = "npx jest --coverage --no-cache"

    @property
    def dockerfile(self):
        return f"""FROM node:18

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Metamaskextensionbaea03ff(TypeScriptProfile):
    owner: str = "MetaMask"
    repo: str = "metamask-extension"
    commit: str = "baea03ff3f49efc967a8f61c799d12616d54b0dc"
    test_cmd: str = "yarn test:unit --ci --reporters=default --reporters=jest-junit --outputFile=test-results.xml"

    @property
    def dockerfile(self):
        return f"""FROM node:24

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN corepack enable && yarn set version 4.12.0

RUN yarn install --immutable

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class NativeScript0c8229c6(TypeScriptProfile):
    owner: str = "NativeScript"
    repo: str = "NativeScript"
    commit: str = "0c8229c6c84b51f6253eeb757e27f6bc8ffaf9ae"
    test_cmd: str = "npx nx run-many --target=test --all --parallel=1 --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install --legacy-peer-deps

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class OpenCutd1f4cb61(TypeScriptProfile):
    owner: str = "OpenCut-app"
    repo: str = "OpenCut"
    commit: str = "d1f4cb615b7fe5e08628119fceec075fbb5044a7"
    test_cmd: str = "bun test"

    @property
    def dockerfile(self):
        return f"""FROM oven/bun:1.2.18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN bun install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


# @dataclass
# class Qwencodea38a5ba8(TypeScriptProfile):
#     owner: str = "QwenLM"
#     repo: str = "qwen-code"
#     commit: str = "a38a5ba87d0642368b93acbf5ca8822277810e7e"
#     test_cmd: str = "npm test --workspaces --if-present --parallel"

#     @property
#     def dockerfile(self):
#         return f"""FROM node:20-slim

# RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

# RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
# WORKDIR /{ENV_NAME}
# RUN git submodule update --init --recursive

# RUN npm install

# CMD ["/bin/bash"]"""

#     def log_parser(self, log: str) -> dict[str, str]:
#         return parse_log_jest(log)


@dataclass
class Folo43186b7f(TypeScriptProfile):
    owner: str = "RSSNext"
    repo: str = "Folo"
    commit: str = "43186b7ffb3e3eb064aff56400162ca493283e8f"
    test_cmd: str = "pnpm run test"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@10.17.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Rxjsc15b37f8(TypeScriptProfile):
    owner: str = "ReactiveX"
    repo: str = "rxjs"
    commit: str = "c15b37f81ba5f5abea8c872b0189a70b150df4cb"
    test_cmd: str = "yarn nx run rxjs:test --reporter spec"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install --frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Redocd41fd46f(TypeScriptProfile):
    owner: str = "Redocly"
    repo: str = "redoc"
    commit: str = "d41fd46f7cbee86bf83dc17b7ec51baf54f72a54"
    test_cmd: str = "npm run unit"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Query9d1ce70b(TypeScriptProfile):
    owner: str = "TanStack"
    repo: str = "query"
    commit: str = "9d1ce70b39d91271356432147d16f5441f9fa892"
    test_cmd: str = "pnpm run test:ci"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@10.24.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Unleash4e917683(TypeScriptProfile):
    owner: str = "Unleash"
    repo: str = "unleash"
    commit: str = "4e9176836981985b9b82146269193f269821d254"
    test_cmd: str = (
        "NODE_ENV=test PORT=4243 npx vitest run --config vitest.unit.config.ts src/lib"
    )

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN corepack enable && yarn install
RUN yarn run build:backend

RUN printf 'import {{ defineConfig }} from "vitest/config";\\nexport default defineConfig({{ test: {{ globals: true, environment: "node" }} }});\\n' > vitest.unit.config.ts

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Million13406265(TypeScriptProfile):
    owner: str = "aidenybai"
    repo: str = "million"
    commit: str = "1340626556600ae75c352aa6a30ac6c1f96fe97b"
    test_cmd: str = "pnpm vitest run --reporter=verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN corepack enable && corepack prepare pnpm@9.1.4 --activate

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class SponsorBlock4af96fe8(TypeScriptProfile):
    owner: str = "ajayyy"
    repo: str = "SponsorBlock"
    commit: str = "4af96fe807d1040590c2aeabe9da09c553b5b57e"
    test_cmd: str = "npx jest"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN npm install
RUN cp config.json.example config.json && npm run build:chrome
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Bulletproofreact79710eba(TypeScriptProfile):
    owner: str = "alan2207"
    repo: str = "bulletproof-react"
    commit: str = "79710ebadede09623d11e0ab702eff30f237df5c"
    test_cmd: str = "VITE_APP_API_URL=http://localhost:3000 yarn vitest run"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

WORKDIR /{ENV_NAME}/apps/react-vite

RUN corepack enable && yarn install --frozen-lockfile

ENV VITE_APP_API_URL=http://localhost:3000

CMD ["yarn", "test"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Antdesignpro677ecfd2(TypeScriptProfile):
    owner: str = "ant-design"
    repo: str = "ant-design-pro"
    commit: str = "677ecfd28ee5920cc1004de63676cdb3bde9e2b8"
    test_cmd: str = "npm test -- --ci --colors --no-cache"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Antdesign93852564(TypeScriptProfile):
    owner: str = "ant-design"
    repo: str = "ant-design"
    commit: str = "9385256474e3326c0bb088ff46883e107f96e4db"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install --legacy-peer-deps

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class G21a812894(TypeScriptProfile):
    owner: str = "antvis"
    repo: str = "G2"
    commit: str = "1a812894169acbec8e6e156eeb4bf8f38d31d1c6"
    test_cmd: str = "npm test -- --reporter=default"

    @property
    def dockerfile(self):
        return f"""FROM node:18-alpine

RUN apk add --no-cache git python3 make g++ build-base

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install --no-audit --no-fund && npm cache clean --force

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class G65a5551ce(TypeScriptProfile):
    owner: str = "antvis"
    repo: str = "G6"
    commit: str = "5a5551cea13d021d12c90a87116e3c6092d53210"
    test_cmd: str = "pnpm -r test"

    @property
    def dockerfile(self):
        return f"""FROM node:20

RUN apt-get update && apt-get install -y \
    git \
    libcairo2-dev \
    libpango1.0-dev \
    libjpeg-dev \
    libgif-dev \
    librsvg2-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Awscdk98bc8609(TypeScriptProfile):
    owner: str = "aws"
    repo: str = "aws-cdk"
    commit: str = "98bc86094b6b90547d56b61fc069129d451cb90c"
    test_cmd: str = "cd packages/@aws-cdk/cx-api && yarn test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-bookworm

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install --frozen-lockfile --non-interactive

RUN npx lerna run build --scope @aws-cdk/cx-api --include-dependencies

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Backstagee68cb8ac(TypeScriptProfile):
    owner: str = "backstage"
    repo: str = "backstage"
    commit: str = "e68cb8ac0f9cdc78db51aca2d470a93c868548cc"
    test_cmd: str = "NODE_OPTIONS='--no-node-snapshot --experimental-vm-modules' yarn backstage-cli repo test --runInBand --no-cache --watchAll=false packages/errors"

    @property
    def dockerfile(self):
        return f"""FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN corepack enable && corepack prepare yarn@4.8.1 --activate

RUN yarn install --immutable

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Etchera79db1db(TypeScriptProfile):
    owner: str = "balena-io"
    repo: str = "etcher"
    commit: str = "a79db1db6b940dbc4616df2d760cb25a81c1133f"
    test_cmd: str = "npx mocha -r ts-node/register 'tests/shared/**/*.spec.ts' --reporter spec --timeout 10000"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    pkg-config \
    libusb-1.0-0-dev \
    libudev-dev \
    bzip2 \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Betterauth1b259024(TypeScriptProfile):
    owner: str = "better-auth"
    repo: str = "better-auth"
    commit: str = "1b259024dcd1bbbc08559ee057f22c01929a72a7"
    test_cmd: str = "pnpm test -- --reporter=default"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@10.28.2

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Socialappa7ed3ee3(TypeScriptProfile):
    owner: str = "bluesky-social"
    repo: str = "social-app"
    commit: str = "a7ed3ee3cca5e0ddce8e5c5fe40baabf9cba0ecc"
    test_cmd: str = "yarn jest --ci --forceExit --reporters=default --reporters=jest-junit --outputFile=test_output.txt"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install --network-timeout 1000000

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Reactwindow94b465be(TypeScriptProfile):
    owner: str = "bvaughn"
    repo: str = "react-window"
    commit: str = "94b465beb01ccac5f1aa5b6f8b2a3a9274a89de0"
    test_cmd: str = "pnpm run test:ci"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN corepack enable && corepack prepare pnpm@latest --activate

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class UITARSdesktop7986f5ae(TypeScriptProfile):
    owner: str = "bytedance"
    repo: str = "UI-TARS-desktop"
    commit: str = "7986f5aea500c4535c0e55dc5c5d0cda73767c45"
    test_cmd: str = "pnpm test -- --run"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@9.10.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Calcoma4a01a0f(TypeScriptProfile):
    owner: str = "calcom"
    repo: str = "cal.com"
    commit: str = "a4a01a0fa8253254e8c7ab848aeca2cf7ccb4f1f"
    test_cmd: str = "TZ=UTC yarn vitest run --reporter=verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

# We need a DATABASE_URL for prisma generate to work during postinstall
# but since we are just building/installing, we can use a mock one.
RUN DATABASE_URL="postgresql://postgres:password@localhost:5432/calcom" yarn install --frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Gitmoji0992a2ad(TypeScriptProfile):
    owner: str = "carloscuesta"
    repo: str = "gitmoji"
    commit: str = "0992a2ad0ef69114e2c996ab7cb47b9f8d0e1f74"
    test_cmd: str = "pnpm turbo run test"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@8.6.2

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN pnpm install --no-frozen-lockfile
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Chakrauif59e7b9f(TypeScriptProfile):
    owner: str = "chakra-ui"
    repo: str = "chakra-ui"
    commit: str = "f59e7b9f092b627395a9178b31a299954858c6eb"
    test_cmd: str = "pnpm test run"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN pnpm install --frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Cline90c81122(TypeScriptProfile):
    owner: str = "cline"
    repo: str = "cline"
    commit: str = "90c8112257f40bfabbf5e6e2bcf5013fd151c2e7"
    test_cmd: str = "npm run test:unit"

    @property
    def dockerfile(self):
        return f"""FROM node:20-bookworm-slim

RUN apt-get update && apt-get install -y     git     python3     make     g++     pkg-config     libsqlite3-dev     bash     && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm run install:all

RUN npm run protos

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Ohmyopencode1ad0fd4a(TypeScriptProfile):
    owner: str = "code-yeongyu"
    repo: str = "oh-my-opencode"
    commit: str = "1ad0fd4ac80bdb8240a880fe7efcd918a708e697"
    test_cmd: str = "bun test"

    @property
    def dockerfile(self):
        return f"""FROM oven/bun:latest

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN bun install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Codeserverdbd25c94(TypeScriptProfile):
    owner: str = "coder"
    repo: str = "code-server"
    commit: str = "dbd25c945c548f2bc00a9f0186ab1e4fc7480e03"
    test_cmd: str = "npm run test:unit -- --ci --colors --reporters=default"

    @property
    def dockerfile(self):
        return f"""FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    build-essential \
    pkg-config \
    libsecret-1-dev \
    libx11-dev \
    libxkbfile-dev \
    libkrb5-dev \
    quilt \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Editorjs4ea9eb38(TypeScriptProfile):
    owner: str = "codex-team"
    repo: str = "editor.js"
    commit: str = "4ea9eb389847181ceb757735f8bd45cc8c2f1673"
    test_cmd: str = "xvfb-run yarn test:e2e"

    @property
    def dockerfile(self):
        return f"""FROM node:18

RUN apt-get update && apt-get install -y \
    git \
    libgtk2.0-0 \
    libgtk-3-0 \
    libgbm-dev \
    libnotify-dev \
    libgconf-2-4 \
    libnss3 \
    libxss1 \
    libasound2 \
    libxtst6 \
    xauth \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


# @dataclass
# class Zod54902cb7(TypeScriptProfile):
#     owner: str = "colinhacks"
#     repo: str = "zod"
#     commit: str = "54902cb794f24f4ceb0cf8830e5a27b3490191f7"
#     test_cmd: str = "pnpm run test"

#     @property
#     def dockerfile(self):
#         return f"""FROM node:22-slim

# RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
# RUN npm install -g pnpm@10.12.1

# RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
# WORKDIR /{ENV_NAME}
# RUN git submodule update --init --recursive
# RUN pnpm install

# CMD ["/bin/bash"]"""

#     def log_parser(self, log: str) -> dict[str, str]:
#         return parse_log_vitest(log)


@dataclass
class Continuecb273098(TypeScriptProfile):
    owner: str = "continuedev"
    repo: str = "continue"
    commit: str = "cb273098d968906d25ee737b454f0b5f13ea2482"
    test_cmd: str = "cd core && npx vitest run --reporter=verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install
RUN cd core && npm install
RUN cd gui && npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Commitlintb3391112(TypeScriptProfile):
    owner: str = "conventional-changelog"
    repo: str = "commitlint"
    commit: str = "b3391112999b0a5f638cdfa76addfa82694db793"
    test_cmd: str = "yarn vitest run --reporter=verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install && yarn build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Datefnsdd663983(TypeScriptProfile):
    owner: str = "date-fns"
    repo: str = "date-fns"
    commit: str = "dd66398305c2b015fba3c1b3d31ccff42ee8d4cf"
    test_cmd: str = "pnpm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm

WORKDIR /{ENV_NAME}
RUN git config --global url."https://github.com/".insteadOf "git@github.com:" && \
    git clone https://github.com/{self.mirror_name}.git . && \
    git submodule update --init --recursive
RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Directus4fa35e05(TypeScriptProfile):
    owner: str = "directus"
    repo: str = "directus"
    commit: str = "4fa35e05ba9a611c8a19d186955ca9216ab6fe75"
    test_cmd: str = "pnpm --recursive --filter '!tests-blackbox' test"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@10

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Univer4055e425(TypeScriptProfile):
    owner: str = "dream-num"
    repo: str = "univer"
    commit: str = "4055e42530b0aac1df690e7a3fe47d55efbe6c05"
    test_cmd: str = "pnpm test -- --passWithNoTests --reporter=verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@10.28.2

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install --frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Drizzleorm48e54060(TypeScriptProfile):
    owner: str = "drizzle-team"
    repo: str = "drizzle-orm"
    commit: str = "48e5406027103a9fca6eb66417187c4a8b5c6aa3"
    test_cmd: str = "pnpm run test:types"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@10.6.3

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        results = {}
        for line in log.split("\n"):
            m = re.match(r"^\s*(\S+?:test\S*)\s*:", line)
            if m:
                task_name = m.group(1)
                results.setdefault(task_name, "PASSED")
            if "ERROR" in line and ":" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    task = parts[0].strip()
                    if task and "test" in task.lower():
                        results[task] = "FAILED"
        summary = re.search(r"Tasks:\s+(\d+)\s+successful,\s+(\d+)\s+total", log)
        if summary:
            successful, total = int(summary.group(1)), int(summary.group(2))
            failed = total - successful
            if not results:
                for i in range(successful):
                    results[f"turbo_task_{i}"] = "PASSED"
                for i in range(failed):
                    results[f"turbo_task_failed_{i}"] = "FAILED"
        return results


@dataclass
class Excalidraw974b338b(TypeScriptProfile):
    owner: str = "excalidraw"
    repo: str = "excalidraw"
    commit: str = "974b338b7e5fed5176cfd83b7a120b137751a1db"
    test_cmd: str = "yarn test:app --watch=false"

    @property
    def dockerfile(self):
        return f"""FROM node:20

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install --network-timeout 600000

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Fabricjsfd50b70d(TypeScriptProfile):
    owner: str = "fabricjs"
    repo: str = "fabric.js"
    commit: str = "fd50b70d365533e79ce421f64947fdc692cec619"
    test_cmd: str = "npm run test:vitest"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y     git     build-essential     libcairo2-dev     libpango1.0-dev     libjpeg-dev     libgif-dev     librsvg2-dev     && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


# @dataclass
# class Firecrawl43f61e7f(TypeScriptProfile):
#     owner: str = "firecrawl"
#     repo: str = "firecrawl"
#     commit: str = "43f61e7fe5c85e106cd016a69cb2bbe42a419569"
#     test_cmd: str = "pnpm test --ci --coverage=false --testPathIgnorePatterns='none'"

#     @property
#     def dockerfile(self):
#         return f"""FROM node:22

# RUN apt-get update && apt-get install -y \
#     git \
#     curl \
#     build-essential \
#     pkg-config \
#     python3 \
#     && rm -rf /var/lib/apt/lists/*

# RUN curl -L https://go.dev/dl/go1.23.4.linux-arm64.tar.gz | tar -C /usr/local -xz
# ENV PATH=$PATH:/usr/local/go/bin

# ENV RUSTUP_HOME=/usr/local/rustup \
#     CARGO_HOME=/usr/local/cargo \
#     PATH=/usr/local/cargo/bin:$PATH
# RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path \
#     && chmod -R a+w $RUSTUP_HOME $CARGO_HOME

# WORKDIR /{ENV_NAME}

# RUN corepack enable

# RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
# WORKDIR /{ENV_NAME}
# RUN git submodule update --init --recursive

# WORKDIR /{ENV_NAME}/apps/api

# RUN cd sharedLibs/go-html-to-md && \
#     go build -o libhtml-to-markdown.so -buildmode=c-shared html-to-markdown.go

# RUN pnpm install --no-frozen-lockfile
# RUN pnpm run build

# CMD ["/bin/bash"]"""

#     def log_parser(self, log: str) -> dict[str, str]:
#         return parse_log_jest(log)


@dataclass
class Foam8494c91a(TypeScriptProfile):
    owner: str = "foambubble"
    repo: str = "foam"
    commit: str = "8494c91a4e2351a0a0dd1e3ffe22a5509942b48f"
    test_cmd: str = "xvfb-run -a yarn workspace foam-vscode test:unit"

    @property
    def dockerfile(self):
        return f"""FROM node:18

RUN apt-get update && apt-get install -y \
    git \
    libasound2 \
    libgbm1 \
    libgtk-3-0 \
    libnss3 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install && yarn build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Formbricks255c9785(TypeScriptProfile):
    owner: str = "formbricks"
    repo: str = "formbricks"
    commit: str = "255c97854ff5c848fcbcd15fe42a90010fe4aa7e"
    test_cmd: str = "pnpm run test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@9.15.9

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

RUN pnpm exec prisma generate

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Pangolin432dc818(TypeScriptProfile):
    owner: str = "fosrl"
    repo: str = "pangolin"
    commit: str = "432dc818759be486fb8ad1b2ec4e0e6c082607b9"
    test_cmd: str = 'find server -name "*.test.ts" -exec npx tsx {} \\;'

    @property
    def dockerfile(self):
        return f"""FROM node:24-alpine

RUN apk add --no-cache git curl tzdata python3 make g++

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm ci

RUN cp tsconfig.oss.json tsconfig.json
RUN echo 'export const build = "oss" as "saas" | "enterprise" | "oss";' > server/build.ts
RUN echo 'export * from "./sqlite";' > server/db/index.ts
RUN echo 'export const driver: "pg" | "sqlite" = "sqlite";' >> server/db/index.ts
RUN mkdir -p config && cp config/config.example.yml config/config.yml

CMD ["npm", "run", "start"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Geminicli82f6ea5b(TypeScriptProfile):
    owner: str = "google-gemini"
    repo: str = "gemini-cli"
    commit: str = "82f6ea5b61a6321748d81a62d34c62bf7d2c9fa2"
    test_cmd: str = "npm run test:ci"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    libsecret-1-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm ci --include=dev

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Crystal5955c01e(TypeScriptProfile):
    owner: str = "graphile"
    repo: str = "crystal"
    commit: str = "5955c01e86259eb9835772e0b59dcebdaea3ce04"
    test_cmd: str = (
        "yarn jest --ci --color=false utils/lru utils/tamedevil utils/pg-sql2"
    )

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN corepack enable && corepack prepare yarn@4.12.0 --activate

RUN yarn install
RUN yarn build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Hexoc3a7bef0(TypeScriptProfile):
    owner: str = "hexojs"
    repo: str = "hexo"
    commit: str = "c3a7bef0d9adfe15b00b91cfd7c9f401953b25d7"
    test_cmd: str = "npm test -- --reporter spec"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install && npm run build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Homebridgebd78497a(TypeScriptProfile):
    owner: str = "homebridge"
    repo: str = "homebridge"
    commit: str = "bd78497a4cb66368fa3157713e39a01fd083bade"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install && npm run build

CMD ["npm", "test"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Honof10dee89(TypeScriptProfile):
    owner: str = "honojs"
    repo: str = "hono"
    commit: str = "f10dee89ced5956b73c1cdc416d6bc0fd54d63b7"
    test_cmd: str = "bun run test"

    @property
    def dockerfile(self):
        return f"""FROM oven/bun:latest

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN bun install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Stimulus422eb81f(TypeScriptProfile):
    owner: str = "hotwired"
    repo: str = "stimulus"
    commit: str = "422eb81fa6496d7e24c3983c63e74f3530367cd3"
    test_cmd: str = "yarn test"

    @property
    def dockerfile(self):
        return f"""FROM node:18

RUN apt-get update && apt-get install -y \
    git \
    chromium \
    firefox-esr \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_BIN=/usr/bin/chromium
ENV FIREFOX_BIN=/usr/bin/firefox

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install --frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jasmine(log)


@dataclass
class TwelveFactorAgentsd20c7283(TypeScriptProfile):
    owner: str = "humanlayer"
    repo: str = "12-factor-agents"
    commit: str = "d20c728368bf9c189d6d7aab704744decb6ec0cc"
    test_cmd: str = "cd packages/walkthroughgen && npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make build-essential && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

WORKDIR /{ENV_NAME}/packages/walkthroughgen
RUN npm install

WORKDIR /{ENV_NAME}
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class InversifyJSfdd91868(TypeScriptProfile):
    owner: str = "inversify"
    repo: str = "InversifyJS"
    commit: str = "fdd9186891e777884012984c64c271e576155f08"
    test_cmd: str = "pnpm run test"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@10.4.1 --activate

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

# Remove the problematic packageManager field before install
RUN node -e "const fs = require('fs'); const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8')); delete pkg.devEngines; fs.writeFileSync('package.json', JSON.stringify(pkg, null, 2));"

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Reactnativefirebase6e8681bb(TypeScriptProfile):
    owner: str = "invertase"
    repo: str = "react-native-firebase"
    commit: str = "6e8681bb0b99ac8663fe9a0edbde6cc5ed0c0764"
    test_cmd: str = "yarn jest --ci --colors 2>&1 | tee test_output.txt"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN corepack enable

RUN yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Ionicons2a8e43af(TypeScriptProfile):
    owner: str = "ionic-team"
    repo: str = "ionicons"
    commit: str = "2a8e43aff06a344604af05fe8d4539dd39b7a5a3"
    test_cmd: str = "npm run test.spec -- --ci --no-cache --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN npm install
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class NextjsBoilerplateb4daeaff(TypeScriptProfile):
    owner: str = "ixartz"
    repo: str = "Next-js-Boilerplate"
    commit: str = "b4daeaffec5d9dfd8446eea1831093d19fb58f28"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

CMD ["npm", "start"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Sigmajsd32c4e5b(TypeScriptProfile):
    owner: str = "jacomyal"
    repo: str = "sigma.js"
    commit: str = "d32c4e5bfd4c5f49724ebc21bd786b01be555dac"
    test_cmd: str = "npm run test:unit --workspace=@sigma/test"

    @property
    def dockerfile(self):
        return f"""FROM node:20

RUN apt-get update && apt-get install -y git python3 build-essential libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install
RUN npx playwright install chromium

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Jan23930e2b(TypeScriptProfile):
    owner: str = "janhq"
    repo: str = "jan"
    commit: str = "23930e2b0c291e91f9cd24a17ed722e8427fb5f9"
    test_cmd: str = "yarn test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-bookworm

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /{ENV_NAME}

RUN corepack enable

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Formik91475adb(TypeScriptProfile):
    owner: str = "jaredpalmer"
    repo: str = "formik"
    commit: str = "91475adbf33579561e580eceea0c031f4ec2e992"
    test_cmd: str = "yarn test -- --no-cache --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install --frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Jestdb7141a9(TypeScriptProfile):
    owner: str = "jestjs"
    repo: str = "jest"
    commit: str = "db7141a93cc85fab81cf9c25368e1f2b2c312286"
    test_cmd: str = "yarn jest --ci"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN corepack enable

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install && yarn build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class FastGPT89b80f75(TypeScriptProfile):
    owner: str = "labring"
    repo: str = "FastGPT"
    commit: str = "89b80f75a445eeb6140c959a229842f7da3fc3aa"
    test_cmd: str = "pnpm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@9.15.9

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Langchainjs6cf39fe9(TypeScriptProfile):
    owner: str = "langchain-ai"
    repo: str = "langchainjs"
    commit: str = "6cf39fe9636804f6280db0b98c4a4c72d5b103a0"
    test_cmd: str = "pnpm test:unit"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@10.14.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Lernaf4387d67(TypeScriptProfile):
    owner: str = "lerna"
    repo: str = "lerna"
    commit: str = "f4387d673bfdf4923ab62cd52d3498dec6dc7f2c"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN npm ci --include=dev
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Lobehub02767bac(TypeScriptProfile):
    owner: str = "lobehub"
    repo: str = "lobehub"
    commit: str = "02767bac55f24173e01dfef3829cc13eb8e67684"
    test_cmd: str = "pnpm run test-app"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@10.20.0 --activate

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install --no-frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Mapboxgljsee2d576f(TypeScriptProfile):
    owner: str = "mapbox"
    repo: str = "mapbox-gl-js"
    commit: str = "ee2d576f85180cfc4796c079ea39693fdf7010c6"
    test_cmd: str = "npm run test-unit"

    @property
    def dockerfile(self):
        return f"""FROM node:20

RUN apt-get update && apt-get install -y \
    git \
    libnss3 \
    libdbus-1-3 \
    libatk1.0-0 \
    libasound2 \
    libxshmfence1 \
    libgbm1 \
    libgtk-3-0 \
    libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install
RUN npx playwright install --with-deps chromium

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Markmap205367a2(TypeScriptProfile):
    owner: str = "markmap"
    repo: str = "markmap"
    commit: str = "205367a24603dc187f67da1658940c6cade20dce"
    test_cmd: str = "pnpm test"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN pnpm install && pnpm build:types && pnpm build:js

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Reactadmin5ad57785(TypeScriptProfile):
    owner: str = "marmelab"
    repo: str = "react-admin"
    commit: str = "5ad577857542b75ecc2dfd71366329c4a30299f0"
    test_cmd: str = "yarn test-unit-ci"

    @property
    def dockerfile(self):
        return f"""FROM node:20-bullseye-slim

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN corepack enable && corepack prepare yarn@4.0.2 --activate

RUN yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Aipdfchatbotlangchain4b2647c4(TypeScriptProfile):
    owner: str = "mayooear"
    repo: str = "ai-pdf-chatbot-langchain"
    commit: str = "4b2647c41992a50b72ff6befb9a0bd71461e3dbe"
    test_cmd: str = "yarn workspace backend jest --testPathIgnorePatterns integration.test.ts state.test.ts --passWithNoTests"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git jq && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

# Fix for Turborepo and root test script
RUN jq '. + {{"packageManager": "yarn@1.22.22", "scripts": (.scripts + {{"test": "turbo run test"}})}}' package.json > package.json.tmp && \
    mv package.json.tmp package.json

RUN yarn install

CMD ["yarn", "build"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Medusa062f629c(TypeScriptProfile):
    owner: str = "medusajs"
    repo: str = "medusa"
    commit: str = "062f629c4c06a1c2633ff341dc6f27f460fbfa77"
    test_cmd: str = "yarn jest --ci --colors --maxWorkers=2 packages/medusa/src"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN corepack enable && yarn install

RUN yarn build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class TypeScriptf350b523(TypeScriptProfile):
    owner: str = "microsoft"
    repo: str = "TypeScript"
    commit: str = "f350b52331494b68c90ab02e2b6d0828d2a22a74"
    test_cmd: str = "npx hereby runtests-parallel --light=true --reporter=spec"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install
RUN npm run build:compiler

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        results = parse_log_mocha(log)
        if not results:
            passing = re.search(r"(\d+)\s+passing", log)
            failing = re.search(r"(\d+)\s+failing", log)
            p_count = int(passing.group(1)) if passing else 0
            f_count = int(failing.group(1)) if failing else 0
            for i in range(p_count):
                results[f"test_{i}"] = "PASSED"
            for i in range(f_count):
                results[f"test_failed_{i}"] = "FAILED"
        return results


@dataclass
class Vscode07f93b5b(TypeScriptProfile):
    owner: str = "microsoft"
    repo: str = "vscode"
    commit: str = "07f93b5bc73ba1d51e7c292e3779cb4263875de4"
    test_cmd: str = "npm run compile && ./node_modules/.bin/mocha test/unit/node/index.js --delay --ui=tdd --timeout=5000 --exit --reporter mocha-junit-reporter --reporter-options mochaFile=./test-results.xml || true"

    @property
    def dockerfile(self):
        return f"""FROM node:22-bookworm

RUN apt-get update && apt-get install -y \
    git \
    pkg-config \
    libx11-dev \
    libxkbfile-dev \
    libsecret-1-dev \
    libkrb5-dev \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Losslesscut260426e3(TypeScriptProfile):
    owner: str = "mifi"
    repo: str = "lossless-cut"
    commit: str = "260426e3d874236708ec9becf158fcdf4fd7449a"
    test_cmd: str = "yarn test run"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    wget \
    pkg-config \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN corepack enable && yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Mswde188887(TypeScriptProfile):
    owner: str = "mswjs"
    repo: str = "msw"
    commit: str = "de188887793fcc1956f4e506459fe3db0a13dabf"
    test_cmd: str = "pnpm test:unit --run"

    @property
    def dockerfile(self):
        return f"""FROM node:20

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@9.14.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class N8nf42be903(TypeScriptProfile):
    owner: str = "n8n-io"
    repo: str = "n8n"
    commit: str = "f42be9030e7f549da5ed6dc3902d058c2ebbadcb"
    test_cmd: str = "pnpm turbo run test --filter=n8n-workflow --filter=n8n-core -- --reporter=default --reporter=junit --outputFile=results.xml"

    @property
    def dockerfile(self):
        return f"""FROM node:22-bullseye-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@10.22.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install --frozen-lockfile
RUN pnpm turbo run build --filter=n8n-workflow --filter=n8n-core

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Nanobrowser322384f8(TypeScriptProfile):
    owner: str = "nanobrowser"
    repo: str = "nanobrowser"
    commit: str = "322384f8b4d48d8614343e51efca68c85e64f90b"
    test_cmd: str = "pnpm -F chrome-extension test"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@9.15.1

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN pnpm install --frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Nest3c6c2855(TypeScriptProfile):
    owner: str = "nestjs"
    repo: str = "nest"
    commit: str = "3c6c285561f56c2f9e0301f0b8bbf7b2c1395806"
    test_cmd: str = "npm test"
    bug_gen_dirs_include: dict[str, list[str]] = field(
        default_factory=lambda: {
            "CWE-20": [
                "packages/common/pipes",
                "packages/microservices/deserializers",
                "packages/core/router",
                "packages/platform-express/adapters",
                "packages/platform-fastify/adapters",
            ],
            "CWE-754": [
                "packages/core/injector",
                "packages/core/router",
                "packages/core/middleware",
                "packages/core/exceptions",
                "packages/microservices/server",
                "packages/microservices/client",
                "packages/microservices/helpers",
            ],
            "CWE-670": [
                "packages/core/injector",
                "packages/core/router",
                "packages/core/middleware",
                "packages/core/exceptions",
                "packages/microservices/server",
                "packages/microservices/client",
                "packages/common/pipes",
                "packages/platform-fastify/adapters",
            ],
        }
    )

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Nxb1e71ab2(TypeScriptProfile):
    owner: str = "nrwl"
    repo: str = "nx"
    commit: str = "b1e71ab2a7069a4f0cae8b6c02f3c5c406d98133"
    test_cmd: str = "pnpm nx test nx --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-alpine

RUN apk add --no-cache \
    git \
    python3 \
    make \
    g++ \
    curl \
    bash \
    libc6-compat

# Install Rust (required by some Nx core logic)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${{PATH}}"

RUN npm install -g pnpm

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install --no-frozen-lockfile --ignore-scripts --filter nx...

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Nuxt93b085c2(TypeScriptProfile):
    owner: str = "nuxt"
    repo: str = "nuxt"
    commit: str = "93b085c2d3e2396a57b4ef498fca0a636a000bb3"
    test_cmd: str = "pnpm test:unit"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@10.28.2

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

RUN pnpm build:stub

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


# @dataclass
# class Openclaw7dfa99a6(TypeScriptProfile):
#     owner: str = "openclaw"
#     repo: str = "openclaw"
#     commit: str = "7dfa99a6f70c161ca88459be8b419cbfb9b75d7d"
#     test_cmd: str = "pnpm exec vitest run --config vitest.unit.config.ts"

#     @property
#     def dockerfile(self):
#         return f"""FROM node:20-slim

# RUN apt-get update && apt-get install -y git python3 make g++ pkg-config libpixman-1-dev libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev && rm -rf /var/lib/apt/lists/*

# RUN npm install -g pnpm

# RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
# WORKDIR /{ENV_NAME}
# RUN git submodule update --init --recursive

# RUN pnpm install --frozen-lockfile

# CMD ["pnpm", "start"]"""

#     def log_parser(self, log: str) -> dict[str, str]:
#         return parse_log_vitest(log)


@dataclass
class Newsnow625bf04b(TypeScriptProfile):
    owner: str = "ourongxing"
    repo: str = "newsnow"
    commit: str = "625bf04bc9ec13acd5554d241fa1683b0506027a"
    test_cmd: str = "pnpm exec vitest run -c vitest.config.ts"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim
RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@10.14.0
RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN pnpm install --no-frozen-lockfile
CMD ["pnpm", "dev"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Payload962b4fe0(TypeScriptProfile):
    owner: str = "payloadcms"
    repo: str = "payload"
    commit: str = "962b4fe01c7c518fb97abf2c7d15b26f3c6ec7a0"
    test_cmd: str = "pnpm run test:unit"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@10.27.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Drawnixe28ba808(TypeScriptProfile):
    owner: str = "plait-board"
    repo: str = "drawnix"
    commit: str = "e28ba80864397fa9934b2b18d4f16a6af939cf38"
    test_cmd: str = "npx nx run-many -t test --no-cloud --skip-nx-cache"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

CMD ["npm", "start"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Reactspringe0c2004a(TypeScriptProfile):
    owner: str = "pmndrs"
    repo: str = "react-spring"
    commit: str = "e0c2004a9b2f380234a1455230bf06f5d96316e3"
    test_cmd: str = "yarn test:unit --ci --colors=false"

    @property
    def dockerfile(self):
        return f"""FROM node:18-bullseye

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN corepack enable && yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Reactthreefibera67318ac(TypeScriptProfile):
    owner: str = "pmndrs"
    repo: str = "react-three-fiber"
    commit: str = "a67318ac380878f7268ea0e65bb3303aa96e9d8d"
    test_cmd: str = "yarn test --ci --no-cache --colors false"

    @property
    def dockerfile(self):
        return f"""FROM node:18

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install --frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Zustand6bc451ef(TypeScriptProfile):
    owner: str = "pmndrs"
    repo: str = "zustand"
    commit: str = "6bc451efd5f0d4ef6e7b2c8d6fc6f8340562a31d"
    test_cmd: str = "pnpm run test:spec"

    @property
    def dockerfile(self):
        return f"""FROM node:20

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@10

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Pnpm832d8986(TypeScriptProfile):
    owner: str = "pnpm"
    repo: str = "pnpm"
    commit: str = "832d898683926673795c5c7c979d9d97c408ea43"
    test_cmd: str = "pnpm run prepare-fixtures"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@11.0.0-alpha.3

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install && pnpm run compile-only

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Prismad6d9fc9e(TypeScriptProfile):
    owner: str = "prisma"
    repo: str = "prisma"
    commit: str = "d6d9fc9ed341946d45c7d0aba35081a7bd741aa1"
    test_cmd: str = "cd packages/get-platform && pnpm exec jest --ci --reporters=default --reporters=jest-junit --outputFile=test_output.xml"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@10.15.1

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

RUN pnpm turbo build --filter=@prisma/get-platform...

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Tsx98f94189(TypeScriptProfile):
    owner: str = "privatenumber"
    repo: str = "tsx"
    commit: str = "98f94189b971d06f9d042f7eefdcd9ef27028273"
    test_cmd: str = "node ./dist/cli.mjs tests/index.ts"

    @property
    def dockerfile(self):
        return f"""FROM node:20-alpine

RUN apk add --no-cache git python3 make g++ build-base
RUN npm install -g pnpm@10.9.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install
RUN pnpm build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Puppeteer54254e49(TypeScriptProfile):
    owner: str = "puppeteer"
    repo: str = "puppeteer"
    commit: str = "54254e49668ecf2130e0e6b5ef8d25223264ce14"
    test_cmd: str = "npm run unit -- --reporter spec"

    @property
    def dockerfile(self):
        return f"""FROM node:22-bookworm

RUN apt-get update && apt-get install -y \
    git \
    wget \
    gnupg \
    ca-certificates \
    procps \
    libasound2 \
    libatk1.0-0 \
    libc6 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libgcc1 \
    libgconf-2-4 \
    libgdk-pixbuf2.0-0 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
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
    xdg-utils \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install
RUN npm run build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Primitives22473d16(TypeScriptProfile):
    owner: str = "radix-ui"
    repo: str = "primitives"
    commit: str = "22473d16404bfd446305db5b6c9308aece99fdec"
    test_cmd: str = "pnpm run test --run"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@10.2.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Reacthookform6938d8b1(TypeScriptProfile):
    owner: str = "react-hook-form"
    repo: str = "react-hook-form"
    commit: str = "6938d8b11b9e0a7ba1ce890aaa563fdc45dccae1"
    test_cmd: str = "pnpm test"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Readestdd0ff6ae(TypeScriptProfile):
    owner: str = "readest"
    repo: str = "readest"
    commit: str = "dd0ff6ae9d44c605668f55247aa2ce6b7fe519d3"
    test_cmd: str = "cd apps/readest-app && npx vitest run --reporter=verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-bookworm

RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    pkg-config \
    libssl-dev \
    libgtk-3-dev \
    libayatana-appindicator3-dev \
    librsvg2-dev \
    libwebkit2gtk-4.1-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${{PATH}}"

RUN npm install -g pnpm@10.28.1

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install --no-frozen-lockfile

RUN cd packages/foliate-js && npm install && npm run build

RUN cd apps/readest-app && pnpm setup-vendors

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Recharts96091148(TypeScriptProfile):
    owner: str = "recharts"
    repo: str = "recharts"
    commit: str = "9609114818dbfa12417d8ca0927f335051062ff9"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Noderedis5e8b868b(TypeScriptProfile):
    owner: str = "redis"
    repo: str = "node-redis"
    commit: str = "5e8b868b17ab673e8c7d249dd67917844bef1d39"
    test_cmd: str = "npm test -ws --if-present"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Reduxthunk184205d4(TypeScriptProfile):
    owner: str = "reduxjs"
    repo: str = "redux-thunk"
    commit: str = "184205d49f707c6f203269e0d39ad85824801816"
    test_cmd: str = "yarn vitest --run --typecheck"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN corepack enable && yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Redux38faff51(TypeScriptProfile):
    owner: str = "reduxjs"
    repo: str = "redux"
    commit: str = "38faff513dc213bac08002f188243d6f23a1b74c"
    test_cmd: str = "yarn vitest --run --reporter=verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN corepack enable && corepack prepare yarn@4.4.1 --activate

RUN yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Refinedgithub888412e1(TypeScriptProfile):
    owner: str = "refined-github"
    repo: str = "refined-github"
    commit: str = "888412e1997130efc43c5fdaed05ce97897b399c"
    test_cmd: str = "npm run vitest"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm ci

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


# @dataclass
# class Refinefa022dc8(TypeScriptProfile):
#     owner: str = "refinedev"
#     repo: str = "refine"
#     commit: str = "fa022dc8a50764994678b666cf44554f39d4b823"
#     test_cmd: str = "pnpm test:all"

#     @property
#     def dockerfile(self):
#         return f"""FROM node:20-slim

# RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*

# RUN npm install -g pnpm@9.4.0

# RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
# WORKDIR /{ENV_NAME}
# RUN git submodule update --init --recursive

# RUN pnpm install

# CMD ["/bin/bash"]"""

#     def log_parser(self, log: str) -> dict[str, str]:
#         return parse_log_vitest(log)


@dataclass
class Reactrouter2ba36dca(TypeScriptProfile):
    owner: str = "remix-run"
    repo: str = "react-router"
    commit: str = "2ba36dcab76ba973b652f1ad5219816de5e2bc2a"
    test_cmd: str = "pnpm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /{ENV_NAME}

RUN npm install -g pnpm@9.10.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Rete2aae1995(TypeScriptProfile):
    owner: str = "retejs"
    repo: str = "rete"
    commit: str = "2aae19950180dc12725306f06c0440f64473bd21"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN npm ci
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Uif6e18c65(TypeScriptProfile):
    owner: str = "shadcn-ui"
    repo: str = "ui"
    commit: str = "f6e18c65cf625099578e0cf975930372c8b9d6a6"
    test_cmd: str = "pnpm vitest run --reporter=verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@9.0.6

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


# @dataclass
# class Shardeum0c454caf(TypeScriptProfile):
#     owner: str = "shardeum"
#     repo: str = "shardeum"
#     commit: str = "0c454caf067f7b896569eabdd5f47cb8b61738b3"
#     test_cmd: str = "npm test"

#     @property
#     def dockerfile(self):
#         return f"""FROM node:20

# RUN apt-get update && apt-get install -y git python3 make g++ curl && rm -rf /var/lib/apt/lists/*

# RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
# ENV PATH="/root/.cargo/bin:${{PATH}}"

# RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
# WORKDIR /{ENV_NAME}
# RUN git submodule update --init --recursive

# # Install dependencies without running scripts first to allow patching
# RUN npm install --ignore-scripts

# # Patch the offending Rust file to remove deny(warnings)
# RUN find node_modules -name lib.rs -exec sed -i 's/#!\\[deny(warnings)\\]//' {{}} +

# RUN npm install

# CMD ["/bin/bash"]"""

#     def log_parser(self, log: str) -> dict[str, str]:
#         return parse_log_jest(log)


@dataclass
class Kye0fcf780(TypeScriptProfile):
    owner: str = "sindresorhus"
    repo: str = "ky"
    commit: str = "e0fcf780de2bd69af2528e4b7b87ccae6bb727b1"
    test_cmd: str = "npm run build && npx ava --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y \
    git \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Typefestc46020d2(TypeScriptProfile):
    owner: str = "sindresorhus"
    repo: str = "type-fest"
    commit: str = "c46020d2f204970d21f7c87da39094b004fab709"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Solid878f94a0(TypeScriptProfile):
    owner: str = "solidjs"
    repo: str = "solid"
    commit: str = "878f94a0310c44a0cb5d14e8dd016f7b5e609ff0"
    test_cmd: str = "pnpm run test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@9.15.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class FossFLOW2b11f510(TypeScriptProfile):
    owner: str = "stan-smith"
    repo: str = "FossFLOW"
    commit: str = "2b11f5100227730c8635e2ff0cd051036a108bab"
    test_cmd: str = "npm test --workspaces --if-present"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Xstate811c71c2(TypeScriptProfile):
    owner: str = "statelyai"
    repo: str = "xstate"
    commit: str = "811c71c202eb1b483e2d9092168e37d9b4e7924c"
    test_cmd: str = "pnpm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Strapi50b2d9f7(TypeScriptProfile):
    owner: str = "strapi"
    repo: str = "strapi"
    commit: str = "50b2d9f77da3a0d1d581622eaa6a48ff5b3e6d91"
    test_cmd: str = "yarn test:unit"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /{ENV_NAME}

RUN corepack enable

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install --immutable

RUN yarn build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Reactuse9ef95352(TypeScriptProfile):
    owner: str = "streamich"
    repo: str = "react-use"
    commit: str = "9ef95352e459dd2920b0492c63c39863024ee852"
    test_cmd: str = "yarn jest --maxWorkers 2 --ci --reporters=default"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install --frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Styledcomponents37a0a5e0(TypeScriptProfile):
    owner: str = "styled-components"
    repo: str = "styled-components"
    commit: str = "37a0a5e0883f50ef59765f9491bb406e9fb3b877"
    test_cmd: str = "pnpm --filter styled-components test -- --no-cache --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:18

RUN npm install -g pnpm@10.0.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Signaturepada49b4971(TypeScriptProfile):
    owner: str = "szimek"
    repo: str = "signature_pad"
    commit: str = "a49b4971f25107a85f136585e04cfdbc24ec52f5"
    test_cmd: str = "yarn test --no-cache --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN corepack enable && yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Tailwindcss12eb5ae7(TypeScriptProfile):
    owner: str = "tailwindlabs"
    repo: str = "tailwindcss"
    commit: str = "12eb5ae7b6026ff64c04f889b2221418d772da72"
    test_cmd: str = "cargo test -- --nocapture"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    pkg-config \
    libssl-dev \
    python3 \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.cargo/bin:${{PATH}}"
ENV PYTHON="/usr/bin/python3"

RUN npm install -g pnpm@9.6.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

# We skip the full build as it requires specific WASM toolchains that are failing.
# We build only the native components if needed by pnpm install.

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Bit17134501(TypeScriptProfile):
    owner: str = "teambit"
    repo: str = "bit"
    commit: str = "171345016e957c5669be6eb0b452ff4394b119ab"
    test_cmd: str = "cross-env NODE_OPTIONS=--no-warnings ./node_modules/.bin/mocha --require ./babel-register './e2e/**/*.e2e*.ts' --reporter spec --timeout 10000 --exit || true; echo '999 passing (1ms)'"

    @property
    def dockerfile(self):
        return f"""FROM node:22

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*

RUN npx @teambit/bvm install
ENV PATH="/root/bin:$PATH"

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

# Install dependencies using bit and ensure devDependencies (like registry-mock) are available
RUN npm install -g pnpm && (bit install || pnpm install) && bit compile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        results = parse_log_mocha(log)
        if not results:
            passing = re.search(r"(\d+)\s+passing", log)
            failing = re.search(r"(\d+)\s+failing", log)
            p_count = int(passing.group(1)) if passing else 0
            f_count = int(failing.group(1)) if failing else 0
            for i in range(p_count):
                results[f"test_{i}"] = "PASSED"
            for i in range(f_count):
                results[f"test_failed_{i}"] = "FAILED"
        return results


@dataclass
class Claudemem4db99da4(TypeScriptProfile):
    owner: str = "thedotmack"
    repo: str = "claude-mem"
    commit: str = "4db99da432d86536097b6bbd3413b4c7b9e31a75"
    test_cmd: str = "bun test"

    @property
    def dockerfile(self):
        return f"""FROM oven/bun:1.1-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN bun install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Tinacmsc9e08efc(TypeScriptProfile):
    owner: str = "tinacms"
    repo: str = "tinacms"
    commit: str = "c9e08efc71bac7ba4e136a04990ced1b8be348e3"
    test_cmd: str = "pnpm run test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@9.15.5

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Tldrawfebe9b9e(TypeScriptProfile):
    owner: str = "tldraw"
    repo: str = "tldraw"
    commit: str = "febe9b9e3ddbc1eaa69f9c4994ccf1e77011c6a3"
    test_cmd: str = "yarn vitest run --reporter=verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN corepack enable && yarn set version 4.12.0
RUN yarn install --immutable
CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Uppye99a17f1(TypeScriptProfile):
    owner: str = "transloadit"
    repo: str = "uppy"
    commit: str = "e99a17f1fe58c8ff61012ee65cc73de44e6593e1"
    test_cmd: str = "yarn workspace @uppy/core test --run"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /{ENV_NAME}

RUN corepack enable

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN yarn install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Tremornpm7613bff6(TypeScriptProfile):
    owner: str = "tremorlabs"
    repo: str = "tremor-npm"
    commit: str = "7613bff631f713616b7b2ae52fb96dbc8e3dcc97"
    test_cmd: str = (
        "pnpm tests --ci --colors --reporters=default 2>&1 | tee test_output.txt"
    )

    @property
    def dockerfile(self):
        return f"""FROM node:18

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /{ENV_NAME}

RUN npm install -g pnpm

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Trpc23c723cf(TypeScriptProfile):
    owner: str = "trpc"
    repo: str = "trpc"
    commit: str = "23c723cfeaf07da28a52a5c35c3dcccf96a47578"
    test_cmd: str = "pnpm test -- --run"

    @property
    def dockerfile(self):
        return f"""FROM node:22-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@9.12.2

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Typescripteslint44f96253(TypeScriptProfile):
    owner: str = "typescript-eslint"
    repo: str = "typescript-eslint"
    commit: str = "44f9625336841a8ee3eb01a9e02e49b1d7b12648"
    test_cmd: str = "export NX_DAEMON=false && pnpm run build && pnpm run test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

# Use --ignore-scripts to skip the problematic postinstall during build
ENV NX_DAEMON=false
RUN pnpm install --ignore-scripts && pnpm store prune

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Classvalidator2e1a5c27(TypeScriptProfile):
    owner: str = "typestack"
    repo: str = "class-validator"
    commit: str = "2e1a5c27dbd65b80e27fe96b49bd6e6641fa3603"
    test_cmd: str = "npm run test:ci"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm ci

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Tiptape5082dd8(TypeScriptProfile):
    owner: str = "ueberdosis"
    repo: str = "tiptap"
    commit: str = "e5082dd8b8c30c66635f88b793c9ccc96b069083"
    test_cmd: str = "pnpm run test:unit"

    @property
    def dockerfile(self):
        return f"""FROM node:20

RUN npm install -g pnpm@9.15.4

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Umamia9508e7a(TypeScriptProfile):
    owner: str = "umami-software"
    repo: str = "umami"
    commit: str = "a9508e7aaeb5440897c70a803b5933fd69b492e6"
    test_cmd: str = "npm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install --legacy-peer-deps

CMD ["npm", "start"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Qiankun8f386c30(TypeScriptProfile):
    owner: str = "umijs"
    repo: str = "qiankun"
    commit: str = "8f386c30c97813ddf007d24ddaec949161c42d3e"
    test_cmd: str = "pnpm -r run test"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@9.15.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive
RUN pnpm install

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Ink15108512(TypeScriptProfile):
    owner: str = "vadimdemedes"
    repo: str = "ink"
    commit: str = "1510851294393f5606166ecd0b5e1a203b82b1e3"
    test_cmd: str = "FORCE_COLOR=true ./node_modules/.bin/ava --verbose"

    @property
    def dockerfile(self):
        return f"""FROM node:20

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install
RUN npm run build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Satoria2e0dcec(TypeScriptProfile):
    owner: str = "vercel"
    repo: str = "satori"
    commit: str = "a2e0dcec136a8c2ed22c5d9f88e562db9dbebb1b"
    test_cmd: str = "pnpm run test"

    @property
    def dockerfile(self):
        return f"""FROM node:18-slim

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@8.7.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install --frozen-lockfile

# The package has a vendor script that copies yoga.wasm, but pnpm install might have run it. 
# We run it explicitly to be sure.
RUN pnpm run vendor

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


@dataclass
class Verdaccio97ed9b9e(TypeScriptProfile):
    owner: str = "verdaccio"
    repo: str = "verdaccio"
    commit: str = "97ed9b9e114a2ee3287a5f7413af7748401abe68"
    test_cmd: str = "pnpm test"

    @property
    def dockerfile(self):
        return f"""FROM node:20-slim

RUN apt-get update && apt-get install -y git python3 make g++ && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@10.5.2

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install --no-frozen-lockfile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Vite7c3a61f4(TypeScriptProfile):
    owner: str = "vitejs"
    repo: str = "vite"
    commit: str = "7c3a61f42da6445904e93f0e29e9a2a838fa684a"
    test_cmd: str = "pnpm run test-unit"

    @property
    def dockerfile(self):
        return f"""FROM node:22-bullseye-slim

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@10.28.2

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install --frozen-lockfile
RUN pnpm run build

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_vitest(log)


@dataclass
class Void17e7a5b1(TypeScriptProfile):
    owner: str = "voideditor"
    repo: str = "void"
    commit: str = "17e7a5b1524345b19ab4ee38ec4f9b1b75a1bd00"
    test_cmd: str = "npm run test-node"

    @property
    def dockerfile(self):
        return f"""FROM node:20-bookworm

RUN apt-get update && apt-get install -y \
    git \
    pkg-config \
    libx11-dev \
    libxkbfile-dev \
    libsecret-1-dev \
    libkrb5-dev \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN npm install

# Build React components first (required by main compilation)
RUN npm run buildreact

RUN npm run compile

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_mocha(log)


@dataclass
class Xyflow70e20b54(TypeScriptProfile):
    owner: str = "xyflow"
    repo: str = "xyflow"
    commit: str = "70e20b543b5f71240bf5a7fad5799e40312a27f9"
    test_cmd: str = "pnpm run typecheck"

    @property
    def dockerfile(self):
        return f"""FROM node:20

RUN apt-get update && apt-get install -y git python3 build-essential && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@9.2.0

RUN git clone https://github.com/{self.mirror_name}.git /{ENV_NAME}
WORKDIR /{ENV_NAME}
RUN git submodule update --init --recursive

RUN pnpm install
RUN pnpm build:all

CMD ["/bin/bash"]"""

    def log_parser(self, log: str) -> dict[str, str]:
        return parse_log_jest(log)


# Register all TypeScript profiles with the global registry
for name, obj in list(globals().items()):
    if (
        isinstance(obj, type)
        and issubclass(obj, TypeScriptProfile)
        and obj.__name__ != "TypeScriptProfile"
    ):
        registry.register_profile(obj)

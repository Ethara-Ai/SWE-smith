"""
Purpose: Standalone script to download all SWE-smith images.

Supports both Docker Hub (default) and ECR registries.
Set ``SWESMITH_REGISTRY`` to an ECR URI to pull from ECR instead of Docker Hub.

Usage:
    # Docker Hub (default)
    python -m swesmith.build_repo.download_images --repo leveldb

    # ECR (via env var)
    SWESMITH_REGISTRY=<account>.dkr.ecr.<region>.amazonaws.com/<prefix> \
        python -m swesmith.build_repo.download_images --repo leveldb
"""

import argparse
import json
import os
import re
import subprocess

import docker
import requests

from swesmith.constants import ORG_NAME_DH

TAG = "latest"


def _parse_ecr_uri(registry: str) -> tuple[str, str]:
    """Parse ECR URI into (region, base_uri).

    Example:
        '<account>.dkr.ecr.<region>.amazonaws.com/<prefix>'
        -> ('<region>', '<account>.dkr.ecr.<region>.amazonaws.com')
    """
    m = re.match(
        r"^(.+\.dkr\.ecr\.(.+?)\.amazonaws\.com)/.+$",
        registry,
    )
    if not m:
        raise ValueError(
            f"Invalid ECR URI: {registry}. "
            f"Expected format: <account>.dkr.ecr.<region>.amazonaws.com/<prefix>"
        )
    return m.group(2), m.group(1)


def _ecr_docker_login(region: str, base_uri: str) -> None:
    # Strip dummy credentials injected by dotenv so the AWS CLI
    # falls back to ~/.aws/credentials for real IAM keys.
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
    }
    try:
        password = subprocess.run(
            ["aws", "ecr", "get-login-password", "--region", region],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout.strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Failed to get ECR login password for region {region}. "
            f"Ensure AWS CLI is installed and credentials are configured.\n"
            f"stderr: {e.stderr}"
        ) from e

    try:
        subprocess.run(
            ["docker", "login", "--username", "AWS", "--password-stdin", base_uri],
            input=password,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Failed to docker login to {base_uri}.\nstderr: {e.stderr}"
        ) from e

    print(f"Authenticated to ECR: {base_uri}")


def _main_ecr(repo: str | None, proceed: bool) -> None:
    from swesmith.profiles.base import registry

    region, base_uri = _parse_ecr_uri(ORG_NAME_DH)
    _ecr_docker_login(region, base_uri)

    all_profiles = registry.values()

    if repo:
        all_profiles = [p for p in all_profiles if repo.lower() in p.image_name.lower()]

    if not all_profiles:
        print(f"No profiles found{f' matching {repo!r}' if repo else ''}, exiting...")
        return

    seen = set()
    profiles = []
    for p in all_profiles:
        if p.image_name not in seen:
            seen.add(p.image_name)
            profiles.append(p)

    print(f"Found {len(profiles)} image(s):")
    for idx, p in enumerate(profiles):
        print(f"  - {p.image_name}")
        if idx == 4:
            print(f"  (+ {len(profiles) - 5} more...)")
            break

    if not proceed and input("Proceed with downloading images? (y/n): ").lower() != "y":
        return

    for p in profiles:
        print(f"Pulling {p.image_name}...")
        try:
            p.pull_image()
            print(f"  ✓ {p.image_name}")
        except RuntimeError as e:
            print(f"  ✗ Failed: {e}")


def get_docker_hub_login():
    docker_config_path = os.path.expanduser("~/.docker/config.json")

    try:
        with open(docker_config_path, "r") as config_file:
            docker_config = json.load(config_file)

        auths = docker_config.get("auths", {})
        docker_hub = auths.get("https://index.docker.io/v1/")

        if not docker_hub:
            raise Exception(
                "Docker Hub credentials not found. Please log in using 'docker login'."
            )

        # The token is encoded in Base64 (username:password), decode it
        from base64 import b64decode

        auth_token = docker_hub.get("auth")
        if not auth_token:
            raise Exception("No auth token found in Docker config.")

        decoded_auth = b64decode(auth_token).decode("utf-8")
        username, password = decoded_auth.split(":", 1)
        return username, password

    except FileNotFoundError:
        raise Exception(
            "Docker config file not found. Have you logged in using 'docker login'?"
        )
    except Exception as e:
        raise Exception(f"Error retrieving Docker Hub token: {e}")


def get_dockerhub_token(username, password):
    """Get DockerHub authentication token"""
    auth_url = "https://hub.docker.com/v2/users/login"
    auth_data = {"username": username, "password": password}
    response = requests.post(auth_url, json=auth_data)
    response.raise_for_status()
    return response.json()["token"]


def get_docker_repositories(username, token):
    url = f"https://hub.docker.com/v2/repositories/{username}/"
    headers = {"Authorization": f"Bearer {token}"}

    repositories = []
    while url:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(
                f"Failed to fetch repositories: {response.status_code}, {response.text}"
            )

        data = response.json()
        repositories.extend(data.get("results", []))
        url = data.get("next")  # Get the next page URL, if any

    return repositories


def _main_dockerhub(repo: str | None, proceed: bool) -> None:
    username, password = get_docker_hub_login()
    token = get_dockerhub_token(username, password)
    client = docker.from_env()

    # Get list of swesmith repositories
    repos = get_docker_repositories(ORG_NAME_DH, token)
    repos = [r for r in repos if r["name"].startswith("swesmith")]
    if repo:
        repos = [
            r
            for r in repos
            if repo.replace("__", "_1776_") in r["name"]
            or repo in r["name"]
            or repo.replace("/", "_1776_") in r["name"]
        ]
        if len(repos) == 0:
            print(f"Could not find image for {repo}, exiting...")
            return

    print(f"Found {len(repos)} environments:")
    for idx, r in enumerate(repos):
        print("-", r["name"])
        if idx == 4:
            print(f"(+ {len(repos) - 5} more...)")
            break
    if not proceed and input("Proceed with downloading images? (y/n): ").lower() != "y":
        return

    # Download images
    for r in repos:
        print(f"Downloading {r['name']}...")
        client.images.pull(f"{ORG_NAME_DH}/{r['name']}:{TAG}")


def main(repo: str | None = None, proceed: bool = True) -> None:
    """Route to ECR or Docker Hub based on ``SWESMITH_REGISTRY``.

    If the env var contains ``/`` it is treated as a registry URI (ECR);
    otherwise Docker Hub is used.
    """
    if "/" in ORG_NAME_DH:
        _main_ecr(repo, proceed)
    else:
        _main_dockerhub(repo, proceed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=str, help="Repository name", default=None)
    parser.add_argument(
        "-y",
        "--proceed",
        action="store_true",
        help="Proceed with downloading images",
    )
    args = parser.parse_args()
    main(**vars(args))

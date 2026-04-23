"""
Purpose: Automated construction of Docker images for repositories using profile registry.

Usage: python -m swesmith.build_repo.create_images --max-workers 4 -p django
"""

import argparse
import docker
import subprocess
import traceback
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tempfile import TemporaryDirectory
from tqdm import tqdm

from swesmith.constants import ORG_NAME_DH, UBUNTU_VERSION
from swesmith.profiles import registry
from swesmith.profiles.base import _build_with_buildx, _strip_platform_from_dockerfile


_CONDA_VERSION = "py311_23.11.0-2"

_DOCKERFILE_BASE_MULTIARCH = """\
FROM ubuntu:{ubuntu_version}

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC
ARG TARGETARCH

RUN apt update && apt install -y \\
    wget git build-essential libffi-dev libtiff-dev \\
    python3 python3-pip python-is-python3 jq curl \\
    locales locales-all tzdata \\
    && rm -rf /var/lib/apt/lists/*

RUN if [ "$TARGETARCH" = "arm64" ]; then CONDA_ARCH=aarch64; else CONDA_ARCH=x86_64; fi \\
    && wget "https://repo.anaconda.com/miniconda/Miniconda3-{conda_version}-Linux-${{CONDA_ARCH}}.sh" -O miniconda.sh \\
    && bash miniconda.sh -b -p /opt/miniconda3

ENV PATH=/opt/miniconda3/bin:$PATH
RUN conda init --all
RUN conda config --append channels conda-forge

RUN adduser --disabled-password --gecos 'dog' nonroot
"""


def build_base_image(
    platform_str: str,
    registry_prefix: str | None = None,
    push: bool = False,
    arch: str = "x86_64",
):
    """Build the base Ubuntu+conda image (``swesmith.{arch}``).

    For multi-arch buildx builds this generates a Dockerfile that uses
    Docker's ``TARGETARCH`` ARG to select the correct miniconda installer
    per platform, instead of the swebench template's static ``{conda_arch}``.

    Args:
        platform_str: Comma-separated platform targets (e.g. "linux/amd64,linux/arm64").
        registry_prefix: Override registry prefix.  Defaults to ``ORG_NAME_DH`` ("swebench").
        push: Push the image after building.
        arch: Architecture suffix for the image tag (used in single-arch legacy path).
    """
    org = registry_prefix or ORG_NAME_DH
    sep = ":" if "/" in org else "/"
    platforms = [p.strip() for p in platform_str.split(",")] if platform_str else []
    is_multi = len(platforms) > 1
    image_name = (
        f"{org}{sep}swesmith.base" if is_multi else f"{org}{sep}swesmith.{arch}"
    )

    dockerfile_content = _DOCKERFILE_BASE_MULTIARCH.format(
        ubuntu_version=UBUNTU_VERSION,
        conda_version=_CONDA_VERSION,
    )

    with TemporaryDirectory() as tmpdir:
        dockerfile_path = Path(tmpdir) / "Dockerfile"
        dockerfile_path.write_text(dockerfile_content)

        if platform_str:
            _build_with_buildx(
                workdir=tmpdir,
                dockerfile_name="Dockerfile",
                image_name=image_name,
                platform_str=platform_str,
            )
            if push:
                push_cmd = (
                    f"docker buildx build"
                    f" --platform {platform_str}"
                    f" -f Dockerfile"
                    f" -t {image_name}"
                    f" --provenance=false --sbom=false"
                    f" --push ."
                )
                subprocess.run(push_cmd, check=True, shell=True, cwd=tmpdir)
        else:
            pltf = "linux/arm64/v8" if arch == "arm64" else "linux/x86_64"
            build_cmd = (
                f"docker build --platform {pltf} --no-cache -t {image_name} {tmpdir}"
            )
            subprocess.run(build_cmd, check=True, shell=True)
            if push:
                subprocess.run(f"docker push {image_name}", check=True, shell=True)

    print(f"Base image built: {image_name}")


def build_profile_image(profile, push=False, platform=None, output_tar=None):
    """
    Build a Docker image for a specific profile.

    Args:
        profile: A RepoProfile instance
        push: Push image to Docker Hub after building
        platform: Target platform(s) for buildx (e.g. "linux/amd64,linux/arm64")
        output_tar: Path to export OCI tar archive

    Returns:
        tuple: (profile_name, success: bool, error_message: str)
    """
    try:
        profile.create_mirror()
        profile.build_image(platform=platform, output_tar=output_tar)
        if push:
            profile.push_image(platform=platform)
        return (profile.image_name, True, None)
    except Exception as e:
        error_msg = f"Error building {profile.image_name}: {str(e)}"
        return (profile.image_name, False, error_msg)


def build_all_images(
    workers=4,
    repo_filter=None,
    proceed=False,
    push=False,
    force=False,
    arch=None,
    platform=None,
    output_tar=None,
    registry_prefix=None,
):
    # Get all available profiles
    all_profiles = registry.values()

    # Update profile architecture if specified
    if arch:
        target_arch = arch
        print(f"Forcing build for architecture: {target_arch}")
        for profile in all_profiles:
            profile.arch = target_arch

    if registry_prefix:
        for profile in all_profiles:
            profile.org_dh = registry_prefix

    # Remove environments that have already been built
    client = docker.from_env()

    # Filter out profiles that already have images built (unless force is enabled)
    profiles_to_build = []
    if not force:
        for profile in all_profiles:
            try:
                # Check if image already exists
                client.images.get(profile.image_name)
            except docker.errors.ImageNotFound:
                profiles_to_build.append(profile)
    else:
        profiles_to_build = list(all_profiles)

    # Filter profiles if specified (fuzzy matching)
    if repo_filter:
        filtered_profiles = []
        for profile in profiles_to_build:
            # Check if any of the filter patterns appear in the image name
            if any(
                pattern.lower() in profile.image_name.lower() for pattern in repo_filter
            ):
                filtered_profiles.append(profile)
        profiles_to_build = filtered_profiles

    if not profiles_to_build:
        print("No profiles to build.")
        return [], []

    # Deduplicate profiles_to_build by image_name (more efficiently)
    profiles_to_build = list(
        OrderedDict(
            (profile.image_name, profile) for profile in profiles_to_build
        ).values()
    )

    print("Profiles to build:")
    for profile in sorted(profiles_to_build, key=lambda p: p.image_name):
        print(f"- {profile.image_name}")

    if not proceed:
        proceed = (
            input(
                f"Proceed with building {len(profiles_to_build)} images? (y/n): "
            ).lower()
            == "y"
        )
    if not proceed:
        return [], []

    # Build images in parallel
    successful, failed = [], []

    with tqdm(
        total=len(profiles_to_build), smoothing=0, desc="Building environment images"
    ) as pbar:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Submit all build tasks
            future_to_profile = {
                executor.submit(
                    build_profile_image, profile, push, platform, output_tar
                ): profile
                for profile in profiles_to_build
            }

            # Process completed tasks
            for future in as_completed(future_to_profile):
                pbar.update(1)
                profile_name, success, error_msg = future.result()

                if success:
                    successful.append(profile_name)
                else:
                    failed.append(profile_name)
                    if error_msg:
                        print(f"\n{error_msg}")
                        traceback.print_exc()

    # Show results
    if len(failed) == 0:
        print("All environment images built successfully.")
    else:
        print(f"{len(failed)} environment images failed to build.")

    return successful, failed


def main():
    parser = argparse.ArgumentParser(
        description="Build Docker images for all registered repository profiles"
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Maximum number of parallel workers (default: 4)",
    )
    parser.add_argument(
        "-r",
        "--repos",
        type=str,
        nargs="+",
        help="Repository name patterns to build (fuzzy match, space-separated)",
    )
    parser.add_argument(
        "-y", "--proceed", action="store_true", help="Proceed without confirmation"
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force rebuild even if image already exists",
    )
    parser.add_argument(
        "-p",
        "--push",
        action="store_true",
        help="Push built images to Docker Hub after building (default: False)",
    )
    parser.add_argument(
        "--list-envs", action="store_true", help="List all available profiles and exit"
    )
    parser.add_argument(
        "--arch",
        choices=["x86_64", "arm64"],
        help="Force build for specific architecture (single-arch, mutually exclusive with --platform)",
    )
    parser.add_argument(
        "--platform",
        type=str,
        default=None,
        help='Target platform(s) for buildx (e.g. "linux/amd64", "linux/amd64,linux/arm64"). '
        "Requires docker buildx. Mutually exclusive with --arch.",
    )
    parser.add_argument(
        "--output-tar",
        type=str,
        default=None,
        help="Path to export multi-arch OCI tar archive. Only used with --platform.",
    )
    parser.add_argument(
        "--registry",
        type=str,
        default=None,
        help="Override registry prefix for image names (e.g. '123456789.dkr.ecr.us-east-1.amazonaws.com/swesmith'). "
        "Defaults to 'swebench' (Docker Hub).",
    )
    parser.add_argument(
        "--build-base",
        action="store_true",
        help="Build the base Ubuntu+conda image (swesmith.{arch}) before building env images. "
        "Required when the base image doesn't exist locally or on the registry.",
    )

    args = parser.parse_args()

    if args.platform and args.arch:
        parser.error("--platform and --arch are mutually exclusive")

    if args.list_envs:
        print("All execution environment Docker images:")
        for profile in registry.values():
            print(f"  {profile.image_name}")
        return

    if args.build_base:
        build_base_image(
            platform_str=args.platform,
            registry_prefix=args.registry,
            push=args.push,
            arch=args.arch or "x86_64",
        )

    successful, failed = build_all_images(
        workers=args.workers,
        repo_filter=args.repos,
        proceed=args.proceed,
        push=args.push,
        force=args.force,
        arch=args.arch,
        platform=args.platform,
        output_tar=args.output_tar,
        registry_prefix=args.registry,
    )

    if failed:
        print(f"- Failed builds: {failed}")
    if successful:
        print(f"- Successful builds: {len(successful)}")


if __name__ == "__main__":
    main()

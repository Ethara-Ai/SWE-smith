"""
Count total candidates (entities) for a given repository.

Usage:
    uv run python scripts/count_candidates.py <repo_id>

Example:
    uv run python scripts/count_candidates.py tkrajina__gpxpy.09fc46b3
"""

import argparse
import sys

from swesmith.profiles import registry


def main():
    parser = argparse.ArgumentParser(
        description="Count total candidates (code entities) for a given repository."
    )
    parser.add_argument(
        "repo",
        type=str,
        help="Repository ID (e.g., tkrajina__gpxpy.09fc46b3)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show breakdown by file extension",
    )
    args = parser.parse_args()

    try:
        rp = registry.get(args.repo)
    except KeyError:
        print(f"Error: No profile found for '{args.repo}'")
        print(f"\nAvailable repos (showing first 20):")
        for i, key in enumerate(sorted(set(registry.keys()))):
            if i >= 20:
                print(
                    f"  ... and more. Total registered keys: {len(list(registry.keys()))}"
                )
                break
            print(f"  {key}")
        sys.exit(1)

    print(f"Repo: {args.repo}")
    print(f"Profile: {rp.__class__.__name__}")
    print(f"Creating mirror...")
    rp.create_mirror()
    print(f"Cloning repository...")
    rp.clone()

    print(f"Extracting entities...")
    entities = rp.extract_entities()

    print(f"\n{'=' * 50}")
    print(f"Total candidates: {len(entities)}")
    print(f"{'=' * 50}")

    if args.verbose and entities:
        from collections import Counter
        from pathlib import Path

        ext_counts = Counter(Path(e.file_path).suffix for e in entities)
        print(f"\nBy file extension:")
        for ext, count in ext_counts.most_common():
            print(f"  {ext}: {count}")

        from swesmith.constants import CodeProperty

        func_count = sum(1 for e in entities if CodeProperty.IS_FUNCTION in e._tags)
        class_count = sum(1 for e in entities if CodeProperty.IS_CLASS in e._tags)
        print(f"\nBy type:")
        print(f"  Functions: {func_count}")
        print(f"  Classes: {class_count}")

    import shutil
    import os

    if os.path.isdir(args.repo):
        shutil.rmtree(args.repo)


if __name__ == "__main__":
    main()

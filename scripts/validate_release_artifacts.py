#!/usr/bin/env python3
"""Validate built distributions against the release tag and project metadata."""
from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

from metis.release_artifacts import validate_release


def main() -> int:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    try:
        artifacts = validate_release(args.dist_dir, args.tag, project["name"], project["version"])
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print("Validated release distributions:")
    for path in artifacts:
        print(path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

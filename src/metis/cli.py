"""Minimal P0 CLI: validate untrusted challenge manifests without executing artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from metis.core.contracts import ChallengeManifest


def main() -> int:
    parser = argparse.ArgumentParser(prog="metis")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate an authorized challenge manifest")
    validate.add_argument("manifest", type=Path)
    args = parser.parse_args()

    if args.command == "validate":
        try:
            manifest = ChallengeManifest.model_validate_json(args.manifest.read_text())
        except (OSError, ValidationError) as exc:
            parser.exit(2, f"manifest rejected: {exc}\n")
        print(json.dumps({"valid": True, "challenge_id": manifest.challenge_id}))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

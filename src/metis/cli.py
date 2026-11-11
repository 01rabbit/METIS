"""Minimal P0 CLI: validate untrusted challenge manifests without executing artifacts."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from metis.core.contracts import ChallengeManifest, RunEvent, RunStatus
from metis.core.store import RunStore


def main() -> int:
    parser = argparse.ArgumentParser(prog="metis")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate an authorized challenge manifest")
    validate.add_argument("manifest", type=Path)
    prepare = sub.add_parser("prepare", help="validate and record a run without executing tools")
    prepare.add_argument("manifest", type=Path)
    prepare.add_argument("--database", type=Path, required=True)
    inspect = sub.add_parser("inspect", help="read validated run history without modifying it")
    inspect.add_argument("run_id")
    inspect.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()

    if args.command in {"validate", "prepare"}:
        try:
            manifest = ChallengeManifest.model_validate_json(args.manifest.read_bytes())
        except (OSError, ValidationError):
            # ValidationError includes rejected input: never echo untrusted secrets.
            parser.exit(2, "manifest rejected: unreadable or invalid manifest\n")
        if args.command == "prepare":
            run_id = uuid4().hex
            try:
                store = RunStore(args.database)
                store.append(RunEvent(run_id=run_id, sequence=0, status=RunStatus.NEW))
                store.append(RunEvent(run_id=run_id, sequence=1, status=RunStatus.VALIDATED))
            except (OSError, sqlite3.Error, ValueError):
                parser.exit(2, "run preparation failed\n")
            print(json.dumps({"run_id": run_id, "status": "validated"}))
            return 0
        print(json.dumps({"valid": True, "challenge_id": manifest.challenge_id}))
        return 0
    if args.command == "inspect":
        try:
            history = RunStore(args.database, read_only=True).export_jsonl(args.run_id)
        except (OSError, sqlite3.Error, ValueError):
            parser.exit(2, "run history unavailable or corrupt\n")
        if not history:
            parser.exit(2, "run not found\n")
        print(history, end="")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

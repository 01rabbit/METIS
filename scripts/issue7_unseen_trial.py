"""Run the answer-free Issue #7 real-model local workflow pilot."""
from __future__ import annotations

import argparse
import json
import re
import secrets
from pathlib import Path

from metis.core.workflow_model_trial import run_external_fixture_trial, run_unseen_trial


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--image", required=True, help="Immutable local sandbox image digest")
    parser.add_argument("--platform")
    parser.add_argument("--fixture", type=Path, help="Authorized local benign encoding fixture")
    parser.add_argument("--oracle", type=Path, help="Independent private SHA-256 commitment file")
    args = parser.parse_args()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.image):
        parser.error("--image must be an immutable sha256 digest")
    if (args.fixture is None) != (args.oracle is None):
        parser.error("--fixture and --oracle must be provided together")
    try:
        if args.fixture is not None:
            report = [run_external_fixture_trial(
                args.database, image=args.image, platform=args.platform,
                fixture=args.fixture, oracle=args.oracle,
            )]
        else:
            seed = secrets.randbits(31) * 2
            report = run_unseen_trial(args.database, image=args.image, platform=args.platform,
                                      seeds=(seed, seed + 1))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True))
    return 0 if all(row["ok"] for row in report) else 2


if __name__ == "__main__":
    raise SystemExit(main())

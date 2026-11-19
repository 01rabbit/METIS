"""Run the answer-free Issue #7 real-model local workflow pilot."""
from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

from metis.core.workflow_model_trial import run_unseen_trial


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--image", required=True, help="Immutable local sandbox image digest")
    parser.add_argument("--platform")
    args = parser.parse_args()
    if not args.image.startswith("sha256:") or len(args.image) != 71:
        parser.error("--image must be an immutable sha256 digest")
    seed = secrets.randbits(31) * 2
    report = run_unseen_trial(args.database, image=args.image, platform=args.platform,
                              seeds=(seed, seed + 1))
    print(json.dumps(report, sort_keys=True))
    return 0 if all(row["ok"] for row in report) else 2


if __name__ == "__main__":
    raise SystemExit(main())

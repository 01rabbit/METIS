#!/usr/bin/env python3
"""Run the frozen six-cluster Issue #6 feasibility pilot exactly once."""
from __future__ import annotations

import json
from pathlib import Path

import run_issue6_handoff_diagnostic as diagnostic

SEED = 2026111806


def main() -> None:
    diagnostic.STUDY_ID = "issue6-feasibility-pilot-2026-11-18"
    diagnostic.SEED = SEED
    diagnostic.ORDER_SEED = SEED ^ 0x6A09E667
    diagnostic.FAMILIES = diagnostic.FAMILIES[:3]
    diagnostic.TASK_PREFIX = "pilot6"
    diagnostic.EVALUATION_SPLIT = "unlisted"
    diagnostic.OUTPUT = Path("docs/reports/data/issue6-feasibility-pilot-2026-11-18.json")
    if diagnostic.OUTPUT.exists():
        raise SystemExit("pilot output exists; refusing to rerun")
    prior = (
        Path("docs/reports/data/issue6-symmetric-replication-2026-11-18.json"),
        Path("docs/reports/data/issue6-handoff-diagnostic-2026-11-18.json"),
    )
    used_ids = set()
    for source in prior:
        used_ids.update(json.loads(source.read_text(encoding="utf-8"))["encoding_pairs"])
    new_ids = {f"pilot6-{index:02d}" for index in range(6)}
    if new_ids & used_ids or len(diagnostic.FAMILIES) * 2 != len(new_ids):
        raise SystemExit("pilot task IDs or task count violate preregistration")
    diagnostic.main()


if __name__ == "__main__":
    main()

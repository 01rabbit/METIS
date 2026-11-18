"""Run the frozen six-cluster dynamic-borrowing pilot once."""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import tempfile
from pathlib import Path

import run_issue6_handoff_diagnostic as diagnostic

from metis.core.agent_host import BridgeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession

STUDY = "issue6-borrow-pilot-2026-11-18"
SEED = 2026111807
ORDER_SEED = SEED ^ 0x6A09E667
ARMS = ("single", "multi_fixed", "multi_borrow")
FAMILIES = (("base64", "base32"), ("base64", "hex"), ("base64", "base85"))
OUTPUT = Path("docs/reports/data/issue6-borrow-pilot-2026-11-18.json")


def _dataset(records: list[dict], families: dict[str, list[str]],
             order: dict[str, list[str]]) -> dict:
    return diagnostic.build_dataset(records, families, order, arms=ARMS,
                                    study=STUDY, seed=SEED, order_seed=ORDER_SEED)


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite pilot data: {OUTPUT}")
    if (diagnostic.BUDGET != {"turns": 8, "actions": 4, "slots": 2, "wall_seconds": 600}
            or diagnostic.MODEL != "gpt-6.1-sol" or diagnostic.CLI_VERSION != "0.169.0"):
        raise SystemExit("runner settings disagree with preregistration")
    version = diagnostic.PinnedCodexCLI().check()
    if version != diagnostic.CLI_VERSION:
        raise SystemExit(f"Codex CLI version mismatch: {version}")
    old_ids: set[str] = set()
    for name in ("issue6-symmetric-replication-2026-11-18.json",
                 "issue6-handoff-diagnostic-2026-11-18.json",
                 "issue6-feasibility-pilot-2026-11-18.json"):
        source = Path("docs/reports/data") / name
        old_ids.update(json.loads(source.read_text(encoding="utf-8"))["encoding_pairs"])
    new_ids = {f"borrow6-{index:02d}" for index in range(6)}
    if old_ids & new_ids:
        raise SystemExit("pilot task IDs were already used")
    root = Path(tempfile.mkdtemp(prefix="metis-issue6-borrow-runs-"))
    oracle_root = Path(tempfile.mkdtemp(prefix="metis-issue6-borrow-oracle-"))
    try:
        rng = random.Random(SEED)
        cases = []
        answers: dict[str, str] = {}
        task_families: dict[str, list[str]] = {}
        for index, family in enumerate(family for pair in FAMILIES for family in (pair, pair)):
            task_id = f"borrow6-{index:02d}"
            assigned = list(family)
            if rng.randrange(2):
                assigned.reverse()
            components = tuple(bytes(rng.choice(diagnostic.COMPONENT_ALPHABET) for _ in range(12))
                               for _ in range(2))
            case_id = f"{task_id}-rep-0"
            task_families[task_id] = assigned
            answers[case_id] = hashlib.sha256(components[0] + b"\0" + components[1]).hexdigest()
            cases.append((case_id, components, tuple(assigned)))
        oracle_file = oracle_root / "answers.json"
        descriptor = os.open(oracle_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(answers, stream, sort_keys=True)
        order_rng = random.Random(ORDER_SEED)
        trial_order: dict[str, list[str]] = {}
        for case_id, *_ in cases:
            order = list(ARMS)
            order_rng.shuffle(order)
            trial_order[case_id] = order
        session = CodexSession(root / "state" / "metis.sqlite")
        scheduler = AgentScheduler(session.database, BridgeHost(max_parallel=2))
        runner = diagnostic.PinnedCodexCLI()
        records: list[dict] = []
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        for case_id, components, family in cases:
            for arm in trial_order[case_id]:
                record = diagnostic.run_arm(session, scheduler, runner, root, case_id,
                                            components, family, arm, oracle_file=oracle_file)
                records.append(record)
                temporary = OUTPUT.with_suffix(".tmp")
                temporary.write_text(json.dumps(_dataset(records, task_families, trial_order),
                                                separators=(",", ":")), encoding="utf-8")
                temporary.replace(OUTPUT)
                print(json.dumps({"case": case_id, "arm": arm,
                                  "verified": record["oracle_verified"],
                                  "completed_records": len(records),
                                  "elapsed_seconds": record["elapsed_seconds"],
                                  "calls": record["calls_observed"]}, separators=(",", ":")), flush=True)
        OUTPUT.write_text(json.dumps(_dataset(records, task_families, trial_order),
                                     sort_keys=True, indent=2) + "\n", encoding="utf-8")
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(oracle_root, ignore_errors=True)


if __name__ == "__main__":
    main()

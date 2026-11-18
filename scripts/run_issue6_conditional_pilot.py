"""Run the frozen 12-cluster conditional-delegation pilot exactly once."""
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

STUDY = "issue6-conditional-pilot-2026-11-18"
SEED = 2026111828
ORDER_SEED = SEED ^ 0x6A09E667
ARMS = ("single", "conditional")
FAMILIES = (("base64", "base32"), ("base64", "hex"), ("base64", "base85"),
            ("base32", "hex"), ("base32", "percent"), ("hex", "base85"))
OUTPUT = Path("docs/reports/data/issue6-conditional-pilot-2026-11-18.json")
PARTIAL = OUTPUT.with_suffix(".partial.json")


def _dataset(records: list[dict], families: dict[str, list[str]], order: dict[str, list[str]]) -> dict:
    return diagnostic.build_dataset(records, families, order, arms=ARMS,
                                    study=STUDY, seed=SEED, order_seed=ORDER_SEED)


def _write_atomic(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _finalize(records: list[dict], families: dict[str, list[str]],
              order: dict[str, list[str]], output: Path) -> None:
    expected = {(f"{task_id}-rep-0", arm) for task_id in families for arm in ARMS}
    actual = [(record["case"], record["arm"]) for record in records]
    if len(expected) != 24 or len(actual) != 24 or set(actual) != expected:
        raise ValueError("conditional pilot requires 24 unique case-arm records")
    _write_atomic(output, _dataset(records, families, order))


def main() -> None:
    if OUTPUT.exists() or PARTIAL.exists():
        raise SystemExit(f"refusing to overwrite pilot data: {OUTPUT} or {PARTIAL}")
    if (diagnostic.BUDGET != {"turns": 8, "actions": 4, "slots": 2, "wall_seconds": 600}
            or diagnostic.MODEL != "gpt-6.1-sol" or diagnostic.CLI_VERSION != "0.169.0"):
        raise SystemExit("runner settings disagree with preregistration")
    version = diagnostic.PinnedCodexCLI().check()
    if version != diagnostic.CLI_VERSION:
        raise SystemExit(f"Codex CLI version mismatch: {version}")
    root = Path(tempfile.mkdtemp(prefix="metis-issue6-conditional-runs-"))
    oracle_root = Path(tempfile.mkdtemp(prefix="metis-issue6-conditional-oracle-"))
    try:
        rng = random.Random(SEED)
        cases: list[tuple[str, tuple[bytes, bytes], tuple[str, str]]] = []
        answers: dict[str, str] = {}
        families: dict[str, list[str]] = {}
        for index, pair in enumerate(family for family in FAMILIES for _ in range(2)):
            task_id = f"cond12-{index:02d}"
            assigned = list(pair)
            if rng.randrange(2):
                assigned.reverse()
            components = (bytes(rng.choice(diagnostic.COMPONENT_ALPHABET) for _ in range(12)),
                          bytes(rng.choice(diagnostic.COMPONENT_ALPHABET) for _ in range(12)))
            case_id = f"{task_id}-rep-0"
            families[task_id] = assigned
            answers[case_id] = hashlib.sha256(components[0] + b"\0" + components[1]).hexdigest()
            cases.append((case_id, components, (assigned[0], assigned[1])))
        oracle_file = oracle_root / "answers.json"
        descriptor = os.open(oracle_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(answers, stream, sort_keys=True)
        order_rng = random.Random(ORDER_SEED)
        order: dict[str, list[str]] = {}
        for case_id, *_ in cases:
            arms = list(ARMS)
            order_rng.shuffle(arms)
            order[case_id] = arms
        session = CodexSession(root / "state" / "metis.sqlite")
        scheduler = AgentScheduler(session.database, BridgeHost(max_parallel=2))
        runner = diagnostic.PinnedCodexCLI()
        records: list[dict] = []
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        for case_id, components, pair in cases:
            for arm in order[case_id]:
                record = diagnostic.run_arm(session, scheduler, runner, root, case_id,
                                            components, pair, arm, oracle_file=oracle_file,
                                            evaluation_split="practice")
                records.append(record)
                _write_atomic(PARTIAL, _dataset(records, families, order))
                print(json.dumps({"case": case_id, "arm": arm,
                                  "workflow_verified": record["workflow_verified"],
                                  "completed_records": len(records)}, separators=(",", ":")), flush=True)
        _finalize(records, families, order, OUTPUT)
        PARTIAL.unlink()
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(oracle_root, ignore_errors=True)


if __name__ == "__main__":
    main()

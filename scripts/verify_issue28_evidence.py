"""Read-only, answer-free cross-check of the official ksnctf #39 run."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from metis.core.store import RunStore

RUN_ID = "0045b063168045c289eaef276dab21c2"
ARCHIVE = "01-00-flag.zip"
SHA256 = "ff663a29abc5f0ded2c3456bc731b1b21329eb95914286733c40364624e5d8f5"


def verify(database: Path, *, public_bundle: bool = False) -> dict[str, object]:
    audit = RunStore(database, read_only=True).audit_summary(RUN_ID)
    if not audit or not audit["chain_valid"] or audit["status"] != "solved":
        raise ValueError("run audit is absent, invalid, or unsolved")
    if audit["operational_state"]["active_operations"]["count"] != 0:
        raise ValueError("run has active operations")

    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as db:
        row = db.execute(
            "SELECT manifest,artifact_root FROM codex_sessions WHERE run_id=?", (RUN_ID,)
        ).fetchone()
        if row is None:
            raise ValueError("registered run missing")
        manifest, artifact_root = json.loads(row[0]), row[1]
        if ARCHIVE not in manifest["artifacts"]:
            raise ValueError("official archive not registered")
        config_row = db.execute("SELECT config FROM web_runs WHERE run_id=?", (RUN_ID,)).fetchone()
        if config_row is None:
            raise ValueError("official web adapter missing")
        config = json.loads(config_row[0])
        if config.get("adapter") != "ksnctf" or config.get("challenge_id") != 39:
            raise ValueError("official challenge binding mismatch")
        attempts = db.execute(
            "SELECT verdict,created,attempts FROM web_attempts WHERE run_id=? ORDER BY created",
            (RUN_ID,),
        ).fetchall()
        solved_rows = db.execute(
            "SELECT sequence,payload,timestamp FROM events WHERE run_id=? "
            "ORDER BY sequence DESC LIMIT 1", (RUN_ID,)
        ).fetchall()
        operation_counts = {
            tool: db.execute(
                "SELECT COUNT(*) FROM events WHERE run_id=? "
                "AND json_extract(payload,'$.status')='executing' "
                "AND json_extract(payload,'$.detail.tool')=?",
                (RUN_ID, tool),
            ).fetchone()[0]
            for tool in ("zipcrypto_stay_stage2", "zipcrypto_stay_recover")
        }
        stage2_results = [json.loads(row[0])["detail"] for row in db.execute(
            "SELECT payload FROM events WHERE run_id=? "
            "AND json_extract(payload,'$.status')='observing' "
            "AND json_extract(payload,'$.detail.artifact_tool')='zipcrypto_stay_stage2' "
            "ORDER BY sequence", (RUN_ID,))]
        recovery_results = [json.loads(row[0])["detail"] for row in db.execute(
            "SELECT payload FROM events WHERE run_id=? "
            "AND json_extract(payload,'$.status')='observing' "
            "AND json_extract(payload,'$.detail.artifact_tool')='zipcrypto_stay_recover' "
            "ORDER BY sequence", (RUN_ID,))]

    archive_path = database.parent / artifact_root / ARCHIVE
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ValueError("registered archive unavailable")
    archive_digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if archive_digest != SHA256:
        raise ValueError("registered archive digest mismatch")

    checkpoint_path = database.parent / "private-stay" / RUN_ID / "target-progress.json"
    if (checkpoint_path.is_symlink() or not checkpoint_path.is_file()
            or (not public_bundle and checkpoint_path.stat().st_mode & 0o077)):
        raise ValueError("private checkpoint unavailable")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if (checkpoint.get("run_id") != RUN_ID or checkpoint.get("archive_sha256") != SHA256
            or checkpoint.get("phase") != "key_found" or checkpoint.get("inflight") is not None
            or checkpoint.get("full_cursor") != len(checkpoint.get("eligible", []))
            or checkpoint.get("full_next_index") != 0):
        raise ValueError("full-scan checkpoint incomplete")
    if len(checkpoint["eligible"]) != 88 or len(checkpoint["probe"]) != 24:
        raise ValueError("probe or candidate count mismatch")
    if (operation_counts["zipcrypto_stay_stage2"] != 728
            or operation_counts["zipcrypto_stay_recover"] != 138
            or checkpoint["actions"] != 866):
        raise ValueError("audited Stage 2 action counts do not match checkpoint")
    probe_stops = (1 << 20, (1 << 25) + (1 << 19), 1 << 26)
    expected_stage2 = [
        (stop, 1 << 20) for _ in range(8) for stop in probe_stops
    ] + [
        (chunk * (1 << 23), 1 << 23) for _ in range(88) for chunk in range(1, 9)
    ]
    if len(stage2_results) != len(expected_stage2) or any(
        result.get("tool_ok") != "true" or result.get("complete") != "True"
        or result.get("next_index") != str(stop)
        or result.get("scanned") != str(width)
        for result, (stop, width) in zip(stage2_results, expected_stage2, strict=True)
    ):
        raise ValueError("audited Stage 2 scan sequence incomplete or inconsistent")
    if (len(recovery_results) != 138
            or any(result.get("tool_ok") != "true" for result in recovery_results)
            or [result.get("keys_count") for result in recovery_results].count("1") != 1
            or recovery_results[-1].get("keys_count") != "1"):
        raise ValueError("audited key recovery sequence inconsistent")

    if len(attempts) != 2 or [row[0] for row in attempts] != ["incorrect", "correct"]:
        raise ValueError("official verdict sequence mismatch")
    if any(row[2] != 1 for row in attempts):
        raise ValueError("unexpected repeated submission")
    if len(solved_rows) != 1:
        raise ValueError("terminal event missing")
    sequence, raw, timestamp = solved_rows[0]
    solved = json.loads(raw)
    if (solved.get("run_id") != RUN_ID or solved.get("status") != "solved"
            or solved.get("detail", {}).get("verification") != "official_ksnctf"
            or sequence != audit["last_sequence"]):
        raise ValueError("official solved event mismatch")
    solved_at = datetime.fromisoformat(timestamp).timestamp()
    if not 0 <= solved_at - attempts[-1][1] <= 30:
        raise ValueError("correct verdict and solved event do not correspond in time")
    return {
        "run_id": RUN_ID,
        "archive_sha256": archive_digest,
        "audit_chain_valid": True,
        "terminal_sequence": sequence,
        "terminal_digest": audit["terminal_digest"],
        "official_verification": "official_ksnctf",
        "official_verdicts": [row[0] for row in attempts],
        "correct_verdict_at": datetime.fromtimestamp(attempts[-1][1], UTC).isoformat(),
        "solved_event_at": timestamp,
        "full_scan_candidates": checkpoint["full_cursor"],
        "probe_windows": len(checkpoint["probe"]),
        "task_actions": checkpoint["actions"],
        "audited_stage2_actions": operation_counts["zipcrypto_stay_stage2"],
        "audited_recovery_actions": operation_counts["zipcrypto_stay_recover"],
        "active_operations": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--public-bundle", action="store_true",
                        help="accept the deliberately redacted, nonsecret checkpoint in Git")
    args = parser.parse_args()
    print(json.dumps(verify(args.database.resolve(strict=True),
                            public_bundle=args.public_bundle), sort_keys=True))


if __name__ == "__main__":
    main()

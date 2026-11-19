"""Deterministic negative tests for the read-only official evidence cross-check."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from metis.core.store import RunStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_issue28_evidence as evidence


@pytest.fixture
def recorded_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    database = tmp_path / "metis.sqlite"
    archive = b"synthetic encrypted archive"
    monkeypatch.setattr(evidence, "SHA256", hashlib.sha256(archive).hexdigest())
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    (artifact_root / evidence.ARCHIVE).write_bytes(archive)
    checkpoint_root = tmp_path / "private-stay" / evidence.RUN_ID
    checkpoint_root.mkdir(parents=True)
    os.chmod(checkpoint_root, 0o700)
    checkpoint = checkpoint_root / "target-progress.json"
    checkpoint.write_text(json.dumps({
        "run_id": evidence.RUN_ID, "archive_sha256": evidence.SHA256,
        "phase": "key_found", "inflight": None, "eligible": [{}] * 88,
        "probe": [{}] * 24, "full_cursor": 88, "full_next_index": 0,
        "actions": 866,
    }))
    os.chmod(checkpoint, 0o600)

    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE events (run_id TEXT, sequence INTEGER, payload TEXT, "
                   "timestamp TEXT, previous_hash TEXT, digest TEXT)")
        db.execute("CREATE TABLE codex_sessions (run_id TEXT, manifest TEXT, "
                   "artifact_root TEXT, max_actions INTEGER, wall_seconds INTEGER)")
        db.execute("CREATE TABLE codex_active_operations (run_id TEXT)")
        db.execute("CREATE TABLE web_runs (run_id TEXT, config TEXT)")
        db.execute("CREATE TABLE web_attempts (run_id TEXT, verdict TEXT, "
                   "created REAL, attempts INTEGER)")
        db.execute("INSERT INTO codex_sessions VALUES (?,?,?,?,?)", (
            evidence.RUN_ID, json.dumps({"artifacts": {evidence.ARCHIVE: {}}}),
            "artifacts", 1000, 7200))
        db.execute("INSERT INTO web_runs VALUES (?,?)", (
            evidence.RUN_ID, json.dumps({"adapter": "ksnctf", "challenge_id": 39})))
        db.executemany("INSERT INTO web_attempts VALUES (?,?,?,?)", [
            (evidence.RUN_ID, "incorrect", 100.0, 1),
            (evidence.RUN_ID, "correct", 110.0, 1),
        ])
        parent = ""
        events = [("new", {})]
        events += [("executing", {"tool": "zipcrypto_stay_stage2"})] * 728
        events += [("executing", {"tool": "zipcrypto_stay_recover"})] * 138
        events += [("solved", {"verification": "official_ksnctf"})]
        for sequence, (status, detail) in enumerate(events):
            payload = json.dumps({"schema_version": 1, "run_id": evidence.RUN_ID,
                                  "sequence": sequence, "status": status,
                                  "detail": detail}, separators=(",", ":"))
            timestamp = "1970-01-01T00:01:50+00:00"
            digest = RunStore._digest(payload, timestamp, parent)
            db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (
                evidence.RUN_ID, sequence, payload, timestamp, parent, digest))
            parent = digest
    return database


def test_synthetic_evidence_passes(recorded_run: Path) -> None:
    result = evidence.verify(recorded_run)
    assert result["official_verdicts"] == ["incorrect", "correct"]
    assert result["audited_stage2_actions"] == 728


def test_rejects_corrupt_audit_chain(recorded_run: Path) -> None:
    with sqlite3.connect(recorded_run) as db:
        db.execute("UPDATE events SET digest='corrupt' WHERE sequence=1")
    with pytest.raises(ValueError, match="event chain is corrupt"):
        evidence.verify(recorded_run)


@pytest.mark.parametrize("change", [
    "UPDATE web_attempts SET verdict='incorrect' WHERE verdict='correct'",
    "UPDATE web_runs SET config='{" + '"adapter":"html","challenge_id":39' + "}'",
    "UPDATE events SET payload='{}' WHERE sequence=867",
])
def test_rejects_verdict_or_binding_mismatch(recorded_run: Path, change: str) -> None:
    with sqlite3.connect(recorded_run) as db:
        db.execute(change)
    with pytest.raises(ValueError):
        evidence.verify(recorded_run)


def test_rejects_incomplete_scan(recorded_run: Path) -> None:
    path = recorded_run.parent / "private-stay" / evidence.RUN_ID / "target-progress.json"
    state = json.loads(path.read_text())
    state["full_cursor"] = 87
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="full-scan checkpoint incomplete"):
        evidence.verify(recorded_run)

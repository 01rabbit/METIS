"""Task runner guards and checkpoint continuation without target secrets."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_issue28_stay_target as runner


def test_projection_and_private_checkpoint(tmp_path: Path) -> None:
    projection = runner._projection([{"seconds": 1.0, "scanned": 1000}], 88)
    assert projection["stage2_actions"] == 704
    assert projection["fits"] is False
    path = tmp_path / "state.json"
    runner._write_private(path, {"phase": "probe"})
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text()) == {"phase": "probe"}


def test_operation_timeout_obeys_phase_and_run_caps(monkeypatch) -> None:
    now = runner.time.time()
    monkeypatch.setattr(runner.time, "time", lambda: now)

    class Session:
        def context(self, _run_id):
            return {"seconds_remaining": 240}

    assert runner._operation_seconds({"phase": "probe", "started_at": now - 1700},
                                     Session()) == 100
    with pytest.raises(RuntimeError, match="wall-time"):
        runner._operation_seconds({"phase": "scanning", "started_at": now - 5395}, Session())


def test_full_scan_resumes_from_saved_cursor(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "GUESS_SPACE", 8)
    monkeypatch.setattr(runner, "STAGE2_CHUNK", 3)
    path = tmp_path / "progress.json"
    state = {"phase": "ready", "eligible": [{"shard": "private", "hit_index": 0}],
             "full_cursor": 0, "full_next_index": 0, "stage2_hits": [],
             "actions": 0, "started_at": runner.time.time(), "inflight": None}
    runner._write_private(path, state)
    calls = []

    def scan(_session, checkpoint, data, _item, _headers, start, stop):
        calls.append((start, stop))
        if len(calls) == 2:
            raise RuntimeError("interrupted")
        data["actions"] += 1
        return {"next_index": stop, "hits_count": 0}

    monkeypatch.setattr(runner, "_scan", scan)
    with pytest.raises(RuntimeError, match="interrupted"):
        runner.full(object(), path, state, "00")
    saved = json.loads(path.read_text())
    assert saved["full_next_index"] == 3
    monkeypatch.setattr(runner, "_scan", lambda _s, _p, d, _i, _h, start, stop: (
        d.__setitem__("actions", d["actions"] + 1) or
        {"next_index": stop, "hits_count": 0}))
    outcome = runner.full(object(), path, saved, "00")
    assert outcome["phase"] == "no_key"
    assert json.loads(path.read_text())["full_cursor"] == 1

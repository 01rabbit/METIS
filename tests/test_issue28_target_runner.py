"""Task runner guards and checkpoint continuation without target secrets."""
from __future__ import annotations

import json
import os
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


@pytest.mark.parametrize("response", [
    {"ok": False},
    {"ok": True, "result": None},
    {"ok": True, "result": {"next_index": 0}},
    {"ok": True, "result": {"next_index": 1, "reason": "worker_failed"}},
])
def test_scan_uncertain_result_blocks_restart(tmp_path: Path, response: dict) -> None:
    class Session:
        def context(self, _run_id):
            return {"status": "planning", "seconds_remaining": 300, "actions_remaining": 10}

        def artifact(self, *_args):
            return response

    state = {"phase": "probe", "started_at": runner.time.time(), "actions": 0,
             "inflight": None, "stage2_hits": []}
    path = tmp_path / "progress.json"
    with pytest.raises((RuntimeError, TypeError)):
        runner._scan(Session(), path, state, {"shard": "private", "hit_index": 0}, "00", 0, 1)
    reloaded = json.loads(path.read_text())
    assert reloaded["inflight"]["kind"] == "stage2"
    with pytest.raises(RuntimeError, match="audit before resume"):
        runner._check_budget(reloaded, Session())


def test_private_checkpoint_ignores_orphaned_temp(tmp_path: Path) -> None:
    path = tmp_path / "progress.json"
    (tmp_path / "progress.json.tmp").write_text("interrupted")
    runner._write_private(path, {"phase": "safe"})
    assert json.loads(path.read_text()) == {"phase": "safe"}
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("response", [
    {"ok": False},
    {"ok": True, "result": None},
    {"ok": True, "result": {"keys_count": 1, "key_shard": "private-stay/"
     + runner.RUN_ID + "/k-" + "0" * 32 + ".json"}},
    {"ok": True, "result": {"keys_count": 0, "reason": "time_limit",
     "next_product": 0, "next_extra": 0}},
])
def test_recovery_uncertain_result_blocks_restart(tmp_path: Path, response: dict) -> None:
    root = tmp_path / "private-stay" / runner.RUN_ID
    root.mkdir(parents=True)
    os.chmod(root, 0o700)
    shard = root / ("s2-" + "0" * 32 + ".json")
    shard.write_text(json.dumps({"hits": [[1]]}))
    os.chmod(shard, 0o600)

    class Session:
        database = tmp_path / "metis.sqlite"

        def context(self, _run_id):
            return {"status": "planning", "seconds_remaining": 300, "actions_remaining": 10}

        def artifact(self, *_args):
            return response

    state = {"phase": "recovering", "started_at": runner.time.time(),
             "actions": 0, "inflight": None,
             "stage2_hits": [{"shard": str(shard.relative_to(tmp_path))}]}
    path = root / "progress.json"
    with pytest.raises((RuntimeError, TypeError)):
        runner._recover(Session(), path, state, "00")
    reloaded = json.loads(path.read_text())
    assert reloaded["inflight"]["kind"] == "recover"
    with pytest.raises(RuntimeError, match="audit before resume"):
        runner._check_budget(reloaded, Session())


def test_recovery_rejects_symlink_key_shard(tmp_path: Path) -> None:
    root = tmp_path / "private-stay" / runner.RUN_ID
    root.mkdir(parents=True)
    os.chmod(root, 0o700)
    shard = root / ("s2-" + "0" * 32 + ".json")
    shard.write_text(json.dumps({"hits": [[1]]}))
    os.chmod(shard, 0o600)
    key_ref = "private-stay/" + runner.RUN_ID + "/k-" + "1" * 32 + ".json"
    (tmp_path / key_ref).symlink_to(shard)

    class Session:
        database = tmp_path / "metis.sqlite"

        def context(self, _run_id):
            return {"status": "planning", "seconds_remaining": 300, "actions_remaining": 10}

        def artifact(self, *_args):
            return {"ok": True, "result": {"keys_count": 1, "key_shard": key_ref}}

    state = {"phase": "recovering", "started_at": runner.time.time(),
             "actions": 0, "inflight": None,
             "stage2_hits": [{"shard": str(shard.relative_to(tmp_path))}]}
    path = root / "progress.json"
    with pytest.raises(RuntimeError, match="shard unsafe"):
        runner._recover(Session(), path, state, "00")
    assert json.loads(path.read_text())["inflight"]["kind"] == "recover"

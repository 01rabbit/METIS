import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from metis.core.contracts import RunEvent, RunStatus
from metis.core.store import RunStore


def event(sequence, status, run_id="run-1"):
    return RunEvent(run_id=run_id, sequence=sequence, status=status)


def test_reopen_replay_and_jsonl_export(tmp_path):
    path = tmp_path / "runs.sqlite"
    store = RunStore(path)
    statuses = [RunStatus.NEW, RunStatus.VALIDATED, RunStatus.CLASSIFIED,
                RunStatus.PLANNING, RunStatus.EXECUTING, RunStatus.OBSERVING,
                RunStatus.REPLANNING, RunStatus.PLANNING, RunStatus.EXECUTING,
                RunStatus.OBSERVING, RunStatus.VERIFYING, RunStatus.SOLVED]
    for sequence, status in enumerate(statuses):
        store.append(event(sequence, status))
    restored = RunStore(path)
    assert [entry.status for entry in restored.read("run-1")] == statuses
    lines = restored.export_jsonl("run-1").splitlines()
    assert len(lines) == len(statuses)
    assert json.loads(lines[-1])["status"] == "solved"
    with pytest.raises(ValueError, match="invalid transition"):
        restored.append(event(len(statuses), RunStatus.PLANNING))


def test_invalid_writes_roll_back(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    with pytest.raises(ValueError, match="begin in NEW"):
        store.append(event(0, RunStatus.SOLVED))
    store.append(event(0, RunStatus.NEW))
    for entry in [event(0, RunStatus.NEW), event(2, RunStatus.VALIDATED),
                  event(1, RunStatus.SOLVED)]:
        with pytest.raises(ValueError):
            store.append(entry)
    assert len(store.read("run-1")) == 1
    store.append(event(1, RunStatus.CANCELLED))
    with pytest.raises(ValueError):
        store.append(event(2, RunStatus.VALIDATED))


def test_run_isolation_and_append_only(tmp_path):
    path = tmp_path / "runs.sqlite"
    store = RunStore(path)
    store.append(event(0, RunStatus.NEW))
    store.append(event(0, RunStatus.NEW, "run-2"))
    store.append(event(1, RunStatus.POLICY_DENIED, "run-2"))
    assert len(store.read("run-1")) == 1
    assert len(store.read("run-2")) == 2
    with sqlite3.connect(path) as db:
        for statement in ["DELETE FROM events", "UPDATE events SET digest='broken'"]:
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                db.execute(statement)


def test_concurrent_sequence_collision_has_one_winner(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite")
    store.append(event(0, RunStatus.NEW))

    def append_once(_):
        try:
            store.append(event(1, RunStatus.VALIDATED))
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(append_once, range(2))) == [False, True]
    assert len(store.read("run-1")) == 2


def test_corrupt_chain_is_rejected_on_read_and_append(tmp_path):
    path = tmp_path / "runs.sqlite"
    store = RunStore(path)
    store.append(event(0, RunStatus.NEW))
    # Simulate an out-of-band writer bypassing the trigger, not a solver operation.
    with sqlite3.connect(path) as db:
        db.execute("DROP TRIGGER deny_update")
        db.execute("UPDATE events SET digest='corrupt'")
    with pytest.raises(ValueError, match="corrupt"):
        store.read("run-1")
    with pytest.raises(ValueError, match="corrupt"):
        store.append(event(1, RunStatus.VALIDATED))

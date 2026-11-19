import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing
from multiprocessing import get_context
from pathlib import Path

import pytest

from metis.core.study_token_admission import (
    FixtureClaimBusy,
    SlotTokenPin,
    StudyTokenAdmission,
    StudyTokenPin,
    TokenAdmissionReceipt,
    TokenAttempt,
    TokenLaunchOutcome,
)

_STUDY = StudyTokenPin(
    study_id="fixture", protocol_sha256="a" * 64, runtime_sha256="b" * 64,
    model_sha256="c" * 64, token_limit=15,
)
_SLOT = SlotTokenPin(run_id="run", task_id="fixture", repetition=0, arm="test", token_limit=15)
_ATTEMPT = TokenAttempt(
    assignment_id="assignment", attempt_id="attempt", turn_reservation_id=1,
    prompt_sha256="d" * 64, tokens=15,
)
_SYNTHETIC_CHILD = """
from pathlib import Path
import sys
import time

ready, release, exited = map(Path, sys.argv[1:])
ready.touch()
deadline = time.monotonic() + 10
while not release.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
exited.touch()
"""


def _wait_for(path: Path) -> None:
    deadline = time.monotonic() + 10
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.015)
    assert path.exists()


def _crash_after_claim(database: Path, receipt: TokenAdmissionReceipt, scratch: Path | None) -> None:
    with StudyTokenAdmission(database).claim_fixture_launch(receipt):
        if scratch is not None:
            ready, release, exited = (scratch / marker for marker in ("ready", "release", "exited"))
            subprocess.Popen(
                [sys.executable, "-c", _SYNTHETIC_CHILD, str(ready), str(release), str(exited)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            _wait_for(ready)
        os._exit(91)


def _finish_with_lock(database: Path, receipt: TokenAdmissionReceipt, ready, release) -> None:
    admission = StudyTokenAdmission(database)
    with admission.claim_fixture_launch(receipt) as claim:
        ready.set()
        if not release.wait(timeout=10):
            raise RuntimeError("fixture controller release not received")
        admission.record_outcome(claim, TokenLaunchOutcome(status="launch_failed"))


def _reconcile(database: Path, receipt: TokenAdmissionReceipt, barrier) -> str:
    barrier.wait(timeout=10)
    try:
        return StudyTokenAdmission(database).reconcile_lost_fixture_claim(receipt).status
    except FixtureClaimBusy:
        return "denied"
    except ValueError as error:
        assert "outcome already recorded" in str(error)
        return "denied"


@pytest.fixture
def reserved(tmp_path):
    admission = StudyTokenAdmission(tmp_path / "state.sqlite")
    return admission, admission.reserve(_STUDY, _SLOT, _ATTEMPT)


@pytest.mark.parametrize("launch_child", [False, True])
def test_crashed_controller_reconciles_once_with_full_charge(reserved, tmp_path, launch_child):
    admission, receipt = reserved
    scratch = tmp_path if launch_child else None
    process = get_context("spawn").Process(target=_crash_after_claim, args=(admission.database, receipt, scratch))
    process.start()
    try:
        process.join(timeout=15)
        assert process.exitcode == 91
        if launch_child:
            assert (tmp_path / "ready").exists() and not (tmp_path / "exited").exists()

        result = admission.reconcile_lost_fixture_claim(receipt)
        assert (result.status, result.exit_status, result.observed_work) == ("lost", None, None)
        if launch_child:
            assert not (tmp_path / "exited").exists()
        with pytest.raises(ValueError, match="outcome already recorded"):
            admission.reconcile_lost_fixture_claim(receipt)
        with pytest.raises(ValueError, match="already claimed"), admission.claim_fixture_launch(receipt):
            pytest.fail("a lost claim was reissued")
        with pytest.raises(ValueError, match="study token budget exhausted"):
            admission.reserve(_STUDY, _SLOT, _ATTEMPT.model_copy(update={"turn_reservation_id": 2, "tokens": 1}))
    finally:
        if launch_child:
            (tmp_path / "release").touch()
    if launch_child:
        _wait_for(tmp_path / "exited")
    process.close()


def test_reconcile_refuses_a_live_controller_and_keeps_its_terminal_outcome(reserved):
    admission, receipt = reserved
    context = get_context("spawn")
    ready, release = context.Event(), context.Event()
    process = context.Process(target=_finish_with_lock, args=(admission.database, receipt, ready, release))
    process.start()
    try:
        assert ready.wait(timeout=10)
        with pytest.raises(FixtureClaimBusy, match="active owner"):
            admission.reconcile_lost_fixture_claim(receipt)
    finally:
        release.set()
        process.join(timeout=12)
    assert process.exitcode == 0
    process.close()
    with pytest.raises(ValueError, match="outcome already recorded"):
        admission.reconcile_lost_fixture_claim(receipt)
    with closing(sqlite3.connect(admission.database)) as db:
        assert db.execute("SELECT status FROM study_token_outcomes").fetchall() == [("launch_failed",)]


def test_racing_reconcilers_record_exactly_one_loss(reserved):
    admission, receipt = reserved
    with admission.claim_fixture_launch(receipt):
        pass
    context = get_context("spawn")
    with context.Manager() as manager, ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
        barrier = manager.Barrier(2)
        requests = [pool.submit(_reconcile, admission.database, receipt, barrier) for _ in range(2)]
        assert sorted(request.result(timeout=15) for request in requests) == ["denied", "lost"]
    with closing(sqlite3.connect(admission.database)) as db:
        assert db.execute("SELECT status FROM study_token_outcomes").fetchall() == [("lost",)]


def test_legacy_claim_and_forged_receipts_cannot_be_reconciled(reserved):
    admission, receipt = reserved
    with pytest.raises(ValueError, match="no recoverable fixture claim"):
        admission.reconcile_lost_fixture_claim(receipt)
    admission.claim_for_launch(receipt)
    with pytest.raises(ValueError, match="no recoverable fixture claim"):
        admission.reconcile_lost_fixture_claim(receipt)
    forged = receipt.model_copy(update={"attempt": receipt.attempt.model_copy(update={"tokens": 14})})
    with pytest.raises(ValueError, match="committed reservation"):
        admission.reconcile_lost_fixture_claim(forged)


def test_recovery_refuses_a_symlinked_lock_directory(reserved, tmp_path):
    admission, receipt = reserved
    foreign = tmp_path / "foreign"
    foreign.mkdir(mode=0o700)
    lock_path = tmp_path / ".state.sqlite.fixture-locks"
    lock_path.symlink_to(foreign, target_is_directory=True)
    with pytest.raises(OSError):
        admission.reconcile_lost_fixture_claim(receipt)
    assert list(foreign.iterdir()) == []

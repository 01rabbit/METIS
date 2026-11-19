from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

import pytest
from pydantic import ValidationError

from metis.core.study_token_admission import (
    SlotTokenPin,
    StudyTokenAdmission,
    StudyTokenPin,
    TokenAttempt,
)

STUDY = StudyTokenPin(study_id="issue8", protocol_sha256="a" * 64, runtime_sha256="b" * 64,
                      model_sha256="c" * 64, token_limit=100)
SLOT = SlotTokenPin(run_id="run1", task_id="task", repetition=0, arm="full", token_limit=70)
ATTEMPT = TokenAttempt(assignment_id="assignment", attempt_id="attempt1", turn_reservation_id=1,
                       prompt_sha256="d" * 64, tokens=60)


def _concurrent_reservation(database: Path, distinct_slots: bool, index: int, barrier) -> str:
    slot = (
        SLOT.model_copy(update={"run_id": f"run{index}", "repetition": index})
        if distinct_slots else SLOT
    )
    attempt = ATTEMPT.model_copy(update={
        "turn_reservation_id": index + 1, "tokens": 60 if distinct_slots else 40,
    })
    barrier.wait(timeout=10)
    try:
        StudyTokenAdmission(database).reserve(STUDY, slot, attempt)
    except ValueError as exc:
        return str(exc)
    return "admitted"


@pytest.mark.parametrize(("distinct_slots", "exhausted"), [
    (False, "run token budget exhausted"),
    (True, "study token budget exhausted"),
])
def test_parallel_controllers_share_study_and_run_caps(tmp_path, distinct_slots, exhausted):
    database = tmp_path / "state.sqlite"
    context = get_context("spawn")
    with context.Manager() as manager, ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
        barrier = manager.Barrier(2)
        requests = [pool.submit(_concurrent_reservation, database, distinct_slots, index, barrier)
                    for index in range(2)]
        assert sorted(request.result(timeout=15) for request in requests) == [
            "admitted", exhausted,
        ]


@pytest.mark.parametrize("failure", [TimeoutError, OSError])
def test_timeout_or_failure_retains_entire_allowance(tmp_path, failure):
    database = tmp_path / "state.sqlite"
    with pytest.raises(failure):
        StudyTokenAdmission(database).reserve(STUDY, SLOT, ATTEMPT)
        raise failure("runtime did not return a receipt")
    restarted = StudyTokenAdmission(database)
    with pytest.raises(ValueError, match="already has a token receipt"):
        restarted.reserve(STUDY, SLOT, ATTEMPT.model_copy(update={"attempt_id": "retry"}))
    next_attempt = ATTEMPT.model_copy(update={"turn_reservation_id": 2, "tokens": 11})
    with pytest.raises(ValueError, match="run token budget exhausted"):
        restarted.reserve(STUDY, SLOT, next_attempt)


@pytest.mark.parametrize(("field", "value"), [
    ("study_id", "alternate"), ("protocol_sha256", "e" * 64),
    ("runtime_sha256", "e" * 64), ("model_sha256", "e" * 64), ("token_limit", 101),
])
def test_study_pin_cannot_change(tmp_path, field, value):
    admission = StudyTokenAdmission(tmp_path / "state.sqlite")
    admission.reserve(STUDY, SLOT, ATTEMPT)
    changed = STUDY.model_copy(update={field: value})
    with pytest.raises(ValueError, match="study token pin mismatch"):
        admission.reserve(changed, SLOT, ATTEMPT)


@pytest.mark.parametrize(("field", "value"), [
    ("run_id", "replacement-run"), ("task_id", "replacement-task"),
    ("repetition", 1), ("arm", "other"), ("token_limit", 71),
])
def test_run_and_slot_pin_cannot_change(tmp_path, field, value):
    admission = StudyTokenAdmission(tmp_path / "state.sqlite")
    admission.reserve(STUDY, SLOT, ATTEMPT)
    changed = SLOT.model_copy(update={field: value})
    with pytest.raises(ValueError, match="run or study slot token pin mismatch"):
        admission.reserve(STUDY, changed, ATTEMPT)


def test_denied_reservations_roll_back_and_success_is_frozen(tmp_path):
    admission = StudyTokenAdmission(tmp_path / "state.sqlite")
    with pytest.raises(ValueError, match="run token budget exhausted"):
        admission.reserve(STUDY, SLOT.model_copy(update={"token_limit": 50}), ATTEMPT)
    receipt = admission.reserve(STUDY, SLOT, ATTEMPT)
    assert (receipt.study, receipt.slot, receipt.attempt) == (STUDY, SLOT, ATTEMPT)
    with pytest.raises(ValidationError):
        receipt.attempt.tokens = 1
    remaining = ATTEMPT.model_copy(update={"turn_reservation_id": 2, "tokens": 10})
    assert admission.reserve(STUDY, SLOT, remaining).attempt.tokens == 10


@pytest.mark.parametrize("tokens", [True, "1", 0, -1])
def test_invalid_amount_cannot_bypass_validation(tmp_path, tokens):
    admission = StudyTokenAdmission(tmp_path / "state.sqlite")
    with pytest.raises(ValidationError):
        admission.reserve(STUDY, SLOT, ATTEMPT.model_copy(update={"tokens": tokens}))

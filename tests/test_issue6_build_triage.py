from dataclasses import asdict, replace

import pytest

from metis.evaluation.issue6_build_generator import FAMILIES, _events, make_fixture
from metis.evaluation.issue6_build_oracle import (
    BuildFixture,
    Cause,
    Job,
    Observation,
    matching_causes,
    verify_proposal,
)


def test_artifact_delay_is_distinct_from_a_slow_build() -> None:
    jobs = (Job("app", "build", 2), Job("unit", "test", 1, ("app",)))
    slow = Cause("slow_job", "app", 3)
    delayed = Cause("late_artifact", "app", 3)
    fixture = BuildFixture(
        jobs, (slow, delayed),
        (Observation("app", "finish", 2), Observation("unit", "start", 5)),
    )
    assert _events(jobs, delayed) == {
        ("app", "start"): 0, ("app", "finish"): 2,
        ("unit", "start"): 5, ("unit", "finish"): 6,
    }
    assert matching_causes(fixture) == (delayed,)
    assert verify_proposal(fixture, delayed)
    assert not verify_proposal(fixture, slow)

    ambiguous = replace(fixture, observations=fixture.observations[1:])
    assert matching_causes(ambiguous) == (slow, delayed)
    assert not verify_proposal(ambiguous, delayed)

    mutated = replace(fixture, observations=(Observation("unit", "start", 4),))
    assert matching_causes(mutated) == ()
    assert not verify_proposal(mutated, delayed)


def test_worker_loss_preserves_running_jobs_and_dispatches_at_window_end() -> None:
    jobs = (
        Job("b", "build", 5),
        Job("c", "build", 3),
        Job("a", "build", 2, ("d",)),
        Job("d", "test", 2),
    )
    loss = Cause("worker_loss", "build", 2, 2)
    alternative = Cause("worker_loss", "build", 3, 2)
    fixture = BuildFixture(
        jobs, (loss, alternative),
        (Observation("a", "start", 4), Observation("c", "finish", 3)),
    )
    assert _events(jobs, loss) == {
        ("b", "start"): 0, ("c", "start"): 0, ("d", "start"): 0,
        ("d", "finish"): 2, ("c", "finish"): 3, ("a", "start"): 4,
        ("b", "finish"): 5, ("a", "finish"): 6,
    }
    assert matching_causes(fixture) == (loss,)


def test_rejects_cycle_and_duplicate_observation() -> None:
    jobs = (Job("a", "build", 2, ("b",)), Job("b", "test", 1, ("a",)))
    option = Cause("slow_job", "a", 2)
    event = Observation("a", "start", 0)
    fixture = BuildFixture(jobs, (option,), (event,))
    with pytest.raises(ValueError, match="cycle"):
        matching_causes(fixture)
    with pytest.raises(ValueError, match="distinct event"):
        matching_causes(replace(fixture, jobs=(Job("a", "build", 2),), observations=(event, event)))


@pytest.mark.parametrize("difficulty", ["small", "medium", "large"])
@pytest.mark.parametrize("family", FAMILIES)
def test_seeded_admission_is_deterministic_unique_and_answer_free(difficulty, family) -> None:
    for seed in range(5):
        entry = make_fixture(seed, difficulty, family)
        assert entry == make_fixture(seed, difficulty, family)
        (answer,) = matching_causes(entry.fixture)
        assert answer.kind == family
        assert entry.attempts == 1 + entry.ambiguous + entry.incompatible
        assert set(asdict(entry)) == {"fixture", "attempts", "ambiguous", "incompatible"}
        assert set(asdict(entry.fixture)) == {"jobs", "options", "observations"}


def test_ambiguity_rejection_is_bounded_and_defective_generator_halts(monkeypatch) -> None:
    from metis.evaluation import issue6_build_generator as generator

    monkeypatch.setattr(generator, "MAX_ATTEMPTS", 3)
    monkeypatch.setattr(generator, "matching_causes", lambda fixture: fixture.options)
    with pytest.raises(ValueError, match="admission exhausted"):
        make_fixture(1, "small", "worker_loss")

    monkeypatch.setattr(generator, "matching_causes", lambda fixture: ())
    with pytest.raises(ValueError, match="generator and oracle disagree"):
        make_fixture(1, "small", "worker_loss")

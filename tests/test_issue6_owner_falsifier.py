from __future__ import annotations

from metis.evaluation.issue6_owner_falsifier import (
    Counterexample,
    analyze_paired,
    first_counterexample,
    make_task,
    validate_counterexample,
)


def test_task_is_reproducible_and_has_unique_order_constraints() -> None:
    task, answer = make_task(2026111901)
    assert (task, answer) == make_task(2026111901)
    assert first_counterexample(task, answer) is None
    assert len(task.symbols) == 20
    assert len(set(task.symbols)) == 20


def test_public_witness_catches_swap_without_hidden_answer() -> None:
    task, answer = make_task(2026111902)
    proposal = list(answer)
    proposal[0], proposal[1] = proposal[1], proposal[0]
    witness = first_counterexample(task, tuple(proposal))
    assert witness is not None
    assert witness.kind == "precedence"
    assert validate_counterexample(task, tuple(proposal), witness).valid


def test_fabricated_witness_cannot_trigger_repair() -> None:
    task, answer = make_task(2026111903)
    assert not validate_counterexample(
        task, answer, Counterexample(kind="missing", symbol=answer[0])
    ).valid
    before, after = task.precedences[0]
    assert not validate_counterexample(
        task, answer, Counterexample(kind="precedence", before=before, after=after)
    ).valid


def test_paired_analysis_requires_all_predeclared_cases() -> None:
    records = [{"case": f"task-{index:02d}", "arm": arm,
                "workflow_verified": arm == "owner_falsifier"}
               for index in range(30) for arm in ("single", "owner_falsifier")]
    data = {"study": "issue6-owner-falsifier-2026-11-19", "seed": 2026111906,
            "arms": ["single", "owner_falsifier"], "records": records}
    result = analyze_paired(data)
    assert result["gain_gate_met"] is True
    assert result["discordance"]["owner_falsifier_only"] == 30
    data["records"].pop()
    import pytest
    with pytest.raises(ValueError, match="60 arm records"):
        analyze_paired(data)

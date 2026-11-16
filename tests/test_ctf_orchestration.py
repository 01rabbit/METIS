import pytest

from metis.core.codex_session import CodexSession
from metis.core.ctf_orchestration import AgentLedger, plan_agent_wave


def test_wave_is_bounded_distinct_and_keeps_submission_with_daybreak():
    wave = plan_agent_wave({
        "run_id": "run-1",
        "challenge": {"categories": ["crypto", "forensics", "misc"],
                      "artifacts": ["capture.pcap", "payload.bin"]},
    })
    assignments = wave["assignments"]
    assert 2 <= len(assignments) <= 4
    assert len({item["role"] for item in assignments}) == len(assignments)
    assert all(item["context_policy"].startswith("no-history") for item in assignments)
    assert all(not item["may_submit"] and not item["may_expand_scope"] for item in assignments)
    assert wave["synthesis_gate"]["official_submission_owner"] == "Daybreak"


def test_empty_problem_is_sequential_and_forced_delegation_keeps_legacy_roles():
    wave = plan_agent_wave({"run_id": "run-2", "challenge": {"categories": [], "artifacts": []}})
    assert wave["execution_mode"] == "sequential" and wave["assignments"] == []
    assert set(wave["daybreak_covers"]) == {"misc-specialist", "independent-critic"}
    legacy = plan_agent_wave({"run_id": "run-2", "challenge": {"categories": [], "artifacts": []}},
                             force_mode="delegated")
    roles = {item["role"] for item in legacy["assignments"]}
    assert roles == {"misc-specialist", "independent-critic"}


def test_agent_reports_persist_evidence_and_synthesize_without_submission(tmp_path):
    database = tmp_path / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.demo()[0]["run_id"]
    sequence = session.store.read(run_id)[-1].sequence
    ledger = AgentLedger(database)
    wave = ledger.create_wave(run_id, mode="delegated")
    initial = ledger.synthesize(run_id, wave["wave_id"])
    assert initial["missing_assignments"]
    for index, assignment in enumerate(wave["assignments"]):
        stored = ledger.record_report(run_id, wave["wave_id"], assignment["assignment_id"], {
            "hypothesis": f"Decoder family {index} matches the observed representation.",
            "evidence": "The recorded challenge metadata identifies a bounded text puzzle.",
            "falsifier": "A decoder rejection or non-text output would reject this hypothesis.",
            "next_action": f"Run bounded decoder option {index} against the declared input.",
            "event_sequences": [sequence],
            "status": "supported" if index == 0 else "inconclusive",
        })
        assert stored["candidate_stored"] is False
    result = ledger.synthesize(run_id, wave["wave_id"])
    assert result["complete"]
    assert result["supported_hypotheses"]
    assert result["submission"] == {"owner": "orchestrator", "allowed": False,
                                    "reason": "official_verifier_required"}


def test_agent_reports_reject_unknown_evidence_duplicates_and_flags(tmp_path):
    database = tmp_path / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.demo()[0]["run_id"]
    sequence = session.store.read(run_id)[-1].sequence
    ledger = AgentLedger(database)
    wave = ledger.create_wave(run_id, mode="delegated")
    assignment = wave["assignments"][0]["assignment_id"]
    base = {
        "hypothesis": "The input likely uses a standard text encoding.",
        "evidence": "The challenge record declares a short textual payload.",
        "falsifier": "Binary output would reject the text-encoding hypothesis.",
        "next_action": "Inspect the alphabet and padding before decoding.",
        "event_sequences": [sequence],
        "status": "inconclusive",
    }
    with pytest.raises(ValueError, match="unknown run evidence"):
        ledger.record_report(run_id, wave["wave_id"], assignment,
                             {**base, "event_sequences": [9999]})
    ledger.record_report(run_id, wave["wave_id"], assignment, base)
    other = wave["assignments"][1]["assignment_id"]
    with pytest.raises(ValueError, match="duplicate next action"):
        ledger.record_report(run_id, wave["wave_id"], other, base)
    with pytest.raises(ValueError, match="flag-shaped"):
        ledger.record_report(run_id, wave["wave_id"], other,
                             {**base, "hypothesis": "The answer is FLAG_privatevalue.",
                              "next_action": "Try a different bounded inspection method."})

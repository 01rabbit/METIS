import pytest

from metis.core.agent_host import FakeHost
from metis.core.agent_scheduler import AgentScheduler
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
    run_id = session.intake(title="Synthetic hypotheses", description="Compare independent parser hypotheses.",
                            categories=["crypto", "web", "misc"], paths=[])["run_id"]
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


def _record_synthesis_reports(ledger, run_id, wave, sequence, *, conflict):
    assignments = wave["assignments"]
    assert len(assignments) >= 2
    for index, assignment in enumerate(assignments):
        if index == 0:
            hypothesis, status = "The payload is base64 encoded.", "supported"
        elif index == 1 and conflict:
            hypothesis, status = "  THE   PAYLOAD IS BASE64 ENCODED. ", "rejected"
        else:
            hypothesis, status = "The archive uses compression.", "rejected"
        ledger.record_report(run_id, wave["wave_id"], assignment["assignment_id"], {
            "hypothesis": hypothesis,
            "evidence": f"Distinct role {index} cites the observed input representation.",
            "falsifier": f"A bounded parse result can test role {index}'s hypothesis.",
            "next_action": f"Inspect distinct representation window {index}.",
            "event_sequences": [sequence],
            "status": status,
        })


def test_synthesis_scores_hypotheses_and_reports_only_matching_contradictions(tmp_path):
    database = tmp_path / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.intake(title="Synthetic hypotheses", description="Compare independent parser hypotheses.",
                            categories=["crypto", "web", "misc"], paths=[])["run_id"]
    sequence = session.store.read(run_id)[-1].sequence
    ledger = AgentLedger(database)
    wave = ledger.create_wave(run_id, mode="delegated")
    _record_synthesis_reports(ledger, run_id, wave, sequence, conflict=True)

    result = ledger.synthesize(run_id, wave["wave_id"])
    by_hypothesis = {item["hypothesis"].casefold(): item for item in result["hypothesis_scores"]}
    matching = by_hypothesis["the payload is base64 encoded."]
    unrelated = by_hypothesis["the archive uses compression."]
    assert matching["score"] == 0 and matching["contradicted"] is True
    assert matching["supported"] == matching["rejected"] == 1
    assert unrelated["score"] < 0 and unrelated["contradicted"] is False
    assert len(result["contradicted_hypotheses"]) == 1
    assert len(result["contradictions"]) == 1
    assert result["decision"]["new_wave"]["allowed"] is True


def test_unrelated_supported_and_rejected_hypotheses_are_not_conflicted(tmp_path):
    database = tmp_path / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.demo()[0]["run_id"]
    sequence = session.store.read(run_id)[-1].sequence
    ledger = AgentLedger(database)
    wave = ledger.create_wave(run_id, mode="delegated")
    _record_synthesis_reports(ledger, run_id, wave, sequence, conflict=False)

    result = ledger.synthesize(run_id, wave["wave_id"])
    assert result["contradicted_hypotheses"] == []
    assert result["contradictions"] == []
    assert result["decision"]["new_wave"]["allowed"] is False
    assert "no open or contradicted hypothesis" in result["decision"]["new_wave"]["blocked_by"]


def test_synthesis_flags_repeated_next_action_across_waves(tmp_path):
    database = tmp_path / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.demo()[0]["run_id"]
    events = session.store.read(run_id)
    ledger = AgentLedger(database)
    first = ledger.create_wave(run_id, mode="delegated")
    repeated_action = "Inspect decoder padding at the declared offset."
    for index, assignment in enumerate(first["assignments"]):
        ledger.record_report(run_id, first["wave_id"], assignment["assignment_id"], {
            "hypothesis": f"Encoding hypothesis {index} has not been falsified.",
            "evidence": "The declared input is a bounded local fixture.",
            "falsifier": "A strict parser rejection falsifies this decoder hypothesis.",
            "next_action": repeated_action if index == 0 else f"Inspect representation layer {index}.",
            "event_sequences": [events[0].sequence],
            "status": "inconclusive",
        })
    second = ledger.create_wave(run_id, mode="delegated",
                                reason="Retest decoder after the new parser observation.")
    assignment = second["assignments"][0]
    ledger.record_report(run_id, second["wave_id"], assignment["assignment_id"], {
        "hypothesis": "Encoding hypothesis 0 has not been falsified.",
        "evidence": "The parser feedback event is now present in the run ledger.",
        "falsifier": "A strict parser rejection falsifies this decoder hypothesis.",
        "next_action": repeated_action,
        "event_sequences": [events[1].sequence],
        "status": "inconclusive",
    })
    result = ledger.synthesize(run_id, second["wave_id"])
    assert result["stuckness"]["detected"] is True
    assert result["stuckness"]["repeated_actions"] == [{
        "action": repeated_action, "hypothesis": "Encoding hypothesis 0 has not been falsified.",
        "wave_count": 2, "stalled": True, "statuses": ["inconclusive"],
    }]
    for index, extra_assignment in enumerate(second["assignments"][1:], 1):
        ledger.record_report(run_id, second["wave_id"], extra_assignment["assignment_id"], {
            "hypothesis": f"Alternative representation hypothesis {index} remains open.",
            "evidence": "The next event records a distinct local observation.",
            "falsifier": "A strict decoder rejection would falsify this hypothesis.",
            "next_action": f"Inspect alternative representation layer {index}.",
            "event_sequences": [events[2].sequence],
            "status": "inconclusive",
        })
    with pytest.raises(ValueError, match="distinct reason"):
        ledger.create_wave(run_id, mode="delegated",
                           reason="Retest decoder after the new parser observation.")
    third = ledger.create_wave(run_id, mode="delegated",
                                reason="Switch to a length-based decoder after the latest observation.")
    third_assignment = third["assignments"][0]
    ledger.record_report(run_id, third["wave_id"], third_assignment["assignment_id"], {
        "hypothesis": "Encoding hypothesis 0 has not been falsified.",
        "evidence": "The latest observation motivates testing another route.",
        "falsifier": "A strict decoder rejection falsifies this decoder hypothesis.",
        "next_action": "Inspect the decoded length before trying another parser.",
        "event_sequences": [events[3].sequence],
        "status": "inconclusive",
    })
    moved = ledger.synthesize(run_id, third["wave_id"])
    assert moved["stuckness"]["detected"] is False
    assert all(not item["stalled"] for item in moved["stuckness"]["repeated_actions"])


@pytest.mark.parametrize("second_data, second_status, expected_stalled", [
    ("61 62", "inconclusive", True),
    ("61 62", "rejected", False),
    ("6163", "inconclusive", False),
])
def test_synthesis_detects_controller_identity_across_paraphrased_proposals(
        tmp_path, second_data, second_status, expected_stalled):
    database = tmp_path / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.demo()[0]["run_id"]
    ledger = AgentLedger(database)
    scheduler = AgentScheduler(database, FakeHost())
    scheduler.configure(global_slots=1, per_run_slots=1)

    def run_wave(wave, data, status, description):
        scheduler.enqueue(run_id, wave["wave_id"])
        job = scheduler.dispatch(run_id)["started"][0]
        intent = {"kind": "data", "tool": "hex_decode", "data": data}
        observed = scheduler.intent(run_id, job["assignment_id"], job["attempt_id"], intent)
        report = {
            "hypothesis": "The supplied payload is hexadecimal text.",
            "evidence": description,
            "falsifier": "A strict hexadecimal parse failure would reject this hypothesis.",
            "next_action": description,
            "next_action_intent": intent,
            "event_sequences": [observed["evidence_sequence"]],
            "status": status,
        }
        scheduler.complete(run_id, job["assignment_id"], job["attempt_id"], report)
        scheduler.cancel(wave_id=wave["wave_id"], reason="unused synthetic assignments")

    first = ledger.create_wave(run_id, mode="delegated")
    run_wave(first, "6162", "inconclusive", "Decode the payload as hex.")
    second = ledger.create_wave(run_id, mode="delegated",
                                reason="Use the latest event to recheck the same encoding hypothesis.")
    run_wave(second, second_data, second_status, "Apply hexadecimal decoding to the observed bytes.")

    result = ledger.synthesize(run_id, second["wave_id"])
    assert result["stuckness"]["detected"] is expected_stalled
    if second_data == "61 62":
        repeated = next(item for item in result["stuckness"]["repeated_actions"]
                        if item["hypothesis"] == "The supplied payload is hexadecimal text.")
        assert repeated["stalled"] is expected_stalled
    else:
        assert result["stuckness"]["repeated_actions"] == []


def test_synthesis_does_not_trust_unexecuted_proposal_identity(tmp_path):
    database = tmp_path / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.demo()[0]["run_id"]
    initial_sequence = session.store.read(run_id)[0].sequence
    ledger = AgentLedger(database)
    scheduler = AgentScheduler(database, FakeHost())
    scheduler.configure(global_slots=1, per_run_slots=1)
    proposal = {"kind": "data", "tool": "hex_decode", "data": "6162"}

    def report_wave(wave, executed, evidence_text, next_action, *, cited_sequence=None):
        scheduler.enqueue(run_id, wave["wave_id"])
        job = scheduler.dispatch(run_id)["started"][0]
        observed = scheduler.intent(run_id, job["assignment_id"], job["attempt_id"], executed)
        report = {
            "hypothesis": "The supplied payload is hexadecimal text.",
            "evidence": evidence_text,
            "falsifier": "A strict hexadecimal parse failure would reject this hypothesis.",
            "next_action": next_action,
            "next_action_intent": proposal,
            "event_sequences": [cited_sequence if cited_sequence is not None
                                else observed["evidence_sequence"]],
            "status": "inconclusive",
        }
        scheduler.complete(run_id, job["assignment_id"], job["attempt_id"], report)
        scheduler.cancel(wave_id=wave["wave_id"], reason="unused synthetic assignments")
        return observed["evidence_sequence"]

    first = ledger.create_wave(run_id, mode="delegated")
    first_sequence = report_wave(
        first, {"kind": "data", "tool": "hex_decode", "data": "6162"},
        "The initial metadata observation supports text decoding.", "Decode the supplied hex text.",
        cited_sequence=initial_sequence,
    )
    second = ledger.create_wave(run_id, mode="delegated",
                                reason="Use the newer decode result to test another representation.")
    report_wave(
        second, {"kind": "data", "tool": "base64_decode", "data": "YWI="},
        "A newer base64 decode observation supports a representation comparison.",
        "Apply hexadecimal decoding to the original payload.", cited_sequence=first_sequence,
    )

    result = ledger.synthesize(run_id, second["wave_id"])
    assert result["stuckness"]["detected"] is False
    assert result["stuckness"]["repeated_actions"] == []


def test_report_cannot_supply_unbound_action_identity(tmp_path):
    database = tmp_path / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.demo()[0]["run_id"]
    sequence = session.store.read(run_id)[0].sequence
    ledger = AgentLedger(database)
    wave = ledger.create_wave(run_id, mode="delegated")
    report = {
        "hypothesis": "The input uses a standard text encoding.",
        "evidence": "The challenge description labels the input as text.",
        "falsifier": "A binary-only parse would reject this text hypothesis.",
        "next_action": "Inspect the alphabet and padding before decoding.",
        "event_sequences": [sequence], "status": "inconclusive", "action_identity": "a" * 64,
    }
    with pytest.raises(ValueError, match="controller-checkable"):
        ledger.record_report(run_id, wave["wave_id"], wave["assignments"][0]["assignment_id"], report)


def test_report_rejects_unsupported_derive_proposal(tmp_path):
    database = tmp_path / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.demo()[0]["run_id"]
    sequence = session.store.read(run_id)[0].sequence
    ledger = AgentLedger(database)
    wave = ledger.create_wave(run_id, mode="delegated")
    report = {
        "hypothesis": "The payload may contain a nested compressed stream.",
        "evidence": "The recorded overview identifies a possible binary container.",
        "falsifier": "A non-container parse result would reject this hypothesis.",
        "next_action": "Inspect the input with the overview parser.",
        "event_sequences": [sequence], "status": "inconclusive",
        "next_action_intent": {"kind": "derive", "tool": "overview", "artifact": "missing.bin",
                               "data": None, "options": {}, "new_evidence": []},
    }
    with pytest.raises(ValueError, match="unsupported tool"):
        ledger.record_report(run_id, wave["wave_id"], wave["assignments"][0]["assignment_id"], report)


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

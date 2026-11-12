from metis.core.ctf_orchestration import plan_agent_wave


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


def test_wave_always_has_specialist_and_independent_critic():
    wave = plan_agent_wave({"run_id": "run-2", "challenge": {"categories": [], "artifacts": []}})
    roles = {item["role"] for item in wave["assignments"]}
    assert roles == {"misc-specialist", "independent-critic"}

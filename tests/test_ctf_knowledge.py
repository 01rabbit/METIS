import json

import pytest

from metis.core.ctf_knowledge import KnowledgeBase, TechniqueCard
from metis.core.runtime import ToolRequest


def card(run_id, **changes):
    value = {
        "title": "Decode a Base64 distribution file", "category": "crypto",
        "summary": "Inspect the alphabet and padding, then decode the data and preserve exact output.",
        "conditions": "A text distribution file uses standard Base64 encoding.",
        "failure_reason": "", "outcome": "success", "source_run_id": run_id,
        "source_split": "practice",
    }
    value.update(changes)
    return TechniqueCard.model_validate(value)


def test_memory_requires_verification_and_persists_abstract_experience(tmp_path):
    database = tmp_path / "metis.sqlite"
    memory = KnowledgeBase(database)
    context = memory.session.demo()[0]
    run_id = context["run_id"]
    with pytest.raises(ValueError, match="verified solve"):
        memory.remember(card(run_id))
    payload = context["challenge"]["description"].rsplit(": ", 1)[1]
    memory.session.act(run_id, ToolRequest(tool="hex_decode", data="not-hex"))
    failed = memory.remember(card(run_id, outcome="failure",
                                  summary="Hex decoding was rejected; inspect the input alphabet before selecting a decoder.",
                                  failure_reason="The input contained characters outside the hexadecimal alphabet."))
    assert failed["stored"]
    result = memory.session.act(run_id, ToolRequest(tool="base64_decode", data=payload))
    assert memory.session.submit(run_id, result["output"])["verified"]
    good = memory.remember(card(run_id))
    assert good["stored"]
    assert memory.remember(card(run_id))["already_known"]
    reopened = KnowledgeBase(database)
    results = reopened.search("Base64", category="crypto")
    assert results
    assert any(item["card"]["outcome"] == "success" for item in results)
    assert any(item["card"]["outcome"] == "failure" for item in results)
    assert result["output"] not in json.dumps(results)
    assert not reopened.search("Base64", category="web")


def test_flags_credentials_and_heldout_data_are_not_reusable_cards(tmp_path):
    memory = KnowledgeBase(tmp_path / "metis.sqlite")
    context = memory.session.demo()[0]
    run_id = context["run_id"]
    with pytest.raises(ValueError, match="held-out"):
        memory.remember(card(run_id, source_split="heldout", outcome="inconclusive"))
    for value in ("The answer was CTF{must-not-store} and that is private.",
                  "The answer was FLAG_privatevalue and is confidential.",
                  "The captured cookie=session-secret-value must not be saved."):
        with pytest.raises(ValueError):
            memory.remember(card(run_id, summary=value, outcome="inconclusive"))


def test_hypothesis_revision_is_concise_and_evidence_backed(tmp_path):
    memory = KnowledgeBase(tmp_path / "metis.sqlite")
    run_id = memory.session.demo()[0]["run_id"]
    recorded = memory.reason(run_id,
                             summary="The prior decoder assumed the wrong alphabet.",
                             evidence="The decoder returned an invalid-input observation.",
                             next_step="Inspect padding and try the supported Base64 decoder.")
    notes = KnowledgeBase(tmp_path / "metis.sqlite").hypotheses(run_id)
    assert notes[0]["id"] == recorded["hypothesis_id"]
    assert notes[0]["status"] == "revised"
    with pytest.raises(ValueError):
        memory.reason(run_id, summary="The result was FLAG_privatevalue",
                      evidence="Observed secret answer material.", next_step="Do not persist this value.")

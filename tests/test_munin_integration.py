"""Split-aware MUNIN transfer and a deterministic retrieval ablation."""
from __future__ import annotations

import codecs
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from metis.core.agent_host import FakeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession
from metis.core.codex_specialist import render_prompt
from metis.core.contracts import ChallengeManifest
from metis.core.ctf_knowledge import KnowledgeBase, TechniqueCard
from metis.core.runtime import ToolRequest


def _manifest(challenge_id: str, title: str, description: str) -> dict:
    return {
        "schema_version": 1,
        "challenge_id": challenge_id,
        "title": title,
        "description": description,
        "categories": ["crypto"],
        "artifacts": [],
        "scope": {"granted_by": "synthetic-munin-test", "challenge_id": challenge_id,
                  "allowed_endpoints": [], "authorized": True},
    }


def _rank_tools(brief: dict) -> list[str]:
    """One fixed policy: retrieved card hints reorder the same baseline candidates."""
    baseline = ["base64_decode", "rot13"]
    hinted: list[str] = []
    for item in brief["prior_knowledge"]:
        card = item["card"]
        text = " ".join((card["title"], card["summary"], card["conditions"])).lower()
        for tool in baseline:
            if tool in text and tool not in hinted:
                hinted.append(tool)
    return hinted + [tool for tool in baseline if tool not in hinted]


def test_munin_transfers_across_fixtures_and_heldout_retrieval_is_abated(tmp_path: Path):
    database = tmp_path / "state" / "metis.sqlite"
    session = CodexSession(database)
    knowledge = KnowledgeBase(database)

    source_text = "Source fixture uses an alphabetic cipher with a separate sentence."
    source_answer = source_text
    source = session.start(
        ChallengeManifest.model_validate(_manifest(
            "munin-source", "Source text exercise", "Decode the ROT13 source string.")),
        commitment=hashlib.sha256(source_answer.encode()).hexdigest(), evaluation_split="practice",
    )
    source_payload = codecs.encode(source_text, "rot_13")
    decoded_source = session.act(source["run_id"], ToolRequest(tool="rot13", data=source_payload))
    assert session.submit(source["run_id"], decoded_source["output"])["verified"]
    knowledge.remember(TechniqueCard(
        title="ROT13 for alphabetic ciphertext",
        category="crypto",
        summary="For readable alphabetic ciphertext, test ROT13 and verify the decoded bytes.",
        conditions="The ciphertext is alphabetic text and the method is a letter rotation.",
        outcome="success", source_run_id=source["run_id"], source_split="practice",
    ))

    trials = [
        "A different paragraph crosses the second fixture boundary.",
        "The later challenge contains its own unrelated sentence.",
        "Transfer should work on another distinct alphabetic message.",
    ]
    action_counts: dict[str, list[int]] = {"retrieval": [], "ablation": []}
    for index, expected in enumerate(trials):
        ciphertext = codecs.encode(expected, "rot_13")
        challenge = ChallengeManifest.model_validate(_manifest(
            f"munin-target-{index}", "Mystery message",
            "Recover the alphabetic ciphertext: " + ciphertext,
        ))
        successful: dict[str, bool] = {}
        for mode in ("retrieval", "ablation"):
            target = session.start(challenge, commitment=hashlib.sha256(expected.encode()).hexdigest(),
                                   evaluation_split="practice")
            scheduler = AgentScheduler(database, FakeHost())
            scheduler.configure(memory_retrieval=(mode == "retrieval"))
            brief = scheduler.brief(target["run_id"], {
                "assignment_id": f"wave-{index}:crypto-specialist",
                "role": "crypto-specialist", "objective": "Inspect the supplied cipher evidence.",
                "deliverable": "Report evidence and a next step.", "max_turns": 4,
                "deadline_seconds": 300,
            }, "attempt")
            prompt = render_prompt(brief, [])
            assert "PRIOR EXPERIENCE" in prompt
            if mode == "retrieval":
                assert brief["prior_knowledge"]
            else:
                assert brief["prior_knowledge"] == []

            tool_order = _rank_tools(brief)
            used_actions = 0
            for tool in tool_order:
                result = session.act(target["run_id"], ToolRequest(tool=tool, data=ciphertext))
                used_actions += 1
                if result["ok"] and result["output"] == expected:
                    successful[mode] = session.submit(target["run_id"], result["output"])["verified"]
                    break
            assert successful.get(mode) is True
            action_counts[mode].append(used_actions)

        assert session.store.read(target["run_id"])[-1].status.value == "solved"

    assert action_counts["retrieval"] == [1, 1, 1]
    assert action_counts["ablation"] == [2, 2, 2]
    assert sum(action_counts["ablation"]) / len(trials) - sum(action_counts["retrieval"]) / len(trials) == 1

    heldout = session.start(
        ChallengeManifest.model_validate(_manifest(
            "munin-heldout", "Held-out message", "Recover the alphabetic ciphertext.")),
        evaluation_split="heldout",
    )
    unlisted = session.start(
        ChallengeManifest.model_validate(_manifest(
            "munin-unlisted", "Unclassified message", "Recover the alphabetic ciphertext.")),
    )
    assert knowledge.search_for_run(heldout["run_id"], "alphabetic ciphertext", category="crypto") == []
    assert knowledge.search_for_run(unlisted["run_id"], "alphabetic ciphertext", category="crypto") == []


def test_search_for_run_redacts_answer_and_credential_terms(tmp_path: Path):
    session = CodexSession(tmp_path / "state" / "metis.sqlite")
    knowledge = KnowledgeBase(session.database)
    context = session.start(
        ChallengeManifest.model_validate(_manifest(
            "munin-redaction", "Alphabetic ciphertext", "Decode a supplied text.")),
        evaluation_split="practice",
    )
    knowledge.remember(TechniqueCard(
        title="Alphabetic ciphertext", category="crypto",
        summary="Check the alphabet before selecting a bounded decoder.",
        conditions="A short text uses a standard encoding.", outcome="inconclusive",
        source_run_id=context["run_id"], source_split="practice",
    ))
    found = knowledge.search_for_run(context["run_id"],
                                     "alphabetic CTF{private-answer} token=private abcdefghijklmnopq"
                                     "rstuvwxyz012345678901234567890123456789012345678901234567890",
                                     category="crypto")
    assert found and "CTF{private-answer}" not in json.dumps(found)


def test_heldout_snapshot_is_fixed_before_work(tmp_path: Path):
    session = CodexSession(tmp_path / "state" / "metis.sqlite")
    knowledge = KnowledgeBase(session.database)
    source = session.start(ChallengeManifest.model_validate(_manifest(
        "snapshot-source", "Alphabetic ciphertext", "Decode a supplied text.")),
        evaluation_split="practice")
    first = knowledge.remember(TechniqueCard(
        title="Alphabetic ciphertext", category="crypto",
        summary="Check the alphabet before selecting a bounded decoder.",
        conditions="A short text uses a standard encoding.", outcome="inconclusive",
        source_run_id=source["run_id"], source_split="practice"))
    heldout = session.start(ChallengeManifest.model_validate(_manifest(
        "snapshot-target", "Held-out ciphertext", "Recover the text.")),
        evaluation_split="heldout")
    run_id = heldout["run_id"]
    assert knowledge.search_for_run(run_id, "alphabetic", category="crypto") == []
    knowledge.freeze_for_heldout(run_id, [first["id"]])
    found = knowledge.search_for_run(run_id, "alphabetic", category="crypto")
    assert [item["id"] for item in found] == [first["id"]]
    with pytest.raises(ValueError, match="already frozen"):
        knowledge.freeze_for_heldout(run_id, [first["id"]])
    second = knowledge.remember(TechniqueCard(
        title="Second alphabetic method", category="crypto",
        summary="Inspect frequency before deciding how to decode the text.",
        conditions="The input is an alphabetic ciphertext.", outcome="inconclusive",
        source_run_id=source["run_id"], source_split="practice"))
    assert second["id"] not in [item["id"] for item in knowledge.search_for_run(
        run_id, "alphabetic", category="crypto")]
    with sqlite3.connect(session.database) as db:
        db.execute("UPDATE heldout_memory_snapshots SET payload=? WHERE run_id=?",
                   ('{"category":"crypto","title":"tampered"}', run_id))
    with pytest.raises(ValueError, match="digest mismatch"):
        knowledge.search_for_run(run_id, "alphabetic", category="crypto")


def test_heldout_snapshot_rejects_worked_or_nonheldout_run(tmp_path: Path):
    session = CodexSession(tmp_path / "state" / "metis.sqlite")
    knowledge = KnowledgeBase(session.database)
    source = session.start(ChallengeManifest.model_validate(_manifest(
        "snapshot-late-source", "Source", "A practice problem.")),
        evaluation_split="practice")
    card = knowledge.remember(TechniqueCard(
        title="Method from practice", category="crypto",
        summary="Test the format using a bounded local decoder.",
        conditions="The input is an encoded text.", outcome="inconclusive",
        source_run_id=source["run_id"], source_split="practice"))
    with pytest.raises(ValueError, match="held-out run"):
        knowledge.freeze_for_heldout(source["run_id"], [card["id"]])
    target = session.start(ChallengeManifest.model_validate(_manifest(
        "snapshot-late-target", "Target", "A held-out problem.")),
        evaluation_split="heldout")
    late = knowledge.remember(TechniqueCard(
        title="Too late method", category="crypto",
        summary="Inspect the alphabet before choosing a bounded decoder.",
        conditions="An encoded message is present.", outcome="inconclusive",
        source_run_id=source["run_id"], source_split="practice"))
    with pytest.raises(ValueError, match="unavailable"):
        knowledge.freeze_for_heldout(target["run_id"], [late["id"]])
    session.act(target["run_id"], ToolRequest(tool="rot13", data="test"))
    with pytest.raises(ValueError, match="precede held-out work"):
        knowledge.freeze_for_heldout(target["run_id"], [card["id"]])


def test_unlisted_source_cannot_be_mislabeled_as_practice_memory(tmp_path: Path):
    session = CodexSession(tmp_path / "state" / "metis.sqlite")
    knowledge = KnowledgeBase(session.database)
    context = session.start(ChallengeManifest.model_validate(
        _manifest("munin-unlisted-source", "Source", "Unclassified source.")))
    with pytest.raises(ValueError, match="unlisted source runs"):
        knowledge.remember(TechniqueCard(
            title="Unlisted method", category="crypto",
            summary="This method was tested on an unclassified source.",
            conditions="A synthetic-looking fixture may be present.", outcome="inconclusive",
            source_run_id=context["run_id"], source_split="practice",
        ))

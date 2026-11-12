import pytest

from metis.core.codex_session import CodexSession
from metis.core.ctf_contest import ContestBoard
from metis.core.runtime import ToolRequest


def test_jeopardy_dispatch_balances_value_and_category_then_unlocks_dependency(tmp_path):
    database = tmp_path / "state" / "metis.sqlite"
    board = ContestBoard(database)
    contest = board.create({"name": "Large Qualifier", "format": "jeopardy", "max_parallel": 2})
    contest_id = contest["contest_id"]
    board.add(contest_id, [
        {"challenge_id": "web-fast", "title": "Fast Web", "category": "web",
         "points": 400, "estimated_minutes": 10, "confidence": 0.8},
        {"challenge_id": "web-slow", "title": "Slow Web", "category": "web",
         "points": 500, "estimated_minutes": 20, "confidence": 0.8},
        {"challenge_id": "crypto", "title": "Crypto", "category": "crypto",
         "points": 300, "estimated_minutes": 20, "confidence": 0.5},
        {"challenge_id": "dependent", "title": "Dependent", "category": "misc",
         "points": 1000, "estimated_minutes": 5, "confidence": 0.9,
         "prerequisites": ["web-fast"]},
    ])
    work = board.dispatch(contest_id)
    assert {item["challenge_id"] for item in work["active"]} == {"web-fast", "crypto"}
    with pytest.raises(ValueError, match="official verified"):
        board.update(contest_id, "web-fast", {"state": "solved"})
    session = CodexSession(database)
    context = session.demo()[0]
    run_id = context["run_id"]
    encoded = context["challenge"]["description"].rsplit(": ", 1)[1]
    answer = session.act(run_id, ToolRequest(tool="base64_decode", data=encoded))["output"]
    assert session.submit(run_id, answer)["verified"]
    board.update(contest_id, "web-fast", {"state": "solved", "official_verified": True,
                                          "run_id": run_id})
    board.update(contest_id, "crypto", {"state": "abandoned"})
    next_work = board.dispatch(contest_id)
    assert {item["challenge_id"] for item in next_work["active"]} == {"dependent", "web-slow"}
    assert ContestBoard(database).board(contest_id)["score"] == 400


def test_attack_defense_prioritizes_service_health_and_patch_validation(tmp_path):
    board = ContestBoard(tmp_path / "metis.sqlite")
    contest_id = board.create({"name": "Finals", "format": "attack-defense",
                               "max_parallel": 2})["contest_id"]
    board.add(contest_id, [
        {"challenge_id": "svc", "title": "Service", "category": "service",
         "points": 1, "estimated_minutes": 60, "confidence": 0.1},
        {"challenge_id": "attack", "title": "Attack", "category": "pwn",
         "points": 500, "estimated_minutes": 10, "confidence": 0.9},
    ])
    board.update(contest_id, "svc", {"service_health": "down"})
    work = board.dispatch(contest_id)
    packets = {item["challenge_id"]: item for item in work["active"]}
    assert packets["svc"]["action"] == "restore_and_verify_service"
    assert packets["svc"]["timebox_minutes"] == 30


def test_jeopardy_rejects_service_state(tmp_path):
    board = ContestBoard(tmp_path / "metis.sqlite")
    contest_id = board.create({"name": "Quals"})["contest_id"]
    board.add(contest_id, [{"challenge_id": "one", "title": "One"}])
    with pytest.raises(ValueError, match="attack-defense"):
        board.update(contest_id, "one", {"service_health": "down"})

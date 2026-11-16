import pytest

from metis.core.codex_session import CodexSession
from metis.core.contracts import ChallengeManifest
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


def test_update_category_and_explicit_errors(tmp_path):
    from metis.core.ctf_contest import ContestBoard
    board = ContestBoard(tmp_path / "metis.sqlite")
    contest_id = board.create({"name": "ksnctf", "format": "jeopardy", "max_parallel": 4})["contest_id"]
    board.add(contest_id, [{"challenge_id": "23", "title": "Villager B"}])
    updated = board.update(contest_id, "23", {"category": "pwn", "estimated_minutes": 90})
    assert updated["category"] == "pwn" and updated["estimated_minutes"] == 90
    with pytest.raises(ValueError, match="unsupported update fields: title"):
        board.update(contest_id, "23", {"title": "x"})
    with pytest.raises(ValueError, match="allowed: abandoned"):
        board.update(contest_id, "23", {"state": "working"})
    with pytest.raises(ValueError):
        board.update(contest_id, "23", {"run_id": "no-such-run"})


def test_sync_links_existing_runs_and_marks_official_solves(tmp_path):
    import json as json_module
    import sqlite3

    from metis.core.codex_session import CodexSession
    from metis.core.contracts import RunStatus
    from metis.core.ctf_contest import ContestBoard
    database = tmp_path / "metis.sqlite"
    session = CodexSession(database)
    board = ContestBoard(database)

    def web_run(challenge_id, solved):
        run_id = session.start(ChallengeManifest.model_validate({
            "challenge_id": f"c{challenge_id}", "title": "t", "description": "d",
            "scope": {"authorized": True, "granted_by": "test", "challenge_id": f"c{challenge_id}"}}))["run_id"]
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE IF NOT EXISTS web_runs (run_id TEXT PRIMARY KEY, config TEXT NOT NULL, "
                       "state TEXT NOT NULL, forms TEXT NOT NULL, links TEXT NOT NULL, salt TEXT NOT NULL, "
                       "paused_until REAL NOT NULL DEFAULT 0)")
            db.execute("INSERT INTO web_runs VALUES (?,?,?,?,?,?,0)", (run_id, json_module.dumps({
                "adapter": "ksnctf", "auth_origin": "https://ksnctf.sweetduet.info",
                "challenge_id": challenge_id}), "{}", "[]", "[]", "00"))
        if solved:
            for state in (RunStatus.EXECUTING, RunStatus.OBSERVING, RunStatus.VERIFYING, RunStatus.SOLVED):
                session._emit(run_id, state)
        return run_id

    solved_run = web_run(2, True)
    open_run = web_run(23, False)
    contest_id = board.create({"name": "ksnctf", "format": "jeopardy", "max_parallel": 4})["contest_id"]
    board.add(contest_id, [{"challenge_id": "2", "title": "Easy Cipher"},
                           {"challenge_id": "23", "title": "Villager B"},
                           {"challenge_id": "41", "title": "Private BBS"}])
    result = board.sync(contest_id, "https://ksnctf.sweetduet.info/problem/1")
    assert result["solved"] == ["2"]
    assert result["linked"] == [{"challenge_id": "23", "run_id": open_run, "status": "planning"}]
    states = {item["challenge_id"]: (item["state"], item["run_id"]) for item in board.board(contest_id)["challenges"]}
    assert states["2"] == ("solved", solved_run) and states["23"][1] == open_run and states["41"][1] is None
    assert board.sync(contest_id, "https://other.example")["solved"] == []


def test_sync_matches_html_page_runs_by_url_and_slug(tmp_path):
    import json as json_module
    import sqlite3

    from metis.core.contracts import RunStatus
    database = tmp_path / "metis.sqlite"
    session = CodexSession(database)
    board = ContestBoard(database)

    def page_run(page_url, solved):
        run_id = session.start(ChallengeManifest.model_validate({
            "challenge_id": "c", "title": "t", "description": "d",
            "scope": {"authorized": True, "granted_by": "test", "challenge_id": "c"}}))["run_id"]
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE IF NOT EXISTS web_runs (run_id TEXT PRIMARY KEY, config TEXT NOT NULL, "
                       "state TEXT NOT NULL, forms TEXT NOT NULL, links TEXT NOT NULL, salt TEXT NOT NULL, "
                       "paused_until REAL NOT NULL DEFAULT 0)")
            db.execute("INSERT INTO web_runs VALUES (?,?,?,?,?,?,0)", (run_id, json_module.dumps({
                "adapter": "html", "auth_origin": "https://alpacahack.com", "challenge_id": None,
                "page_url": page_url}), "{}", "[]", "[]", "00"))
        if solved:
            for state in (RunStatus.EXECUTING, RunStatus.OBSERVING, RunStatus.VERIFYING, RunStatus.SOLVED):
                session._emit(run_id, state)
        return run_id

    by_url = page_run("https://alpacahack.com/daily/challenges/settable-counter/", True)
    by_slug = page_run("https://alpacahack.com/daily/challenges/yell?x=1", False)
    page_run("https://alpacahack.com/", False)
    contest_id = board.create({"name": "daily", "format": "jeopardy", "max_parallel": 4})["contest_id"]
    board.add(contest_id, [
        {"challenge_id": "counter", "title": "settable counter",
         "url": "https://alpacahack.com/daily/challenges/settable-counter"},
        {"challenge_id": "yell", "title": "YELL"},
        {"challenge_id": "unknown", "title": "Unknown"}])
    result = board.sync(contest_id, "https://alpacahack.com/daily")
    assert result["solved"] == ["counter"]
    assert result["linked"] == [{"challenge_id": "yell", "run_id": by_slug, "status": "planning"}]
    states = {item["challenge_id"]: (item["state"], item["run_id"], item["url"])
              for item in board.board(contest_id)["challenges"]}
    assert states["counter"][:2] == ("solved", by_url)
    assert states["yell"][2] == "https://alpacahack.com/daily/challenges/yell?x=1"
    assert states["unknown"][1] is None

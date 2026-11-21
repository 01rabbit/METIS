import base64
import html
import io
import json
import socket
import sqlite3
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from metis.cli import main
from metis.core.ctf_http import HTTPResult, SafeHTTP, clean_url, origin
from metis.core.ctf_knowledge import TechniqueCard
from metis.core.ctf_ksnctf import is_official_problem
from metis.core.ctf_web import WebWorkflow

FLAG = "FLAG_mock_server_correct"


@pytest.fixture
def site(monkeypatch):
    monkeypatch.setattr("urllib.request.getproxies", dict)
    state = {"posts": 0, "rate_limit": False, "bad_rate_body": False, "seen_auth": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def send(self, body, status=200, content_type="text/html", extra=None):
            body = body.encode() if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/v1/challenges":
                if self.headers.get("Authorization") != "Token test-token":
                    return self.send('{"success":false}', 401, "application/json")
                return self.send(json.dumps({"success": True, "data": [{
                    "id": 1, "name": "Mock encoded challenge", "category": "crypto",
                    "value": 500, "solves": 7,
                }]}), content_type="application/json")
            if self.path == "/problem/2":
                return self.send('<title>Mock ksnctf</title><p>Decode a letter substitution.</p>'
                                 '<form id="form"><input id="id" value="2">'
                                 '<input id="flag"></form>'
                                 '<div id="modalCorrect">Correct!</div>'
                                 '<div id="modalWrong">Wrong...</div>')
            if self.path == "/api/v1/challenges/1":
                if self.headers.get("Authorization") != "Token test-token":
                    return self.send('{"success":false}', 401, "application/json")
                return self.send(json.dumps({"success": True, "data": {
                    "name": "Mock encoded challenge", "category": "crypto",
                    "description": "Decode the supplied Base64 distribution file.",
                    "files": ["/files/task.txt"],
                }}), content_type="application/json")
            if self.path == "/files/task.txt":
                return self.send(base64.b64encode(FLAG.encode()), content_type="text/plain")
            if self.path == "/redirect":
                return self.send("", 302, extra={"Location": "/problem"})
            if self.path == "/outside":
                return self.send("", 302, extra={"Location": "http://127.0.0.2:9/private"})
            if self.path == "/huge":
                self.send_response(200)
                self.send_header("Content-Length", "999999999")
                self.end_headers()
                return
            if self.path == "/problem":
                return self.send('<title>Mock form challenge</title><p>Decode the distribution.</p>'
                                 '<a href="/files/task.txt" download>task</a>'
                                 '<form action="/submit" method="post">'
                                 '<input type="hidden" name="csrf" value="csrf-session-123">'
                                 '<input name="answer"><input type="submit" name="send" value="Send">'
                                 '</form>', extra={"Set-Cookie": "session=mock-cookie; HttpOnly; Path=/"})
            return self.send("missing", 404)

        def do_POST(self):
            state["posts"] += 1
            state["seen_auth"].append(self.headers.get("Authorization"))
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if state["rate_limit"]:
                payload = "not-json" if state["bad_rate_body"] else '{"success":true,"data":{"status":"ratelimited"}}'
                return self.send(payload, 429, "application/json", {"Retry-After": "60"})
            if self.path == "/api/submit":
                assert self.headers.get("Content-Type") == "application/json"
                payload = json.loads(body)
                assert set(payload) == {"id", "flag"} and type(payload["id"]) is int
                if state.get("ksnctf_redirect"):
                    return self.send("", 307, extra={"Location": state["ksnctf_redirect"]})
                reply = state.get("ksnctf_body", json.dumps({
                    "result": payload["id"] == 2 and payload["flag"] == FLAG, "update": False,
                    "message": payload["flag"],  # Reflected fields must never become feedback.
                }))
                return self.send(reply, state.get("ksnctf_status", 200),
                                 state.get("ksnctf_content_type", "application/json"))
            if self.path == "/api/v1/challenges/attempt":
                if self.headers.get("Authorization") != "Token test-token":
                    return self.send('{"success":false}', 401, "application/json")
                candidate = json.loads(body)["submission"]
                verdict = "correct" if candidate == FLAG else "incorrect"
                return self.send(json.dumps({"success": True, "data": {"status": verdict,
                                      "message": verdict + " candidate=" + candidate}}), content_type="application/json")
            if self.path == "/submit":
                values = urllib.parse.parse_qs(body.decode())
                if (values.get("csrf") != ["csrf-session-123"]
                        or "session=mock-cookie" not in self.headers.get("Cookie", "")):
                    return self.send("CSRF/authentication failed", 403)
                candidate = values.get("answer", [""])[0]
                verdict = "Correct" if candidate == FLAG else "Incorrect"
                return self.send('<div id="verdict">' + verdict + '</div><pre>' + html.escape(candidate) + '</pre>')
            return self.send("missing", 404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_ctfd_intake_wrong_answer_replan_correct_answer_and_reopen(site, tmp_path, monkeypatch):
    base, state = site
    monkeypatch.setenv("TEST_CTF_TOKEN", "test-token")
    database = tmp_path / "session.sqlite"
    workflow = WebWorkflow(database)
    result = workflow.open(base, adapter="ctfd", challenge_id=1, token_env="TEST_CTF_TOKEN")
    run_id = result["context"]["run_id"]
    assert result["downloaded_files"] == 1
    artifacts = result["context"]["challenge"]["artifacts"]
    name = next(name for name in artifacts if name.endswith("task.txt"))
    encoded = workflow.session.artifact(run_id, name, "text")["result"]["text"]
    wrong = workflow.submit(run_id, "definitely-wrong")
    assert wrong["verdict"] == "incorrect" and not wrong["verified"]
    assert wrong["status"] == "planning"
    with pytest.raises(ValueError, match="identical candidate"):
        workflow.submit(run_id, "definitely-wrong")
    reopened = WebWorkflow(database)
    candidate = base64.b64decode(encoded).decode()
    with pytest.raises(ValueError, match="revised hypothesis"):
        reopened.submit(run_id, candidate)
    reopened.knowledge.reason(run_id, summary="The first guess ignored the stated file encoding.",
                              evidence="The official checker rejected it; the supplied text uses Base64.",
                              next_step="Decode the file using the documented encoding and submit exact text.")
    correct = reopened.submit(run_id, candidate)
    assert correct["verified"] and correct["status"] == "solved"
    assert state["posts"] == 2
    assert FLAG not in reopened.session.store.export_jsonl(run_id)
    assert FLAG not in correct["feedback"]
    assert "test-token" not in json.dumps(reopened.context(run_id))


def test_ctfd_catalog_is_bounded_and_contest_ready(site, tmp_path, monkeypatch):
    base, _ = site
    monkeypatch.setenv("TEST_CTF_TOKEN", "test-token")
    result = WebWorkflow(tmp_path / "session.sqlite").catalog(
        base, token_env="TEST_CTF_TOKEN")
    assert result["count"] == 1
    assert result["credentials_exposed"] is False
    assert result["challenges"][0] == {
        "challenge_id": "1", "title": "Mock encoded challenge", "category": "crypto",
        "points": 500.0, "solves": 7, "estimated_minutes": 30, "confidence": 0.35,
        "url": base, "adapter": "ctfd",
    }


def test_generic_form_refreshes_csrf_keeps_cookies_and_ignores_reflected_marker(site, tmp_path):
    base, _ = site
    workflow = WebWorkflow(tmp_path / "session.sqlite")
    context = workflow.open(base + "/problem")
    run_id = context["context"]["run_id"]
    public = json.dumps(workflow.context(run_id))
    assert "csrf-session-123" not in public and "mock-cookie" not in public
    workflow.configure_form(run_id, form_index=0, flag_field="answer", selector="#verdict",
                            correct_text="Correct", incorrect_text="Incorrect")
    result = workflow.submit(run_id, "Correct")
    assert not result["verified"] and result["verdict"] == "incorrect"
    workflow.knowledge.reason(run_id, summary="A reflected response word is not the recovered answer.",
                              evidence="The official verdict element reported rejection.",
                              next_step="Use the decoded distribution data instead of a response marker.")
    result = WebWorkflow(tmp_path / "session.sqlite").submit(run_id, FLAG)
    assert result["verified"] and result["status"] == "solved"


def test_unknown_form_never_guesses_acceptance(site, tmp_path):
    base, _ = site
    workflow = WebWorkflow(tmp_path / "session.sqlite")
    run_id = workflow.open(base + "/problem")["context"]["run_id"]
    with pytest.raises(ValueError, match="trusted official verdict"):
        workflow.submit(run_id, FLAG)


def test_html_intake_uses_only_declared_supported_category(site, tmp_path):
    from metis.core.ctf_html import Page

    page = Page('<a href="/challenges?q=category%3ARev">Rev</a>'
                '<title>Uses crypto words</title><p>crypto challenge</p>', "https://example.test/")
    assert page.categories == ["rev"]
    unsupported = Page('<a href="/challenges?q=category%3ABlockchain">crypto</a>'
                       '<p>crypto</p>', "https://example.test/")
    assert unsupported.categories == []


def test_alpacahack_html_intake_passes_declared_category_to_manifest(site, tmp_path):
    base, _ = site
    workflow = WebWorkflow(tmp_path / "session.sqlite")
    # Explicit parser fixture is exercised through the same workflow branch with a mock response.
    from metis.core.ctf_http import HTTPResult
    body = (b'<a href="/challenges?q=category%3AWeb">Web</a>'
            b'<title>Call me crypto</title><p>analyzing syscalls</p>')
    response = HTTPResult(url="https://alpacahack.com/challenges/example", status=200,
                          headers={"content-type": "text/html"}, body=body,
                          size=len(body), sha256="0" * 64)
    workflow._client = lambda config, state: type("Client", (), {
        "request": lambda self, *args, **kwargs: response,
        "export_state": lambda self: {"cookies": {}},
        "auth_generation": 0,
    })()
    result = workflow.open(base + "/problem")
    assert result["context"]["challenge"]["categories"] == ["web"]


def test_browser_plan_surfaces_spawn_submit_forms_and_commands(tmp_path):
    from metis.core.ctf_http import HTTPResult

    workflow = WebWorkflow(tmp_path / "session.sqlite")
    page_url = "https://alpacahack.com/daily-bside/challenges/wimp"
    body = (b'<title>what is my pointer 3</title><p>malloc</p>'
            b'<form action="/challenges/wimp/request-instance" method="post">'
            b'<input type="hidden" name="programCanonical" value="wimp"></form>'
            b'<form action="/challenges/wimp/submit-flag" method="post">'
            b'<input type="hidden" name="programCanonical" value="wimp">'
            b'<input name="flag" type="text"></form>')
    response = HTTPResult(url=page_url, status=200, headers={"content-type": "text/html"},
                          body=body, size=len(body), sha256="0" * 64)
    workflow._client = lambda config, state: type("Client", (), {
        "request": lambda self, *args, **kwargs: response,
        "export_state": lambda self: {"cookies": {}},
        "auth_generation": 0,
    })()
    run_id = workflow.open(page_url)["context"]["run_id"]

    plan = WebWorkflow(tmp_path / "session.sqlite").browser_plan(run_id)
    assert plan["submission_mode"] == "browser"
    assert plan["page_url"] == page_url
    assert plan["spawn_form"]["action"].endswith("/request-instance")
    assert plan["submit_form"]["action"].endswith("/submit-flag")
    assert plan["flag_field"] == "flag"
    assert plan["submission_state"] == {
        "pending": False, "remaining": 10, "verdicts": [], "cooldown_active": False}
    joined = " ".join(plan["next_commands"])
    assert "prepare-browser" in joined and "attest" in joined and run_id in joined
    # Read-only: the plan must not reserve a submission or change verdict state.
    assert WebWorkflow(tmp_path / "session.sqlite").context(run_id)["web"]["verdicts"] == []


def test_browser_plan_points_api_runs_at_submit(site, tmp_path, monkeypatch):
    base, _ = site
    monkeypatch.setenv("TEST_CTF_TOKEN", "test-token")
    workflow = WebWorkflow(tmp_path / "session.sqlite")
    run_id = workflow.open(base, adapter="ctfd", challenge_id=1,
                           token_env="TEST_CTF_TOKEN")["context"]["run_id"]
    plan = workflow.browser_plan(run_id)
    assert plan["submission_mode"] == "api"
    assert plan["next_commands"] == []
    assert "metis web submit" in plan["guidance"]


@pytest.mark.parametrize("alpacahack", [False, True])
def test_generic_html_and_ambiguous_alpacahack_links_do_not_claim_category(site, tmp_path,
                                                                            alpacahack):
    from metis.core.ctf_http import HTTPResult

    base, _ = site
    workflow = WebWorkflow(tmp_path / "session.sqlite")
    body = (b'<a href="/challenges?q=category%3AWeb">Web</a>'
            b'<a href="/challenges?q=category%3ACrypto">Crypto</a>')
    response_url = "https://alpacahack.com/challenges/example" if alpacahack else base + "/problem"
    response = HTTPResult(url=response_url, status=200,
                          headers={"content-type": "text/html"}, body=body,
                          size=len(body), sha256="0" * 64)
    workflow._client = lambda config, state: type("Client", (), {
        "request": lambda self, *args, **kwargs: response,
        "export_state": lambda self: {"cookies": {}},
        "auth_generation": 0,
    })()
    result = workflow.open(base + "/problem")
    assert result["context"]["challenge"]["categories"] == []


def test_network_scope_redirects_and_download_limits(site):
    base, _ = site
    client = SafeHTTP([base], auth_origin=base)
    assert client.request(base + "/redirect").status == 200
    assert client.export_state()["cookies"]
    with pytest.raises(ValueError, match="outside"):
        client.request(base + "/outside")
    with pytest.raises(ValueError, match="outside"):
        client.request("http://127.0.0.2:9/unrelated")
    with pytest.raises(ValueError, match="limit"):
        client.request(base + "/huge", max_bytes=100)


def test_dns_rebinding_is_denied_without_connecting(monkeypatch):
    client = SafeHTTP(["https://ctf.example"], auth_origin="https://ctf.example")
    current = ["1.1.1.1"]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (current[0], 443)),
    ])
    assert client._addresses("https://ctf.example/") == ["1.1.1.1"]
    current[0] = "8.8.8.8"
    with pytest.raises(ValueError, match="DNS changed"):
        client._addresses("https://ctf.example/")
    private = SafeHTTP(["https://other.example"], auth_origin="https://other.example")
    current[0] = "127.0.0.1"
    with pytest.raises(ValueError, match="private address"):
        private._addresses("https://other.example/")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://user:secret@example.com/", "http://example.com/\r\nInjected:yes"])
def test_url_validation(url):
    with pytest.raises(ValueError):
        clean_url(url)
    assert origin("https://EXAMPLE.com:443/path?secret=1") == "https://example.com"


def test_rate_limit_persists_across_processes(site, tmp_path, monkeypatch):
    base, state = site
    monkeypatch.setenv("TEST_CTF_TOKEN", "test-token")
    path = tmp_path / "session.sqlite"
    workflow = WebWorkflow(path)
    run_id = workflow.open(base, adapter="ctfd", challenge_id=1, token_env="TEST_CTF_TOKEN")["context"]["run_id"]
    state["rate_limit"] = True
    result = workflow.submit(run_id, "new-candidate")
    assert result["verdict"] == "ratelimited"
    with pytest.raises(ValueError, match="cooldown"):
        WebWorkflow(path).submit(run_id, "another-candidate")


def test_ksnctf_replan_solve_reopen_and_learn_without_storing_candidate(site, tmp_path):
    base, state = site
    database = tmp_path / "session.sqlite"
    workflow = WebWorkflow(database)
    opened = workflow.open(base + "/problem/2", adapter="ksnctf")
    run_id = opened["context"]["run_id"]
    assert opened["web"]["challenge_id"] == 2
    assert opened["web"]["verification_configured"]
    assert not workflow.submit(run_id, "wrong-answer")["verified"]
    reopened = WebWorkflow(database)
    with pytest.raises(ValueError, match="identical candidate"):
        reopened.submit(run_id, "wrong-answer")
    with pytest.raises(ValueError, match="revised hypothesis"):
        reopened.submit(run_id, FLAG)
    reopened.knowledge.reason(run_id, summary="The output formatting needed a separator.",
                              evidence="The official JSON result explicitly rejected the first answer.",
                              next_step="Apply the separator instruction before another submission.")
    solved = reopened.submit(run_id, FLAG)
    assert solved["verified"] and solved["verdict"] == "correct" and solved["status"] == "solved"
    assert state["posts"] == 2
    assert WebWorkflow(database).context(run_id)["web"]["verdicts"] == ["incorrect", "correct"]
    assert FLAG not in json.dumps(solved) + reopened.session.store.export_jsonl(run_id)
    assert FLAG.encode() not in database.read_bytes()
    stored = reopened.knowledge.remember(TechniqueCard(
        title="Decode a letter substitution and apply explicit output formatting",
        category="crypto", summary="Decode the substitution then follow the separator instruction.",
        conditions="A readable decoded statement specifies additional formatting.",
        outcome="success", source_run_id=run_id, source_split="practice",
    ))
    assert stored["stored"]
    assert FLAG not in json.dumps(reopened.knowledge.search("substitution"))
    with pytest.raises(ValueError, match="not awaiting a decision"):
        reopened.submit(run_id, "another-answer")
    assert state["posts"] == 2


@pytest.mark.parametrize("body,status,content_type,verdict", [
    ('{"result":"true"}', 200, "application/json", "unknown"),
    ('{"result":1}', 200, "application/json", "unknown"),
    ('{"result":null}', 200, "application/json", "unknown"),
    ('{"success":true}', 200, "application/json", "unknown"),
    ('true', 200, "application/json", "unknown"),
    ('[]', 200, "application/json", "unknown"),
    ('not-json', 200, "application/json", "unknown"),
    ('<div id="modalCorrect">Correct!</div>', 200, "text/html", "unknown"),
    ('{"result":true}', 200, "text/html", "unknown"),
    ('{"result":true}', 500, "application/json", "unknown"),
    ('{"result":true}', 401, "application/json", "authentication_required"),
    ('{"result":true}', 403, "application/json", "authentication_required"),
    ('{"result":true}', 201, "application/json", "unknown"),
    ('{"result":false}', 200, "application/json", "incorrect"),
    ('{"result":true,"update":false}', 200, "application/json; charset=utf-8", "correct"),
])
def test_ksnctf_only_accepts_official_boolean_json(site, tmp_path, body, status, content_type, verdict):
    base, state = site
    workflow = WebWorkflow(tmp_path / "session.sqlite")
    run_id = workflow.open(base + "/problem/2", adapter="ksnctf")["context"]["run_id"]
    state.update(ksnctf_body=body, ksnctf_status=status, ksnctf_content_type=content_type)
    result = workflow.submit(run_id, FLAG)
    assert result["verdict"] == verdict
    assert result["verified"] is (verdict == "correct")
    assert state["posts"] == 1


@pytest.mark.parametrize("destination", ["/api/submit", "http://127.0.0.2:9/private"])
def test_ksnctf_does_not_follow_or_replay_submission_redirects(site, tmp_path, destination):
    base, state = site
    workflow = WebWorkflow(tmp_path / "session.sqlite")
    run_id = workflow.open(base + "/problem/2", adapter="ksnctf")["context"]["run_id"]
    state["ksnctf_redirect"] = destination
    result = workflow.submit(run_id, FLAG)
    assert result["verdict"] == "unknown" and not result["verified"]
    assert state["posts"] == 1


def test_ksnctf_rate_limit_persists_and_oversized_response_fails_closed(site, tmp_path):
    base, state = site
    database = tmp_path / "session.sqlite"
    workflow = WebWorkflow(database)
    run_id = workflow.open(base + "/problem/2", adapter="ksnctf")["context"]["run_id"]
    state.update(rate_limit=True, bad_rate_body=True)
    assert workflow.submit(run_id, FLAG)["verdict"] == "ratelimited"
    with pytest.raises(ValueError, match="cooldown"):
        WebWorkflow(database).submit(run_id, FLAG)
    assert state["posts"] == 1
    state.update(rate_limit=False, ksnctf_body='{"result":true,"padding":"' + 'x' * 16384 + '"}')
    second = workflow.open(base + "/problem/2", adapter="ksnctf")["context"]["run_id"]
    assert workflow.submit(second, FLAG)["verdict"] == "unknown"


def test_ksnctf_unknown_transport_can_retry_same_candidate(site, tmp_path):
    base, state = site
    database = tmp_path / "session.sqlite"
    workflow = WebWorkflow(database)
    run_id = workflow.open(base + "/problem/2", adapter="ksnctf")["context"]["run_id"]
    state.update(ksnctf_body="not-json")
    first = workflow.submit(run_id, FLAG)
    assert first["verdict"] == "unknown" and not first["verified"]
    state.update(ksnctf_body=json.dumps({"result": True, "update": False}))
    second = WebWorkflow(database).submit(run_id, FLAG)
    assert second["verified"] and second["status"] == "solved"
    assert state["posts"] == 2


def test_generic_unknown_verdict_does_not_replay_same_candidate(site, tmp_path):
    base, _ = site
    workflow = WebWorkflow(tmp_path / "session.sqlite")
    run_id = workflow.open(base + "/problem")["context"]["run_id"]
    workflow.configure_form(run_id, form_index=0, flag_field="answer", selector="#missing",
                            correct_text="Correct", incorrect_text="Incorrect")
    assert workflow.submit(run_id, FLAG)["verdict"] == "unknown"
    with pytest.raises(ValueError, match="identical candidate"):
        workflow.submit(run_id, FLAG)


@pytest.mark.parametrize("path,challenge_id", [
    ("/", None), ("/problem/0", None), ("/problem/1000001", None),
    ("/problem/2?other=3", None), ("/problem/2", 3),
])
def test_ksnctf_rejects_ambiguous_identity_before_network(site, tmp_path, monkeypatch, path, challenge_id):
    base, _ = site
    workflow = WebWorkflow(tmp_path / "session.sqlite")
    def unexpected_request(*args, **kwargs):
        pytest.fail("invalid identity must fail before HTTP")
    monkeypatch.setattr(SafeHTTP, "request", unexpected_request)
    with pytest.raises(ValueError, match="ksnctf"):
        workflow.open(base + path, adapter="ksnctf", challenge_id=challenge_id)


def test_ksnctf_cli_auto_detection_and_stdin_submission(tmp_path, monkeypatch, capsys):
    official = "https://ksnctf.sweetduet.info"
    posts = []
    def request(self, url, **kwargs):
        if kwargs.get("method") == "POST":
            assert url == official + "/api/submit"
            assert json.loads(kwargs["body"]) == {"id": 2, "flag": FLAG}
            posts.append(url)
            body = b'{"result":true,"update":false}'
            content_type = "application/json"
        else:
            assert url == official + "/problem/2"
            body, content_type = b'<title>Mock ksnctf</title>', "text/html"
        return HTTPResult(url, 200, {"content-type": content_type}, body, len(body), "0" * 64)
    monkeypatch.setattr(SafeHTTP, "request", request)
    args = ["metis", "web", "--database", str(tmp_path / "session.sqlite")]
    monkeypatch.setattr(sys, "argv", [*args, "open", official + "/problem/2"])
    assert main() == 0
    opened = json.loads(capsys.readouterr().out)
    assert opened["web"]["adapter"] == "ksnctf"
    assert opened["web"]["challenge_id"] == 2
    monkeypatch.setattr(sys, "argv", [*args, "submit", opened["context"]["run_id"]])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(FLAG.encode())))
    assert main() == 0
    output = capsys.readouterr().out
    assert json.loads(output)["verified"] is True and FLAG not in output
    assert len(posts) == 1


@pytest.mark.parametrize("url", [
    "http://ksnctf.sweetduet.info/problem/2",
    "https://ksnctf.sweetduet.info.evil.example/problem/2",
    "https://other.example/problem/2",
    "https://ksnctf.sweetduet.info/",
    "https://ksnctf.sweetduet.info/problem/2?other=3",
])
def test_ksnctf_auto_detection_is_limited_to_official_problem_urls(url):
    assert not is_official_problem(url)


def test_ksnctf_submission_limit_and_cancel_prevent_further_posts(site, tmp_path):
    base, state = site
    database = tmp_path / "session.sqlite"
    workflow = WebWorkflow(database)
    run_id = workflow.open(base + "/problem/2", adapter="ksnctf")["context"]["run_id"]
    for index in range(10):
        if index:
            workflow.knowledge.reason(
                run_id, summary="The prior formatting hypothesis was rejected.",
                evidence="The official JSON verdict was negative.",
                next_step="Test a materially revised synthetic candidate.",
            )
        assert workflow.submit(run_id, f"synthetic-guess-{index}")["verdict"] == "incorrect"
    with pytest.raises(ValueError, match="submission limit"):
        WebWorkflow(database).submit(run_id, FLAG)
    assert state["posts"] == 10
    second = workflow.open(base + "/problem/2", adapter="ksnctf")["context"]["run_id"]
    workflow.session.cancel(second)
    with pytest.raises(ValueError, match="not awaiting a decision"):
        workflow.submit(second, FLAG)
    third = workflow.open(base + "/problem/2", adapter="ksnctf")["context"]["run_id"]
    with sqlite3.connect(database) as db:
        db.execute("UPDATE codex_sessions SET max_actions=0 WHERE run_id=?", (third,))
    with pytest.raises(ValueError, match="budget exhausted"):
        workflow.submit(third, FLAG)
    assert state["posts"] == 10


def test_distribution_detection_covers_ksnctf_problem_files():
    from metis.core.ctf_web import is_distribution
    page = "https://ksnctf.sweetduet.info/problem/23"

    def link(url):
        return {"url": url, "text": "", "download": False}
    assert is_distribution(link("https://ksnctf.sweetduet.info/q/23/villager"), page, "ksnctf", 23)
    assert is_distribution(link("https://ksnctf.sweetduet.info/q/23/libc.so.6"), page, "ksnctf", 23)
    assert is_distribution(link("https://ksnctf.sweetduet.info/q/15/Jewel.apk"), page, "html", None)
    assert not is_distribution(link("https://ksnctf.sweetduet.info/q/31/kangacha.php"), page, "ksnctf", 31)
    assert not is_distribution(link("https://ksnctf.sweetduet.info/q/4/villager"), page, "ksnctf", 23)
    assert not is_distribution(link("https://ksnctf.sweetduet.info/problem/4"), page, "ksnctf", 23)
    assert is_distribution(link("https://cdn.example/x/libc.so.6"), page, "html", None)


def test_parallel_submissions_are_serialized_and_pending_sends_are_kept(site, tmp_path, monkeypatch):
    base, state = site
    monkeypatch.setenv("TEST_CTF_TOKEN", "test-token")
    database = tmp_path / "session.sqlite"
    run_id = WebWorkflow(database).open(base, adapter="ctfd", challenge_id=1,
                                        token_env="TEST_CTF_TOKEN")["context"]["run_id"]
    outcomes = []

    def submit(candidate):
        try:
            outcomes.append(WebWorkflow(database).submit(run_id, candidate)["verdict"])
        except ValueError as exc:
            outcomes.append(str(exc))

    threads = [threading.Thread(target=submit, args=(f"wrong-{index}",)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert state["posts"] == 1 and outcomes.count("incorrect") == 1
    assert sum("revised hypothesis" in item for item in outcomes) == 3
    workflow = WebWorkflow(database)
    workflow.knowledge.reason(run_id, summary="The guesses ignored the supplied file encoding.",
                              evidence="The official checker rejected the first attempt.",
                              next_step="Decode the distribution file before the next submission.")
    with sqlite3.connect(database) as db:  # a send interrupted mid-request
        db.execute("INSERT INTO web_attempts(run_id,digest,verdict,created) VALUES (?,?,?,?)",
                   (run_id, "ab" * 32, "pending", __import__("time").time()))
    with pytest.raises(ValueError, match="in flight"):
        workflow.submit(run_id, FLAG)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE web_attempts SET created=created-600 WHERE verdict='pending'")
    assert workflow.submit(run_id, FLAG)["verified"]
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT verdict FROM web_attempts WHERE digest=?", ("ab" * 32,)).fetchone()[0] == "unknown"


def test_browser_reservation_survives_restart_and_binds_candidate(site, tmp_path):
    base, state = site
    database = tmp_path / "browser.sqlite"
    workflow = WebWorkflow(database)
    run_id = workflow.open(base + "/problem")["context"]["run_id"]
    assert workflow.prepare_browser(run_id, "private-candidate")["may_send_once"]
    reopened = WebWorkflow(database)
    for candidate in ("private-candidate", "other-candidate"):
        with pytest.raises(ValueError, match="pending browser"):
            reopened.prepare_browser(run_id, candidate)
    with pytest.raises(ValueError, match="different candidate"):
        reopened.attest(run_id, "other-candidate", verdict="correct", evidence="Official UI showed Correct")
    result = reopened.attest(run_id, "private-candidate", verdict="correct", evidence="Official UI showed Correct")
    assert result["verified"]
    retried = WebWorkflow(database).attest(
        run_id, "private-candidate", verdict="correct", evidence="Official UI showed Correct")
    assert retried["verified"] and retried["idempotent_retry"]
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT attempts,verdict FROM web_attempts").fetchall() == [(1, "correct")]
    assert state["posts"] == 0
    assert "private-candidate" not in reopened.session.store.export_jsonl(run_id)


def test_browser_verdict_requires_reservation_and_recovers_terminal_event_crash(site, tmp_path, monkeypatch):
    from metis.core.contracts import RunStatus

    base, _ = site
    database = tmp_path / "browser.sqlite"
    workflow = WebWorkflow(database)
    run_id = workflow.open(base + "/problem")["context"]["run_id"]
    with pytest.raises(ValueError, match="prepare this exact browser submission"):
        workflow.attest(run_id, "candidate", verdict="correct", evidence="Official UI showed Correct")

    workflow.prepare_browser(run_id, "candidate")
    original_emit = workflow.session._emit

    def crash_before_terminal(run, status, **detail):
        if status == RunStatus.SOLVED:
            raise RuntimeError("simulated process interruption")
        original_emit(run, status, **detail)

    monkeypatch.setattr(workflow.session, "_emit", crash_before_terminal)
    with pytest.raises(RuntimeError, match="simulated process interruption"):
        workflow.attest(run_id, "candidate", verdict="correct", evidence="Official UI showed Correct")
    assert workflow.session.context(run_id)["status"] == RunStatus.VERIFYING.value

    recovered = WebWorkflow(database).attest(
        run_id, "candidate", verdict="correct", evidence="Official UI showed Correct")
    assert recovered["verified"] and recovered["idempotent_retry"]
    assert recovered["status"] == RunStatus.SOLVED.value
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT attempts,verdict FROM web_attempts").fetchall() == [(1, "correct")]


def test_browser_reservation_requires_revision_and_honors_cap(site, tmp_path):
    base, _ = site
    workflow = WebWorkflow(tmp_path / "browser.sqlite")
    run_id = workflow.open(base + "/problem")["context"]["run_id"]
    with sqlite3.connect(workflow.database) as db:
        row = db.execute("SELECT config FROM web_runs WHERE run_id=?", (run_id,)).fetchone()
        config = json.loads(row[0])
        config["max_submissions"] = 1
        db.execute("UPDATE web_runs SET config=? WHERE run_id=?", (json.dumps(config), run_id))
    workflow.prepare_browser(run_id, "first-candidate")
    workflow.attest(run_id, "first-candidate", verdict="incorrect", evidence="Official UI showed Incorrect")
    with pytest.raises(ValueError, match="submission limit"):
        workflow.prepare_browser(run_id, "second-candidate")
    with pytest.raises(ValueError, match="identical candidate"):
        workflow.prepare_browser(run_id, "first-candidate")


class _FakeCTFd:
    """Port-free CTFd stand-in that replaces SafeHTTP.request."""

    BASE = "http://ctfd.test"

    def __init__(self):
        self.calls = []
        self.attempt = {"success": True, "data": {"status": "incorrect", "message": "no"}}
        self.files = ["/files/abc/x.zip"]
        self.file_redirect = None
        self.challenge_body = None
        self.nonce_page = "<script>var init = {'csrfNonce': \"nonce-0123456789abcdef\"};</script>"

    def result(self, url, body, status=200):
        data = body if isinstance(body, bytes) else body.encode()
        return HTTPResult(url, status, {}, data, len(data), "0" * 64)

    def request(self, url, *, method="GET", body=None, headers=None, sink=None, **_):
        from metis.core.ctf_http import OutOfScopeRedirect
        self.calls.append((method, url, dict(headers or {})))
        path = url[len(self.BASE):]
        if path == "/api/v1/challenges/1":
            if self.challenge_body is not None:
                return self.result(url, self.challenge_body)
            return self.result(url, json.dumps({"success": True, "data": {
                "name": "c", "category": "misc", "description": "d", "files": self.files}}))
        if path == "/api/v1/challenges":
            return self.result(url, self.challenge_body or "{}")
        if path == "/challenges":
            return self.result(url, self.nonce_page)
        if path.startswith("/files/"):
            if self.file_redirect:
                raise OutOfScopeRedirect(self.file_redirect)
            sink.write(b"zipdata")
            return self.result(url, b"")
        if path == "/api/v1/challenges/attempt":
            return self.result(url, json.dumps(self.attempt))
        return self.result(url, "missing", 404)


@pytest.fixture
def fake_ctfd(monkeypatch):
    fake = _FakeCTFd()
    monkeypatch.setattr(SafeHTTP, "request", lambda self, url, **kw: fake.request(url, **kw))
    monkeypatch.setenv("TEST_CTF_TOKEN", "test-token")
    monkeypatch.setenv("TEST_CTF_COOKIE", "session=abc123")
    return fake


def test_ctfd_file_redirect_to_other_origin_is_skipped_with_allow_origin_hint(fake_ctfd, tmp_path):
    fake_ctfd.file_redirect = "https://cdn.example.net"
    result = WebWorkflow(tmp_path / "s.sqlite").open(
        fake_ctfd.BASE, adapter="ctfd", challenge_id=1, token_env="TEST_CTF_TOKEN")
    assert result["context"]["run_id"] and result["downloaded_files"] == 0
    skipped = result["skipped_files"]
    assert len(skipped) == 1 and "https://cdn.example.net" in skipped[0]["reason"]
    assert "--allow-origin https://cdn.example.net" in skipped[0]["next"]
    assert not any(url.startswith("https://cdn") for _, url, _ in fake_ctfd.calls)


def test_safehttp_out_of_scope_redirect_is_never_followed(monkeypatch):
    from metis.core.ctf_http import OutOfScopeRedirect

    class Redirect:
        status = 302
        headers = {"Location": "https://cdn.example.net/x?sig=secret"}  # noqa: RUF012

        def close(self):
            pass

    opened = []
    client = SafeHTTP(["http://127.0.0.1:9"], auth_origin="http://127.0.0.1:9")
    monkeypatch.setattr(client, "_open", lambda url, *a: opened.append(url) or (Redirect(), None))
    with pytest.raises(OutOfScopeRedirect) as caught:
        client.request("http://127.0.0.1:9/files/a/x.zip")
    assert caught.value.destination_origin == "https://cdn.example.net"
    assert "sig=secret" not in str(caught.value) and len(opened) == 1


def test_ctfd_login_html_is_reported_as_authentication_required(fake_ctfd, tmp_path):
    fake_ctfd.challenge_body = "<html><title>Login</title></html>"
    workflow = WebWorkflow(tmp_path / "s.sqlite")
    with pytest.raises(ValueError, match="authentication required"):
        workflow.catalog(fake_ctfd.BASE, cookie_env="TEST_CTF_COOKIE")
    with pytest.raises(ValueError, match="authentication required"):
        workflow.open(fake_ctfd.BASE, adapter="ctfd", challenge_id=1, cookie_env="TEST_CTF_COOKIE")


def _ctfd_run(fake, directory, **auth):
    workflow = WebWorkflow(directory / "s.sqlite")
    run_id = workflow.open(fake.BASE, adapter="ctfd", challenge_id=1, download=False, **auth)["context"]["run_id"]
    return workflow, run_id


def test_ctfd_paused_is_retryable_and_partial_is_recorded_not_solved(fake_ctfd, tmp_path):
    workflow, run_id = _ctfd_run(fake_ctfd, tmp_path, token_env="TEST_CTF_TOKEN")
    fake_ctfd.attempt = {"success": True, "data": {"status": "paused", "message": "paused"}}
    first = workflow.submit(run_id, "cand-one")
    assert first["verdict"] == "paused" and not first["verified"]
    fake_ctfd.attempt = {"success": True, "data": {"status": "partial", "message": "half"}}
    again = workflow.submit(run_id, "cand-one")  # paused did not burn the candidate
    assert again["verdict"] == "partial" and not again["verified"]
    with sqlite3.connect(tmp_path / "s.sqlite") as db:
        stored = db.execute("SELECT verdict FROM web_attempts WHERE run_id=?", (run_id,)).fetchall()
    assert stored == [("partial",)]
    with pytest.raises(ValueError, match="identical candidate"):
        workflow.submit(run_id, "cand-one")


def test_ctfd_cookie_submit_sends_csrf_nonce_and_token_auth_does_not(fake_ctfd, tmp_path):
    workflow, run_id = _ctfd_run(fake_ctfd, tmp_path, cookie_env="TEST_CTF_COOKIE")
    workflow.submit(run_id, "cookie-cand")
    post = next(call for call in fake_ctfd.calls if call[1].endswith("/attempt"))
    assert post[2]["CSRF-Token"] == "nonce-0123456789abcdef"
    token_dir = tmp_path / "token"
    token_dir.mkdir()
    workflow2, run2 = _ctfd_run(fake_ctfd, token_dir, token_env="TEST_CTF_TOKEN")
    fake_ctfd.calls.clear()
    workflow2.submit(run2, "token-cand")
    assert not any(url.endswith("/challenges") for _, url, _ in fake_ctfd.calls)
    post = next(call for call in fake_ctfd.calls if call[1].endswith("/attempt"))
    assert "CSRF-Token" not in post[2]


def test_ctfd_cookie_submit_without_nonce_fails_clearly_before_sending(fake_ctfd, tmp_path):
    fake_ctfd.nonce_page = "<html>please log in</html>"
    workflow, run_id = _ctfd_run(fake_ctfd, tmp_path, cookie_env="TEST_CTF_COOKIE")
    with pytest.raises(ValueError, match="csrfNonce not found"):
        workflow.submit(run_id, "cookie-cand")
    assert not any(url.endswith("/attempt") for _, url, _ in fake_ctfd.calls)

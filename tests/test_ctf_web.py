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

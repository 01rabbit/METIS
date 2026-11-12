import base64
import html
import json
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from metis.core.ctf_http import SafeHTTP, clean_url, origin
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

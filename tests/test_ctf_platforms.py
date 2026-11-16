import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from metis.cli import main
from metis.core.ctf_rctf import verdict
from metis.core.ctf_web import WebWorkflow

FLAG = "flag{rctf_mock_correct}"
AUTH = "Bearer rctf-auth-token"


@pytest.fixture
def rctf(monkeypatch):
    monkeypatch.setattr("urllib.request.getproxies", dict)
    state = {"posts": 0, "limit": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def send(self, payload, status=200, content_type="application/json"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/v1/challs":
                if self.headers.get("Authorization") != AUTH:
                    return self.send({"kind": "badToken", "message": "bad token"}, 401)
                return self.send({"kind": "goodChallenges", "message": "ok", "data": [
                    {"id": "baby-rsa", "name": "Baby RSA", "category": "crypto", "author": "mock",
                     "description": "<p>Small <b>e</b>.</p>", "points": 120, "solves": 30,
                     "files": [{"name": "out.txt", "url": "/uploads/out.txt"}]},
                    {"id": "warmup", "name": "Warmup", "category": "misc", "description": "nc",
                     "points": 50, "solves": 100, "files": []}]})
            if self.path == "/uploads/out.txt":
                return self.send(b"n = 77\ne = 3\nc = 8\n", content_type="text/plain")
            if self.path == "/spa":
                return self.send(b"<title>SPA</title><div id=app></div><script src=app.js></script>",
                                 content_type="text/html")
            return self.send({"kind": "badEndpoint"}, 404)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/api/v1/auth/login":
                if body.get("teamToken") == "team-token":
                    return self.send({"kind": "goodLogin", "data": {"authToken": "rctf-auth-token"}})
                return self.send({"kind": "badTokenVerification"}, 401)
            if self.path == "/api/v1/challs/baby-rsa/submit":
                state["posts"] += 1
                if self.headers.get("Authorization") != AUTH:
                    return self.send({"kind": "badToken"}, 401)
                if state["limit"]:
                    return self.send({"kind": "badRateLimit", "data": {"timeLeft": 30000}}, 429)
                if body.get("flag") == FLAG:
                    return self.send({"kind": "goodFlag", "message": "The flag is correct."})
                return self.send({"kind": "badFlag", "message": "The flag was incorrect."}, 400)
            return self.send({"kind": "badEndpoint"}, 404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", state
    server.shutdown()
    thread.join()


def test_rctf_login_catalog_open_submit_cycle(rctf, tmp_path):
    base, _ = rctf
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    with pytest.raises(ValueError):
        workflow.rctf_login(base, "wrong")
    stored = workflow.rctf_login(base, "team-token")
    assert stored["credential_stored"] is True and "rctf-auth-token" not in json.dumps(stored)

    catalog = workflow.catalog(base, adapter="rctf")
    assert catalog["count"] == 2
    assert catalog["challenges"][0]["challenge_id"] == "baby-rsa"

    opened = workflow.open(base + "/challs", adapter="rctf", challenge_id="baby-rsa")
    assert opened["downloaded_files"] == 1
    assert opened["context"]["challenge"]["categories"] == ["crypto"]
    assert "Small" in opened["context"]["challenge"]["description"]
    run_id = opened["context"]["run_id"]
    assert opened["web"]["verification_configured"] is True

    wrong = workflow.submit(run_id, "flag{nope}")
    assert wrong["verdict"] == "incorrect" and wrong["verified"] is False
    workflow.knowledge.reason(run_id, summary="Cube root attack", evidence="e is three",
                              next_step="take integer cube root", status="revised")
    right = workflow.submit(run_id, FLAG)
    assert right["verdict"] == "correct" and right["status"] == "solved"
    assert FLAG not in json.dumps(right)


def test_rctf_rate_limit_uses_time_left(rctf, tmp_path):
    base, state = rctf
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    workflow.auth(base, kind="token", value="rctf-auth-token", scheme="Bearer")
    run_id = workflow.open(base, adapter="rctf", challenge_id="baby-rsa")["context"]["run_id"]
    state["limit"] = True
    limited = workflow.submit(run_id, "flag{first}")
    assert limited["verdict"] == "ratelimited"
    paused = workflow.context(run_id)["web"]["paused_until"]
    with pytest.raises(ValueError, match="cooldown"):
        workflow.submit(run_id, "flag{first}")
    assert paused > 0


def test_rctf_unknown_id_and_bad_ids(rctf, tmp_path):
    base, _ = rctf
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    workflow.auth(base, kind="token", value="rctf-auth-token", scheme="Bearer")
    with pytest.raises(ValueError, match="not found"):
        workflow.open(base, adapter="rctf", challenge_id="missing")
    with pytest.raises(ValueError):
        workflow.open(base, adapter="rctf", challenge_id="../x")
    with pytest.raises(ValueError):
        workflow.open(base, adapter="rctf")


@pytest.mark.parametrize("payload,expected", [
    ({"kind": "goodFlag"}, "correct"), ({"kind": "badFlag"}, "incorrect"),
    ({"kind": "badAlreadySolvedChallenge"}, "already_solved"), ({"kind": "weird"}, "unknown"),
    ({"result": True}, "unknown"), ([], "unknown"),
])
def test_rctf_verdict_contract(payload, expected):
    assert verdict(payload)[0] == expected


def test_render_uses_scoped_renderer_output(rctf, tmp_path):
    base, _ = rctf
    calls = {}

    def fake_renderer(url, allowed, *, cookies):
        calls.update(url=url, allowed=allowed)
        return url, ('<title>Rendered</title><p>Built by JS</p>'
                     '<a href="/uploads/out.txt" download>file</a>'), ["https://cdn.example"]

    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    opened = workflow.open(base + "/spa", render=True, renderer=fake_renderer)
    assert calls["allowed"] == [base]
    assert opened["render"] == {"rendered": True, "blocked_origins": ["https://cdn.example"]}
    assert opened["context"]["challenge"]["title"] == "Rendered"
    assert opened["downloaded_files"] == 1


def test_render_rejects_out_of_scope_navigation(rctf, tmp_path):
    base, _ = rctf
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    with pytest.raises(ValueError, match="scope"):
        workflow.open(base + "/spa", render=True,
                      renderer=lambda url, allowed, cookies: ("https://evil.example/", "<p>x</p>", []))
    with pytest.raises(ValueError):
        workflow.open(base, adapter="ctfd", challenge_id=1, render=True)


def test_cli_rctf_catalog(rctf, tmp_path, monkeypatch, capsys):
    base, _ = rctf
    database = tmp_path / "state" / "metis.sqlite"
    WebWorkflow(database).auth(base, kind="token", value="rctf-auth-token", scheme="Bearer")
    monkeypatch.setattr(sys, "argv", ["metis", "web", "--database", str(database), "catalog", base,
                                      "--adapter", "rctf"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["source"] == "rctf"


def test_real_browser_render_is_opt_in(tmp_path):
    import os

    from metis.core import ctf_browser
    if not ctf_browser.available() or not os.environ.get("METIS_TEST_BROWSER"):
        pytest.skip("set METIS_TEST_BROWSER=1 with the browser extra and Chromium installed")
    page = tmp_path / "index.html"
    page.write_text("<title>shell</title><div id=app></div>"
                    "<script>document.title='Built';app.innerHTML='<p>dynamic</p>'</script>"
                    "<img src='https://example.com/x.png'>")
    import functools
    import http.server
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _url, html, blocked = ctf_browser.render(base + "/index.html", [base])
    finally:
        server.shutdown()
    assert "<p>dynamic</p>" in html and "https://example.com" in blocked

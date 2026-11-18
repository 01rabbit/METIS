import json
import sqlite3
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from metis.cli import main
from metis.core.codex_session import CodexSession
from metis.core.ctf_web import WebRequest, WebWorkflow


def _server(handler_class):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def sites(monkeypatch):
    monkeypatch.setattr("urllib.request.getproxies", dict)
    seen = {"platform_auth": [], "platform_cookie": []}

    class Platform(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def do_GET(self):
            seen["platform_auth"].append(self.headers.get("Authorization"))
            seen["platform_cookie"].append(self.headers.get("Cookie"))
            body = b"<title>Simple Auth</title><p>Log in at the challenge server.</p>"
            self.send_response(200)
            if self.path == "/set-cookie":
                self.send_header("Set-Cookie", "session=stored-auth-cookie; Path=/")
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class Challenge(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def send(self, body, status=200, extra=None):
            body = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/admin":
                if "session=admin-token" in (self.headers.get("Cookie") or ""):
                    return self.send("<p>CHALLENGE_SECRET_mock</p>")
                return self.send("denied", 403)
            if self.path == "/whoami":
                return self.send("ua=" + (self.headers.get("User-Agent") or "") + " xff="
                                 + (self.headers.get("X-Forwarded-For") or ""))
            if self.path.startswith("/item?id="):
                value = urllib.parse.unquote(self.path.split("=", 1)[1])
                return self.send("found" if value.endswith("'1'='1") else "none")
            return self.send("not found", 404)

        def do_POST(self):
            body = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            if self.path == "/login" and body.get("user") == ["admin' --"]:
                return self.send("ok", 302, {"Location": "/admin", "Set-Cookie": "session=admin-token; Path=/"})
            return self.send("bad login", 401)

        def do_PUT(self):
            return self.send("put:" + self.rfile.read(int(self.headers["Content-Length"])).decode())

    platform, platform_url = _server(Platform)
    challenge, challenge_url = _server(Challenge)
    yield platform_url, challenge_url, seen
    platform.shutdown()
    challenge.shutdown()


def _open(tmp_path, platform_url):
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    workflow.auth(platform_url, kind="token", value="platform-secret-token")
    run_id = workflow.open(platform_url + "/problem")["context"]["run_id"]
    return workflow, run_id


def test_grant_login_cookie_flow_and_batch(tmp_path, sites):
    platform_url, challenge_url, seen = sites
    workflow, run_id = _open(tmp_path, platform_url)
    with pytest.raises(ValueError, match="not granted"):
        workflow.request(run_id, [WebRequest(url=challenge_url + "/admin")])
    workflow.grant_origin(run_id, challenge_url)
    login = workflow.request(run_id, [WebRequest(url=challenge_url + "/login", method="POST",
                                                 form={"user": "admin' --", "pass": "x"})])
    response = login["responses"][0]
    assert response["status"] == 302 and "session=admin-token" in response["headers"]["set-cookie"]
    assert login["cookies"][challenge_url]["session"] == "admin-token"
    admin = workflow.request(run_id, [WebRequest(url=challenge_url + "/admin", extract=r"CHALLENGE_\w+")])
    assert admin["responses"][0]["matches"] == ["CHALLENGE_SECRET_mock"]
    artifact = admin["responses"][0]["artifact"]
    assert artifact in CodexSession(workflow.database).context(run_id)["challenge"]["artifacts"]

    batch = workflow.request(run_id, [
        WebRequest(url=challenge_url + "/item?id=" + urllib.parse.quote(payload), preview=0)
        for payload in ("1", "1' OR '1'='1")
    ] + [WebRequest(url=challenge_url + "/whoami", headers={"User-Agent": "Mozilla/5.0 METIS",
                                                            "X-Forwarded-For": "127.0.0.1"}),
         WebRequest(url=challenge_url + "/upload", method="PUT", data="abc")])
    lengths = [entry["length"] for entry in batch["responses"][:2]]
    assert lengths == [4, 5]  # "none" vs "found": a boolean oracle without bodies
    assert batch["responses"][2]["body"] == "ua=Mozilla/5.0 METIS xff=127.0.0.1"
    assert batch["responses"][3]["body"] == "put:abc"
    # The platform token never travelled to the challenge origin; platform cookies stay hidden.
    assert platform_url not in batch["cookies"]
    assert seen["platform_auth"] == ["Token platform-secret-token"]


def test_platform_credentials_cannot_be_overridden(tmp_path, sites):
    platform_url, _, _ = sites
    workflow, run_id = _open(tmp_path, platform_url)
    result = workflow.request(run_id, [WebRequest(url=platform_url + "/x", headers={"Authorization": "Bearer x"})])
    assert "unsupported request header" in result["responses"][0]["error"]
    result = workflow.request(run_id, [WebRequest(url=platform_url + "/x", headers={"Host": "evil"})])
    assert "unsupported request header" in result["responses"][0]["error"]
    with pytest.raises(ValueError):
        WebRequest(url=platform_url, data="a", form={"b": "c"}).body()


def test_reauth_replaces_stored_platform_credential(tmp_path, sites):
    platform_url, _, seen = sites
    workflow, run_id = _open(tmp_path, platform_url)

    workflow.auth(platform_url, kind="token", value="replacement-token", scheme="Bearer")
    workflow.request(run_id, [WebRequest(url=platform_url + "/rotate-check")])

    assert seen["platform_auth"][-1] == "Bearer replacement-token"
    with sqlite3.connect(workflow.database) as db:
        payload, = db.execute("SELECT payload FROM web_credentials WHERE origin=?",
                              (platform_url,)).fetchone()
    assert "replacement-token" in payload
    assert "platform-secret-token" not in payload


def test_cli_forget_revokes_stored_origin_credential(tmp_path, sites, monkeypatch, capsys):
    platform_url, _, seen = sites
    workflow, run_id = _open(tmp_path, platform_url)
    monkeypatch.setattr(sys, "argv", ["metis", "web", "--database", str(workflow.database),
                                      "forget", platform_url])

    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["origin"] == platform_url and output["credential_removed"] is True
    assert "in-flight request" in output["limit"]
    assert "platform-secret-token" not in json.dumps(output)

    workflow.request(run_id, [WebRequest(url=platform_url + "/after-forget")])
    assert seen["platform_auth"][-1] is None
    assert workflow.forget_auth(platform_url)["credential_removed"] is False


def test_forget_auth_removes_cookie_and_fences_stale_client(tmp_path, sites):
    platform_url, _, seen = sites
    workflow, run_id = _open(tmp_path, platform_url)
    workflow.request(run_id, [WebRequest(url=platform_url + "/set-cookie")])
    assert seen["platform_cookie"][-1] is None

    config, state, *_ = workflow._load(run_id)
    stale_client = workflow._client(config, state)
    assert any(cookie.value == "stored-auth-cookie"
               for cookie in stale_client.jars[platform_url])

    workflow.forget_auth(platform_url)
    # Model a request that had loaded state before forget_auth and saves afterward.
    with pytest.raises(ValueError, match="authentication has been forgotten"):
        stale_client.request(platform_url + "/after-forget")
    workflow._save_client(run_id, stale_client)
    # Also model forget_auth between the persisted-state load and client creation.
    late_client = workflow._client(config, state)
    with pytest.raises(ValueError, match="authentication has been forgotten"):
        late_client.request(platform_url + "/after-forget")
    workflow._save_client(run_id, late_client)
    config, state, *_ = workflow._load(run_id)
    assert platform_url not in state.get("cookies", {})
    workflow.request(run_id, [WebRequest(url=platform_url + "/after-forget")])
    assert seen["platform_cookie"][-1] is None
    assert workflow.forget_auth(platform_url)["credential_removed"] is False


def test_open_does_not_persist_cookie_if_auth_is_forgotten_during_intake(tmp_path, sites, monkeypatch):
    platform_url, _, seen = sites
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    workflow.auth(platform_url, kind="token", value="platform-secret-token")
    original_intake = workflow.session.intake

    def forget_between_fetch_and_persist(**kwargs):
        workflow.forget_auth(platform_url)
        return original_intake(**kwargs)

    monkeypatch.setattr(workflow.session, "intake", forget_between_fetch_and_persist)
    result = workflow.open(platform_url + "/set-cookie")
    run_id = result["context"]["run_id"]
    with sqlite3.connect(workflow.database) as db:
        persisted_state, = db.execute("SELECT state FROM web_runs WHERE run_id=?", (run_id,)).fetchone()
    assert platform_url not in json.loads(persisted_state).get("cookies", {})
    config, state, *_ = workflow._load(run_id)
    assert config["auth_origin"] == platform_url
    assert platform_url not in state.get("cookies", {})
    workflow.request(run_id, [WebRequest(url=platform_url + "/after-forget")])
    assert seen["platform_cookie"][-1] is None


def test_render_fences_auth_cookies_forgotten_during_render(tmp_path, sites):
    platform_url, _, seen = sites
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    workflow.auth(platform_url, kind="token", value="platform-secret-token")

    def forget_during_render(url, allowed, *, cookies, auth_origin, auth_generation_check):
        assert cookies == []
        assert auth_origin == platform_url
        assert auth_generation_check()
        workflow.forget_auth(platform_url)
        assert not auth_generation_check()
        return url, "<title>Rendered</title>", []

    with pytest.raises(ValueError, match="authentication has been forgotten"):
        workflow.open(platform_url + "/problem", render=True, renderer=forget_during_render)
    assert seen["platform_auth"][-1] == "Token platform-secret-token"
    with sqlite3.connect(workflow.database) as db:
        count, = db.execute("SELECT COUNT(*) FROM web_runs").fetchone()
    assert count == 0


def test_cli_web_request(tmp_path, sites, monkeypatch, capsys):
    platform_url, challenge_url, _ = sites
    workflow, run_id = _open(tmp_path, platform_url)
    database = str(workflow.database)
    monkeypatch.setattr(sys, "argv", ["metis", "web", "--database", database, "grant", run_id, challenge_url])
    assert main() == 0
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["metis", "web", "--database", database, "request", run_id,
                                      challenge_url + "/login", "--method", "POST", "--form", "user=admin' --",
                                      "--form", "pass=x", "--follow", "--extract", r"CHALLENGE_\w+"])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["responses"][0]["matches"] == ["CHALLENGE_SECRET_mock"]
    monkeypatch.setattr(sys, "argv", ["metis", "web", "--database", database, "request", run_id,
                                      "https://elsewhere.example/"])
    with pytest.raises(SystemExit):
        main()
    assert "not granted" in capsys.readouterr().err

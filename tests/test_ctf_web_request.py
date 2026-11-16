import json
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
    seen = {"platform_auth": []}

    class Platform(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def do_GET(self):
            seen["platform_auth"].append(self.headers.get("Authorization"))
            body = b"<title>Simple Auth</title><p>Log in at the challenge server.</p>"
            self.send_response(200)
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

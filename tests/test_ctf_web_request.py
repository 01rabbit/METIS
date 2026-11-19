import json
import sqlite3
import sys
import threading
import urllib.parse
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from metis.cli import main
from metis.core.codex_session import CodexSession
from metis.core.ctf_http import HTTPResult, SafeHTTP
from metis.core.ctf_web import WebRequest, WebWorkflow


def test_precreated_public_database_never_gets_a_local_credential(tmp_path):
    database = tmp_path / "precreated.sqlite"
    with closing(sqlite3.connect(database)) as db:
        db.execute("CREATE TABLE unrelated (value TEXT)")
    database.chmod(0o644)
    with pytest.raises(ValueError, match="database must be private and owned"):
        WebWorkflow(database).auth("https://fixture.invalid", kind="token", value="synthetic-only")
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT COUNT(*) FROM web_credentials").fetchone() == (0,)


def test_local_auth_requires_current_owner(tmp_path, monkeypatch):
    database = tmp_path / "state.sqlite"
    web = WebWorkflow(database)
    different_owner = database.stat().st_uid + 1
    monkeypatch.setattr("metis.core.ctf_web.os.geteuid", lambda: different_owner)
    with pytest.raises(ValueError, match="database must be private and owned"):
        web.auth("https://fixture.invalid", kind="token", value="synthetic-only")


def test_restored_database_refuses_local_auth_and_allows_forgetting(tmp_path, monkeypatch):
    database = tmp_path / "restored.sqlite"
    web = WebWorkflow(database)
    auth_origin = "https://fixture.invalid"
    config = {"origins": [auth_origin], "auth_origin": auth_origin}
    assert database.stat().st_mode & 0o777 == 0o600
    web.auth(auth_origin, kind="token", value="synthetic-before-restore")
    database.chmod(0o644)
    web = WebWorkflow(database)

    def no_request(*_args, **_kwargs):
        pytest.fail("unsafe local authentication reached a request")

    monkeypatch.setattr("metis.core.ctf_web.SafeHTTP.request", no_request)
    with pytest.raises(ValueError, match="database must be private and owned"):
        web.auth(auth_origin, kind="token", value="synthetic-after-restore")
    with pytest.raises(ValueError, match="database must be private and owned"):
        web._client(config, {})
    with pytest.raises(ValueError, match="database must be private and owned"):
        web.rctf_login(auth_origin, "synthetic-team-token")
    with closing(sqlite3.connect(database)) as db:
        assert json.loads(db.execute("SELECT payload FROM web_credentials").fetchone()[0])["token"] == (
            "synthetic-before-restore"
        )
    monkeypatch.setenv("METIS_WEB_AUTH_STORAGE", "environment")
    monkeypatch.setenv("METIS_SYNTHETIC_TOKEN", "synthetic-environment-token")
    assert web._client(config | {"token_env": "METIS_SYNTHETIC_TOKEN"}, {}).secret_values() == [
        "synthetic-environment-token"
    ]
    assert web.forget_auth(auth_origin)["credential_removed"] is True
    assert web.forget_all_auth(apply=True)["stored_credentials"] == 0


@pytest.mark.parametrize(("suffix", "label"), [("-wal", "WAL"), ("-shm", "SHM")])
def test_local_auth_refuses_unsafe_sqlite_sidecar(tmp_path, suffix, label):
    database = tmp_path / "state.sqlite"
    web = WebWorkflow(database)
    with closing(sqlite3.connect(database)) as db:
        db.execute("SELECT * FROM web_credentials").fetchall()
        sidecar = database.with_name(database.name + suffix)
        sidecar.chmod(0o644)
        with pytest.raises(ValueError, match=f"{label} must be private and owned"):
            web.auth("https://fixture.invalid", kind="token", value="synthetic-only")


@pytest.mark.parametrize(("suffix", "label"), [("", "database"), ("-wal", "WAL"), ("-shm", "SHM")])
def test_web_workflow_rejects_symlinked_sqlite_files_before_open(tmp_path, suffix, label):
    database = tmp_path / "state.sqlite"
    target = tmp_path / "untouched"
    target.write_bytes(b"keep")
    database.with_name(database.name + suffix).symlink_to(target)
    with pytest.raises(ValueError, match=f"{label} must be a regular file"):
        WebWorkflow(database)
    assert target.read_bytes() == b"keep"


@pytest.mark.parametrize(("suffix", "label"), [("", "database"), ("-wal", "WAL"), ("-shm", "SHM")])
def test_remediation_and_environment_mode_recheck_paths_after_open(tmp_path, monkeypatch, suffix, label):
    database = tmp_path / "state.sqlite"
    web = WebWorkflow(database)
    auth_origin = "https://fixture.invalid"
    config = {"origins": [auth_origin], "auth_origin": auth_origin}
    web.auth(auth_origin, kind="token", value="synthetic-only")
    monkeypatch.setenv("METIS_WEB_AUTH_STORAGE", "environment")
    client = web._client(config, {})
    target = tmp_path / "untouched"
    target.write_bytes(b"keep")
    replacement = tmp_path / "replacement"
    replacement.symlink_to(target)
    replacement.replace(database.with_name(database.name + suffix))

    for operation in (lambda: web._client(config, {}), lambda: web._load("fixture-run"),
                      lambda: web._save_client("fixture-run", client), lambda: web.forget_auth(auth_origin),
                      lambda: web.forget_all_auth(apply=True)):
        with pytest.raises(ValueError, match=f"{label} must be a regular file"):
            operation()
    assert target.read_bytes() == b"keep"


def test_local_client_cannot_load_save_or_use_auth_after_storage_mode_change(tmp_path):
    database = tmp_path / "state.sqlite"
    web = WebWorkflow(database)
    auth_origin = "https://fixture.invalid"
    config = {"origins": [auth_origin], "auth_origin": auth_origin}
    client = web._client(config, {})
    database.chmod(0o644)
    for operation in (lambda: web._load("fixture-run"), lambda: web._save_client("fixture-run", client),
                      lambda: client.auth_generation_check(client.auth_generation)):
        with pytest.raises(ValueError, match="database must be private and owned"):
            operation()


@pytest.mark.parametrize("database_mode", [0o600, 0o644])
def test_environment_mode_persists_alternate_origin_cookie_only_in_private_state(tmp_path, monkeypatch, database_mode):
    database = tmp_path / "state.sqlite"
    web = WebWorkflow(database)
    database.chmod(database_mode)
    monkeypatch.setenv("METIS_WEB_AUTH_STORAGE", "environment")
    platform = "https://platform.invalid"
    alternate = "https://alternate.invalid"
    secret = "synthetic-alternate-cookie"
    cookie_client = SafeHTTP([alternate], auth_origin=alternate, credentials={"cookie": f"session={secret}"})

    def fake_request(client, url, **_kwargs):
        client.jars.update(cookie_client.jars)
        body = b"<title>Storage fixture</title>"
        return HTTPResult(url, 200, {}, body, len(body), "a" * 64)

    def stored_state():
        with closing(sqlite3.connect(database)) as db:
            return db.execute("SELECT state FROM web_runs").fetchone()[0]

    monkeypatch.setattr(SafeHTTP, "request", fake_request)
    run_id = web.open(platform, allowed_origins=[alternate], download=False)["context"]["run_id"]
    assert (secret in stored_state()) == (database_mode == 0o600)
    config, state, *_ = web._load(run_id)
    assert (secret in json.dumps(state)) == (database_mode == 0o600)
    client = web._client(config, state)
    client.jars.update(cookie_client.jars)
    web._save_client(run_id, client)
    assert (secret in stored_state()) == (database_mode == 0o600)


@pytest.fixture
def saved_run_cookies(tmp_path):
    web = WebWorkflow(tmp_path / "state.sqlite")
    platform = "https://platform.invalid"
    alternate = "https://alternate.invalid"
    config = {"origins": [platform, alternate], "auth_origin": platform}
    web.auth(platform, kind="token", value="synthetic-platform-token")
    client = web._client(config, {})
    for site, value in ((platform, "synthetic-platform-cookie"), (alternate, "synthetic-alternate-cookie")):
        issuer = SafeHTTP([site], auth_origin=site, credentials={"cookie": f"session={value}"})
        client.jars.update(issuer.jars)
    with closing(sqlite3.connect(web.database)) as db, db:
        db.execute("INSERT INTO web_runs (run_id,config,state,forms,links,salt) VALUES (?,?,?,?,?,?)",
                   ("synthetic-run", json.dumps(config), json.dumps(client.export_state()), "[]", "[]", ""))
    return web, client


def test_cli_opt_in_previews_cookie_jars_and_retires_them_on_broad_database(saved_run_cookies, monkeypatch, capsys):
    web, _ = saved_run_cookies
    web.database.chmod(0o644)
    command = ["metis", "web", "--database", str(web.database), "forget-all", "--include-run-cookies"]
    monkeypatch.setattr(sys, "argv", command)
    assert main() == 0
    output = capsys.readouterr().out
    assert json.loads(output)["run_cookie_jars"] == 2
    assert "synthetic-" not in output and ".invalid" not in output
    with closing(sqlite3.connect(web.database)) as db:
        assert web._cookie_epoch(db) == 0
        assert "synthetic-alternate-cookie" in db.execute("SELECT state FROM web_runs").fetchone()[0]

    result = web.forget_all_auth(apply=True)
    assert "run_cookie_jars" not in result
    with closing(sqlite3.connect(web.database)) as db:
        assert web._cookie_epoch(db) == 0
        assert "synthetic-alternate-cookie" in db.execute("SELECT state FROM web_runs").fetchone()[0]

    monkeypatch.setattr(sys, "argv", [*command, "--apply"])
    assert main() == 0
    output = capsys.readouterr().out
    assert json.loads(output)["run_cookie_jars"] == 1
    assert "synthetic-" not in output and ".invalid" not in output
    with closing(sqlite3.connect(web.database)) as db:
        assert web._cookie_epoch(db) == 1
        assert "cookies" not in json.loads(db.execute("SELECT state FROM web_runs").fetchone()[0])


def test_cookie_epoch_rejects_late_load_and_save_without_overwriting_fresh_cookies(saved_run_cookies):
    web, stale = saved_run_cookies
    config, before, *_ = web._load("synthetic-run")
    web.forget_all_auth(apply=True, include_run_cookies=True)
    late = web._client(config, before)
    assert "synthetic-alternate-cookie" not in late.secret_values()
    web._save_client("synthetic-run", stale)
    _, state, *_ = web._load("synthetic-run")
    assert not state.get("cookies")

    origin = "https://alternate.invalid"
    issuer = SafeHTTP([origin], auth_origin=origin, credentials={"cookie": "session=synthetic-fresh-cookie"})
    fresh = web._client(config, state)
    fresh.jars.update(issuer.jars)
    web._save_client("synthetic-run", fresh)
    web._save_client("synthetic-run", stale)
    _, state, *_ = web._load("synthetic-run")
    assert "synthetic-fresh-cookie" in json.dumps(state)
    assert "synthetic-alternate-cookie" not in json.dumps(state)


def test_opt_in_rolls_back_auth_and_cookie_epoch_on_failed_write(saved_run_cookies):
    web, _ = saved_run_cookies
    with closing(sqlite3.connect(web.database)) as db, db:
        db.execute("""CREATE TRIGGER deny_cookie_update BEFORE UPDATE ON web_runs
            BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        web.forget_all_auth(apply=True, include_run_cookies=True)
    with closing(sqlite3.connect(web.database)) as db:
        assert web._cookie_epoch(db) == 0
        assert db.execute("SELECT generation FROM web_auth_generations").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM web_credentials").fetchone() == (1,)
        assert "synthetic-alternate-cookie" in db.execute("SELECT state FROM web_runs").fetchone()[0]


def test_cookie_epoch_fences_intake_started_before_retirement_with_no_saved_runs(tmp_path, monkeypatch):
    web = WebWorkflow(tmp_path / "state.sqlite")
    platform = "https://platform.invalid"
    alternate = "https://alternate.invalid"
    issuer = SafeHTTP([alternate], auth_origin=alternate, credentials={"cookie": "session=synthetic-inflight"})

    def fake_request(client, url, **_kwargs):
        assert web.forget_all_auth(apply=True, include_run_cookies=True)["selected_runs"] == 0
        client.jars.update(issuer.jars)
        body = b"<title>Storage fixture</title>"
        return HTTPResult(url, 200, {}, body, len(body), "a" * 64)

    monkeypatch.setattr(SafeHTTP, "request", fake_request)
    web.open(platform, allowed_origins=[alternate], download=False)
    with closing(sqlite3.connect(web.database)) as db:
        assert web._cookie_epoch(db) == 1
        assert "cookies" not in json.loads(db.execute("SELECT state FROM web_runs").fetchone()[0])


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


def test_reauth_switches_kind_and_clears_previous_auth_state(tmp_path, sites):
    platform_url, _, seen = sites
    workflow, run_id = _open(tmp_path, platform_url)
    workflow.request(run_id, [WebRequest(url=platform_url + "/set-cookie")])
    config, state, *_ = workflow._load(run_id)
    stale_client = workflow._client(config, state)

    workflow.auth(platform_url, kind="cookie", value="session=replacement-cookie")
    with pytest.raises(ValueError, match="authentication has been forgotten"):
        stale_client.request(platform_url + "/stale")
    workflow._save_client(run_id, stale_client)
    workflow.request(run_id, [WebRequest(url=platform_url + "/cookie-check")])
    assert seen["platform_auth"][-1] is None
    assert seen["platform_cookie"][-1] == "session=replacement-cookie"
    with sqlite3.connect(workflow.database) as db:
        payload, = db.execute("SELECT payload FROM web_credentials WHERE origin=?",
                              (platform_url,)).fetchone()
    assert json.loads(payload) == {"cookie": "session=replacement-cookie", "scheme": "Token"}

    workflow.auth(platform_url, kind="token", value="final-token", scheme="Bearer")
    workflow.request(run_id, [WebRequest(url=platform_url + "/token-check")])
    assert seen["platform_auth"][-1] == "Bearer final-token"
    assert seen["platform_cookie"][-1] is None
    with sqlite3.connect(workflow.database) as db:
        payload, = db.execute("SELECT payload FROM web_credentials WHERE origin=?",
                              (platform_url,)).fetchone()
    assert json.loads(payload) == {"token": "final-token", "scheme": "Bearer"}


def test_reauth_between_state_load_and_client_creation_fences_old_generation(tmp_path, sites):
    platform_url, _, seen = sites
    workflow, run_id = _open(tmp_path, platform_url)
    workflow.request(run_id, [WebRequest(url=platform_url + "/set-cookie")])
    config, state, *_ = workflow._load(run_id)
    requests_before = len(seen["platform_auth"])

    workflow.auth(platform_url, kind="token", value="platform-secret-token")
    late_client = workflow._client(config, state)
    with pytest.raises(ValueError, match="authentication has been forgotten"):
        late_client.request(platform_url + "/stale-after-load")
    assert len(seen["platform_auth"]) == requests_before

    workflow._save_client(run_id, late_client)
    workflow.request(run_id, [WebRequest(url=platform_url + "/fresh-after-reauth")])
    assert seen["platform_auth"][-1] == "Token platform-secret-token"
    assert seen["platform_cookie"][-1] is None


def test_environment_auth_mode_ignores_legacy_storage_and_does_not_persist_cookie(tmp_path, sites, monkeypatch):
    platform_url, _, seen = sites
    workflow, run_id = _open(tmp_path, platform_url)
    workflow.request(run_id, [WebRequest(url=platform_url + "/set-cookie")])
    config, pre_switch_state, *_ = workflow._load(run_id)
    stale_client = workflow._client(config, pre_switch_state)
    with sqlite3.connect(workflow.database) as db:
        old_payload = db.execute("SELECT payload FROM web_credentials WHERE origin=?", (platform_url,)).fetchone()[0]
    monkeypatch.setenv("METIS_WEB_AUTH_STORAGE", "environment")
    with pytest.raises(ValueError, match="authentication has been forgotten"):
        stale_client.request(platform_url + "/after-switch")
    with pytest.raises(ValueError, match="stored web authentication is disabled"):
        workflow.auth(platform_url, kind="token", value="new-private-token")
    with pytest.raises(ValueError, match="stored web authentication is disabled"):
        workflow.rctf_login(platform_url, "team-token")
    workflow.request(run_id, [WebRequest(url=platform_url + "/after-switch")])
    assert seen["platform_auth"][-1] is None
    assert seen["platform_cookie"][-1] is None
    workflow.request(run_id, [WebRequest(url=platform_url + "/set-cookie")])
    with sqlite3.connect(workflow.database) as db:
        assert db.execute("SELECT payload FROM web_credentials WHERE origin=?", (platform_url,)).fetchone()[0] == old_payload
        state = json.loads(db.execute("SELECT state FROM web_runs WHERE run_id=?", (run_id,)).fetchone()[0])
    assert platform_url not in state.get("cookies", {})
    monkeypatch.setenv("METIS_WEB_AUTH_STORAGE", "local")
    workflow.request(run_id, [WebRequest(url=platform_url + "/after-restore")])
    assert seen["platform_auth"][-1] == "Token platform-secret-token"


def test_environment_auth_mode_uses_explicit_variable(tmp_path, sites, monkeypatch):
    platform_url, _, seen = sites
    monkeypatch.setenv("METIS_WEB_AUTH_STORAGE", "environment")
    monkeypatch.setenv("METIS_TEST_PLATFORM_TOKEN", "private-env-token")
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    run_id = workflow.open(platform_url + "/problem", token_env="METIS_TEST_PLATFORM_TOKEN")["context"]["run_id"]
    workflow.request(run_id, [WebRequest(url=platform_url + "/check")])
    assert seen["platform_auth"][-1] == "Token private-env-token"
    with sqlite3.connect(workflow.database) as db:
        assert db.execute("SELECT COUNT(*) FROM web_credentials").fetchone()[0] == 0
        persisted = db.execute("SELECT config,state FROM web_runs WHERE run_id=?", (run_id,)).fetchone()
    assert "private-env-token" not in "".join(persisted)


def test_environment_auth_mode_uses_bearer_for_rctf(tmp_path, sites, monkeypatch):
    platform_url, _, seen = sites
    monkeypatch.setenv("METIS_WEB_AUTH_STORAGE", "environment")
    monkeypatch.setenv("METIS_TEST_RCTF_TOKEN", "private-rctf-token")
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    client = workflow._client({"origins": [platform_url], "auth_origin": platform_url,
                               "adapter": "rctf", "token_env": "METIS_TEST_RCTF_TOKEN"}, {})
    client.request(platform_url + "/check")
    assert seen["platform_auth"][-1] == "Bearer private-rctf-token"


def test_environment_auth_mode_rejects_unknown_setting(tmp_path, monkeypatch):
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    monkeypatch.setenv("METIS_WEB_AUTH_STORAGE", "unknown")
    with pytest.raises(ValueError, match="must be local or environment"):
        workflow.auth("https://example.com", kind="token", value="private")


def test_environment_auth_mode_cli_rejects_before_secret_prompt(tmp_path, monkeypatch, capsys):
    database = tmp_path / "state" / "metis.sqlite"
    monkeypatch.setenv("METIS_WEB_AUTH_STORAGE", "environment")
    monkeypatch.setattr("getpass.getpass", lambda *_: pytest.fail("secret prompt should not occur"))
    monkeypatch.setattr(sys, "argv", ["metis", "web", "--database", str(database),
                                      "auth", "https://example.com", "--kind", "token"])
    with pytest.raises(SystemExit) as rejection:
        main()
    assert rejection.value.code == 2
    assert "CTF web command rejected" in capsys.readouterr().err


def test_cli_forget_revokes_stored_origin_credential(tmp_path, sites, monkeypatch, capsys):
    platform_url, _, seen = sites
    workflow, run_id = _open(tmp_path, platform_url)
    monkeypatch.setattr(sys, "argv", ["metis", "web", "--database", str(workflow.database),
                                      "forget", platform_url])

    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["origin"] == platform_url and output["credential_removed"] is True
    assert output["provider_revocation_required"] is True
    assert "in-flight request" in output["limit"]
    assert "WAL" in output["limit"] and "backups" in output["limit"]
    assert "platform-secret-token" not in json.dumps(output)

    workflow.request(run_id, [WebRequest(url=platform_url + "/after-forget")])
    assert seen["platform_auth"][-1] is None
    # Recreating the workflow over the same database must not regain the credential.
    WebWorkflow(workflow.database).request(run_id, [WebRequest(url=platform_url + "/after-reopen")])
    assert seen["platform_auth"][-1] is None
    assert workflow.forget_auth(platform_url)["credential_removed"] is False


def test_auth_retirement_enables_secure_delete_on_write_connection(tmp_path, monkeypatch):
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    real_connect = sqlite3.connect
    connections = []

    def track_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", track_connect)
    workflow.auth("https://example.com", kind="token", value="synthetic-token")
    workflow.forget_auth("https://example.com")
    workflow.forget_all_auth(apply=True)
    assert len(connections) == 3
    assert all(db.execute("PRAGMA secure_delete").fetchone()[0] == 1 for db in connections)
    for db in connections:
        db.close()


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


def test_forget_all_previews_then_fences_saved_auth(tmp_path, sites, monkeypatch, capsys):
    platform_url, _, seen = sites
    workflow, run_id = _open(tmp_path, platform_url)
    other_origin = "https://other.example"
    workflow.auth(other_origin, kind="token", value="other-private-token")
    workflow.request(run_id, [WebRequest(url=platform_url + "/set-cookie")])
    config, state, *_ = workflow._load(run_id)
    stale_client = workflow._client(config, state)
    with sqlite3.connect(workflow.database) as db:
        generations_before = db.execute("SELECT origin,generation FROM web_auth_generations ORDER BY origin").fetchall()
    monkeypatch.setattr(sys, "argv", ["metis", "web", "--database", str(workflow.database), "forget-all"])
    assert main() == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["applied"] is False
    assert preview["origins"] == 2
    assert preview["stored_credentials"] == 2
    assert preview["selected_runs"] == 1
    assert preview["provider_revocation_required"] is False
    assert "private-token" not in json.dumps(preview)
    with sqlite3.connect(workflow.database) as db:
        assert db.execute("SELECT COUNT(*) FROM web_credentials").fetchone()[0] == 2
        assert db.execute("SELECT origin,generation FROM web_auth_generations ORDER BY origin").fetchall() == generations_before
        preview_state = json.loads(db.execute("SELECT state FROM web_runs WHERE run_id=?", (run_id,)).fetchone()[0])
        assert platform_url in preview_state.get("cookies", {})

    monkeypatch.setattr(sys, "argv", ["metis", "web", "--database", str(workflow.database),
                                      "forget-all", "--apply"])
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["applied"] is True
    assert result["provider_revocation_required"] is True
    assert "WAL" in result["limit"] and "backups" in result["limit"]
    with sqlite3.connect(workflow.database) as db:
        assert db.execute("SELECT COUNT(*) FROM web_credentials").fetchone()[0] == 0
        assert db.execute("SELECT generation FROM web_auth_generations WHERE origin=?",
                          (other_origin,)).fetchone()[0] == 2
    with pytest.raises(ValueError, match="authentication has been forgotten"):
        stale_client.request(platform_url + "/after-forget")
    workflow._save_client(run_id, stale_client)
    _, saved_state, *_ = workflow._load(run_id)
    assert platform_url not in saved_state.get("cookies", {})
    workflow.request(run_id, [WebRequest(url=platform_url + "/after-forget")])
    assert seen["platform_auth"][-1] is None
    assert seen["platform_cookie"][-1] is None
    assert workflow.forget_all_auth(apply=True)["stored_credentials"] == 0


def test_forget_all_refuses_over_limit_without_mutation(tmp_path):
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    with sqlite3.connect(workflow.database) as db:
        db.executemany("INSERT INTO web_credentials(origin,payload) VALUES (?,?)",
                       [(f"https://site{i}.example", '{"token":"private"}') for i in range(101)])
    with pytest.raises(ValueError, match="exceeds 100 origins"):
        workflow.forget_all_auth(apply=True)
    with sqlite3.connect(workflow.database) as db:
        assert db.execute("SELECT COUNT(*) FROM web_credentials").fetchone()[0] == 101


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

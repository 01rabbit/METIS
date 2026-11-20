"""Local operator view exposes safe audit and authenticated cancellation projections."""
from __future__ import annotations

import http.client
import json
import shutil
import sqlite3
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from metis.core.agent_host import FakeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession
from metis.core.contracts import ChallengeManifest, RunEvent, RunStatus
from metis.core.ctf_web import WebWorkflow
from metis.core.operator_ui import create_server
from metis.core.store import RunStore, ensure_run_audit_list_index

RUN_ID = "a" * 32
TOKEN = "secret-operator-token-with-32-chars-minimum"


@contextmanager
def server_for(database: Path, *, cancel_run=None, dispatch_control=None, dispatch_status=None,
               credential_retention_preview=None):
    server = create_server(database, port=0, token=TOKEN, cancel_run=cancel_run,
                           dispatch_control=dispatch_control,
                           dispatch_status=dispatch_status,
                           credential_retention_preview=credential_retention_preview)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(port: int, method: str, path: str, *, token: str | None = None,
            host: str | None = None, origin: str | None = None,
            body: bytes | None = None) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    headers = {"Host": host or f"127.0.0.1:{port}"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    if origin is not None:
        headers["Origin"] = origin
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    conn.close()
    return result


def fixture_database(tmp_path: Path) -> Path:
    database = tmp_path / "state.sqlite"
    store = RunStore(database)
    store.append(RunEvent(run_id=RUN_ID, sequence=0, status=RunStatus.NEW,
                          detail={"private": "private-output-canary"}))
    return database


def test_loopback_view_requires_token_and_omits_event_details(tmp_path: Path) -> None:
    database = fixture_database(tmp_path)
    before = database.stat().st_mtime_ns
    with server_for(database) as port:
        status, headers, page = request(port, "GET", "/")
        assert status == 200 and b"METIS operator" in page
        assert headers["Content-Security-Policy"].startswith("default-src 'none'")
        assert request(port, "GET", f"/api/runs/{RUN_ID}/audit")[0] == 401
        assert request(port, "GET", f"/api/runs/{RUN_ID}/audit", token="wrong")[0] == 401
        assert request(port, "GET", f"/api/runs/{RUN_ID}/audit", token="é" * 32)[0] == 401
        assert request(port, "GET", f"/api/runs/{RUN_ID}/audit",
                       token=TOKEN, host="evil.example")[0] == 403
        assert request(port, "GET", f"/api/runs/{RUN_ID}/audit",
                       token=TOKEN, origin="https://evil.example")[0] == 403
        status, headers, body = request(port, "GET", f"/api/runs/{RUN_ID}/audit", token=TOKEN)
        assert status == 200 and headers["Cache-Control"] == "no-store"
        assert json.loads(body)["run_id"] == RUN_ID
        assert b"private-output-canary" not in body and TOKEN.encode() not in body
        assert request(port, "POST", f"/api/runs/{RUN_ID}/audit", token=TOKEN)[0] == 405
    assert database.stat().st_mtime_ns == before


def test_corrupt_audit_is_unavailable_and_missing_db_is_not_created(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(ValueError, match="unavailable"):
        create_server(missing, port=0, token=TOKEN)
    assert not missing.exists()
    database = fixture_database(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("DROP TRIGGER deny_update")
        db.execute("UPDATE events SET digest='corrupt' WHERE run_id=?", (RUN_ID,))
    with server_for(database) as port:
        assert request(port, "GET", f"/api/runs/{RUN_ID}/audit", token=TOKEN)[0] == 503


def test_short_token_and_invalid_port_are_rejected(tmp_path: Path) -> None:
    database = fixture_database(tmp_path)
    with pytest.raises(ValueError, match="token"):
        create_server(database, port=0, token="short")
    with pytest.raises(ValueError, match="ASCII"):
        create_server(database, port=0, token="é" * 32)
    with pytest.raises(ValueError, match="port"):
        create_server(database, port=65536, token=TOKEN)


def _start_run(database: Path) -> tuple[CodexSession, str]:
    session = CodexSession(database)
    manifest = ChallengeManifest.model_validate({
        "challenge_id": "operator-test", "title": "Operator test", "description": "local",
        "scope": {"authorized": True, "granted_by": "test", "challenge_id": "operator-test"},
    })
    return session, session.start(manifest)["run_id"]


def test_cancel_requires_local_origin_token_and_exact_run_route(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "state.sqlite"
    session, run_id = _start_run(database)
    calls: list[str] = []

    def cancel(candidate: str) -> dict[str, Any]:
        calls.append(candidate)
        return session.cancel(candidate)

    monkeypatch.setattr("metis.core.ctf_sandbox.cancel_registered_worker",
                        lambda *_args: {"status": "not_running"})
    with server_for(database, cancel_run=cancel) as port:
        assert request(port, "POST", f"/api/runs/{run_id}/cancel")[0] == 401
        assert request(port, "POST", f"/api/runs/{run_id}/cancel", token="wrong")[0] == 401
        assert request(port, "POST", f"/api/runs/{run_id}/cancel", token=TOKEN,
                       host="evil.example")[0] == 403
        assert request(port, "POST", f"/api/runs/{run_id}/cancel", token=TOKEN,
                       origin="https://evil.example")[0] == 403
        assert request(port, "POST", "/api/runs/not-a-run/cancel", token=TOKEN)[0] == 404
        assert request(port, "POST", f"/api/runs/{run_id}/cancel", token=TOKEN,
                       body=b"unexpected")[0] == 400
        assert calls == []
        status, headers, body = request(port, "POST", f"/api/runs/{run_id}/cancel", token=TOKEN,
                                        origin=f"http://127.0.0.1:{port}")
        assert status == 200 and headers["Cache-Control"] == "no-store"
        projected = json.loads(body)
        assert projected == {"run_id": run_id, "status": "cancelled",
                             "worker_teardown": {"status": "not_running"}}
        assert calls == [run_id]
        assert TOKEN.encode() not in body and b"challenge" not in body
        assert session.context(run_id)["status"] == "cancelled"
        assert request(port, "POST", f"/api/runs/{run_id}/cancel", token=TOKEN)[0] == 200
        assert calls == [run_id, run_id]


def test_cancel_reports_unknown_teardown_without_leaking_reason(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "state.sqlite"
    session, run_id = _start_run(database)
    session._emit(run_id, RunStatus.EXECUTING, operation="private-operator-detail")
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO codex_active_operations(run_id, operation_id, started) "
                   "VALUES (?, ?, ?)", (run_id, "private-operation-id", 1.0))
    monkeypatch.setattr("metis.core.ctf_sandbox.cancel_registered_worker",
                        lambda *_args: {"status": "unknown", "reason": "private-container-detail"})
    with server_for(database, cancel_run=session.cancel) as port:
        status, _headers, body = request(port, "POST", f"/api/runs/{run_id}/cancel", token=TOKEN)
        assert status == 202
        assert json.loads(body) == {"run_id": run_id, "status": "cancelled",
                                    "worker_teardown": {"status": "unknown"}}
        assert b"private-container-detail" not in body
        assert b"private-operator-detail" not in body and b"private-operation-id" not in body
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT cancel_requested FROM codex_active_operations WHERE run_id=?",
                              (run_id,)).fetchone() == (1,)


def test_cancel_unknown_run_and_unavailable_handler_fail_closed(tmp_path: Path) -> None:
    database = fixture_database(tmp_path)
    session = CodexSession(database)
    with server_for(database, cancel_run=session.cancel) as port:
        assert request(port, "POST", f"/api/runs/{'b' * 32}/cancel", token=TOKEN)[0] == 404
    with server_for(database) as port:
        assert request(port, "POST", f"/api/runs/{RUN_ID}/cancel", token=TOKEN)[0] == 503


def test_dispatch_pause_resume_routes_require_auth_origin_and_empty_body(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "state.sqlite"
    session, run_id = _start_run(database)
    scheduler = AgentScheduler(database, FakeHost())
    monkeypatch.setattr("metis.core.ctf_sandbox.cancel_registered_worker",
                        lambda *_args: {"status": "not_running"})
    path = f"/api/runs/{run_id}/dispatch/pause"
    with server_for(database, dispatch_control=scheduler.set_dispatch_paused,
                    dispatch_status=scheduler.dispatch_control,
                    cancel_run=session.cancel) as port:
        assert request(port, "POST", path)[0] == 401
        assert request(port, "POST", path, token="wrong")[0] == 401
        assert request(port, "POST", path, token=TOKEN, host="evil.example")[0] == 403
        assert request(port, "POST", path, token=TOKEN, origin="https://evil.example")[0] == 403
        assert request(port, "POST", path + "?extra=1", token=TOKEN)[0] == 404
        assert request(port, "POST", f"/api/runs/{'b' * 32}/dispatch/pause", token=TOKEN)[0] == 404
        assert request(port, "POST", path, token=TOKEN, body=b"unexpected")[0] == 400
        status, headers, body = request(port, "POST", path, token=TOKEN,
                                        origin=f"http://127.0.0.1:{port}")
        assert status == 200 and headers["Cache-Control"] == "no-store"
        paused_payload = json.loads(body)
        assert paused_payload["run_id"] == run_id and paused_payload["dispatch_paused"] is True
        assert paused_payload["scope"] == "queued_specialist_dispatch_only"
        assert [event["action"] for event in paused_payload["history"]] == ["pause"]
        assert AgentScheduler(database, FakeHost()).dispatch_control(run_id)["dispatch_paused"] is True

        status_path = f"/api/runs/{run_id}/dispatch"
        assert request(port, "GET", status_path)[0] == 401
        assert request(port, "GET", status_path, token=TOKEN, host="evil.example")[0] == 403
        assert request(port, "GET", status_path, token=TOKEN,
                       origin="https://evil.example")[0] == 403
        assert request(port, "GET", f"/api/runs/{'b' * 32}/dispatch", token=TOKEN)[0] == 404

        cancel_status, _headers, cancel_body = request(
            port, "POST", f"/api/runs/{run_id}/cancel", token=TOKEN,
        )
        assert cancel_status == 200 and json.loads(cancel_body)["status"] == "cancelled"
        resume_status, _headers, resume_body = request(
            port, "POST", f"/api/runs/{run_id}/dispatch/resume", token=TOKEN,
        )
        assert resume_status == 200
        assert [event["action"] for event in json.loads(resume_body)["history"]] == ["pause", "resume"]
        status, _headers, body = request(port, "GET", status_path, token=TOKEN)
        assert status == 200
        status_payload = json.loads(body)
        assert status_payload["dispatch_paused"] is False
        assert [event["action"] for event in status_payload["history"]] == ["pause", "resume"]

    with server_for(database) as port:
        status, _headers, body = request(port, "POST", path, token=TOKEN)
        assert status == 503 and body == b"dispatch control unavailable"
        status, _headers, body = request(port, "GET", f"/api/runs/{run_id}/dispatch", token=TOKEN)
        assert status == 503 and body == b"dispatch status unavailable"

    with server_for(database, dispatch_control=lambda candidate, paused: {
        "run_id": candidate, "dispatch_paused": not paused,
    }) as port:
        status, _headers, body = request(port, "POST", path, token=TOKEN)
        assert status == 503 and body == b"dispatch control status unavailable"

    with server_for(database, dispatch_status=lambda candidate: {
        "run_id": candidate, "dispatch_paused": False,
        "scope": "queued_specialist_dispatch_only", "history": [{"action": "secret", "updated": 1.0}],
    }) as port:
        status, _headers, body = request(port, "GET", f"/api/runs/{run_id}/dispatch", token=TOKEN)
        assert status == 503 and body == b"dispatch status unavailable"


def test_malformed_dispatch_control_history_fails_closed_and_is_redacted(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite"
    _session, run_id = _start_run(database)
    scheduler = AgentScheduler(database, FakeHost())
    scheduler.set_dispatch_paused(run_id, True)
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA ignore_check_constraints=ON")
        db.execute("UPDATE agent_run_control_log SET action=? WHERE run_id=?", (
            "secret-audit-corruption-sentinel", run_id,
        ))
    with pytest.raises(ValueError, match="history"):
        scheduler.dispatch_control(run_id)
    with server_for(database, dispatch_status=scheduler.dispatch_control) as port:
        status, _headers, body = request(port, "GET", f"/api/runs/{run_id}/dispatch", token=TOKEN)
        assert status == 503 and body == b"dispatch status unavailable"
        assert b"secret-audit-corruption-sentinel" not in body

def test_run_list_is_authenticated_bounded_redacted_and_read_only(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite"
    session, first_id = _start_run(database)
    time.sleep(0.002)
    _session, second_id = _start_run(database)
    # Server construction prepares this lookup index before it starts serving.
    ensure_run_audit_list_index(database)
    before = database.read_bytes()

    with server_for(database, cancel_run=session.cancel) as port:
        assert request(port, "GET", "/api/runs")[0] == 401
        assert request(port, "GET", "/api/runs", token=TOKEN, host="evil.example")[0] == 403
        assert request(port, "GET", "/api/runs?limit=0", token=TOKEN)[0] == 400
        assert request(port, "GET", "/api/runs?limit=101", token=TOKEN)[0] == 400
        assert request(port, "GET", "/api/runs?limit=2&extra=1", token=TOKEN)[0] == 400
        status, headers, body = request(port, "GET", "/api/runs?limit=2", token=TOKEN)
        assert status == 200 and headers["Cache-Control"] == "no-store"
        payload = json.loads(body)
        assert [run["run_id"] for run in payload["runs"]] == [second_id, first_id]
        assert payload["truncated"] is False
        assert all(run["status"] == "planning" for run in payload["runs"])
        assert all(run["codex_budget"]["actions_remaining"] == 40 for run in payload["runs"])
        assert "private" not in body.decode()
    assert database.read_bytes() == before


def test_credential_retention_preview_is_authenticated_bounded_redacted_and_read_only(
    tmp_path: Path,
) -> None:
    database = fixture_database(tmp_path)
    WebWorkflow(database)
    now = 10_000_000.0
    old_origin = "https://private-origin.example"
    newer_origin = "https://newer-origin.example"
    unknown_origin = "https://unknown-origin.example"
    old_token = "private-retention-token-sentinel"
    cookie_secret = "private-retention-cookie-sentinel"
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO web_credentials(origin,payload,updated_at) VALUES (?,?,?)",
                   (old_origin, json.dumps({"token": old_token}), now - 31 * 86_400))
        db.execute("INSERT INTO web_credentials(origin,payload,updated_at) VALUES (?,?,?)",
                   (newer_origin, json.dumps({"token": "newer-private-token"}), now))
        db.execute("INSERT INTO web_credentials(origin,payload,updated_at) VALUES (?,?,NULL)",
                   (unknown_origin, json.dumps({"token": "unknown-private-token"})))
        db.execute(
            "INSERT INTO web_runs(run_id,config,state,forms,links,salt) VALUES (?,?,?,?,?,?)",
            ("retention-preview-run", json.dumps({"auth_origin": old_origin}),
             json.dumps({"cookies": {old_origin: [{"value": cookie_secret}]}}),
             "[]", "[]", "fixture-salt"),
        )
        credentials_before = db.execute(
            "SELECT origin,payload,updated_at FROM web_credentials ORDER BY origin",
        ).fetchall()
        state_before = db.execute(
            "SELECT state FROM web_runs WHERE run_id='retention-preview-run'",
        ).fetchone()
        generations_before = db.execute(
            "SELECT * FROM web_auth_generations ORDER BY origin",
        ).fetchall()

    preview_calls: list[int] = []

    def preview(days: int) -> dict[str, Any]:
        preview_calls.append(days)
        return WebWorkflow.preview_credential_retention(database, older_than_days=days, now=now)

    with server_for(database, credential_retention_preview=preview) as port:
        path = "/api/credentials/retention?older_than_days=30"
        assert request(port, "GET", path)[0] == 401
        assert request(port, "GET", path, token=TOKEN, host="evil.example")[0] == 403
        assert request(port, "GET", path, token=TOKEN,
                       origin="https://evil.example")[0] == 403
        assert request(port, "GET", "/api/credentials/retention", token=TOKEN)[0] == 400
        assert request(port, "GET", "/api/credentials/retention?older_than_days=0", token=TOKEN)[0] == 400
        assert request(port, "GET", "/api/credentials/retention?older_than_days=36501",
                       token=TOKEN)[0] == 400
        assert request(port, "GET", "/api/credentials/retention?older_than_days=030",
                       token=TOKEN)[0] == 400
        assert request(port, "GET", path + "&extra=1", token=TOKEN)[0] == 400
        assert preview_calls == []

        status, headers, body = request(port, "GET", path, token=TOKEN)
        assert status == 200 and headers["Cache-Control"] == "no-store"
        payload = json.loads(body)
        assert payload["applied"] is False
        assert payload["older_than_days"] == 30
        assert payload["credentials_considered"] == 3
        assert payload["eligible_credentials"] == 1
        assert payload["newer_credentials_retained"] == 1
        assert payload["age_unknown_retained"] == 1
        assert payload["selected_runs"] == 1 and payload["cookie_jars_selected"] == 1
        assert "private-origin.example" not in body.decode()
        assert "private-retention-token-sentinel" not in body.decode()
        assert "private-retention-cookie-sentinel" not in body.decode()
        assert TOKEN.encode() not in body
        assert set(payload) == {
            "applied", "older_than_days", "credentials_considered", "eligible_credentials",
            "newer_credentials_retained", "age_unknown_retained", "selected_runs",
            "cookie_jars_selected", "sqlite_wal_sidecars_may_be_created", "note",
        }

    assert preview_calls == [30]
    with sqlite3.connect(database) as db:
        assert db.execute(
            "SELECT origin,payload,updated_at FROM web_credentials ORDER BY origin",
        ).fetchall() == credentials_before
        assert db.execute(
            "SELECT state FROM web_runs WHERE run_id='retention-preview-run'",
        ).fetchone() == state_before
        assert db.execute("SELECT * FROM web_auth_generations ORDER BY origin").fetchall() == generations_before


def test_credential_retention_preview_rejects_malformed_callback_results(tmp_path: Path) -> None:
    database = fixture_database(tmp_path)
    valid = {
        "applied": False, "older_than_days": 1,
        "credentials_considered": 0, "eligible_credentials": 0,
        "newer_credentials_retained": 0, "age_unknown_retained": 0,
        "selected_runs": 0, "cookie_jars_selected": 0,
        "sqlite_wal_sidecars_may_be_created": False, "wal_cleanup_complete": None,
    }
    malformed = [
        lambda days: {**valid, "older_than_days": days, "applied": True},
        lambda days: {**valid, "older_than_days": days + 1},
        lambda days: {**valid, "older_than_days": True},
        lambda days: {**valid, "older_than_days": days, "eligible_credentials": -1},
        lambda days: {**valid, "older_than_days": days, "wal_cleanup_complete": True},
        lambda days: {key: value for key, value in {**valid, "older_than_days": days}.items()
                      if key != "sqlite_wal_sidecars_may_be_created"},
        None,
        sqlite3.Error("private callback failure"),
    ]
    calls = 0

    def callback(_days: int):
        nonlocal calls
        item = malformed[calls]
        calls += 1
        if isinstance(item, sqlite3.Error):
            raise item
        return item(_days) if callable(item) else item

    with server_for(database, credential_retention_preview=callback) as port:
        for age in range(1, len(malformed) + 1):
            status, _headers, body = request(
                port, "GET", f"/api/credentials/retention?older_than_days={age}", token=TOKEN,
            )
            assert status == 503
            assert body == b"credential retention preview unavailable"
    assert calls == len(malformed)


def test_run_list_fails_closed_on_corrupt_selected_chain(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite"
    _session, run_id = _start_run(database)
    with sqlite3.connect(database) as db:
        db.execute("DROP TRIGGER deny_update")
        db.execute("UPDATE events SET digest='corrupt' WHERE run_id=? AND sequence=0", (run_id,))
    with server_for(database) as port:
        status, _headers, body = request(port, "GET", "/api/runs", token=TOKEN)
        assert status == 503
        assert b"unavailable" in body
        assert b"private" not in body


@pytest.mark.parametrize("field", ["run_id", "payload", "timestamp", "previous_hash", "digest"])
def test_audit_routes_reject_blob_in_event_text_column(
    tmp_path: Path, field: str, capsys: pytest.CaptureFixture[str],
) -> None:
    database = fixture_database(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("DROP TRIGGER deny_update")
        db.execute(f"UPDATE events SET {field} = CAST({field} AS BLOB)")
    with server_for(database) as port:
        status, _headers, body = request(port, "GET", "/api/runs", token=TOKEN)
        assert status == 503
        assert body == b"run list unavailable"
        if field != "run_id":
            status, _headers, body = request(port, "GET", f"/api/runs/{RUN_ID}/audit", token=TOKEN)
            assert status == 503
            assert body == b"audit unavailable"
    assert capsys.readouterr().err == ""


def test_operator_script_handles_auth_and_selection_changes(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to drive the operator script")
    with server_for(fixture_database(tmp_path)) as port:
        status, _headers, script = request(port, "GET", "/operator.js")
        assert status == 200

    subprocess.run(
        [node, "-e", """
        const assert = require('node:assert/strict');
        const {readFileSync} = require('node:fs');
        const test = require('node:test');
        const {runInNewContext} = require('node:vm');

        class Element {
          value = '';
          textContent = '';
          options = [];
          handlers = {};
          addEventListener(event, callback) { this.handlers[event] = callback; }
          replaceChildren(...options) { this.options = options; this.value = options[0].value; }
          append(option) { this.options.push(option); }
          fire(event) { return this.handlers[event](); }
        }

        const elements = Object.fromEntries(
          ['token', 'run', 'result', 'dispatch-result', 'run-list', 'refresh', 'inspect',
           'dispatch-status', 'cancel',
           'pause-dispatch', 'resume-dispatch',
           'retention-age', 'retention-preview']
            .map(id => [id, new Element()])
        );
        const document = {
          getElementById: id => elements[id],
          createElement: () => new Element(),
        };
        class Option {
          constructor(textContent, value) { Object.assign(this, {textContent, value}); }
        }
        const confirmations = [];
        const window = {
          confirm(message) { confirmations.push(message); return true; }
        };
        let mockFetch;
        runInNewContext(readFileSync(0, 'utf8'), {
          document, Option, window, fetch: (...args) => mockFetch(...args),
        });

        const select = elements['run-list'];
        const runId = 'a'.repeat(32);
        const otherRunId = 'b'.repeat(32);
        const payload = {
          runs: [{run_id: runId, status: 'planning'}, {run_id: otherRunId, status: 'new'}],
          truncated: false,
        };
        const success = () => ({ok: true, status: 200, json: async () => payload});
        const refresh = () => elements.refresh.fire('click');
        const inspect = () => elements.inspect.fire('click');
        const dispatchStatus = () => elements['dispatch-status'].fire('click');
        const pauseDispatch = () => elements['pause-dispatch'].fire('click');
        const resumeDispatch = () => elements['resume-dispatch'].fire('click');
        const retentionPreview = () => elements['retention-preview'].fire('click');
        const deny = status => { mockFetch = async () => ({ok: false, status}); };

        async function loadAndSelect() {
          mockFetch = async () => success();
          await refresh();
          assert.equal(select.options.length, 3);
          select.value = runId;
          select.fire('change');
          assert.equal(elements.run.value, runId);
        }

        function assertCleared(message) {
          assert.equal(select.options.length, 1);
          assert.equal(elements.run.value, '');
          assert.equal(elements.result.textContent, message);
        }

        test('authorization failures clear the view and ignore earlier successes', async () => {
          await loadAndSelect();
          elements.run.value = 'b'.repeat(32);
          elements.run.fire('input');
          deny(401);
          await elements.inspect.fire('click');
          assertCleared('Audit unavailable (401)');

          await loadAndSelect();
          let resolveBody;
          const bodyPending = new Promise(resolve => { resolveBody = resolve; });
          mockFetch = async () => ({ok: true, status: 200, json: () => bodyPending});
          const olderList = refresh();
          await Promise.resolve();
          deny(401);
          await refresh();
          assertCleared('Run list unavailable (401)');
          resolveBody(payload);
          await olderList;
          assertCleared('Run list unavailable (401)');

          await loadAndSelect();
          let resolveResponse;
          mockFetch = () => new Promise(resolve => { resolveResponse = resolve; });
          const pendingList = refresh();
          deny(403);
          await elements.inspect.fire('click');
          assertCleared('Audit unavailable (403)');
          resolveResponse(success());
          await pendingList;
          assertCleared('Audit unavailable (403)');
        });

        test('an earlier refresh denial invalidates even a newer pending request', async () => {
          await loadAndSelect();
          let resolveOlder, resolveNewer;
          mockFetch = () => new Promise(resolve => { resolveOlder = resolve; });
          const older = refresh();
          mockFetch = () => new Promise(resolve => { resolveNewer = resolve; });
          const newer = refresh();

          resolveOlder({ok: false, status: 401});
          await older;
          assertCleared('Run list unavailable (401)');
          resolveNewer(success());
          await newer;
          assertCleared('Run list unavailable (401)');
        });

        test('an audit follows the selected run and cancellation confirms its actual target', async () => {
          await loadAndSelect();
          const audit = id => ({ok: true, status: 200, json: async () => ({run_id: id})});
          mockFetch = async () => audit(runId);
          await inspect();
          assert.equal(JSON.parse(elements.result.textContent).run_id, runId);
          let resolveOlder;
          mockFetch = () => new Promise(resolve => { resolveOlder = resolve; });
          const older = inspect();

          select.value = otherRunId;
          select.fire('change');
          assert.equal(elements.result.textContent, '');
          mockFetch = async () => audit(otherRunId);
          await inspect();
          resolveOlder(audit(runId));
          await older;
          assert.equal(JSON.parse(elements.result.textContent).run_id, otherRunId);

          mockFetch = async (path, options) => {
            assert.equal(path, '/api/runs/' + otherRunId + '/cancel');
            assert.equal(options.method, 'POST');
            return audit(otherRunId);
          };
          await elements.cancel.fire('click');
          assert.deepEqual(confirmations, ['Cancel run ' + otherRunId + '?']);
          assert.equal(JSON.parse(elements.result.textContent).run_id, otherRunId);

          mockFetch = async () => ({ok: true, json: async () => ({...payload, runs: []})});
          await refresh();
          assert.equal(select.value, '');
          assert.equal(elements.run.value, '');
        });

        test('dispatch pause and resume are scoped to the selected run and disclose their limit', async () => {
          await loadAndSelect();
          elements.token.value = 'operator-secret';
          mockFetch = async (path, options) => {
            assert.equal(path, '/api/runs/' + runId + '/dispatch');
            assert.equal(options.method, 'GET');
            return {ok: true, status: 200, json: async () => ({
              run_id: runId, dispatch_paused: false,
              scope: 'queued_specialist_dispatch_only', history: [],
            })};
          };
          await dispatchStatus();
          assert.equal(JSON.parse(elements['dispatch-result'].textContent).dispatch_paused, false);
          mockFetch = async (path, options) => {
            assert.equal(path, '/api/runs/' + runId + '/dispatch/pause');
            assert.equal(options.method, 'POST');
            return {ok: true, status: 200, json: async () => ({
              run_id: runId, dispatch_paused: true, scope: 'queued_specialist_dispatch_only',
            })};
          };
          await pauseDispatch();
          assert.equal(confirmations.at(-1),
            'Pause new specialist dispatch for run ' + runId + '? Running specialists continue.');
          assert.equal(JSON.parse(elements.result.textContent).dispatch_paused, true);
          mockFetch = async (path, options) => {
            assert.equal(path, '/api/runs/' + runId + '/dispatch/resume');
            assert.equal(options.method, 'POST');
            return {ok: true, status: 200, json: async () => ({
              run_id: runId, dispatch_paused: false, scope: 'queued_specialist_dispatch_only',
            })};
          };
          await resumeDispatch();
          assert.equal(JSON.parse(elements.result.textContent).dispatch_paused, false);
          mockFetch = async path => ({ok: true, status: 200, json: async () => ({
            run_id: runId, dispatch_paused: false, scope: 'queued_specialist_dispatch_only',
            history: [{action: 'pause', updated: 1}, {action: 'resume', updated: 2}],
          })});
          await dispatchStatus();
          assert.deepEqual(JSON.parse(elements['dispatch-result'].textContent).history.map(item => item.action),
            ['pause', 'resume']);
        });

        test('selected dispatch state and control history reload on selection and refresh', async () => {
          const calls = [];
          mockFetch = async path => {
            calls.push(path);
            if (path === '/api/runs?limit=20') return success();
            return {ok: true, status: 200, json: async () => ({
              run_id: runId, dispatch_paused: true,
              scope: 'queued_specialist_dispatch_only',
              history: [{action: 'pause', updated: 10}, {action: 'resume', updated: 20}],
            })};
          };
          await refresh();
          select.value = runId;
          select.fire('change');
          await dispatchStatus();
          assert.equal(calls.at(-1), '/api/runs/' + runId + '/dispatch');
          assert.deepEqual(JSON.parse(elements['dispatch-result'].textContent).history.map(item => item.action),
            ['pause', 'resume']);
          await refresh();
          assert.equal(calls.at(-1), '/api/runs/' + runId + '/dispatch');
          assert.equal(JSON.parse(elements['dispatch-result'].textContent).dispatch_paused, true);
        });

        test('a delayed cancellation result cannot replace another run audit', async () => {
          await loadAndSelect();
          let resolveCancel;
          mockFetch = (path, options) => {
            assert.equal(path, '/api/runs/' + runId + '/cancel');
            assert.equal(options.method, 'POST');
            return new Promise(resolve => { resolveCancel = resolve; });
          };
          const pendingCancel = elements.cancel.fire('click');
          assert.equal(confirmations.at(-1), 'Cancel run ' + runId + '?');
          assert.equal(typeof resolveCancel, 'function');

          select.value = otherRunId;
          select.fire('change');
          const audit = {run_id: otherRunId, status: 'planning'};
          mockFetch = async () => ({ok: true, status: 200, json: async () => audit});
          await inspect();
          resolveCancel({ok: true, status: 200, json: async () => ({
            run_id: runId, status: 'cancelled',
          })});
          await pendingCancel;
          assert.deepEqual(JSON.parse(elements.result.textContent), audit);
        });

        test('credential retention preview ignores stale age and authorization responses', async () => {
          elements.token.value = 'operator-secret';
          elements['retention-age'].value = '30';
          let resolveOlder;
          mockFetch = (path, options) => {
            assert.equal(path, '/api/credentials/retention?older_than_days=30');
            assert.equal(options.method, 'GET');
            return new Promise(resolve => { resolveOlder = resolve; });
          };
          const older = retentionPreview();
          elements['retention-age'].value = '31';
          elements['retention-age'].fire('input');
          assert.equal(elements.result.textContent, '');

          const current = {applied: false, older_than_days: 31, eligible_credentials: 2};
          mockFetch = async (path, options) => {
            assert.equal(path, '/api/credentials/retention?older_than_days=31');
            assert.equal(options.method, 'GET');
            return {ok: true, status: 200, json: async () => current};
          };
          await retentionPreview();
          resolveOlder({ok: true, status: 200, json: async () => ({
            applied: false, older_than_days: 30, eligible_credentials: 1,
          })});
          await older;
          assert.deepEqual(JSON.parse(elements.result.textContent), current);

          let resolveProtected;
          mockFetch = () => new Promise(resolve => { resolveProtected = resolve; });
          const pending = retentionPreview();
          elements.token.value = '';
          elements.token.fire('input');
          assert.equal(elements.result.textContent, '');
          resolveProtected({ok: true, status: 200, json: async () => ({
            applied: false, older_than_days: 31, eligible_credentials: 99,
          })});
          await pending;
          assert.equal(elements.result.textContent, '');
        });

        test('retention and run views share one output freshness generation', async () => {
          await loadAndSelect();
          elements.token.value = 'operator-secret';
          elements['retention-age'].value = '30';
          let resolveRetention;
          mockFetch = path => {
            assert.equal(path, '/api/credentials/retention?older_than_days=30');
            return new Promise(resolve => { resolveRetention = resolve; });
          };
          const pendingRetention = retentionPreview();

          const audit = {run_id: runId, status: 'planning'};
          mockFetch = async path => {
            assert.equal(path, '/api/runs/' + runId + '/audit');
            return {ok: true, status: 200, json: async () => audit};
          };
          await inspect();
          resolveRetention({ok: true, status: 200, json: async () => ({
            applied: false, older_than_days: 30, eligible_credentials: 1,
          })});
          await pendingRetention;
          assert.deepEqual(JSON.parse(elements.result.textContent), audit);

          let resolveAudit;
          mockFetch = () => new Promise(resolve => { resolveAudit = resolve; });
          const pendingAudit = inspect();
          const retention = {applied: false, older_than_days: 30, eligible_credentials: 2};
          mockFetch = async path => {
            assert.equal(path, '/api/credentials/retention?older_than_days=30');
            return {ok: true, status: 200, json: async () => retention};
          };
          await retentionPreview();
          resolveAudit({ok: true, status: 200, json: async () => audit});
          await pendingAudit;
          assert.deepEqual(JSON.parse(elements.result.textContent), retention);
        });
        """],
        input=script,
        check=True,
        timeout=10,
    )


def test_server_startup_migrates_legacy_run_discovery_index(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite"
    _session, run_id = _start_run(database)
    with sqlite3.connect(database) as db:
        db.execute("DROP INDEX events_latest_by_timestamp")

    with server_for(database) as port:
        status, _headers, body = request(port, "GET", "/api/runs", token=TOKEN)
        assert status == 200
        assert json.loads(body)["runs"][0]["run_id"] == run_id
    with sqlite3.connect(database) as db:
        indexes = {row[1] for row in db.execute("PRAGMA index_list(events)")}
    assert "events_latest_by_timestamp" in indexes

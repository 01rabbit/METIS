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

from metis.core.codex_session import CodexSession
from metis.core.contracts import ChallengeManifest, RunEvent, RunStatus
from metis.core.operator_ui import create_server
from metis.core.store import RunStore

RUN_ID = "a" * 32
TOKEN = "secret-operator-token-with-32-chars-minimum"


@contextmanager
def server_for(database: Path, *, cancel_run=None):
    server = create_server(database, port=0, token=TOKEN, cancel_run=cancel_run)
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


def test_run_list_is_authenticated_bounded_redacted_and_read_only(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite"
    session, first_id = _start_run(database)
    time.sleep(0.002)
    _session, second_id = _start_run(database)
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
def test_run_list_rejects_blob_in_event_text_column(tmp_path: Path, field: str) -> None:
    database = fixture_database(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("DROP TRIGGER deny_update")
        db.execute(f"UPDATE events SET {field} = CAST({field} AS BLOB)")
    with server_for(database) as port:
        status, _headers, body = request(port, "GET", "/api/runs", token=TOKEN)
        assert status == 503
        assert body == b"run list unavailable"


def test_script_clears_protected_view_after_auth_failure(tmp_path: Path) -> None:
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
          ['token', 'run', 'result', 'run-list', 'refresh', 'inspect', 'cancel']
            .map(id => [id, new Element()])
        );
        const document = {
          getElementById: id => elements[id],
          createElement: () => new Element(),
        };
        class Option {
          constructor(textContent, value) { Object.assign(this, {textContent, value}); }
        }
        let mockFetch;
        runInNewContext(readFileSync(0, 'utf8'), {document, Option, fetch: () => mockFetch()});

        const select = elements['run-list'];
        const runId = 'a'.repeat(32);
        const payload = {runs: [{run_id: runId, status: 'planning'}], truncated: false};
        const success = () => ({ok: true, status: 200, json: async () => payload});
        const refresh = () => elements.refresh.fire('click');
        const deny = status => { mockFetch = async () => ({ok: false, status}); };

        async function loadAndSelect() {
          mockFetch = async () => success();
          await refresh();
          assert.equal(select.options.length, 2);
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

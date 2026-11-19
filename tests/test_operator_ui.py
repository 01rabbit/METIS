"""Local operator view exposes safe audit and authenticated cancellation projections."""
from __future__ import annotations

import http.client
import json
import sqlite3
import threading
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

"""Local operator view exposes only authenticated, read-only audit projections."""
from __future__ import annotations

import http.client
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from metis.core.contracts import RunEvent, RunStatus
from metis.core.operator_ui import create_server
from metis.core.store import RunStore

RUN_ID = "a" * 32
TOKEN = "secret-operator-token-with-32-chars-minimum"


@contextmanager
def server_for(database: Path):
    server = create_server(database, port=0, token=TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(port: int, method: str, path: str, *, token: str | None = None,
            host: str | None = None, origin: str | None = None) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    headers = {"Host": host or f"127.0.0.1:{port}"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    if origin is not None:
        headers["Origin"] = origin
    conn.request(method, path, headers=headers)
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
        assert status == 200 and b"METIS audit" in page
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

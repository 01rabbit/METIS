"""Loopback-only operator audit and run-cancellation view."""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

from metis.core.store import RunStore

RUN_AUDIT = re.compile(r"/api/runs/([0-9a-f]{32})/audit")
RUN_CANCEL = re.compile(r"/api/runs/([0-9a-f]{32})/cancel")


def create_server(database: Path, *, port: int, token: str,
                  cancel_run: Callable[[str], dict[str, Any]] | None = None
                  ) -> ThreadingHTTPServer:
    """Bind only 127.0.0.1; the caller owns the server lifetime."""
    if database.is_symlink() or not database.is_file():
        raise ValueError("operator database unavailable")
    if not 0 <= port <= 65_535:
        raise ValueError("invalid operator port")
    if len(token) < 32 or len(token) > 512 or any(ord(char) < 33 for char in token):
        raise ValueError("operator token must be 32..512 visible characters")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: Any) -> None:
            pass  # No URL, token or run metadata in server logs.

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'none'; connect-src 'self'; "
                             "script-src 'self'; "
                             "style-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            return self.headers.get("Host") == f"127.0.0.1:{cast(ThreadingHTTPServer, self.server).server_port}"

        def _origin_ok(self) -> bool:
            origin = self.headers.get("Origin")
            expected = f"http://127.0.0.1:{cast(ThreadingHTTPServer, self.server).server_port}"
            return origin is None or origin == expected

        def do_GET(self) -> None:
            if not self._host_ok() or self.headers.get("Origin") is not None:
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            if self.path == "/":
                self._send(200, _PAGE, "text/html; charset=utf-8")
                return
            if self.path == "/operator.js":
                self._send(200, _SCRIPT, "text/javascript; charset=utf-8")
                return
            match = RUN_AUDIT.fullmatch(self.path)
            if match is None:
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            supplied = self.headers.get("Authorization", "")
            if not secrets.compare_digest(supplied, "Bearer " + token):
                self._send(401, b"unauthorized", "text/plain; charset=utf-8")
                return
            try:
                result = RunStore(database, read_only=True).audit_summary(match.group(1))
            except (OSError, ValueError, sqlite3.Error):
                self._send(503, b"audit unavailable", "text/plain; charset=utf-8")
                return
            if result is None:
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            self._send(200, json.dumps(result, sort_keys=True).encode(),
                       "application/json; charset=utf-8")

        def do_POST(self) -> None:
            if not self._host_ok() or not self._origin_ok():
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            match = RUN_CANCEL.fullmatch(self.path)
            if match is None:
                if RUN_AUDIT.fullmatch(self.path) is not None:
                    self._send(405, b"read-only", "text/plain; charset=utf-8")
                    return
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            supplied = self.headers.get("Authorization", "")
            if not secrets.compare_digest(supplied, "Bearer " + token):
                self._send(401, b"unauthorized", "text/plain; charset=utf-8")
                return
            if (self.headers.get("Transfer-Encoding") is not None
                    or self.headers.get("Content-Length", "0") != "0"):
                self.close_connection = True
                self._send(400, b"empty request required", "text/plain; charset=utf-8")
                return
            if cancel_run is None:
                self._send(503, b"cancellation unavailable", "text/plain; charset=utf-8")
                return
            run_id = match.group(1)
            try:
                result = cancel_run(run_id)
            except ValueError:
                self._send(404, b"run unavailable", "text/plain; charset=utf-8")
                return
            except (OSError, RuntimeError, sqlite3.Error):
                self._send(503, b"cancellation unavailable", "text/plain; charset=utf-8")
                return
            if not isinstance(result, dict):
                self._send(503, b"cancellation status unavailable", "text/plain; charset=utf-8")
                return
            worker = result.get("worker_teardown")
            worker_status = worker.get("status") if isinstance(worker, dict) else None
            run_status = result.get("status")
            if (run_status not in {"cancelled", "solved", "exhausted", "error", "policy_denied"}
                    or worker_status not in {"not_running", "confirmed", "unknown"}):
                self._send(503, b"cancellation status unavailable", "text/plain; charset=utf-8")
                return
            status = 202 if worker_status == "unknown" else 200
            body = json.dumps({"run_id": run_id, "status": run_status,
                               "worker_teardown": {"status": worker_status}},
                              sort_keys=True).encode()
            self._send(status, body, "application/json; charset=utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


_PAGE = """<!doctype html><html lang="ja"><meta charset="utf-8"><title>METIS operator</title>
<h1>METIS operator</h1><p>認証済みローカル操作: 監査表示とrunのキャンセル。</p>
<label>Operator token <input id="token" type="password" autocomplete="off"></label>
<label>Run ID <input id="run" maxlength="32" spellcheck="false"></label>
<button id="inspect">Inspect</button><button id="cancel">Cancel run</button><pre id="result"></pre>
<script src="/operator.js"></script></html>""".encode()

_SCRIPT = b"""document.getElementById('inspect').addEventListener('click', async () => {
  const token = document.getElementById('token').value;
  const run = document.getElementById('run').value;
  const output = document.getElementById('result');
  if (!/^[0-9a-f]{32}$/.test(run)) { output.textContent = 'Invalid run ID'; return; }
  try {
    const response = await fetch('/api/runs/' + run + '/audit',
      {headers: {'Authorization': 'Bearer ' + token}, cache: 'no-store'});
    output.textContent = response.ok ? JSON.stringify(await response.json(), null, 2)
      : 'Audit unavailable (' + response.status + ')';
  } catch (_) { output.textContent = 'Audit unavailable'; }
});
document.getElementById('cancel').addEventListener('click', async () => {
  const token = document.getElementById('token').value;
  const run = document.getElementById('run').value;
  const output = document.getElementById('result');
  if (!/^[0-9a-f]{32}$/.test(run)) { output.textContent = 'Invalid run ID'; return; }
  if (!window.confirm('Cancel this run?')) return;
  try {
    const response = await fetch('/api/runs/' + run + '/cancel',
      {method: 'POST', headers: {'Authorization': 'Bearer ' + token}, cache: 'no-store'});
    output.textContent = response.ok ? JSON.stringify(await response.json(), null, 2)
      : 'Cancellation unavailable (' + response.status + ')';
  } catch (_) { output.textContent = 'Cancellation unavailable'; }
});"""

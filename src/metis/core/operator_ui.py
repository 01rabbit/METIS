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

from metis.core.store import RunStore, ensure_run_audit_list_index

RUN_AUDIT = re.compile(r"/api/runs/([0-9a-f]{32})/audit")
RUN_CANCEL = re.compile(r"/api/runs/([0-9a-f]{32})/cancel")
RUN_LIST = re.compile(r"/api/runs(?:\?limit=(\d{1,3}))?")


def create_server(database: Path, *, port: int, token: str,
                  cancel_run: Callable[[str], dict[str, Any]] | None = None
                  ) -> ThreadingHTTPServer:
    """Bind only 127.0.0.1; the caller owns the server lifetime."""
    if database.is_symlink() or not database.is_file():
        raise ValueError("operator database unavailable")
    if not 0 <= port <= 65_535:
        raise ValueError("invalid operator port")
    if len(token) < 32 or len(token) > 512 or any(not 33 <= ord(char) <= 126 for char in token):
        raise ValueError("operator token must be 32..512 visible ASCII characters")
    ensure_run_audit_list_index(database)

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

        def _authenticated(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            try:
                supplied_bytes = supplied.encode("ascii")
            except UnicodeEncodeError:
                return False
            return secrets.compare_digest(supplied_bytes, ("Bearer " + token).encode("ascii"))

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
            if self.path == "/api/runs" or self.path.startswith("/api/runs?"):
                if not self._authenticated():
                    self._send(401, b"unauthorized", "text/plain; charset=utf-8")
                    return
                match = RUN_LIST.fullmatch(self.path)
                if match is None:
                    self._send(400, b"invalid run list query", "text/plain; charset=utf-8")
                    return
                limit = int(match.group(1) or "20")
                if not 1 <= limit <= 100:
                    self._send(400, b"invalid run list query", "text/plain; charset=utf-8")
                    return
                try:
                    summaries, truncated = RunStore(database, read_only=True).list_audit_summaries(
                        limit=limit,
                    )
                except (OSError, ValueError, sqlite3.Error):
                    self._send(503, b"run list unavailable", "text/plain; charset=utf-8")
                    return
                runs = []
                for summary in summaries:
                    run_id = summary["run_id"]
                    if not isinstance(run_id, str) or re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
                        continue
                    runs.append({"run_id": run_id, "status": summary["status"],
                                 "last_timestamp": summary["last_timestamp"],
                                 "codex_budget": summary["codex_budget"]})
                body = json.dumps({"runs": runs, "truncated": truncated}, sort_keys=True).encode()
                self._send(200, body, "application/json; charset=utf-8")
                return
            match = RUN_AUDIT.fullmatch(self.path)
            if match is None:
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            if not self._authenticated():
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
            if not self._authenticated():
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
<button id="refresh">List recent runs</button>
<label>Recent runs <select id="run-list"><option value="">Select a run</option></select></label>
<label>Run ID <input id="run" maxlength="32" spellcheck="false"></label>
<button id="inspect">Inspect</button><button id="cancel">Cancel run</button><pre id="result"></pre>
<script src="/operator.js"></script></html>""".encode()

_SCRIPT = b"""const tokenInput = document.getElementById('token');
const runInput = document.getElementById('run');
const output = document.getElementById('result');
const select = document.getElementById('run-list');
let authorizationGeneration = 0;
let latestListRequest = 0;
let selectedRunId = '';

function clearProtectedView() {
  authorizationGeneration++;
  select.replaceChildren(new Option('Select a run', ''));
  runInput.value = '';
  selectedRunId = '';
  output.textContent = '';
}

tokenInput.addEventListener('input', clearProtectedView);

async function operatorRequest(path, method, label, render, isLatest = () => true) {
  const generation = authorizationGeneration;
  const token = tokenInput.value;
  const isCurrent = () => generation === authorizationGeneration
    && token === tokenInput.value && isLatest();
  try {
    const response = await fetch(path,
      {method, headers: {'Authorization': 'Bearer ' + token}, cache: 'no-store'});
    if (!isCurrent()) return;
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) clearProtectedView();
      output.textContent = label + ' unavailable (' + response.status + ')';
      return;
    }
    const payload = await response.json();
    if (isCurrent()) render(payload);
  } catch (_) {
    if (isCurrent()) output.textContent = label + ' unavailable';
  }
}

document.getElementById('refresh').addEventListener('click', () => {
  const request = ++latestListRequest;
  return operatorRequest('/api/runs?limit=20', 'GET', 'Run list', payload => {
    if (!Array.isArray(payload.runs)) { output.textContent = 'Run list unavailable'; return; }
    select.replaceChildren(new Option('Select a run', ''));
    for (const run of payload.runs) {
      if (!/^[0-9a-f]{32}$/.test(run.run_id) || typeof run.status !== 'string') continue;
      const option = document.createElement('option');
      option.value = run.run_id;
      const budget = run.codex_budget;
      const timestamp = typeof run.last_timestamp === 'string' ? ' | ' + run.last_timestamp : '';
      const remaining = budget ? ' | ' + budget.actions_remaining + '/' + budget.max_actions + ' actions' : '';
      option.textContent = run.status + ' | ' + run.run_id.slice(0, 8) + timestamp + remaining;
      select.append(option);
    }
    if (Array.from(select.options).some(option => option.value === selectedRunId)) {
      select.value = selectedRunId;
    }
    const count = select.options.length - 1;
    output.textContent = payload.truncated
      ? 'Loaded ' + count + ' recent runs; list is partial at the safety limit'
      : 'Loaded ' + count + ' runs';
  }, () => request === latestListRequest);
});
select.addEventListener('change', () => {
  selectedRunId = select.value;
  runInput.value = selectedRunId;
});
runInput.addEventListener('input', () => {
  if (runInput.value !== selectedRunId) {
    selectedRunId = '';
    select.value = '';
  }
});

function showResult(payload) {
  output.textContent = JSON.stringify(payload, null, 2);
}

document.getElementById('inspect').addEventListener('click', () => {
  const run = runInput.value;
  if (!/^[0-9a-f]{32}$/.test(run)) { output.textContent = 'Invalid run ID'; return; }
  return operatorRequest('/api/runs/' + run + '/audit', 'GET', 'Audit', showResult);
});
document.getElementById('cancel').addEventListener('click', () => {
  const run = runInput.value;
  if (!/^[0-9a-f]{32}$/.test(run)) { output.textContent = 'Invalid run ID'; return; }
  if (!window.confirm('Cancel this run?')) return;
  return operatorRequest('/api/runs/' + run + '/cancel', 'POST', 'Cancellation', showResult);
});"""

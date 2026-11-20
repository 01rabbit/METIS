"""Loopback-only operator audit and run-cancellation view."""
from __future__ import annotations

import json
import math
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
RUN_DISPATCH_CONTROL = re.compile(r"/api/runs/([0-9a-f]{32})/dispatch/(pause|resume)")
RUN_DISPATCH_STATUS = re.compile(r"/api/runs/([0-9a-f]{32})/dispatch")
RUN_LIST = re.compile(r"/api/runs(?:\?limit=(\d{1,3}))?")
CREDENTIAL_RETENTION = re.compile(r"/api/credentials/retention\?older_than_days=([1-9][0-9]{0,4})")
RETENTION_COUNTS = (
    "credentials_considered", "eligible_credentials", "newer_credentials_retained",
    "age_unknown_retained", "selected_runs", "cookie_jars_selected",
)


def _dispatch_control_projection(result: Any, *, run_id: str,
                                 expected_paused: bool | None = None) -> dict[str, Any]:
    if (not isinstance(result, dict) or result.get("run_id") != run_id
            or type(result.get("dispatch_paused")) is not bool
            or result.get("scope") != "queued_specialist_dispatch_only"
            or (expected_paused is not None and result["dispatch_paused"] is not expected_paused)):
        raise ValueError("dispatch control returned an invalid state")
    history = result.get("history")
    if not isinstance(history, list) or len(history) > 20:
        raise ValueError("dispatch control returned invalid history")
    projected_history = []
    for event in history:
        if (not isinstance(event, dict) or event.get("action") not in {"pause", "resume"}
                or type(event.get("updated")) not in (int, float)
                or not math.isfinite(event["updated"])):
            raise ValueError("dispatch control returned invalid history")
        projected_history.append({"action": event["action"], "updated": event["updated"]})
    return {"run_id": run_id, "dispatch_paused": result["dispatch_paused"],
            "scope": "queued_specialist_dispatch_only", "history": projected_history}


def _credential_retention_projection(result: dict[str, Any], *, older_than_days: int) -> dict[str, Any]:
    """Expose only bounded count fields from a local, preview-only retention result."""
    if (result.get("applied") is not False or type(result.get("older_than_days")) is not int
            or result["older_than_days"] != older_than_days
            or result.get("wal_cleanup_complete") is not None):
        raise ValueError("credential retention preview returned an invalid result")
    payload: dict[str, Any] = {"applied": False, "older_than_days": older_than_days}
    for field in RETENTION_COUNTS:
        value = result.get(field)
        if type(value) is not int or value < 0:
            raise ValueError("credential retention preview returned invalid counts")
        payload[field] = value
    sidecars = result.get("sqlite_wal_sidecars_may_be_created")
    if type(sidecars) is not bool:
        raise ValueError("credential retention preview omitted WAL status")
    payload["sqlite_wal_sidecars_may_be_created"] = sidecars
    payload["note"] = (
        "Preview only; credentials remain unchanged. "
        + ("WAL-mode read may create or update SQLite -wal/-shm coordination sidecars."
           if sidecars else "This read-only preview did not require WAL sidecars.")
    )
    return payload


def create_server(database: Path, *, port: int, token: str,
                  cancel_run: Callable[[str], dict[str, Any]] | None = None,
                  dispatch_control: Callable[[str, bool], dict[str, Any]] | None = None,
                  dispatch_status: Callable[[str], dict[str, Any]] | None = None,
                  credential_retention_preview: Callable[[int], dict[str, Any]] | None = None,
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
            if self.path == "/api/credentials/retention" or self.path.startswith(
                "/api/credentials/retention?",
            ):
                if not self._authenticated():
                    self._send(401, b"unauthorized", "text/plain; charset=utf-8")
                    return
                match = CREDENTIAL_RETENTION.fullmatch(self.path)
                if match is None or int(match.group(1)) > 36_500:
                    self._send(400, b"invalid credential retention query", "text/plain; charset=utf-8")
                    return
                if credential_retention_preview is None:
                    self._send(503, b"credential retention preview unavailable", "text/plain; charset=utf-8")
                    return
                older_than_days = int(match.group(1))
                try:
                    retention_result = credential_retention_preview(older_than_days)
                    if not isinstance(retention_result, dict):
                        raise TypeError("invalid preview")
                    retention_payload = _credential_retention_projection(
                        retention_result, older_than_days=older_than_days,
                    )
                except (OSError, TypeError, ValueError, sqlite3.Error):
                    self._send(503, b"credential retention preview unavailable", "text/plain; charset=utf-8")
                    return
                self._send(200, json.dumps(retention_payload, sort_keys=True).encode(),
                           "application/json; charset=utf-8")
                return
            dispatch_match = RUN_DISPATCH_STATUS.fullmatch(self.path)
            if dispatch_match is not None:
                if not self._authenticated():
                    self._send(401, b"unauthorized", "text/plain; charset=utf-8")
                    return
                if dispatch_status is None:
                    self._send(503, b"dispatch status unavailable", "text/plain; charset=utf-8")
                    return
                run_id = dispatch_match.group(1)
                try:
                    if RunStore(database, read_only=True).audit_summary(run_id) is None:
                        self._send(404, b"run unavailable", "text/plain; charset=utf-8")
                        return
                except (OSError, ValueError, sqlite3.Error):
                    self._send(503, b"dispatch status unavailable", "text/plain; charset=utf-8")
                    return
                try:
                    dispatch_result = dispatch_status(run_id)
                except (OSError, RuntimeError, ValueError, sqlite3.Error):
                    self._send(503, b"dispatch status unavailable", "text/plain; charset=utf-8")
                    return
                try:
                    projection = _dispatch_control_projection(dispatch_result, run_id=run_id)
                except (TypeError, ValueError):
                    self._send(503, b"dispatch status unavailable", "text/plain; charset=utf-8")
                    return
                self._send(200, json.dumps(projection, sort_keys=True).encode(),
                           "application/json; charset=utf-8")
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
            cancel_match = RUN_CANCEL.fullmatch(self.path)
            control_match = RUN_DISPATCH_CONTROL.fullmatch(self.path)
            if cancel_match is None and control_match is None:
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
            if control_match is not None:
                if dispatch_control is None:
                    self._send(503, b"dispatch control unavailable", "text/plain; charset=utf-8")
                    return
                run_id = control_match.group(1)
                paused = control_match.group(2) == "pause"
                try:
                    if RunStore(database, read_only=True).audit_summary(run_id) is None:
                        self._send(404, b"run unavailable", "text/plain; charset=utf-8")
                        return
                except (OSError, ValueError, sqlite3.Error):
                    self._send(503, b"dispatch control unavailable", "text/plain; charset=utf-8")
                    return
                try:
                    result = dispatch_control(run_id, paused)
                except (OSError, RuntimeError, ValueError, sqlite3.Error):
                    self._send(503, b"dispatch control unavailable", "text/plain; charset=utf-8")
                    return
                try:
                    projection = _dispatch_control_projection(
                        result, run_id=run_id, expected_paused=paused,
                    )
                except (TypeError, ValueError):
                    self._send(503, b"dispatch control status unavailable", "text/plain; charset=utf-8")
                    return
                body = json.dumps(projection, sort_keys=True).encode()
                self._send(200, body, "application/json; charset=utf-8")
                return
            if cancel_run is None:
                self._send(503, b"cancellation unavailable", "text/plain; charset=utf-8")
                return
            assert cancel_match is not None
            run_id = cancel_match.group(1)
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
<h1>METIS operator</h1><p>認証済みローカル操作: 資格情報整理のプレビュー、監査表示、専門家dispatchのpause/resume、runのキャンセル。</p>
<label>Operator token <input id="token" type="password" autocomplete="off"></label>
<label>Credential age (days) <input id="retention-age" type="number" min="1" max="36500" value="90"></label>
<button id="retention-preview">Preview credential retention</button>
<button id="refresh">List recent runs</button>
<label>Recent runs <select id="run-list"><option value="">Select a run</option></select></label>
<label>Run ID <input id="run" maxlength="32" spellcheck="false"></label>
<button id="inspect">Inspect</button><button id="dispatch-status">Check dispatch</button>
<button id="pause-dispatch">Pause queued specialists</button>
<button id="resume-dispatch">Resume queued specialists</button><button id="cancel">Cancel run</button>
<pre id="dispatch-result"></pre><pre id="result"></pre>
<script src="/operator.js"></script></html>""".encode()

_SCRIPT = b"""const tokenInput = document.getElementById('token');
const runInput = document.getElementById('run');
const output = document.getElementById('result');
const dispatchOutput = document.getElementById('dispatch-result');
const select = document.getElementById('run-list');
const retentionAge = document.getElementById('retention-age');
let authorizationGeneration = 0;
let latestListRequest = 0;
let latestRunRequest = 0;
let latestDispatchRequest = 0;
let latestRetentionRequest = 0;
let latestOutputRequest = 0;
let selectedRunId = '';

function claimOutput() {
  return ++latestOutputRequest;
}

function clearProtectedView() {
  authorizationGeneration++;
  claimOutput();
  latestDispatchRequest++;
  select.replaceChildren(new Option('Select a run', ''));
  runInput.value = '';
  selectedRunId = '';
  output.textContent = '';
  dispatchOutput.textContent = '';
}

tokenInput.addEventListener('input', clearProtectedView);
retentionAge.addEventListener('input', () => {
  latestRetentionRequest++;
  claimOutput();
  output.textContent = '';
});

async function operatorRequest(path, method, label, render, isLatest = () => true, target = output) {
  const generation = authorizationGeneration;
  const token = tokenInput.value;
  const sameAuthorization = () => generation === authorizationGeneration && token === tokenInput.value;
  try {
    const response = await fetch(path,
      {method, headers: {'Authorization': 'Bearer ' + token}, cache: 'no-store'});
    if (!sameAuthorization()) return;
    if (response.status === 401 || response.status === 403) {
      clearProtectedView();
      target.textContent = label + ' unavailable (' + response.status + ')';
      return;
    }
    if (!isLatest()) return;
    if (!response.ok) {
      target.textContent = label + ' unavailable (' + response.status + ')';
      return;
    }
    const payload = await response.json();
    if (sameAuthorization() && isLatest()) await render(payload);
  } catch (_) {
    if (sameAuthorization() && isLatest()) target.textContent = label + ' unavailable';
  }
}

function invalidateRunView() {
  latestRunRequest++;
  latestDispatchRequest++;
  claimOutput();
  output.textContent = '';
  dispatchOutput.textContent = '';
}

function loadDispatchStatus(run) {
  const request = ++latestDispatchRequest;
  if (!/^[0-9a-f]{32}$/.test(run)) {
    dispatchOutput.textContent = '';
    return;
  }
  return operatorRequest('/api/runs/' + run + '/dispatch', 'GET', 'Dispatch status', payload => {
    if (payload.run_id !== run || typeof payload.dispatch_paused !== 'boolean'
        || payload.scope !== 'queued_specialist_dispatch_only' || !Array.isArray(payload.history)) {
      dispatchOutput.textContent = 'Dispatch status unavailable';
      return;
    }
    dispatchOutput.textContent = JSON.stringify(payload, null, 2);
  }, () => request === latestDispatchRequest && run === runInput.value, dispatchOutput);
}

document.getElementById('refresh').addEventListener('click', () => {
  const request = ++latestListRequest;
  const outputRequest = claimOutput();
  return operatorRequest('/api/runs?limit=20', 'GET', 'Run list', async payload => {
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
    } else {
      selectedRunId = '';
      runInput.value = '';
      invalidateRunView();
    }
    const count = select.options.length - 1;
    output.textContent = payload.truncated
      ? 'Loaded ' + count + ' recent runs; list is partial at the safety limit'
      : 'Loaded ' + count + ' runs';
    if (selectedRunId) return loadDispatchStatus(selectedRunId);
  }, () => request === latestListRequest && outputRequest === latestOutputRequest);
});
select.addEventListener('change', () => {
  selectedRunId = select.value;
  runInput.value = selectedRunId;
  invalidateRunView();
});
runInput.addEventListener('input', () => {
  invalidateRunView();
  if (runInput.value !== selectedRunId) {
    selectedRunId = '';
    select.value = '';
  }
});

function showResult(payload) {
  output.textContent = JSON.stringify(payload, null, 2);
}

document.getElementById('retention-preview').addEventListener('click', () => {
  const request = ++latestRetentionRequest;
  const outputRequest = claimOutput();
  const age = retentionAge.value;
  if (!/^[1-9][0-9]{0,4}$/.test(age) || Number(age) > 36500) {
    output.textContent = 'Invalid credential retention age';
    return;
  }
  return operatorRequest('/api/credentials/retention?older_than_days=' + age,
    'GET', 'Credential retention preview', showResult,
    () => request === latestRetentionRequest && age === retentionAge.value
      && outputRequest === latestOutputRequest);
});

document.getElementById('inspect').addEventListener('click', () => {
  const request = ++latestRunRequest;
  const outputRequest = claimOutput();
  const run = runInput.value;
  if (!/^[0-9a-f]{32}$/.test(run)) { output.textContent = 'Invalid run ID'; return; }
  return operatorRequest('/api/runs/' + run + '/audit', 'GET', 'Audit', showResult,
    () => request === latestRunRequest && run === runInput.value
      && outputRequest === latestOutputRequest);
});
document.getElementById('dispatch-status').addEventListener('click', () => {
  const run = runInput.value;
  if (!/^[0-9a-f]{32}$/.test(run)) { dispatchOutput.textContent = 'Invalid run ID'; return; }
  return loadDispatchStatus(run);
});
document.getElementById('cancel').addEventListener('click', () => {
  const run = runInput.value;
  if (!/^[0-9a-f]{32}$/.test(run)) {
    claimOutput();
    output.textContent = 'Invalid run ID';
    return;
  }
  if (!window.confirm('Cancel run ' + run + '?')) return;
  const request = ++latestRunRequest;
  const outputRequest = claimOutput();
  return operatorRequest('/api/runs/' + run + '/cancel', 'POST', 'Cancellation', showResult,
    () => request === latestRunRequest && run === runInput.value
      && outputRequest === latestOutputRequest);
});

function setDispatchPaused(paused) {
  const run = runInput.value;
  if (!/^[0-9a-f]{32}$/.test(run)) {
    claimOutput();
    output.textContent = 'Invalid run ID';
    return;
  }
  const action = paused ? 'Pause' : 'Resume';
  const message = paused
    ? 'Pause new specialist dispatch for run ' + run + '? Running specialists continue.'
    : 'Resume queued specialist dispatch for run ' + run + '?';
  if (!window.confirm(message)) return;
  latestDispatchRequest++;
  dispatchOutput.textContent = '';
  const request = ++latestRunRequest;
  const outputRequest = claimOutput();
  const path = '/api/runs/' + run + '/dispatch/' + (paused ? 'pause' : 'resume');
  return operatorRequest(path, 'POST', action + ' dispatch', payload => {
    showResult(payload);
    return loadDispatchStatus(run);
  },
    () => request === latestRunRequest && run === runInput.value
      && outputRequest === latestOutputRequest);
}
document.getElementById('pause-dispatch').addEventListener('click', () => setDispatchPaused(true));
document.getElementById('resume-dispatch').addEventListener('click', () => setDispatchPaused(false));
"""

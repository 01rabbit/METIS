"""Bounded, leased read interfaces for two SIEM search APIs.

Only structured equality filters are accepted. Query language, scripts, dashboards,
rule deployment and incident mutation are deliberately outside this interface.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import ipaddress
import json
import math
import os
import re
import sqlite3
import ssl
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from metis.blue.ledger import ConnectionLedger, redact

MAX_BODY = 2 * 1024 * 1024
FIELD = r"[A-Za-z_@][A-Za-z0-9_@.]{0,127}"
INDEX = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}"
SID = r"[A-Za-z0-9_.-]{1,160}"
FINAL = {"DONE", "FAILED", "INTERNAL_CANCEL", "USER_CANCEL", "BAD_INPUT_CANCEL", "QUIT"}


class SIEMError(ValueError):
    def __init__(self, reason, status=None):
        super().__init__(reason)
        self.reason, self.status = reason, status


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SIEMError("duplicate-json-key")
        result[key] = value
    return result


def parse_json(raw):
    def bad_constant(_):
        raise SIEMError("non-finite-json-number")
    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise SIEMError("non-finite-json-number")
        return parsed
    def bounded_integer(value):
        if len(value.lstrip("-")) > 512:
            raise SIEMError("json-number-too-large")
        return int(value)
    try:
        return json.loads(raw, object_pairs_hook=strict_pairs, parse_constant=bad_constant,
                          parse_float=finite_float, parse_int=bounded_integer)
    except (ValueError, UnicodeError, RecursionError):
        raise SIEMError("invalid-json-response") from None


def sanitize(value):
    if isinstance(value, dict):
        sensitive = re.compile(r"^(?:password|passwd|api[_-]?key|secret|(?:access_|refresh_)?token|authorization|cookie|set-cookie|private_key)$", re.IGNORECASE)
        return {key: "[REDACTED]" if sensitive.fullmatch(key) else sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return redact(value) if isinstance(value, str) else value


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise SIEMError("integer-out-of-range")
    return value


def validate_profile(profile):
    keys = {"provider", "base_url", "token_env", "resource", "indexes", "fields",
            "timestamp_field", "auth_scheme", "max_rows", "page_size", "timeout_seconds",
            "max_window_seconds", "poll_interval", "ca_file", "test_only_http"}
    required = {"provider", "base_url", "token_env", "resource", "indexes", "fields"}
    if not isinstance(profile, dict) or set(profile) - keys or not required <= set(profile):
        raise SIEMError("invalid-profile-fields")
    p = dict(profile)
    if p["provider"] not in {"splunk", "elastic"}:
        raise SIEMError("unsupported-provider")
    if not isinstance(p["resource"], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", p["resource"]):
        raise SIEMError("invalid-resource")
    if not isinstance(p["token_env"], str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*_TOKEN", p["token_env"]):
        raise SIEMError("invalid-token-reference")
    for name, pattern in (("indexes", INDEX), ("fields", FIELD)):
        values = p[name]
        if not isinstance(values, list) or not 1 <= len(values) <= 64 or any(
                not isinstance(v, str) or not re.fullmatch(pattern, v) for v in values) or len(set(values)) != len(values):
            raise SIEMError("invalid-profile-allowlist")
    if not isinstance(p["base_url"], str):
        raise SIEMError("invalid-endpoint")
    parsed = urlsplit(p["base_url"])
    try:
        port = parsed.port
    except ValueError:
        raise SIEMError("invalid-endpoint") from None
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.path not in ("", "/") or any(c.isspace() for c in p["base_url"])):
        raise SIEMError("endpoint-must-be-a-bare-origin")
    if port is not None and not 1 <= port <= 65535:
        raise SIEMError("invalid-endpoint-port")
    if parsed.scheme != "https":
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = False
        if parsed.scheme != "http" or p.get("test_only_http") is not True or not loopback:
            raise SIEMError("https-required-except-explicit-loopback-test")
    if "test_only_http" in p and type(p["test_only_http"]) is not bool:
        raise SIEMError("invalid-test-mode")
    p["base_url"] = p["base_url"].rstrip("/")
    p.setdefault("auth_scheme", "Bearer")
    if p["auth_scheme"] not in ({"Bearer", "Splunk"} if p["provider"] == "splunk" else {"Bearer", "ApiKey"}):
        raise SIEMError("unsupported-auth-scheme")
    p.setdefault("timestamp_field", "_time" if p["provider"] == "splunk" else "@timestamp")
    if not isinstance(p["timestamp_field"], str) or not re.fullmatch(FIELD, p["timestamp_field"]):
        raise SIEMError("invalid-timestamp-field")
    if p["provider"] == "splunk" and p["timestamp_field"] != "_time":
        raise SIEMError("splunk-time-boundaries-use-time-field")
    for name, default, high in (("max_rows", 1000, 5000), ("page_size", 250, 1000),
                                ("timeout_seconds", 30, 120), ("max_window_seconds", 3600, 86400)):
        p[name] = integer(p.get(name, default), 1, high)
    p.setdefault("poll_interval", 0.2)
    if type(p["poll_interval"]) not in (int, float) or not 0.05 <= p["poll_interval"] <= 2:
        raise SIEMError("invalid-poll-interval")
    if "ca_file" in p and (not isinstance(p["ca_file"], str) or not p["ca_file"]):
        raise SIEMError("invalid-ca-file")
    return p


def utc(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
        raise SIEMError("utc-time-required")
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        raise SIEMError("invalid-time") from None


def validate_request(profile, request):
    if not isinstance(request, dict) or set(request) != {"index", "start", "end", "filters", "fields", "limit"}:
        raise SIEMError("only-structured-search-is-accepted")
    q = dict(request)
    if q["index"] not in profile["indexes"]:
        raise SIEMError("index-outside-profile")
    start, end = utc(q["start"]), utc(q["end"])
    if not 0 < (end - start).total_seconds() <= profile["max_window_seconds"]:
        raise SIEMError("search-window-exceeds-profile")
    if not isinstance(q["fields"], list) or not q["fields"] or any(
            f not in profile["fields"] for f in q["fields"]) or len(q["fields"]) != len(set(q["fields"])):
        raise SIEMError("fields-outside-profile")
    if not isinstance(q["filters"], dict) or len(q["filters"]) > 16:
        raise SIEMError("invalid-equality-filters")
    for field, value in q["filters"].items():
        if field not in profile["fields"] or not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_@.:/ -]{1,256}", value):
            raise SIEMError("invalid-equality-filter")
    q["limit"] = integer(q["limit"], 1, profile["max_rows"])
    return q


def search_body(profile, request):
    if profile["provider"] == "splunk":
        terms = [f'index="{request["index"]}"']
        terms.extend(f'{key}="{value}"' for key, value in sorted(request["filters"].items()))
        return "search " + " ".join(terms) + " | fields " + ",".join(request["fields"])
    filters = [{"range": {profile["timestamp_field"]: {"gte": request["start"], "lt": request["end"]}}}]
    filters.extend({"term": {key: value}} for key, value in sorted(request["filters"].items()))
    return {"query": {"bool": {"filter": filters}}, "size": request["limit"],
            "_source": request["fields"], "track_total_hits": profile["max_rows"] + 1,
            "timeout": str(profile["timeout_seconds"]) + "s"}


class Transport:
    """Direct HTTP connections: no redirects, proxies, cookies or raw error bodies."""
    def __init__(self, profile):
        self.profile = profile
        self.token = os.environ.get(profile["token_env"], "")
        if not re.fullmatch(r"[A-Za-z0-9._~+/=-]{8,8192}", self.token):
            raise SIEMError("credential-unavailable-or-invalid")
        self.url = urlsplit(profile["base_url"])
        self.context = ssl.create_default_context(cafile=profile.get("ca_file")) if self.url.scheme == "https" else None
        self.receipts = []

    def call(self, method, path, body=None, form=False, timeout=5):
        if not path.startswith("/") or path.startswith("//") or "\r" in path or "\n" in path:
            raise SIEMError("invalid-internal-endpoint")
        data = None if body is None else (urlencode(body).encode() if form else json.dumps(body).encode())
        headers = {"Authorization": self.profile["auth_scheme"] + " " + self.token,
                   "Accept": "application/json", "Accept-Encoding": "identity"}
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        cls = http.client.HTTPSConnection if self.context else http.client.HTTPConnection
        kwargs = {"context": self.context} if self.context else {}
        connection = cls(self.url.hostname, self.url.port, timeout=max(0.05, timeout), **kwargs)
        deadline = time.monotonic() + timeout
        try:
            connection.connect()
            connection.sock.settimeout(max(0.05, deadline - time.monotonic()))
            connection.request(method, path, body=data, headers=headers)
            connection.sock.settimeout(max(0.05, deadline - time.monotonic()))
            response = connection.getresponse()
            if response.status < 200 or response.status >= 300:
                raise SIEMError("http-status", response.status)
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise SIEMError("compressed-response-not-supported")
            chunks, length = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SIEMError("transport-timeout")
                # getresponse can detach a closing response socket from connection.sock.
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_BODY + 1 - length))
                if not chunk:
                    break
                chunks.append(chunk)
                length += len(chunk)
                if length > MAX_BODY:
                    raise SIEMError("response-byte-limit")
            raw = b"".join(chunks)
            self.receipts.append(hashlib.sha256(raw).hexdigest())
            return parse_json(raw)
        except SIEMError:
            raise
        except (OSError, http.client.HTTPException, ValueError):
            raise SIEMError("transport-failed") from None
        finally:
            connection.close()


def bit(value):
    if type(value) is bool:
        return value
    if type(value) in (int, str) and value in (0, "0"):
        return False
    if type(value) in (int, str) and value in (1, "1"):
        return True
    raise SIEMError("invalid-job-flag")


def count(value):
    if isinstance(value, str) and re.fullmatch(r"\d{1,18}", value):
        value = int(value)
    return integer(value, 0, 10**18)


def job_state(payload):
    try:
        if not isinstance(payload, dict) or len(payload["entry"]) != 1:
            raise SIEMError("invalid-job-status")
        content = payload["entry"][0]["content"]
        phase = content["dispatchState"]
        done, failed, finalized, zombie = [bit(content[k]) for k in ("isDone", "isFailed", "isFinalized", "isZombie")]
        if phase not in FINAL | {"QUEUED", "PARSING", "RUNNING", "FINALIZING", "PAUSE"} or zombie or (phase == "DONE" and not done):
            raise SIEMError("indeterminate-job-status")
        return {"terminal": phase in FINAL and (phase != "DONE" or done),
                "successful": phase == "DONE" and done and not failed,
                "partial": finalized or bool(content.get("messages")) or bool(payload.get("messages")),
                # Parsing/queued jobs may not have materialized result counters yet.
                "count": count(content["resultCount"]) if phase == "DONE" or "resultCount" in content else None,
                "phase": phase}
    except (KeyError, TypeError, IndexError):
        raise SIEMError("invalid-job-status") from None


def register(store, cid, profile, handle, request_hash):
    with store.transaction() as db:
        db.execute("CREATE TABLE IF NOT EXISTS siem_operations (connection TEXT PRIMARY KEY, profile_sha256 TEXT NOT NULL, handle TEXT, request_sha256 TEXT NOT NULL)")
        db.execute("INSERT INTO siem_operations VALUES(?,?,?,?)", (cid, digest(profile), handle, request_hash))


def cancel_and_confirm(transport, sid, timeout):
    try:
        transport.call("POST", "/services/search/jobs/" + sid + "/control",
                       {"action": "cancel", "output_mode": "json"}, form=True, timeout=timeout)
        try:
            state = job_state(transport.call("GET", "/services/search/jobs/" + sid + "?output_mode=json", timeout=timeout))
            return state["terminal"]
        except SIEMError as error:
            return error.status == 404
    except SIEMError:
        return False


def splunk(transport, profile, request, cid):
    sid = "metis_" + cid
    timeout = profile["timeout_seconds"]
    deadline = time.monotonic() + timeout
    rows, reasons, total, stopped = [], [], None, False
    form = {"id": sid, "search": search_body(profile, request), "output_mode": "json", "exec_mode": "normal",
            "earliest_time": str(utc(request["start"]).timestamp()), "latest_time": str(utc(request["end"]).timestamp()),
            "max_count": profile["max_rows"] + 1, "max_time": timeout, "auto_cancel": timeout,
            "enable_lookups": "false", "preview": "false"}
    try:
        payload = transport.call("POST", "/services/search/jobs", form, form=True, timeout=timeout)
        if not isinstance(payload, dict) or payload.get("sid") != sid:
            raise SIEMError("unexpected-search-identifier")
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SIEMError("search-deadline")
            state = job_state(transport.call("GET", "/services/search/jobs/" + sid + "?output_mode=json", timeout=remaining))
            if state["terminal"]:
                stopped = True
                break
            time.sleep(min(profile["poll_interval"], max(0, deadline - time.monotonic())))
        total = state["count"]
        if not state["successful"]:
            return rows, total, ["search-not-successful"], True
        if state["partial"]:
            reasons.append("backend-partial-or-warning")
        if total > request["limit"] or total >= profile["max_rows"] + 1:
            reasons.append("result-limit")
        expected = min(total, request["limit"])
        while len(rows) < expected:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SIEMError("retrieval-deadline")
            size = min(profile["page_size"], expected - len(rows))
            parameters = urlencode({"output_mode": "json", "offset": len(rows), "count": size})
            page = transport.call("GET", "/services/search/v2/jobs/" + sid + "/results?" + parameters, timeout=remaining)
            if (not isinstance(page, dict) or page.get("preview") is not False or
                    not isinstance(page.get("results"), list) or len(page["results"]) != size or
                    any(not isinstance(row, dict) for row in page["results"]) or
                    count(page.get("init_offset")) != len(rows)):
                raise SIEMError("invalid-or-short-result-page")
            if page.get("messages"):
                reasons.append("backend-result-message")
            rows.extend({k: row[k] for k in request["fields"] if k in row} for row in page["results"])
        return rows, total, sorted(set(reasons)), stopped
    except SIEMError as error:
        reasons.append(error.reason)
        if not stopped:
            stopped = cancel_and_confirm(transport, sid, min(timeout, 5))
        return rows, total, sorted(set(reasons)), stopped


def elastic(transport, profile, request):
    try:
        response = transport.call("POST", "/" + request["index"] + "/_search?allow_partial_search_results=false",
                                  search_body(profile, request), timeout=profile["timeout_seconds"] + 1)
    except SIEMError as error:
        # A lost synchronous response does not prove the server has stopped computing.
        return [], None, [error.reason], False
    try:
        shards, hits = response["_shards"], response["hits"]
        total, relation = count(hits["total"]["value"]), hits["total"]["relation"]
        if (relation not in {"eq", "gte"} or type(response["timed_out"]) is not bool or
                ("terminated_early" in response and type(response["terminated_early"]) is not bool) or
                not isinstance(hits["hits"], list) or len(hits["hits"]) > request["limit"]):
            raise SIEMError("invalid-search-result")
        shard_total, successful, failed, skipped = [count(shards.get(key, 0) if key == "skipped" else shards[key])
                                                   for key in ("total", "successful", "failed", "skipped")]
        if successful + failed > shard_total or skipped > successful or (relation == "eq" and total < len(hits["hits"])):
            raise SIEMError("inconsistent-search-completion-metadata")
        reasons = []
        if response["timed_out"]:
            reasons.append("backend-timeout")
        if response.get("terminated_early") is True:
            reasons.append("backend-early-termination")
        if failed or successful < shard_total:
            reasons.append("incomplete-shards")
        if relation != "eq" or total != len(hits["hits"]):
            reasons.append("result-limit-or-total-not-exact")
        rows = []
        for hit in hits["hits"]:
            if not isinstance(hit, dict) or not isinstance(hit.get("_source"), dict):
                raise SIEMError("invalid-search-hit")
            selected = {}
            for field in request["fields"]:
                value = hit["_source"]
                if field in value:
                    selected[field] = value[field]
                    continue
                for component in field.split("."):
                    if not isinstance(value, dict) or component not in value:
                        break
                    value = value[component]
                else:
                    selected[field] = value
            # Apply the allowlist locally as well; unexpected backend fields are discarded.
            rows.append({"_index": hit.get("_index"), "_id": hit.get("_id"), "fields": selected})
        return rows, total, reasons, True
    except (SIEMError, KeyError, TypeError, IndexError):
        return [], None, ["invalid-search-result"], False


def execute(store, run, task, profile, request):
    profile = validate_profile(profile)
    request = validate_request(profile, request)
    transport = Transport(profile)
    cid = store.begin_connection(run, task, profile["resource"], "siem-" + profile["provider"], "search", False, None)
    try:
        register(store, cid, profile, "metis_" + cid if profile["provider"] == "splunk" else None, digest(request))
    except Exception:
        store.connection_state(cid, "stopped")
        raise
    store.connection_state(cid, "running")
    if profile["provider"] == "splunk":
        rows, total, reasons, stopped = splunk(transport, profile, request, cid)
    else:
        rows, total, reasons, stopped = elastic(transport, profile, request)
    if stopped:
        store.connection_state(cid, "stopped")
    # Never log query text, authorization headers or raw backend errors.
    partial = stopped and total is not None and "search-not-successful" not in reasons
    result = {"provider": profile["provider"], "connection_id": cid, "request_sha256": digest(request),
              "status": "complete" if not reasons and stopped else "partial" if partial else "indeterminate" if not stopped else "failed",
              "complete": not reasons and stopped, "consumer_stopped": stopped, "rows": rows,
              "reported_total": total, "returned": len(rows), "reasons": reasons,
              "response_sha256": transport.receipts}
    result = sanitize(result)
    store.message(run, task, "siem", "owner", "siem-result", json.dumps({k: v for k, v in result.items() if k != "rows"}))
    return result


def reconcile(store, run, task, profile, connection_id):
    profile = validate_profile(profile)
    transport = Transport(profile)
    with store.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='siem_operations'").fetchone():
            raise SIEMError("no-siem-operations-to-reconcile")
        row = db.execute("SELECT c.*,o.profile_sha256,o.handle FROM blue_connections c JOIN siem_operations o ON c.id=o.connection WHERE c.id=? AND c.run=? AND c.task=?",
                         (connection_id, run, task)).fetchone()
    if not row or row["profile_sha256"] != digest(profile) or row["protocol"] != "siem-splunk":
        raise SIEMError("operation-not-reconcilable-with-this-profile")
    if row["state"] == "stopped":
        return {"connection_id": connection_id, "consumer_stopped": True}
    sid = row["handle"]
    if not isinstance(sid, str) or not re.fullmatch(SID, sid):
        raise SIEMError("invalid-stored-search-identifier")
    stopped = False
    try:
        stopped = job_state(transport.call("GET", "/services/search/jobs/" + sid + "?output_mode=json", timeout=5))["terminal"]
    except SIEMError:
        pass
    if not stopped:
        stopped = cancel_and_confirm(transport, sid, 5)
    if stopped:
        store.connection_state(connection_id, "stopped")
    result = {"connection_id": connection_id, "consumer_stopped": stopped}
    store.message(run, task, "siem", "owner", "siem-reconcile", json.dumps(result))
    return result


def load_json_file(path):
    if path is None or not path.is_file() or path.stat().st_size > 65536:
        raise SIEMError("bounded-input-file-required")
    with path.open("rb") as stream:
        data = stream.read(65537)
    if len(data) > 65536:
        raise SIEMError("input-too-large")
    return parse_json(data)


def add_arguments(parser):
    parser.add_argument("action", choices=["search", "reconcile"])
    parser.add_argument("--database", type=Path, default=Path(".metis-state/metis.sqlite"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--profiles", type=Path, required=True, help="JSON profiles (see docs/BLUE_TEAM.md)")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--request", type=Path, help="search: JSON request (index, start, end, filters, fields, limit)")
    parser.add_argument("--connection-id")


def run(args):
    """Print the bounded result (rows included) as JSON. Exit 0 only when complete."""
    try:
        profile = load_json_file(args.profiles)[args.profile]
        ledger = ConnectionLedger(args.database)
        if args.action == "search":
            result = execute(ledger, args.run, args.task, profile, load_json_file(args.request))
        else:
            if not args.connection_id:
                raise SIEMError("connection-id-required")
            result = reconcile(ledger, args.run, args.task, profile, args.connection_id)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("complete", result["consumer_stopped"]) else 2
    except PermissionError as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}))
        return 2
    except (SIEMError, OSError, KeyError, TypeError, ValueError, sqlite3.Error) as error:
        reason = error.reason if isinstance(error, SIEMError) else "invalid-input-or-unavailable-resource"
        print(json.dumps({"status": "blocked", "reason": reason}))
        return 2

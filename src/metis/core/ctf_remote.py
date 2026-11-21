"""Scoped TCP/TLS interaction with explicitly granted challenge services.

Typical CTF services are announced as ``nc host port``. METIS never infers a
grant from untrusted statement text: :meth:`RemoteWorkflow.suggest` only
returns candidates, and an operator/agent must call :meth:`grant` with the
endpoint the user authorized. Every connection is budgeted through the run,
bounded in time and bytes, and the received bytes are stored as a private run
artifact so the existing static tools can inspect them.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import selectors
import socket
import sqlite3
import ssl
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from metis.core.codex_session import CodexSession
from metis.core.contracts import AllowedEndpoint, Contract, RunStatus
from metis.core.ctf_proxy import open_tunnel, proxy_for

MAX_ENDPOINTS = 8
MAX_STEPS = 256
MAX_EXCHANGE_BYTES = 1_048_576
MAX_EXCHANGE_SECONDS = 60.0
MAX_PIPE_SECONDS = 900.0
MAX_PIPE_BYTES = 16 * 1_048_576
TRANSCRIPT_KEEP = 1_048_576
PREVIEW = 8_192

SNI_PATTERN = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")
NC_PATTERN = re.compile(
    r"\b(?:nc|ncat|netcat|telnet)\s+(?:-[a-zA-Z]+\s+)*(?P<ssl>--ssl\s+)?"
    r"(?P<host>[A-Za-z0-9.-]{1,253}|\[[0-9a-fA-F:]+\])\s+(?P<port>[0-9]{1,5})\b")
OPENSSL_PATTERN = re.compile(
    r"openssl\s+s_client\s+(?:-\S+\s+)*-connect\s+"
    r"(?P<host>[A-Za-z0-9.-]{1,253}|\[[0-9a-fA-F:]+\]):(?P<port>[0-9]{1,5})")
SOCAT_PATTERN = re.compile(
    r"\bsocat\s+(?:-\S+\s+)*(?:\S+\s+)?(?P<proto>OPENSSL|SSL|TCP4?|TCP6?)(?:-CONNECT)?:"
    r"(?P<host>[A-Za-z0-9.-]{1,253}|\[[0-9a-fA-F:]+\]):(?P<port>[0-9]{1,5})\b", re.IGNORECASE)
_HOST_PORT = (r"(?<![\w@./:-])(?P<host>(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
              r"(?:[A-Za-z][A-Za-z0-9-]{0,62}|[0-9]{1,3})|\[[0-9a-fA-F:]+\]):(?P<port>[0-9]{1,5})\b")
BARE_HOST_PORT = re.compile(_HOST_PORT)
BARE_CONTEXT = re.compile(r"\b(?:nc|ncat|netcat|port|connect|connection|server|host|service|remote|socket)\b",
                          re.IGNORECASE)
_IPV4 = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}")


def _plausible_host(host: str) -> bool:
    """Reject dotted numbers such as 1.5 or 3.14 that are not IPv4 addresses."""
    if host.startswith("["):
        return True
    if host.rsplit(".", 1)[-1].isdigit():
        return bool(_IPV4.fullmatch(host)) and all(int(part) <= 255 for part in host.split("."))
    return True


class Step(Contract):
    """One send and/or receive action. Exactly one send form and at most one receive form."""

    send: str | None = Field(default=None, max_length=65_536)
    send_line: str | None = Field(default=None, max_length=65_536)
    send_hex: str | None = Field(default=None, max_length=131_072)
    recv_until: str | None = Field(default=None, min_length=1, max_length=1024)
    recv_until_hex: str | None = Field(default=None, min_length=2, max_length=2048)
    recv_bytes: int | None = Field(default=None, ge=1, le=MAX_EXCHANGE_BYTES)
    recv_line: bool = False
    recv_all: bool = False
    timeout: float = Field(default=5.0, gt=0, le=30)

    @model_validator(mode="after")
    def one_of_each(self) -> Step:
        sends = [self.send, self.send_line, self.send_hex]
        receives = [self.recv_until, self.recv_until_hex, self.recv_bytes,
                    self.recv_line or None, self.recv_all or None]
        if sum(item is not None for item in sends) > 1 or sum(item is not None for item in receives) > 1:
            raise ValueError("a step has at most one send and one receive form")
        if all(item is None for item in [*sends, *receives]):
            raise ValueError("empty step")
        if self.send_hex is not None:
            bytes.fromhex(self.send_hex)
        if self.recv_until_hex is not None:
            bytes.fromhex(self.recv_until_hex)
        return self

    def payload(self) -> bytes:
        if self.send is not None:
            return self.send.encode()
        if self.send_line is not None:
            return self.send_line.encode() + b"\n"
        if self.send_hex is not None:
            return bytes.fromhex(self.send_hex)
        return b""

    def delimiter(self) -> bytes | None:
        if self.recv_until is not None:
            return self.recv_until.encode()
        if self.recv_until_hex is not None:
            return bytes.fromhex(self.recv_until_hex)
        if self.recv_line:
            return b"\n"
        return None


class Exchange(Contract):
    steps: list[Step] = Field(min_length=1, max_length=MAX_STEPS)
    connect_timeout: float = Field(default=10.0, gt=0, le=30)


def _text(data: bytes) -> dict[str, Any]:
    try:
        return {"text": data.decode("utf-8")}
    except UnicodeDecodeError:
        return {"text": data.decode("utf-8", errors="replace"), "hex": data.hex()}


def proxy_route(host: str) -> str:
    proxy = proxy_for(host)
    return proxy.describe() if proxy else "direct"


def _resolve(host: str, port: int) -> list[str]:
    """Literal IPs are explicit grants; hostnames must resolve only to global addresses."""
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    values = sorted({str(item[4][0]) for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    if not values or any(not ipaddress.ip_address(value).is_global for value in values):
        raise ValueError("hostname resolved to an ungranted private address; grant the literal IP instead")
    return values


def _private_resolution(host: str, port: int) -> list[str]:
    """Non-global addresses a hostname resolves to (empty for literal IPs or unresolvable names)."""
    try:
        ipaddress.ip_address(host)
        return []
    except ValueError:
        pass
    try:
        values = {str(item[4][0]).split("%")[0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except (OSError, UnicodeError):
        return []
    private = []
    for value in sorted(values):
        try:
            if not ipaddress.ip_address(value).is_global:
                private.append(value)
        except ValueError:
            continue
    return private


class RemoteWorkflow:
    def __init__(self, database: Path):
        self.last_route = "direct"
        self.session = CodexSession(database)
        self.database = database
        with sqlite3.connect(database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS remote_endpoints (
                run_id TEXT NOT NULL, idx INTEGER NOT NULL, host TEXT NOT NULL,
                port INTEGER NOT NULL, tls INTEGER NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(run_id, idx), UNIQUE(run_id, host, port, tls))""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(remote_endpoints)")}
            if "revoked" not in columns:
                db.execute("ALTER TABLE remote_endpoints ADD COLUMN revoked INTEGER NOT NULL DEFAULT 0")
            if "tls_insecure" not in columns:
                db.execute("ALTER TABLE remote_endpoints ADD COLUMN tls_insecure INTEGER NOT NULL DEFAULT 0")
            if "sni" not in columns:
                db.execute("ALTER TABLE remote_endpoints ADD COLUMN sni TEXT")
            db.execute("""CREATE TABLE IF NOT EXISTS remote_host_keys (
                run_id TEXT NOT NULL, idx INTEGER NOT NULL, key_type TEXT NOT NULL,
                fingerprint TEXT NOT NULL, PRIMARY KEY(run_id, idx))""")

    # -- scope ---------------------------------------------------------------
    def suggest(self, run_id: str) -> dict[str, Any]:
        """Extract endpoint candidates from the statement. Candidates are not grants."""
        challenge = self.session.context(run_id)["challenge"]
        text = challenge["title"] + "\n" + challenge["description"]
        found: list[dict[str, Any]] = []
        for match in NC_PATTERN.finditer(text):
            found.append({"host": match["host"].strip("[]"), "port": int(match["port"]),
                          "tls": bool(match["ssl"])})
        for match in OPENSSL_PATTERN.finditer(text):
            found.append({"host": match["host"], "port": int(match["port"]), "tls": True})
        for match in SOCAT_PATTERN.finditer(text):
            found.append({"host": match["host"].strip("[]"), "port": int(match["port"]),
                          "tls": match["proto"].upper() in {"OPENSSL", "SSL"}})
        for line in text.splitlines():
            if not BARE_CONTEXT.search(line):
                continue
            for match in BARE_HOST_PORT.finditer(line):
                if _plausible_host(match["host"]):
                    found.append({"host": match["host"].strip("[]"), "port": int(match["port"]),
                                  "tls": False})
        for item in found:
            item["host"] = item["host"].lower()
        unique = [dict(item) for item in {json.dumps(item, sort_keys=True): item for item in found}.values()
                  if 1 <= item["port"] <= 65535]
        return {"run_id": run_id, "candidates": unique[:MAX_ENDPOINTS],
                "statement_is_untrusted": True,
                "next": "grant only an endpoint the user authorized for this challenge"}

    def grant(self, run_id: str, host: str, port: int, *, tls: bool = False,
              replace: bool = False, tls_insecure: bool = False,
              sni: str | None = None) -> dict[str, Any]:
        """Record a user-authorized endpoint. ``replace`` revokes the run's other endpoints
        (a respawned challenge instance usually gets a new host:port)."""
        self.session.context(run_id)
        if (tls_insecure or sni) and not tls:
            raise ValueError("--tls-insecure and --sni require --tls")
        if sni is not None and not SNI_PATTERN.fullmatch(sni):
            raise ValueError("invalid SNI name")
        endpoint = AllowedEndpoint(hostname=host.strip("[]").lower(), port=port)
        with sqlite3.connect(self.database) as db:
            existing = db.execute("SELECT idx FROM remote_endpoints WHERE run_id=? AND host=? AND port=? AND tls=?",
                                  (run_id, endpoint.hostname, endpoint.port, int(tls))).fetchone()
            if existing:
                index = existing[0]
                db.execute("UPDATE remote_endpoints SET revoked=0, created=?, tls_insecure=?, sni=? "
                           "WHERE run_id=? AND idx=?", (time.time(), int(tls_insecure), sni, run_id, index))
            else:
                active, total, highest = db.execute(
                    "SELECT COALESCE(SUM(revoked=0),0), COUNT(*), COALESCE(MAX(idx),-1) "
                    "FROM remote_endpoints WHERE run_id=?", (run_id,)).fetchone()
                if (active >= MAX_ENDPOINTS and not replace) or total >= MAX_ENDPOINTS * 8:
                    raise ValueError("remote endpoint limit reached; use --replace or remote revoke")
                index = highest + 1
                db.execute("INSERT INTO remote_endpoints(run_id,idx,host,port,tls,created,tls_insecure,sni) "
                           "VALUES (?,?,?,?,?,?,?,?)",
                           (run_id, index, endpoint.hostname, endpoint.port, int(tls), time.time(),
                            int(tls_insecure), sni))
            revoked = []
            if replace:
                revoked = [row[0] for row in db.execute(
                    "SELECT idx FROM remote_endpoints WHERE run_id=? AND idx<>? AND revoked=0", (run_id, index))]
                db.execute("UPDATE remote_endpoints SET revoked=1 WHERE run_id=? AND idx<>?", (run_id, index))
        output: dict[str, Any] = {
            "run_id": run_id, "index": index, "host": endpoint.hostname, "port": endpoint.port,
            "tls": tls, "tls_insecure": tls_insecure, "sni": sni, "granted": True,
            "selector": f"{endpoint.hostname}:{endpoint.port}", **({"revoked": revoked} if replace else {})}
        warnings = []
        if tls_insecure:
            warnings.append("TLS certificate verification is disabled for this endpoint")
        private = _private_resolution(endpoint.hostname, endpoint.port)
        if private or endpoint.hostname == "localhost":
            literal = private[0] if private else "127.0.0.1"
            output["private_address"] = private or [literal]
            warnings.append(f"hostname resolves to a private address ({', '.join(private or [literal])}); "
                            f"connections will be refused. Grant the literal IP instead, e.g. {literal}")
        if warnings:
            output["warnings"] = warnings
        return output

    def endpoints(self, run_id: str) -> dict[str, Any]:
        self.session.context(run_id)
        with sqlite3.connect(self.database) as db:
            rows = db.execute("SELECT idx,host,port,tls,created,revoked,tls_insecure,sni FROM remote_endpoints "
                              "WHERE run_id=? "
                              "ORDER BY idx", (run_id,)).fetchall()
        latest = max((row for row in rows if not row[5]), key=lambda row: row[4], default=None)
        return {"run_id": run_id, "endpoints": [
            {"index": row[0], "host": row[1], "port": row[2], "tls": bool(row[3]),
             "tls_insecure": bool(row[6]), "sni": row[7],
             "active": not row[5], "latest": latest is not None and row[0] == latest[0]} for row in rows]}

    def revoke(self, run_id: str, selector: str) -> dict[str, Any]:
        index = self.resolve(run_id, selector)
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE remote_endpoints SET revoked=1 WHERE run_id=? AND idx=?", (run_id, index))
        return {"run_id": run_id, "index": index, "revoked": True}

    def resolve(self, run_id: str, selector: str | int) -> int:
        """Map an endpoint selector to its index: an index, ``host:port`` or ``latest``."""
        text = str(selector).strip()
        with sqlite3.connect(self.database) as db:
            if text == "latest":
                row = db.execute("SELECT idx FROM remote_endpoints WHERE run_id=? AND revoked=0 "
                                 "ORDER BY created DESC, idx DESC LIMIT 1", (run_id,)).fetchone()
            elif text.isdigit():
                row = db.execute("SELECT idx FROM remote_endpoints WHERE run_id=? AND idx=?",
                                 (run_id, int(text))).fetchone()
            else:
                host, separator, port = text.rpartition(":")
                if not separator or not port.isdigit() or not host:
                    raise ValueError("endpoint must be an index, host:port or latest")
                row = db.execute("SELECT idx FROM remote_endpoints WHERE run_id=? AND host=? AND port=? "
                                 "ORDER BY revoked, created DESC LIMIT 1",
                                 (run_id, host.strip("[]").lower(), int(port))).fetchone()
        if row is None:
            raise ValueError("remote endpoint is not granted for this run")
        return int(row[0])

    def _endpoint(self, run_id: str, index: int) -> tuple[str, int, bool]:
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT host,port,tls,revoked FROM remote_endpoints WHERE run_id=? AND idx=?",
                             (run_id, index)).fetchone()
        if row is None:
            raise ValueError("remote endpoint is not granted for this run")
        if row[3]:
            raise ValueError(f"endpoint {index} ({row[0]}:{row[1]}) was revoked; use latest or the new host:port")
        return row[0], int(row[1]), bool(row[2])

    def _tls_settings(self, run_id: str, index: int) -> tuple[bool, str | None]:
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT tls_insecure,sni FROM remote_endpoints WHERE run_id=? AND idx=?",
                             (run_id, index)).fetchone()
        return (bool(row[0]), row[1]) if row else (False, None)

    def _tls_kwargs(self, run_id: str, index: int) -> dict[str, Any]:
        insecure, sni = self._tls_settings(run_id, index)
        return {"tls_insecure": insecure, "sni": sni}

    def _connect(self, host: str, port: int, tls: bool, timeout: float, *,
                 tls_insecure: bool = False, sni: str | None = None) -> socket.socket:
        proxy = proxy_for(host)
        if proxy is not None:
            # Sandboxed agents only reach the network through their proxy, which also
            # resolves names and enforces the destination allowlist.
            raw = open_tunnel(host, port, timeout, proxy)
            self.last_route = proxy.describe()
            return self._wrap(raw, host, tls, tls_insecure, sni)
        addresses = _resolve(host, port)
        error: OSError | None = None
        for address in addresses:
            try:
                raw = socket.create_connection((address, port), timeout=timeout)
            except OSError as exc:
                error = exc
                continue
            self.last_route = "direct"
            return self._wrap(raw, host, tls, tls_insecure, sni)
        raise error or OSError("connection failed")

    @staticmethod
    def _wrap(raw: socket.socket, host: str, tls: bool, insecure: bool = False,
              sni: str | None = None) -> socket.socket:
        if not tls:
            return raw
        try:
            context = ssl.create_default_context()
            if insecure:
                # Only reachable through an explicit per-endpoint grant (--tls-insecure).
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            return context.wrap_socket(raw, server_hostname=sni or host)
        except BaseException:
            raw.close()
            raise

    def connect_stdio(self, run_id: str, index: int, *, timeout: float = 3600.0,
                      idle_timeout: float = 10.0) -> dict[str, Any]:
        """Bridge this process's stdin/stdout to a granted endpoint, like ``nc``.

        Intended as an ssh ``ProxyCommand`` or for another client that expects a
        byte stream; the scope check, proxy routing and budget still apply. After
        stdin reaches EOF the write side is half-closed and the bridge ends once the
        server closes or stays silent for ``idle_timeout`` seconds.
        """
        if not 1 <= timeout <= 4 * 3600 or not 0.1 <= idle_timeout <= 4 * 3600:
            raise ValueError("invalid timeout")
        host, port, tls = self._endpoint(run_id, index)
        self.session._reserve(run_id, "remote_service_stdio_bridge", endpoint=f"{host}:{port}")
        try:
            connection = self._connect(host, port, tls, 15, **self._tls_kwargs(run_id, index))
        except (OSError, ValueError, ssl.SSLError) as exc:
            self._finish(run_id, False, b"", hashlib.sha256().hexdigest(), [])
            raise OSError("connection failed: " + type(exc).__name__ + ": " + str(exc)[:200]) from exc
        sent, received = hashlib.sha256(), hashlib.sha256()
        counts = [0, 0]
        stdin, stdout = sys.stdin.buffer.fileno(), sys.stdout.buffer.fileno()
        selector = selectors.DefaultSelector()
        selector.register(connection, selectors.EVENT_READ, "socket")
        selector.register(stdin, selectors.EVENT_READ, "stdin")
        deadline = time.monotonic() + timeout
        open_streams = 2
        stdin_closed_at: float | None = None
        last_activity = time.monotonic()
        reason = "closed"
        try:
            while open_streams and time.monotonic() < deadline:
                if stdin_closed_at is not None and time.monotonic() - last_activity >= idle_timeout:
                    reason = "idle_timeout"
                    break
                for key, _ in selector.select(timeout=min(1.0, idle_timeout)):
                    if key.data == "socket":
                        try:
                            data = connection.recv(65_536)
                            while isinstance(connection, ssl.SSLSocket) and connection.pending():
                                data += connection.recv(65_536)
                        except (BlockingIOError, ssl.SSLWantReadError, TimeoutError):
                            continue
                        except OSError as exc:
                            reason = "socket_error:" + type(exc).__name__
                            data = b""
                        if not data:
                            selector.unregister(connection)
                            open_streams = 0
                            break
                        received.update(data)
                        counts[1] += len(data)
                        last_activity = time.monotonic()
                        try:
                            os.write(stdout, data)
                        except OSError as exc:
                            reason = "stdout_error:" + type(exc).__name__
                            open_streams = 0
                            break
                    else:
                        try:
                            data = os.read(stdin, 65_536)
                        except OSError:
                            data = b""
                        if not data:
                            selector.unregister(stdin)
                            open_streams -= 1
                            stdin_closed_at = last_activity = time.monotonic()
                            try:
                                connection.shutdown(socket.SHUT_WR)
                            except OSError:
                                pass
                            continue
                        sent.update(data)
                        counts[0] += len(data)
                        try:
                            connection.sendall(data)
                        except OSError as exc:
                            reason = "socket_error:" + type(exc).__name__
                            open_streams = 0
                            break
                if max(counts) > 64 * MAX_PIPE_BYTES:
                    break
        finally:
            selector.close()
            connection.close()
        ok = ":" not in reason
        self.session._emit(run_id, RunStatus.OBSERVING, tool_ok=str(ok).lower(),
                           received_sha256=received.hexdigest(), sent_sha256=sent.hexdigest())
        self.session._emit(run_id, RunStatus.REPLANNING)
        self.session._emit(run_id, RunStatus.PLANNING)
        return {"run_id": run_id, "sent_bytes": counts[0], "received_bytes": counts[1],
                "route": self.last_route, "termination": reason}

    def _finish(self, run_id: str, ok: bool, received: bytes, sent_digest: str,
                transcript: list[dict[str, Any]]) -> str | None:
        name = None
        if self.session.artifact_root(run_id) is not None and received:
            name = self.session.store_artifact(run_id, received[-TRANSCRIPT_KEEP:],
                                               directory_name=".metis-remote", suffix=".recv")
        if self.session.artifact_root(run_id) is not None and transcript:
            body = json.dumps(transcript).encode()[:TRANSCRIPT_KEEP]
            self.session.store_artifact(run_id, body, directory_name=".metis-remote", suffix=".json")
        self.session._emit(run_id, RunStatus.OBSERVING, tool_ok=str(ok).lower(),
                           received_sha256=hashlib.sha256(received).hexdigest(), sent_sha256=sent_digest)
        self.session._emit(run_id, RunStatus.REPLANNING)
        self.session._emit(run_id, RunStatus.PLANNING)
        return name

    # -- scripted exchange -----------------------------------------------------
    def exchange(self, run_id: str, index: int, script: Exchange) -> dict[str, Any]:
        script = Exchange.model_validate(script.model_dump())
        host, port, tls = self._endpoint(run_id, index)
        self.session._reserve(run_id, "remote_service_exchange", endpoint=f"{host}:{port}",
                              steps=str(len(script.steps)))
        deadline = time.monotonic() + MAX_EXCHANGE_SECONDS
        received_total = bytearray()
        sent = hashlib.sha256()
        results: list[dict[str, Any]] = []
        transcript: list[dict[str, Any]] = []
        ok, error = True, None
        buffer = b""
        eof = False
        try:
            connection = self._connect(host, port, tls, script.connect_timeout,
                                        **self._tls_kwargs(run_id, index))
        except (OSError, ValueError, ssl.SSLError) as exc:
            self._finish(run_id, False, b"", sent.hexdigest(), [])
            return {"run_id": run_id, "ok": False, "error": "connection failed: " + type(exc).__name__,
                    "detail": str(exc)[:200], "route": proxy_route(host)}
        with connection:
            for number, step in enumerate(script.steps):
                result: dict[str, Any] = {"step": number}
                try:
                    payload = step.payload()
                    if payload:
                        connection.settimeout(max(0.01, min(step.timeout, deadline - time.monotonic())))
                        connection.sendall(payload)
                        sent.update(payload)
                        result["sent_bytes"] = len(payload)
                        transcript.append({"dir": "send", "hex": payload.hex()})
                    delimiter = step.delimiter()
                    wants = step.recv_bytes
                    if delimiter is None and wants is None and not step.recv_all:
                        results.append(result)
                        continue
                    step_deadline = min(deadline, time.monotonic() + step.timeout)
                    matched = False
                    while True:
                        if delimiter is not None and delimiter in buffer:
                            cut = buffer.index(delimiter) + len(delimiter)
                            chunk, buffer = buffer[:cut], buffer[cut:]
                            matched = True
                            break
                        if wants is not None and len(buffer) >= wants:
                            chunk, buffer = buffer[:wants], buffer[wants:]
                            matched = True
                            break
                        if eof:
                            chunk, buffer = buffer, b""
                            break
                        remaining = step_deadline - time.monotonic()
                        if remaining <= 0:
                            chunk, buffer = buffer, b""
                            break
                        connection.settimeout(remaining)
                        try:
                            data = connection.recv(65_536)
                        except TimeoutError:
                            chunk, buffer = buffer, b""
                            break
                        if not data:
                            eof = True
                            continue
                        if len(received_total) + len(data) > MAX_EXCHANGE_BYTES:
                            raise ValueError("received byte limit exceeded")
                        received_total.extend(data)
                        transcript.append({"dir": "recv", "hex": data.hex()})
                        buffer += data
                    if step.recv_all:
                        matched = eof
                    result.update(received=_text(chunk[-PREVIEW:]), received_bytes=len(chunk),
                                  matched=matched, eof=eof)
                    results.append(result)
                    if (delimiter is not None or wants is not None) and not matched:
                        ok, error = False, "receive condition not met before timeout/EOF"
                        break
                except (OSError, ValueError, ssl.SSLError) as exc:
                    result["error"] = type(exc).__name__
                    results.append(result)
                    ok, error = False, "transport failure: " + type(exc).__name__
                    break
                if time.monotonic() >= deadline:
                    ok, error = False, "exchange wall-time limit reached"
                    break
        artifact = self._finish(run_id, ok, bytes(received_total), sent.hexdigest(), transcript)
        output: dict[str, Any] = {"run_id": run_id, "ok": ok, "endpoint": {"host": host, "port": port, "tls": tls},
                                  "steps": results, "received_total_bytes": len(received_total),
                                  "unconsumed": _text(buffer[-PREVIEW:]) if buffer else None,
                                  "received_artifact": artifact, "route": self.last_route,
                                  "output_is_untrusted": True}
        if error:
            output["error"] = error
        return output

    # -- SSH -------------------------------------------------------------------
    def ssh(self, run_id: str, index: int, *, username: str, password: str | None = None,
            key_path: Path | None = None, command: str | None = None, stdin: bytes = b"",
            downloads: list[str] | None = None, pty: bool = False, timeout: float = 60.0) -> dict[str, Any]:
        """Run one command and/or fetch files over SSH on a granted endpoint.

        The transport rides the same scoped, proxy-aware socket as other remote
        operations. The server host key is pinned per run on first use (TOFU);
        a different key later is refused. Credentials are used, never stored.
        """
        import paramiko  # Imported lazily: only SSH challenges need it.

        downloads = downloads or []
        if (not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", username) or len(downloads) > 8
                or not 1 <= timeout <= 600 or (command is None and not downloads)
                or (command is not None and not 1 <= len(command) <= 8192)
                or len(stdin) > MAX_EXCHANGE_BYTES):
            raise ValueError("invalid SSH request")
        host, port, tls = self._endpoint(run_id, index)
        if tls:
            raise ValueError("SSH endpoints must be granted without --tls")
        self.session._reserve(run_id, "remote_ssh", endpoint=f"{host}:{port}",
                              command_sha256=hashlib.sha256((command or "").encode()).hexdigest())
        received = bytearray()
        output: dict[str, Any] = {"run_id": run_id, "endpoint": {"host": host, "port": port},
                                  "output_is_untrusted": True}
        ok = False
        try:
            sock = self._connect(host, port, False, 15)
            output["route"] = self.last_route
            transport = paramiko.Transport(sock)
            try:
                transport.start_client(timeout=15)
                key = transport.get_remote_server_key()
                fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
                with sqlite3.connect(self.database) as db:
                    pinned = db.execute("SELECT key_type,fingerprint FROM remote_host_keys WHERE run_id=? AND idx=?",
                                        (run_id, index)).fetchone()
                    if pinned and tuple(pinned) != (key.get_name(), fingerprint):
                        raise ValueError("SSH host key changed since first use in this run")
                    if not pinned:
                        db.execute("INSERT INTO remote_host_keys(run_id,idx,key_type,fingerprint) VALUES (?,?,?,?)",
                                   (run_id, index, key.get_name(), fingerprint))
                output["host_key"] = {"type": key.get_name(), "fingerprint": fingerprint,
                                      "pinned": pinned is not None}
                if key_path is not None:
                    transport.auth_publickey(username, paramiko.PKey.from_path(str(key_path)))
                elif password is not None:
                    transport.auth_password(username, password)
                else:
                    transport.auth_none(username)
                if command is not None:
                    channel = transport.open_session(timeout=15)
                    channel.settimeout(timeout)
                    if pty:
                        channel.get_pty(term="dumb", width=200, height=50)
                    channel.exec_command(command)
                    if stdin:
                        channel.sendall(stdin)
                    channel.shutdown_write()
                    out, err = bytearray(), bytearray()
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        if channel.recv_ready():
                            out.extend(channel.recv(65_536))
                        elif channel.recv_stderr_ready():
                            err.extend(channel.recv_stderr(65_536))
                        elif channel.exit_status_ready() and not channel.recv_ready() \
                                and not channel.recv_stderr_ready():
                            break
                        else:
                            time.sleep(0.02)
                        if len(out) + len(err) > MAX_EXCHANGE_BYTES:
                            break
                    timed_out = not channel.exit_status_ready()
                    status = channel.recv_exit_status() if not timed_out else None
                    channel.close()
                    received.extend(out)
                    output.update(exit_status=status, timed_out=timed_out,
                                  stdout=_text(bytes(out[-4 * PREVIEW:])), stdout_bytes=len(out),
                                  stderr=_text(bytes(err[-PREVIEW:])))
                fetched = []
                if downloads:
                    sftp = paramiko.SFTPClient.from_transport(transport)
                    if sftp is None:
                        raise OSError("SFTP subsystem unavailable")
                    with sftp:
                        for remote_path in downloads:
                            size = sftp.stat(remote_path).st_size or 0
                            if size > 8 * 1_048_576:
                                raise ValueError("remote file exceeds 8 MiB")
                            with sftp.open(remote_path, "rb") as handle:
                                content = handle.read(8 * 1_048_576 + 1)
                            name = self.session.store_artifact(run_id, content, directory_name=".metis-remote",
                                                               suffix=".bin")
                            fetched.append({"remote_path": remote_path, "artifact": name, "size": len(content),
                                            "sha256": hashlib.sha256(content).hexdigest()})
                    output["downloads"] = fetched
                ok = (output.get("exit_status") in (None, 0)) and not output.get("timed_out")
            finally:
                transport.close()
        except (OSError, ValueError, EOFError, paramiko.SSHException) as exc:
            output["error"] = type(exc).__name__ + ": " + str(exc)[:200]
            if isinstance(exc, paramiko.AuthenticationException):
                output["error"] = "SSH authentication failed"
            output.setdefault("route", proxy_route(host))
        output["ok"] = ok and "error" not in output
        self._finish(run_id, output["ok"], bytes(received), hashlib.sha256(stdin).hexdigest(), [])
        return output

    # -- solver bridge ---------------------------------------------------------
    def pipe(self, run_id: str, index: int, command: list[str], *, timeout: float = 120.0,
             cwd: Path | None = None) -> dict[str, Any]:
        """Bridge an agent-authored solver's stdin/stdout to one granted service.

        The solver is the agent's own code. Challenge-supplied programs are refused:
        they must run in the dynamic sandbox, never on the host.
        """
        if not command or len(command) > 64 or not 1 <= timeout <= MAX_PIPE_SECONDS:
            raise ValueError("invalid solver command or timeout")
        host, port, tls = self._endpoint(run_id, index)
        root = self.session.artifact_root(run_id)
        if root is not None:
            resolved_root = root.resolve()
            for item in command:
                candidate = Path(item)
                try:
                    inside = candidate.exists() and candidate.resolve().is_relative_to(resolved_root)
                except (OSError, ValueError):
                    inside = False
                if inside:
                    raise ValueError("challenge artifacts must not run on the host; use metis sandbox")
        self.session._reserve(run_id, "remote_service_solver_pipe", endpoint=f"{host}:{port}",
                              command_sha256=hashlib.sha256("\0".join(command).encode()).hexdigest())
        try:
            connection = self._connect(host, port, tls, 10, **self._tls_kwargs(run_id, index))
        except (OSError, ValueError, ssl.SSLError) as exc:
            self._finish(run_id, False, b"", hashlib.sha256().hexdigest(), [])
            return {"run_id": run_id, "ok": False, "error": "connection failed: " + type(exc).__name__,
                    "detail": str(exc)[:200], "route": proxy_route(host)}
        environment = {key: value for key, value in os.environ.items()
                       if not re.search(r"TOKEN|SECRET|PASSWORD|COOKIE|API_KEY|CREDENTIAL", key, re.IGNORECASE)}
        environment.update(METIS_REMOTE_HOST=host, METIS_REMOTE_PORT=str(port))
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=cwd, env=environment)
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        received = bytearray()
        sent = hashlib.sha256()
        sent_count = 0
        stderr = bytearray()
        transcript_tail = bytearray()
        deadline = time.monotonic() + timeout
        reason = "solver_exited"
        selector = selectors.DefaultSelector()
        connection.setblocking(False)
        selector.register(connection, selectors.EVENT_READ, "socket")
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        socket_open, stdout_open = True, True
        # Solver stdin is non-blocking and buffered so a solver that never reads
        # cannot stall the loop past its deadline.
        stdin_fd = process.stdin.fileno()
        os.set_blocking(stdin_fd, False)
        stdin_buffer = bytearray()
        stdin_state = {"open": True, "registered": False, "closing": False}

        def close_solver_stdin() -> None:
            if stdin_state["registered"]:
                selector.unregister(stdin_fd)
                stdin_state["registered"] = False
            if stdin_state["open"]:
                stdin_state["open"] = False
                stdin_buffer.clear()
                try:
                    process.stdin.close()  # type: ignore[union-attr]
                except (OSError, ValueError):
                    pass

        def pump_solver_stdin() -> None:
            if not stdin_state["open"]:
                return
            while stdin_buffer:
                try:
                    written = os.write(stdin_fd, stdin_buffer)
                except BlockingIOError:
                    break
                except OSError:
                    close_solver_stdin()
                    return
                del stdin_buffer[:written]
            if stdin_buffer:
                if not stdin_state["registered"]:
                    selector.register(stdin_fd, selectors.EVENT_WRITE, "solver_stdin")
                    stdin_state["registered"] = True
            elif stdin_state["closing"]:
                close_solver_stdin()
            elif stdin_state["registered"]:
                selector.unregister(stdin_fd)
                stdin_state["registered"] = False

        try:
            while stdout_open or process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = "timeout"
                    break
                events = selector.select(timeout=min(remaining, 0.5))
                for key, _ in events:
                    if key.data == "socket":
                        try:
                            data = connection.recv(65_536)
                        except (BlockingIOError, ssl.SSLWantReadError):
                            continue
                        except OSError:
                            data = b""
                        if not data:
                            selector.unregister(connection)
                            socket_open = False
                            stdin_state["closing"] = True
                            pump_solver_stdin()
                            continue
                        received.extend(data)
                        transcript_tail.extend(data)
                        del transcript_tail[:-TRANSCRIPT_KEEP]
                        if len(received) > MAX_PIPE_BYTES:
                            raise ValueError("received byte limit exceeded")
                        if stdin_state["open"]:
                            stdin_buffer.extend(data)
                            pump_solver_stdin()
                    elif key.data == "solver_stdin":
                        pump_solver_stdin()
                    elif key.data == "stdout":
                        data = os.read(process.stdout.fileno(), 65_536)
                        if not data:
                            selector.unregister(process.stdout)
                            stdout_open = False
                            if socket_open:
                                try:
                                    connection.shutdown(socket.SHUT_WR)
                                except OSError:
                                    pass
                            continue
                        sent.update(data)
                        sent_count += len(data)
                        if sent_count > MAX_PIPE_BYTES:
                            raise ValueError("sent byte limit exceeded")
                        if socket_open:
                            connection.setblocking(True)
                            connection.settimeout(max(0.01, deadline - time.monotonic()))
                            try:
                                connection.sendall(data)
                            except OSError:
                                socket_open = False
                            connection.setblocking(False)
                    else:
                        data = os.read(process.stderr.fileno(), 65_536)
                        if not data:
                            selector.unregister(process.stderr)
                            continue
                        stderr.extend(data)
                        del stderr[:-PREVIEW]
                if not socket_open and not stdout_open:
                    try:
                        process.wait(timeout=max(0.01, min(5, deadline - time.monotonic())))
                    except subprocess.TimeoutExpired:
                        pass
                    break
        except ValueError as exc:
            reason = str(exc)
        finally:
            selector.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            connection.close()
        artifact = self._finish(run_id, reason == "solver_exited" and process.returncode == 0,
                                bytes(transcript_tail), sent.hexdigest(), [])
        return {"run_id": run_id, "ok": reason == "solver_exited" and process.returncode == 0,
                "termination": reason, "solver_exit_code": process.returncode,
                "sent_bytes": sent_count, "received_bytes": len(received),
                "received_tail": _text(bytes(received[-PREVIEW:])),
                "solver_stderr_tail": bytes(stderr).decode("utf-8", errors="replace"),
                "received_artifact": artifact, "route": self.last_route, "output_is_untrusted": True}

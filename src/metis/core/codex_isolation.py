"""OS-level isolation for Codex specialist turns (Issue #16).

CLI flags (``--disable shell_tool`` ...) only shape what Codex offers the model; Codex 0.166
still exposes collaboration and file tools. This module adds controls that do not depend on
the model or on Codex flags:

* **Files (macOS Seatbelt).** Each turn runs under ``sandbox-exec`` with a generated profile:
  reads and writes under the protected roots (the user's home by default) are denied, except
  the Codex package itself and the turn's own temporary directory. Writes elsewhere are
  denied except the per-turn temp dir. Child processes and in-process sub-agents inherit it.
* **Codex home.** ``CODEX_HOME`` is a fresh per-turn directory holding only a copy of
  ``auth.json``; the user's sessions, memories, config, skills and plugins are not visible.
  A token refreshed during the turn is written back to the original file only when the
  original did not change meanwhile.
* **Network.** Outbound connections are denied except to a local CONNECT proxy that allows
  port 443 to an explicit host allow-list (the model API). Other hosts get 403 and are logged.

Not covered (documented, not claimed): Linux/Windows sandboxes, kernel or Seatbelt escapes,
and what the model API itself receives (the prompt is sent there by design).
"""
from __future__ import annotations

import json
import os
import platform
import select
import shutil
import socket
import subprocess
import sys
import threading
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

MODEL_HOSTS = ("chatgpt.com", "auth.openai.com", "api.openai.com")
TESTED_CODEX_VERSIONS = frozenset({"0.166.0"})
SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def isolation_available() -> bool:
    return sys.platform == "darwin" and Path(SANDBOX_EXEC).is_file()


def codex_version(executable: str) -> str | None:
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=20, check=False,
                                stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    words = result.stdout.strip().split()
    return words[-1] if result.returncode == 0 and words else None


def native_codex(executable: str) -> tuple[str, Path]:
    """Resolve the npm shim to the platform binary; return (binary, package directory).

    Running the binary directly keeps node and its install tree out of the sandbox's read set.
    """
    resolved = Path(executable).resolve()
    package = resolved.parent.parent if resolved.name == "codex.js" else resolved.parent
    machine = {"arm64": "aarch64", "x86_64": "x86_64"}.get(platform.machine(), platform.machine())
    triple = f"{machine}-apple-darwin" if sys.platform == "darwin" else f"{machine}-unknown-linux-musl"
    arch = "arm64" if machine == "aarch64" else "x64"
    osname = "darwin" if sys.platform == "darwin" else "linux"
    for candidate in (package / "node_modules" / "@openai" / f"codex-{osname}-{arch}" / "vendor" / triple / "bin"
                      / "codex", package / "vendor" / triple / "codex" / "codex"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate), package
    return str(resolved), resolved.parent


def _quote(path: Path | str) -> str:
    text = str(path)
    if '"' in text or "\\" in text or "\n" in text:
        raise ValueError("unsupported character in a sandbox path")
    return f'"{text}"'


def seatbelt_profile(*, turn_dir: Path, readable: list[Path], protected: list[Path], proxy_port: int) -> str:
    """Later rules win in SBPL: allow by default, then deny, then re-allow the exceptions."""
    turn = _quote(turn_dir.resolve())
    reads = " ".join(f"(subpath {_quote(path.resolve())})" for path in readable)
    roots = " ".join(f"(subpath {_quote(path.resolve())})" for path in protected)
    metadata = " ".join(f"(literal {_quote(path.resolve())})" for path in protected)
    return f"""(version 1)
(allow default)
(deny network*)
(allow network-outbound (remote ip "localhost:{int(proxy_port)}"))
(allow network* (local ip "localhost:*"))
(deny file-read* {roots})
(allow file-read-metadata {metadata})
(allow file-read* {reads} (subpath {turn}))
(deny file-write* {roots} (subpath "/private/tmp") (subpath "/tmp") (subpath "/private/var/tmp"))
(allow file-write* (subpath {turn}))
(deny process-exec (literal "/usr/bin/sudo") (literal "/usr/bin/osascript"))
"""


@dataclass
class ProxyLog:
    allowed: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)


class AllowlistProxy:
    """Minimal CONNECT proxy on 127.0.0.1: port 443 to allow-listed hosts only.

    When the parent environment names an upstream HTTPS proxy, allowed tunnels are chained
    through it (so a host-level egress proxy still applies).
    """

    def __init__(self, hosts: tuple[str, ...] = MODEL_HOSTS, *, upstream: str | None = None):
        self.hosts = {host.lower() for host in hosts}
        self.upstream = urllib.parse.urlsplit(upstream) if upstream else None
        self.log = ProxyLog()
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(64)
        self.port = self._server.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._server.close()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket) -> None:
        upstream = None
        try:
            client.settimeout(15)
            head = b""
            while b"\r\n\r\n" not in head and len(head) < 8192:
                chunk = client.recv(4096)
                if not chunk:
                    return
                head += chunk
            parts = head.split(b"\r\n", 1)[0].decode("latin-1").split()
            target = parts[1] if len(parts) == 3 else ""
            host, _, port = target.rpartition(":")
            if parts[:1] != ["CONNECT"] or port != "443" or host.lower() not in self.hosts:
                self.log.refused.append(" ".join(parts[:2])[:200])
                client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                return
            self.log.allowed.append(host.lower())
            if self.upstream and self.upstream.hostname:
                upstream = socket.create_connection((self.upstream.hostname, self.upstream.port or 80), timeout=20)
                upstream.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode())
                reply = upstream.recv(4096)
                if b" 200" not in reply.split(b"\r\n", 1)[0]:
                    client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                    return
            else:
                upstream = socket.create_connection((host, 443), timeout=20)
            client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            client.settimeout(None)
            _pipe(client, upstream)
        except OSError:
            return
        finally:
            client.close()
            if upstream is not None:
                upstream.close()


def _pipe(left: socket.socket, right: socket.socket) -> None:
    while True:
        ready, _, _ = select.select([left, right], [], [], 300)
        if not ready:
            return
        for sock in ready:
            data = sock.recv(65536)
            if not data:
                return
            (right if sock is left else left).sendall(data)


class TurnHome:
    """Per-turn CODEX_HOME with only auth.json; refreshed tokens are written back safely."""

    def __init__(self, turn_dir: Path, source: Path):
        self.source = source
        self.path = turn_dir / "codex-home"
        self.path.mkdir(mode=0o700)
        self.original = source.read_bytes() if source.is_file() else None
        if self.original is not None:
            target = self.path / "auth.json"
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(self.original)

    def write_back(self) -> str:
        copy = self.path / "auth.json"
        if self.original is None or not copy.is_file():
            return "no_auth"
        updated = copy.read_bytes()
        if updated == self.original:
            return "unchanged"
        try:
            json.loads(updated)
        except ValueError:
            return "refused_invalid"
        if not self.source.is_file() or self.source.read_bytes() != self.original:
            return "refused_original_changed"  # another process refreshed; keep theirs
        temporary = self.source.with_name(f".auth.json.metis-{os.getpid()}")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(updated)
        os.replace(temporary, self.source)
        return "written_back"


def upstream_proxy() -> str | None:
    for key in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(key)
        if value and value.startswith("http://"):
            return value
    return None


def default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def sandbox_command(profile_path: Path, argv: list[str]) -> list[str]:
    if not shutil.which(SANDBOX_EXEC):
        raise RuntimeError("sandbox-exec is not available")
    return [SANDBOX_EXEC, "-f", str(profile_path), *argv]


def self_test(sentinel: Path, *, protected: list[Path] | None = None) -> dict[str, Any]:
    """Run plain system programs under a turn profile and report what the OS refused.

    ``sentinel`` must be an existing file inside a protected root; its content is never printed.
    """
    import tempfile

    results: dict[str, Any] = {"platform": sys.platform, "available": isolation_available()}
    if not results["available"]:
        return results
    with tempfile.TemporaryDirectory(prefix="metis-isolation-") as temporary, AllowlistProxy() as proxy:
        turn = Path(temporary).resolve()
        roots = protected if protected is not None else [Path.home(), turn.parent]
        profile = turn / "turn.sb"
        profile.write_text(seatbelt_profile(turn_dir=turn, readable=[], protected=roots, proxy_port=proxy.port))

        def attempt(argv: list[str], env: dict[str, str] | None = None) -> int:
            done = subprocess.run(sandbox_command(profile, argv), capture_output=True, timeout=30, check=False,
                                  env={"PATH": "/usr/bin:/bin", **(env or {})}, cwd=turn)
            return done.returncode

        proxy_env = {"HTTPS_PROXY": f"http://127.0.0.1:{proxy.port}"}
        results["read_protected_denied"] = attempt(["/bin/cat", str(sentinel)]) != 0
        results["list_protected_denied"] = attempt(["/bin/ls", str(sentinel.parent)]) != 0
        results["write_outside_denied"] = attempt(["/usr/bin/touch", str(sentinel.parent / ".metis-probe")]) != 0
        results["write_turn_dir_allowed"] = attempt(["/usr/bin/touch", str(turn / "ok")]) == 0
        results["direct_network_denied"] = attempt(["/usr/bin/curl", "--noproxy", "*", "-sS", "-m", "8", "-o",
                                                    "/dev/null", "https://example.com"]) != 0
        results["proxy_other_host_refused"] = attempt(["/usr/bin/curl", "-sS", "-m", "8", "-o", "/dev/null",
                                                       "https://example.com"], proxy_env) != 0
        results["proxy_refusals_logged"] = list(proxy.log.refused)
        results["passed"] = all(results[key] for key in ("read_protected_denied", "list_protected_denied",
                                                         "write_outside_denied", "write_turn_dir_allowed",
                                                         "direct_network_denied", "proxy_other_host_refused"))
    return results

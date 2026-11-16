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

Not covered (documented, not claimed): Windows sandboxes, kernel or Seatbelt escapes,
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
# 0.169.0 added 2026-11-16 after codex-probe --ping passed (self-test, ping, spawn canary).
TESTED_CODEX_VERSIONS = frozenset({"0.166.0", "0.169.0"})
SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def isolation_backend() -> str | None:
    """'seatbelt' (macOS), 'bwrap' (Linux with working user namespaces) or None (fail closed)."""
    if sys.platform == "darwin" and Path(SANDBOX_EXEC).is_file():
        return "seatbelt"
    if sys.platform.startswith("linux") and bwrap_available():
        return "bwrap"
    return None


def isolation_available() -> bool:
    return isolation_backend() is not None


def bwrap_available() -> bool:
    binary = shutil.which("bwrap")
    if not binary:
        return False
    try:
        probe = subprocess.run([binary, "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "true"],
                               capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


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


def seatbelt_profile(*, turn_dir: Path, readable: list[Path], protected: list[Path], proxy_port: int,
                     executable: Path | None = None) -> str:
    """Later rules win in SBPL: allow by default, then deny, then re-allow the exceptions.

    With ``executable`` the process may not fork at all and may exec only that binary: no
    shell, helper or setuid program can start, whatever tools Codex offers the model.
    """
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
""" + ("" if executable is None else f"""(deny process-fork)
(deny process-exec)
(allow process-exec (literal {_quote(executable.resolve())}))
""")


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
        if self._unix is not None:
            self._unix.close()

    _unix: socket.socket | None = None

    def serve_unix(self, path: Path) -> None:
        """Also accept connections on a Unix socket (bound into a Linux network namespace)."""
        self._unix = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._unix.bind(str(path))
        self._unix.listen(64)
        threading.Thread(target=self._serve, args=(self._unix,), daemon=True).start()

    def _serve(self, server: socket.socket | None = None) -> None:
        listener = server or self._server
        while not self._stop.is_set():
            try:
                client, _ = listener.accept()
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


INSIDE_PROXY_PORT = 18080


def wrap(backend: str, *, turn_dir: Path, argv: list[str], env: dict[str, str], proxy: AllowlistProxy,
         readable: list[Path], protected: list[Path], workdir: Path,
         executable: Path | None = None) -> tuple[list[str], dict[str, str]]:
    """Command and environment that run ``argv`` under the OS isolation of ``backend``."""
    if backend == "seatbelt":
        profile = turn_dir / f"turn-{len(list(turn_dir.glob('turn-*.sb')))}.sb"
        profile.write_text(seatbelt_profile(turn_dir=turn_dir, readable=readable, protected=protected,
                                            proxy_port=proxy.port, executable=executable))
        url = f"http://127.0.0.1:{proxy.port}"
        return sandbox_command(profile, argv), {**env, "HTTPS_PROXY": url, "HTTP_PROXY": url, "ALL_PROXY": url}
    if backend == "bwrap":
        socket_path = turn_dir / "proxy.sock"
        if not socket_path.exists():
            proxy.serve_unix(socket_path)
        url = f"http://127.0.0.1:{INSIDE_PROXY_PORT}"
        inside = {**env, "HTTPS_PROXY": url, "HTTP_PROXY": url, "ALL_PROXY": url,
                  "PATH": "/usr/local/bin:/usr/bin:/bin"}
        return bwrap_command(turn_dir=turn_dir, readable=readable, socket_path=socket_path, port=INSIDE_PROXY_PORT,
                             env=inside, argv=argv, workdir=workdir), {"PATH": "/usr/bin:/bin"}
    raise RuntimeError("no OS isolation backend on this host")


def self_test(sentinel: Path, *, protected: list[Path] | None = None) -> dict[str, Any]:
    """Run plain system programs under the turn isolation and report what the OS refused.

    ``sentinel`` must be an existing file outside the turn directory (inside a protected root on
    macOS; not mounted at all on Linux); its content is never printed.
    """
    import tempfile

    backend = isolation_backend()
    results: dict[str, Any] = {"platform": sys.platform, "backend": backend, "available": backend is not None}
    if backend is None:
        return results
    python = str(Path(sys.executable).resolve())
    cat, ls, touch = (shutil.which(name) or f"/bin/{name}" for name in ("cat", "ls", "touch"))
    with tempfile.TemporaryDirectory(prefix="metis-isolation-") as temporary, AllowlistProxy() as proxy:
        turn = Path(temporary).resolve()
        roots = protected if protected is not None else [Path.home(), turn.parent]

        def attempt(argv: list[str], executable: Path | None = None) -> int:
            command, env = wrap(backend, turn_dir=turn, argv=argv, env={"PATH": "/usr/bin:/bin"}, proxy=proxy,
                                readable=[], protected=roots, workdir=turn, executable=executable)
            done = subprocess.run(command, capture_output=True, timeout=60, check=False, env=env, cwd=turn)
            return done.returncode

        curl = "/usr/bin/curl" if Path("/usr/bin/curl").is_file() else None
        if curl:
            direct = [curl, "--noproxy", "*", "-sS", "-m", "8", "-o", "/dev/null", "https://example.com"]
            proxied = [curl, "-sS", "-m", "8", "-o", "/dev/null", "https://example.com"]
        else:
            direct = [python, "-I", "-c", "import socket; socket.create_connection(('1.1.1.1', 443), timeout=5)"]
            proxied = [python, "-I", "-c", ("import urllib.request; urllib.request.urlopen('https://example.com', "
                       "timeout=8)")]
        results["read_protected_denied"] = attempt([cat, str(sentinel)]) != 0
        results["list_protected_denied"] = attempt([ls, str(sentinel.parent)]) != 0
        results["write_outside_denied"] = attempt([touch, str(sentinel.parent / ".metis-probe")]) != 0
        results["write_turn_dir_allowed"] = attempt([touch, str(turn / "ok")]) == 0
        results["direct_network_denied"] = attempt(direct) != 0
        results["proxy_other_host_refused"] = attempt(proxied) != 0 and any("example.com" in item
                                                                            for item in proxy.log.refused)
        if backend == "seatbelt":  # only the named executable may run; it may not fork
            shell = Path("/bin/sh")
            results["child_process_denied"] = (attempt([str(shell), "-c", "/bin/echo hi"], shell) != 0
                                               and attempt([str(shell), "-c", "exec /bin/echo hi"], shell) != 0)
        else:  # process creation is denied; thread creation remains available
            check = "import sys; sys.exit(0 if 'NoNewPrivs:\\t1' in open('/proc/self/status').read() else 1)"
            results["no_new_privileges"] = attempt([python, "-I", "-c", check]) == 0
            process_check = "import os; os.fork()"
            thread_check = "import threading; t=threading.Thread(target=lambda: None); t.start(); t.join()"
            results["child_process_denied"] = attempt([python, "-I", "-c", process_check]) != 0
            results["thread_allowed"] = attempt([python, "-I", "-c", thread_check]) == 0
        results["proxy_refusals_logged"] = list(proxy.log.refused)
        required = ["read_protected_denied", "list_protected_denied", "write_outside_denied",
                    "write_turn_dir_allowed", "direct_network_denied", "proxy_other_host_refused",
                    "child_process_denied"]
        if backend == "bwrap":
            required += ["no_new_privileges", "thread_allowed"]
        results["passed"] = all(results[key] for key in required)
    return results


# -- Linux backend (bubblewrap) ------------------------------------------------------------------
FORWARDER = r"""
import ctypes, errno, os, platform, select, socket, sys

def restrict_process_creation():
    # classic BPF over struct seccomp_data; only thread-group clone is allowed.
    machine = platform.machine()
    numbers = {"x86_64": (0xc000003e, 56, 57, 58), "aarch64": (0xc00000b7, 220, None, None)}
    if machine not in numbers:
        raise RuntimeError("unsupported seccomp architecture")
    arch, clone, fork, vfork = numbers[machine]
    class Filter(ctypes.Structure):
        _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
                    ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint32)]
    class Program(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(Filter))]
    ins = [(0x20, 0, 0, 4), (0x15, 1, 0, arch), (0x06, 0, 0, 0x80000000),
           (0x20, 0, 0, 0)]
    # Reject x32 ABI, whose syscall numbers otherwise bypass x86_64 comparisons.
    if machine == "x86_64":
        ins += [(0x45, 0, 1, 0x40000000), (0x06, 0, 0, 0x80000000)]
    for number in (fork, vfork):
        if number is not None:
            ins += [(0x15, 0, 1, number), (0x06, 0, 0, 0x00050000 | errno.EPERM)]
    # clone3 cannot be inspected by classic BPF; ENOSYS makes libc fall back to clone.
    ins += [(0x15, 0, 1, 435), (0x06, 0, 0, 0x00050000 | errno.ENOSYS),
            (0x15, 0, 3, clone), (0x20, 0, 0, 16),
            (0x45, 1, 0, 0x10000), (0x06, 0, 0, 0x00050000 | errno.EPERM),
            (0x06, 0, 0, 0x7fff0000)]
    filters = (Filter * len(ins))(*(Filter(*item) for item in ins))
    program = Program(len(ins), filters)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.prctl(22, 2, ctypes.byref(program), 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "failed to install process seccomp filter")

port, path, argv = int(sys.argv[1]), sys.argv[2], sys.argv[3:]
listener = socket.socket()
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("127.0.0.1", port))
listener.listen(64)
if os.fork() == 0:
    while True:
        client, _ = listener.accept()
        if os.fork() == 0:
            upstream = socket.socket(socket.AF_UNIX)
            upstream.connect(path)
            while True:
                ready, _, _ = select.select([client, upstream], [], [], 300)
                if not ready:
                    os._exit(0)
                for sock in ready:
                    data = sock.recv(65536)
                    if not data:
                        os._exit(0)
                    (upstream if sock is client else client).sendall(data)
        client.close()
listener.close()
restrict_process_creation()
os.execv(argv[0], argv)
"""
SYSTEM_RO = ("/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc/ssl", "/etc/ca-certificates", "/etc/pki",
             "/etc/alternatives")


def python_roots() -> list[Path]:
    """Install prefixes of the running interpreter (e.g. /opt/hostedtoolcache/... on CI runners)."""
    roots = {Path(sys.base_prefix).resolve(), Path(sys.executable).resolve().parent.parent}
    return sorted(root for root in roots if root.is_dir() and not str(root).startswith("/usr"))


def bwrap_command(*, turn_dir: Path, readable: list[Path], socket_path: Path, port: int, env: dict[str, str],
                  argv: list[str], workdir: Path) -> list[str]:
    """Run ``argv`` in new user/pid/net/ipc/uts/cgroup namespaces with only system dirs (read-only),
    the readable paths (read-only) and the turn dir (read-write) mounted. The home directory and
    shared temp dirs are not mounted at all. Egress: 127.0.0.1:port inside -> Unix socket -> host proxy.
    bwrap sets PR_SET_NO_NEW_PRIVS and drops capabilities, so setuid programs cannot raise privileges.
    A seccomp filter blocks process creation while allowing thread-group clones. It does not block exec."""
    binary = shutil.which("bwrap")
    if not binary:
        raise RuntimeError("bubblewrap is not available")
    python = str(Path(sys.executable).resolve())  # the forwarder uses only the standard library
    readable = [*readable, *python_roots()]
    forwarder = turn_dir / "forward.py"
    forwarder.write_text(FORWARDER)
    command = [binary, "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv",
               "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for system in SYSTEM_RO:
        command += ["--ro-bind-try", system, system]
    for path in readable:
        command += ["--ro-bind", str(path), str(path)]
    command += ["--bind", str(turn_dir), str(turn_dir), "--chdir", str(workdir)]
    for key, value in env.items():
        command += ["--setenv", key, value]
    return [*command, "--", python, "-I", str(forwarder), str(port), str(socket_path), *argv]

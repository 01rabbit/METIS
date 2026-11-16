"""OS-level isolation for Codex specialist turns (Issue #16).

The macOS tests run real system programs under the generated Seatbelt profile and check that
the OS (not the model, not Codex flags) refuses reads, writes and egress. They are skipped
where sandbox-exec is unavailable; the proxy, home and gating tests run everywhere.
"""
import json
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from metis.core import codex_isolation, codex_specialist
from metis.core.codex_isolation import (
    AllowlistProxy,
    TurnHome,
    native_codex,
    seatbelt_profile,
    self_test,
)
from metis.core.codex_specialist import CodexCLI

macos = pytest.mark.skipif(codex_isolation.isolation_backend() != "seatbelt", reason="macOS sandbox-exec is required")


def _connect(port: int, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(request)
        return sock.recv(4096)


# -- profile ---------------------------------------------------------------------------------
def test_profile_denies_network_and_protected_roots(tmp_path):
    turn, secret, package = tmp_path / "turn", tmp_path / "secret", tmp_path / "pkg"
    for path in (turn, secret, package):
        path.mkdir()
    profile = seatbelt_profile(turn_dir=turn, readable=[package], protected=[secret], proxy_port=4242)
    assert "(deny network*)" in profile and '(remote ip "localhost:4242")' in profile
    assert f'(deny file-read* (subpath "{secret.resolve()}"))' in profile
    assert profile.index("(deny file-read*") < profile.index("(allow file-read*")  # exceptions come last
    with pytest.raises(ValueError):
        seatbelt_profile(turn_dir=turn, readable=[tmp_path / 'bad"name'], protected=[secret], proxy_port=1)


# -- egress proxy ------------------------------------------------------------------------------
def test_proxy_refuses_other_hosts_ports_and_methods():
    with AllowlistProxy(("model.example",)) as proxy:
        assert b" 403 " in _connect(proxy.port, b"CONNECT evil.example:443 HTTP/1.1\r\n\r\n")
        assert b" 403 " in _connect(proxy.port, b"CONNECT model.example:22 HTTP/1.1\r\n\r\n")
        assert b" 403 " in _connect(proxy.port, b"GET http://model.example/ HTTP/1.1\r\n\r\n")
        assert proxy.log.refused == ["CONNECT evil.example:443", "CONNECT model.example:22",
                                     "GET http://model.example/"]


def test_allowed_host_is_tunnelled_through_the_upstream_proxy():
    upstream = socket.socket()
    upstream.bind(("127.0.0.1", 0))
    upstream.listen(1)
    seen = {}

    def fake_upstream():
        conn, _ = upstream.accept()
        seen["request"] = conn.recv(4096)
        conn.sendall(b"HTTP/1.1 200 OK\r\n\r\n")
        seen["payload"] = conn.recv(4096)
        conn.sendall(b"pong")
        conn.close()

    threading.Thread(target=fake_upstream, daemon=True).start()
    address = f"http://127.0.0.1:{upstream.getsockname()[1]}"
    with AllowlistProxy(("model.example",), upstream=address) as proxy, \
            socket.create_connection(("127.0.0.1", proxy.port), timeout=5) as sock:
        sock.sendall(b"CONNECT model.example:443 HTTP/1.1\r\n\r\n")
        assert b" 200 " in sock.recv(4096)
        sock.sendall(b"ping")
        assert sock.recv(4096) == b"pong"
    assert seen["request"].startswith(b"CONNECT model.example:443") and seen["payload"] == b"ping"
    upstream.close()


# -- per-turn Codex home -----------------------------------------------------------------------
def test_turn_home_holds_only_auth_and_writes_back_safely(tmp_path):
    source = tmp_path / "codex" / "auth.json"
    source.parent.mkdir()
    (source.parent / "sessions").mkdir()
    source.write_text(json.dumps({"tokens": {"refresh_token": "old"}}))
    turn = tmp_path / "turn"
    turn.mkdir()
    home = TurnHome(turn, source)
    assert sorted(p.name for p in home.path.iterdir()) == ["auth.json"]
    assert home.write_back() == "unchanged"
    (home.path / "auth.json").write_text(json.dumps({"tokens": {"refresh_token": "new"}}))
    assert home.write_back() == "written_back" and "new" in source.read_text()

    second = tmp_path / "turn2"
    second.mkdir()
    other = TurnHome(second, source)
    source.write_text(json.dumps({"tokens": {"refresh_token": "by-another-process"}}))
    (other.path / "auth.json").write_text(json.dumps({"tokens": {"refresh_token": "mine"}}))
    assert other.write_back() == "refused_original_changed" and "another" in source.read_text()
    (other.path / "auth.json").write_text("not json")
    assert other.write_back() == "refused_invalid"


def test_native_binary_is_resolved_from_the_npm_shim(tmp_path, monkeypatch):
    package = tmp_path / "codex"
    (package / "bin").mkdir(parents=True)
    shim = package / "bin" / "codex.js"
    shim.write_text("#!/usr/bin/env node\n")
    monkeypatch.setattr(codex_isolation.sys, "platform", "darwin")
    monkeypatch.setattr(codex_isolation.platform, "machine", lambda: "arm64")
    binary = package / "node_modules" / "@openai" / "codex-darwin-arm64" / "vendor" / "aarch64-apple-darwin" / "bin"
    binary.mkdir(parents=True)
    (binary / "codex").write_text("#!/bin/sh\n")
    (binary / "codex").chmod(0o755)
    resolved, root = native_codex(str(shim))
    assert resolved == str(binary / "codex") and root == package.resolve()


# -- gating ------------------------------------------------------------------------------------
def _fake_codex(tmp_path, version: str):
    fake = tmp_path / "codex"
    fake.write_text(f"#!/bin/sh\nif [ \"$1\" = --version ]; then echo 'codex-cli {version}'; exit 0; fi\n"
                    "if [ \"$1\" = features ]; then echo 'shell_tool stable true'; exit 0; fi\nexit 3\n")
    fake.chmod(0o755)
    return str(fake)


def test_untested_codex_version_is_refused(tmp_path):
    cli = CodexCLI(_fake_codex(tmp_path, "9.9.9"), isolation="none")
    with pytest.raises(RuntimeError, match="not a tested version"):
        cli.run("x", model=None, timeout=5)


def test_codex_version_is_rechecked_for_each_turn(tmp_path, monkeypatch):
    cli = CodexCLI(_fake_codex(tmp_path, "0.166.0"), isolation="none")
    assert cli.check() == "0.166.0"

    monkeypatch.setattr(codex_specialist, "codex_version", lambda _executable: "9.9.9")
    with pytest.raises(RuntimeError, match="not a tested version"):
        cli.run("x", model=None, timeout=5)


def test_missing_isolation_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_specialist, "isolation_available", lambda: False)
    cli = CodexCLI(_fake_codex(tmp_path, "0.166.0"))
    with pytest.raises(RuntimeError, match="isolation"):
        cli.run("x", model=None, timeout=5)
    assert CodexCLI(_fake_codex(tmp_path, "0.166.0"), isolation="none").check() == "0.166.0"


# -- the OS actually refuses (macOS) -----------------------------------------------------------------
@macos
def test_seatbelt_refuses_reads_writes_and_egress(tmp_path):
    secret = tmp_path / "protected"
    secret.mkdir()
    sentinel = secret / "secret.txt"
    sentinel.write_text("do not read")
    result = self_test(sentinel, protected=[secret])
    assert result["passed"], result
    assert result["proxy_refusals_logged"] == ["CONNECT example.com:443"]
    assert result["child_process_denied"] is True


@macos
def test_codex_turn_may_exec_only_the_codex_binary(tmp_path, monkeypatch):
    """A stand-in `codex` shell script cannot even start: the turn may exec only the named binary
    (here the script itself, whose interpreter /bin/sh is then refused) and may not fork."""
    secret = tmp_path / "protected"
    secret.mkdir()
    (secret / "auth.json").write_text("{}")
    package = tmp_path / "pkg"
    package.mkdir()
    fake = package / "codex"
    fake.write_text("#!/bin/sh\nif [ \"$1\" = features ]; then echo 'shell_tool stable true'; exit 0; fi\n"
                    "cat /etc/hosts\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setattr(codex_specialist, "default_codex_home", lambda: secret)
    cli = CodexCLI(str(fake), allow_untested=True, protected=[secret, tmp_path / "elsewhere"])
    turn = cli.run("x", model=None, timeout=60)
    assert turn.isolation["mode"] == "seatbelt" and turn.returncode != 0
    assert "Operation not permitted" in turn.stderr_tail and "localhost" not in turn.stderr_tail



linux = pytest.mark.skipif(codex_isolation.isolation_backend() != "bwrap",
                           reason="Linux with bubblewrap and user namespaces is required")


@linux
def test_bwrap_refuses_reads_writes_and_egress_and_sets_no_new_privs(tmp_path):
    secret = tmp_path / "protected"
    secret.mkdir()
    sentinel = secret / "secret.txt"
    sentinel.write_text("do not read")
    result = self_test(sentinel)
    assert result["backend"] == "bwrap" and result["passed"], result
    assert result["no_new_privileges"] is True


@linux
def test_codex_turn_under_bwrap_cannot_escape(tmp_path, monkeypatch):
    """A stand-in `codex` script runs inside the namespaces: the home directory is not mounted, writes
    outside the turn fail, direct egress has no route and other hosts are refused by the proxy."""
    secret = tmp_path / "protected"
    secret.mkdir()
    (secret / "auth.json").write_text("{}")
    (secret / "private.txt").write_text("private")
    package = tmp_path / "pkg"
    package.mkdir()
    fake = package / "codex"
    fake.write_text(
        f"#!{Path(sys.executable).resolve()}\n"
        "import os, socket, sys, urllib.request\n"
        "if sys.argv[1:2] == ['features']:\n print('shell_tool stable true'); sys.exit(0)\n"
        f"secret = {str(secret)!r}\n"
        "for label, action in [('READ', lambda: open(secret + '/private.txt').read()), "
        "('WRITE', lambda: open(secret + '/x', 'w')), "
        "('NET', lambda: socket.create_connection(('1.1.1.1', 443), timeout=5)), "
        "('PROXY', lambda: urllib.request.urlopen('https://example.com', timeout=8))]:\n"
        " try: action(); print(label + '_OK', file=sys.stderr)\n"
        " except Exception: print(label + '_DENIED', file=sys.stderr)\n"
        "print(os.listdir(os.environ['CODEX_HOME']), file=sys.stderr)\n")
    fake.chmod(0o755)
    monkeypatch.setattr(codex_specialist, "default_codex_home", lambda: secret)
    cli = CodexCLI(str(fake), allow_untested=True)
    turn = cli.run("x", model=None, timeout=60)
    assert turn.isolation["mode"] == "bwrap"
    log = turn.stderr_tail
    for word in ("READ_DENIED", "WRITE_DENIED", "NET_DENIED", "PROXY_DENIED", "auth.json"):
        assert word in log, log
    assert turn.isolation["refused"] == ["CONNECT example.com:443"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux seccomp required")
def test_seccomp_blocks_processes_but_allows_threads(tmp_path):
    # Execute in a disposable subprocess: seccomp is irreversible for the calling process.
    prefix = codex_isolation.FORWARDER.split("port, path, argv =", 1)[0]
    code = prefix + """
restrict_process_creation()
import errno, threading
thread = threading.Thread(target=lambda: None)
thread.start(); thread.join()
for call in (os.fork, lambda: os.posix_spawn('/bin/true', ['/bin/true'], {})):
    try:
        pid = call()
    except OSError as exc:
        assert exc.errno == errno.EPERM, exc
    else:
        if pid == 0: os._exit(0)
        os.waitpid(pid, 0)
        raise AssertionError('process creation allowed')
"""
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr

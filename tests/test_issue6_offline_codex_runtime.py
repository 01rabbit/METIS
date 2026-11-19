import hashlib
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import pytest
from test_issue6_canary_watchdog import prepare, state

from metis.evaluation import _issue6_canary_process as guardian
from metis.evaluation.issue6_canary_watchdog import _CANARY_TABLE, start_offline_runtime_canary


def test_runtime_stage_never_makes_hash_mismatch_executable(tmp_path):
    source = tmp_path / "fake"
    source.write_bytes(b"hello")
    staged = tmp_path / "stage"
    with pytest.raises(RuntimeError, match="pinned native"):
        guardian.stage_native(source, staged, size=5, digest="0" * 64)
    assert not staged.stat().st_mode & 0o111
    staged.unlink()
    guardian.stage_native(source, staged, size=5, digest=hashlib.sha256(b"hello").hexdigest())
    assert staged.read_bytes() == b"hello" and staged.stat().st_mode & 0o777 == 0o500


@pytest.mark.parametrize(("stub", "outcome"), [
    ("print('codex-cli 0.169.0')", "completed"),
    ("expected_isolation_warning", "completed"),
    ("expected_isolation_warning_plus_other", "invalid_probe"),
    ("print('wrong')", "invalid_probe"),
    ("print('codex-cli 0.169.0'); import sys; print('unexpected', file=sys.stderr)", "invalid_probe"),
    ("print('x' * 100_000)", "output_limit"),
    ("import sys; print('x' * 100_000, file=sys.stderr)", "output_limit"),
    ("import time; time.sleep(30)", "deadline"),
])
def test_direct_guardian_bounds_process_output_and_reaps_before_cleanup(tmp_path, monkeypatch, stub, outcome):
    scratch = tmp_path / "probe"
    db_path = tmp_path / "case.sqlite"
    cutoff, wall = time.monotonic() + 1, time.time() + 2
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute(_CANARY_TABLE)
        db.execute("INSERT INTO issue6_canaries VALUES (1, 'nonce', ?, 'pending', NULL, ?, ?)",
                   (scratch.name, wall, cutoff))
    pids = []
    popen = subprocess.Popen

    def direct_child(*args, **kwargs):
        process = popen(*args, **kwargs)
        pids.append(process)
        return process

    def command(directory, _source):
        binary, profile = directory / "pinned-codex", directory / "runtime.sb"
        binary.touch()
        profile.touch()
        if stub.startswith("expected_isolation_warning"):
            warning = (
                "WARNING: proceeding, even though we could not create PATH aliases: "
                f'failed to read CODEX_HOME "{scratch}": Operation not permitted (os error 1)'
            )
            if stub.endswith("_plus_other"):
                warning += "\nextra warning"
            program = f"import sys; print('codex-cli 0.169.0'); print({warning!r}, file=sys.stderr)"
        else:
            program = stub
        return [sys.executable, "-I", "-S", "-c", program]

    monkeypatch.setattr(guardian, "_runtime_command", command)
    monkeypatch.setattr(guardian.subprocess, "Popen", direct_child)
    reader, writer = socket.socketpair()
    with reader, writer:
        assert guardian._runtime_guardian(reader.fileno(), os.getppid(), db_path, 1, "nonce",
                                          scratch, cutoff, wall, Path("/not-read")) == 0
    assert len(pids) == 1 and pids[0].returncode is not None
    assert state(db_path)[1:] == ("reaped", outcome)
    assert not scratch.exists()
    assert b"codex-cli" not in db_path.read_bytes()


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS Seatbelt")
def test_runtime_profile_denies_outside_read_and_write_and_other_exec(tmp_path):
    directory = tmp_path.resolve()
    sentinel = directory / "sentinel"
    sentinel.write_text("private\n")
    denied_write = directory / "forbidden"
    profile = directory / "runtime.sb"
    shell = Path("/bin/bash")
    profile.write_text(guardian.runtime_profile(shell))
    command = guardian._sandbox_argv(
        profile, shell, "-c",
        'if IFS= read -r x <"$1"; then exit 10; fi; '
        'if printf x >"$2"; then exit 11; fi; printf blocked; exec /usr/bin/true',
        "probe", str(sentinel), str(denied_write),
    )
    result = subprocess.run(command, cwd="/", env={"PATH": "/usr/bin:/bin", "LANG": "C"},
                            capture_output=True, check=False, timeout=5)
    assert result.stdout == b"blocked"
    assert result.returncode != 0
    assert not denied_write.exists()
    assert sentinel.read_text() == "private\n"


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS Seatbelt")
def test_bad_pin_cannot_run_even_with_valid_dry_run_approval(tmp_path):
    database, workspace, admission, args = prepare(tmp_path)
    sentinel = tmp_path / "ran"
    source = tmp_path / "not-codex"
    source.write_text(f'#!/bin/sh\ntouch "{sentinel}"\n')
    source.chmod(0o700)
    with start_offline_runtime_canary(admission, workspace, *args, source) as canary:
        assert canary.wait() == 0
    assert state(database)[1:] == ("reaped", "runtime_failed")
    assert not sentinel.exists() and list(workspace.iterdir()) == []


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS Seatbelt")
def test_runtime_profile_denies_local_network_without_contacting_provider(tmp_path):
    profile = tmp_path.resolve() / "runtime.sb"
    shell = Path("/bin/bash")
    profile.write_text(guardian.runtime_profile(shell))
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C"}
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        port = str(listener.getsockname()[1])
        source = 'if : >"/dev/tcp/127.0.0.1/$1"; then printf loopback; else exit 20; fi'
        args = ("-c", source, "probe", port)
        control = subprocess.run([str(shell), *args], cwd="/", env=environment,
                                 capture_output=True, check=False, timeout=5)
        assert control.returncode == 0 and control.stdout == b"loopback"
        result = subprocess.run(guardian._sandbox_argv(profile, shell, *args),
                                cwd="/", env=environment, capture_output=True, check=False, timeout=5)
        assert result.returncode == 20 and result.stdout == b""
        assert b"connect: Operation not permitted" in result.stderr


def test_cleanup_failure_leaves_pending_without_safe_terminal_receipt(tmp_path, monkeypatch):
    scratch = tmp_path / "probe"
    db_path = tmp_path / "case.sqlite"
    cutoff, wall = time.monotonic() + 1, time.time() + 2
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute(_CANARY_TABLE)
        db.execute("INSERT INTO issue6_canaries VALUES (1, 'nonce', ?, 'pending', NULL, ?, ?)",
                   (scratch.name, wall, cutoff))

    def command(directory, _source):
        (directory / "unexpected").touch()
        return [sys.executable, "-I", "-S", "-c", "print('codex-cli 0.169.0')"]

    monkeypatch.setattr(guardian, "_runtime_command", command)
    reader, writer = socket.socketpair()
    with reader, writer, pytest.raises(OSError):
        guardian._runtime_guardian(reader.fileno(), os.getppid(), db_path, 1, "nonce",
                                   scratch, cutoff, wall, Path("/not-read"))
    assert state(db_path)[1:] == ("pending", None)
    assert (scratch / "unexpected").is_file()


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS Seatbelt")
def test_exact_native_offline_probe_when_operator_supplies_pinned_binary(tmp_path):
    binary = os.environ.get("METIS_ISSUE6_PINNED_CODEX")
    if not binary:
        pytest.skip("set METIS_ISSUE6_PINNED_CODEX to the approved native offline version probe binary")
    database, workspace, admission, args = prepare(tmp_path)
    with start_offline_runtime_canary(admission, workspace, *args, Path(binary)) as canary:
        assert canary.wait() == 0
    assert state(database)[1:] == ("reaped", "completed")
    assert list(workspace.iterdir()) == []
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT COUNT(*) FROM issue6_dry_reservations").fetchone() == (1,)
    assert b"CODEX_HOME" not in database.read_bytes()

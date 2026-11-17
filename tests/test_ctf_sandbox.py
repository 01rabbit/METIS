import json
import os
import signal
import sqlite3
import stat
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from metis.cli import main
from metis.core.agent_host import FakeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession
from metis.core.ctf_sandbox import Sandbox, SandboxRequest, configure, status

IMAGE = "sha256:" + "a" * 64


def _metis_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    executable = Path(sys.executable).with_name("metis")
    return subprocess.run([str(executable), *arguments], capture_output=True, text=True,
                          check=False, timeout=30)

FAKE_ENGINE = textwrap.dedent('''\
    #!{python}
    """Test double for a container engine: records argv, emulates /work in a temp dir."""
    import json, os, subprocess, sys, tempfile, time
    log = os.environ["FAKE_ENGINE_LOG"]
    containers = log + ".containers"
    with open(log, "a") as stream:
        stream.write(json.dumps(sys.argv[1:]) + "\\n")
    if sys.argv[1] == "version":
        print('"27.0"')
        raise SystemExit(0)
    if sys.argv[1] == "rm":
        if os.environ.get("FAKE_ENGINE_RM_FAIL") == "1":
            raise SystemExit(2)
        try:
            os.unlink(containers)
        except FileNotFoundError:
            pass
        raise SystemExit(0)
    if sys.argv[1] == "inspect":
        if os.path.exists(containers):
            print("fake-container-id")
            raise SystemExit(0)
        print("Error: No such object: " + sys.argv[-1], file=sys.stderr)
        raise SystemExit(1)
    if sys.argv[1] == "create":
        with open(containers, "w") as stream:
            json.dump(sys.argv[1:], stream)
        print("fake-container-id")
        raise SystemExit(0)
    if sys.argv[1] != "start":
        raise SystemExit("unexpected engine command")
    with open(containers) as stream:
        created = json.load(stream)
    if os.environ.get("FAKE_ENGINE_BLOCK_START") == "1":
        with open(os.environ["FAKE_ENGINE_STARTED"], "w") as stream:
            stream.write("started")
        while True:
            time.sleep(1)
    script = created[created.index("-c") + 1]
    work = tempfile.mkdtemp()
    script = script.replace("/work", work)
    raise SystemExit(subprocess.run([sys.executable, "-I", "-c", script]).returncode)
''')


@pytest.fixture
def engine(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "docker"
    fake.write_text(FAKE_ENGINE.format(python=sys.executable))
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "engine.log"
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_ENGINE_LOG", str(log))
    return log


def _run(tmp_path: Path) -> tuple[Path, str]:
    database = tmp_path / "state" / "metis.sqlite"
    target = tmp_path / "chall"
    target.write_text("#!/bin/sh\nread name\necho \"hello $name\"\necho \"args:$*\" 1>&2\n")
    library = tmp_path / "libc.so.6"
    library.write_bytes(b"\x7fELF fake library")
    context = CodexSession(database).intake(title="Binary", description="Run it",
                                            paths=[target, library], categories=["pwn"])
    return database, context["run_id"]


def test_sandbox_requires_immutable_image(tmp_path):
    database = tmp_path / "state" / "metis.sqlite"
    with pytest.raises(ValueError):
        configure(database, engine="docker", image="debian:latest", platform=None)
    with pytest.raises(ValueError, match="not configured"):
        Sandbox(database)
    assert status(database)["configured"] is False


def test_resource_profiles_are_fixed_and_isolated(tmp_path):
    database = tmp_path / "state" / "metis.sqlite"
    configure(database, engine="docker", image=IMAGE, platform=None)
    sandbox = Sandbox(database)
    standard = sandbox.command("standard")
    zipcrypto = sandbox.command("zipcrypto", profile="zipcrypto")
    lowmem = sandbox.command("zipcrypto-lowmem", profile="zipcrypto_test_lowmem")
    assert "--memory=512m" in standard and "--cpus=1" in standard and "--ipc=none" in standard
    assert "--memory=2g" in zipcrypto and "--memory-swap=2g" in zipcrypto
    assert "--cpus=4" in zipcrypto and "--ipc=private" in zipcrypto
    assert "--memory=128m" in lowmem and "--memory-swap=128m" in lowmem
    assert "--cpus=4" in lowmem and "--ipc=private" in lowmem
    assert "--network=none" in zipcrypto and "--read-only" in zipcrypto
    with pytest.raises(ValueError, match="resource profile"):
        sandbox.command("invalid", profile="unbounded")


def test_sandbox_isolation_flags_and_execution(tmp_path, engine):
    database, run_id = _run(tmp_path)
    configure(database, engine="docker", image=IMAGE, platform="linux/amd64")
    session = CodexSession(database)
    artifacts = session.context(run_id)["challenge"]["artifacts"]
    sandbox = Sandbox(database)
    result = sandbox.execute(run_id, SandboxRequest(target=artifacts[0], extra=[artifacts[1]],
                                                     args=["-x"], stdin=b"metis\n"))
    assert result["ok"] is True, result
    assert result["stdout"]["text"] == "hello metis\n"
    assert "args:-x" in result["stderr"]["text"]
    assert result["files_in_sandbox"] == ["chall", "libc.so.6"]
    commands = [json.loads(line) for line in engine.read_text().splitlines()]
    argv = next(command for command in commands if command[0] == "create")
    for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                 "--user=65534:65534", "--pull=never", "--rm"):
        assert flag in argv
    assert not any(item.startswith(("-v", "--volume", "--mount")) for item in argv)
    assert IMAGE in argv and "linux/amd64" in argv
    assert session.context(run_id)["status"] == "planning"


def test_sandbox_script_mode_and_scope(tmp_path, engine):
    database, run_id = _run(tmp_path)
    configure(database, engine="docker", image=IMAGE, platform=None)
    session = CodexSession(database)
    target = session.context(run_id)["challenge"]["artifacts"][0]
    sandbox = Sandbox(database)
    result = sandbox.execute(run_id, SandboxRequest(
        target=target, mode="script",
        script="import os, subprocess\nprint(subprocess.run([os.environ['METIS_TARGET']], input=b'x\\n',"
               " capture_output=True).stdout.decode().strip())\n"))
    assert result["stdout"]["text"].strip() == "hello x"
    with pytest.raises(ValueError, match="declared"):
        sandbox.execute(run_id, SandboxRequest(target="../../etc/passwd"))
    with pytest.raises(ValueError):
        SandboxRequest(target=target, mode="shell")


def test_sandbox_reports_timeout_and_nonzero_exit(tmp_path, engine):
    database = tmp_path / "state" / "metis.sqlite"
    slow = tmp_path / "slow"
    slow.write_text("#!/bin/sh\nsleep 5\n")
    crash = tmp_path / "crash"
    crash.write_text("#!/bin/sh\nexit 3\n")
    run_id = CodexSession(database).intake(title="t", description="d", paths=[slow, crash])["run_id"]
    configure(database, engine="docker", image=IMAGE, platform=None)
    artifacts = CodexSession(database).context(run_id)["challenge"]["artifacts"]
    sandbox = Sandbox(database)
    timed = sandbox.execute(run_id, SandboxRequest(target=artifacts[0], timeout=1))
    assert timed["timed_out"] is True and timed["ok"] is False
    failed = sandbox.execute(run_id, SandboxRequest(target=artifacts[1]))
    assert failed["exit_code"] == 3 and failed["ok"] is False


@pytest.mark.parametrize("phase", ["container-create", "engine-attach", "oom-inspection"])
def test_zipcrypto_engine_timeouts_are_distinct_from_workload_deadline(tmp_path, monkeypatch, engine, phase):
    from metis.core import ctf_sandbox
    from metis.core.ctf_zipcrypto_worker import run_zipcrypto_attack

    database, run_id = _run(tmp_path)
    configure(database, engine="docker", image=IMAGE, platform=None)
    session = CodexSession(database)
    target = session.context(run_id)["challenge"]["artifacts"][0]
    original_run = ctf_sandbox.subprocess.run
    original_popen = ctf_sandbox.subprocess.Popen
    inspection_timed_out = False

    def timeout_selected(command, *args, **kwargs):
        nonlocal inspection_timed_out
        if command[0] == "docker" and (
            (phase == "container-create" and command[1] == "create")
            or (phase == "oom-inspection" and command[1] == "inspect" and not inspection_timed_out)
        ):
            if phase == "oom-inspection":
                inspection_timed_out = True
            raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))
        return original_run(command, *args, **kwargs)

    class StalledAttach:
        def __init__(self, command):
            self.args = command
            self.returncode = -9
            self.expired = False

        def communicate(self, input=None, timeout=None):
            if not self.expired:
                self.expired = True
                raise subprocess.TimeoutExpired(self.args, timeout)
            return b"", b""

    def attach_selected(command, *args, **kwargs):
        if phase == "engine-attach" and command[:3] == ["docker", "start", "--attach"]:
            return StalledAttach(command)
        return original_popen(command, *args, **kwargs)

    monkeypatch.setattr(ctf_sandbox.subprocess, "run", timeout_selected)
    monkeypatch.setattr(ctf_sandbox.subprocess, "Popen", attach_selected)
    result = run_zipcrypto_attack(database, run_id, target, {
        "member": "known.txt", "plaintext_hex": "4142434445464748494a4b4c", "offset": 0, "seconds": 5,
    })
    assert result["found"] is False
    if phase == "container-create":
        assert result["reason"] == "worker_failed" and result["stage"] == "container-create"
    elif phase == "engine-attach":
        assert result["reason"] == "worker_failed" and result["stage"] == "engine-attach", result
    else:
        assert result["reason"] == "worker_failed" and result["stage"] == "oom-inspection"


def test_cancel_stops_registered_sandbox_worker(tmp_path, engine):
    database, run_id = _run(tmp_path)
    configure(database, engine="docker", image=IMAGE, platform=None)
    Sandbox(database)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO sandbox_workers VALUES (?, ?, ?, ?)",
                   (run_id, "docker", "metis-sandbox-cancel-test", time.time()))
    result = CodexSession(database).cancel(run_id)
    assert result["status"] == "cancelled"
    assert result["worker_teardown"]["status"] == "confirmed"
    assert any(json.loads(line)[:3] == ["rm", "-f", "metis-sandbox-cancel-test"]
               for line in engine.read_text().splitlines())


def test_sandbox_cleanup_failure_keeps_worker_registered_until_recovery(tmp_path, engine, monkeypatch):
    from metis.core import ctf_sandbox

    database, run_id = _run(tmp_path)
    configure(database, engine="docker", image=IMAGE, platform=None)
    session = CodexSession(database)
    target = session.context(run_id)["challenge"]["artifacts"][0]
    original_remove = ctf_sandbox._remove_container
    monkeypatch.setattr(ctf_sandbox, "_remove_container",
                        lambda *_: {"status": "unknown", "reason": "engine did not confirm absence"})

    with pytest.raises(RuntimeError, match="cleanup could not be confirmed"):
        Sandbox(database).execute(run_id, SandboxRequest(target=target))
    assert session.context(run_id)["status"] == "executing"
    with sqlite3.connect(database) as db:
        row = db.execute("SELECT engine, container_name FROM sandbox_workers WHERE run_id=?",
                         (run_id,)).fetchone()
    assert row and row[0] == "docker"

    monkeypatch.setattr(ctf_sandbox, "_remove_container", original_remove)
    recovered = session.recover(run_id)
    assert recovered["worker_teardown"]["status"] == "confirmed"
    assert recovered["status"] == "planning"
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT 1 FROM sandbox_workers WHERE run_id=?", (run_id,)).fetchone() is None


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="process-group termination requires POSIX")
def test_separate_controller_recovers_orphaned_sandbox_idempotently(tmp_path, engine):
    database, run_id = _run(tmp_path)
    configure(database, engine="docker", image=IMAGE, platform=None)
    Sandbox(database)  # create the persistent worker registry before controller A starts
    session = CodexSession(database)
    target = session.context(run_id)["challenge"]["artifacts"][0]
    initial_actions = session.context(run_id)["actions_remaining"]
    started = tmp_path / "fake-engine-started"
    environment = os.environ.copy()
    environment.update(FAKE_ENGINE_BLOCK_START="1", FAKE_ENGINE_STARTED=str(started))
    launch_code = textwrap.dedent(f"""
        from pathlib import Path
        from metis.core.ctf_sandbox import Sandbox, SandboxRequest
        Sandbox(Path({str(database)!r})).execute(
            {run_id!r}, SandboxRequest(target={target!r}, timeout=300))
    """)
    controller_a = subprocess.Popen([sys.executable, "-c", launch_code], env=environment,
                                    start_new_session=True, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
    worker = None
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            with sqlite3.connect(database) as db:
                worker = db.execute("SELECT engine, container_name FROM sandbox_workers WHERE run_id=?",
                                    (run_id,)).fetchone()
            if worker and started.exists():
                break
            if controller_a.poll() is not None:
                raise AssertionError("controller A exited before starting its sandbox worker")
            time.sleep(0.05)
        assert worker and started.exists(), "controller A did not register and start the worker"
        before_recovery = CodexSession(database).context(run_id)
        assert before_recovery["status"] == "executing"
        assert before_recovery["actions_remaining"] < initial_actions
    finally:
        try:
            os.killpg(controller_a.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        controller_a.wait(timeout=10)

    assert worker is not None
    recovery_code = textwrap.dedent(f"""
        import json
        from pathlib import Path
        from metis.core.codex_session import CodexSession
        try:
            result = CodexSession(Path({str(database)!r})).recover({run_id!r})
            print(json.dumps({{"status": result["status"], "worker": result["worker_teardown"]}}))
        except RuntimeError as exc:
            print(json.dumps({{"error": str(exc)}}))
    """)

    def recover_from_new_process(env_overrides):
        child_env = os.environ.copy()
        child_env.update(env_overrides)
        return subprocess.run([sys.executable, "-c", recovery_code], env=child_env,
                              capture_output=True, text=True, timeout=20, check=False)

    uncertain = recover_from_new_process({"FAKE_ENGINE_RM_FAIL": "1"})
    assert uncertain.returncode == 0, uncertain.stderr
    assert json.loads(uncertain.stdout) == {
        "error": "recovery blocked: sandbox worker teardown is unknown"}
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT 1 FROM sandbox_workers WHERE run_id=?", (run_id,)).fetchone() is not None
    after_unknown = CodexSession(database).context(run_id)
    assert after_unknown["status"] == "executing"
    assert after_unknown["actions_remaining"] == before_recovery["actions_remaining"]

    recovered_process = recover_from_new_process({})
    assert recovered_process.returncode == 0, recovered_process.stderr
    recovered = json.loads(recovered_process.stdout)
    assert recovered == {"status": "planning", "worker": {"status": "confirmed"}}
    after_recovery = CodexSession(database).context(run_id)
    assert after_recovery["actions_remaining"] == before_recovery["actions_remaining"]
    assert after_recovery["status"] == "planning"
    assert not any(event.status == "solved" for event in session.store.read(run_id))
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT 1 FROM sandbox_workers WHERE run_id=?", (run_id,)).fetchone() is None

    repeated = recover_from_new_process({})
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout) == {"status": "planning", "worker": {"status": "not_running"}}
    assert CodexSession(database).context(run_id)["actions_remaining"] == before_recovery["actions_remaining"]


def test_cli_sandbox(tmp_path, engine, monkeypatch, capsys):
    database, run_id = _run(tmp_path)
    monkeypatch.setattr(sys, "argv", ["metis", "sandbox", "--database", str(database), "configure",
                                      "--image", IMAGE])
    assert main() == 0
    capsys.readouterr()
    artifacts = CodexSession(database).context(run_id)["challenge"]["artifacts"]
    stdin = tmp_path / "input.txt"
    stdin.write_text("cli\n")
    monkeypatch.setattr(sys, "argv", ["metis", "sandbox", "--database", str(database), "run", run_id,
                                      artifacts[0], "--stdin-file", str(stdin)])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["stdout"]["text"] == "hello cli\n"


def test_real_engine_isolation_smoke(tmp_path):
    image = os.environ.get("METIS_TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("set METIS_TEST_SANDBOX_IMAGE to a built metis sandbox image ID")
    database, run_id = _run(tmp_path)
    configure(database, engine="docker", image=image, platform=None)
    target = CodexSession(database).context(run_id)["challenge"]["artifacts"][0]
    sandbox = Sandbox(database)
    assert sandbox.execute(run_id, SandboxRequest(target=target, stdin=b"real\n"))["stdout"]["text"] \
        == "hello real\n"
    probe = sandbox.execute(run_id, SandboxRequest(target=target, mode="script", script=(
        "import os, socket\n"
        "try:\n    socket.create_connection(('1.1.1.1', 80), timeout=2); print('net-open')\n"
        "except OSError: print('net-blocked')\n"
        "try:\n    open('/etc/metis', 'w'); print('rootfs-writable')\n"
        "except OSError: print('rootfs-readonly')\n"
        "print('uid', os.getuid())\n")))
    assert probe["stdout"]["text"].split() == ["net-blocked", "rootfs-readonly", "uid", "65534"]


def test_real_engine_enforces_memory_limit(tmp_path):
    image = os.environ.get("METIS_TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("set METIS_TEST_SANDBOX_IMAGE to a built metis sandbox image ID")
    database, run_id = _run(tmp_path)
    configure(database, engine="docker", image=image, platform=None)
    target = CodexSession(database).context(run_id)["challenge"]["artifacts"][0]
    result = Sandbox(database).execute(run_id, SandboxRequest(
        target=target, mode="script", timeout=20,
        script=("blocks = []\n"
                "for _ in range(700):\n"
                "    blocks.append(bytearray(1024 * 1024))\n"
                "print('allocation completed')\n")))
    assert result["ok"] is False
    assert result.get("signal") == 9
    assert result["memory_limit_exceeded"] is True
    assert result["stdout"]["text"] == ""


def test_real_engine_timeout_removes_process_group(tmp_path, monkeypatch):
    image = os.environ.get("METIS_TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("set METIS_TEST_SANDBOX_IMAGE to a built metis sandbox image ID")
    from types import SimpleNamespace

    from metis.core import ctf_sandbox

    database, run_id = _run(tmp_path)
    configure(database, engine="docker", image=image, platform=None)
    target = CodexSession(database).context(run_id)["challenge"]["artifacts"][0]
    name = "metis-sandbox-" + "timeout-process-group"[:16]
    monkeypatch.setattr(ctf_sandbox, "uuid4", lambda: SimpleNamespace(hex="timeout-process-group"))
    result = Sandbox(database).execute(run_id, SandboxRequest(
        target=target, mode="script", timeout=1,
        script=("import subprocess, sys, time\n"
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                "time.sleep(60)\n")))
    assert result["timed_out"] is True
    assert result.get("elapsed") is not None  # the in-container supervisor returned its timeout record
    inspected = subprocess.run(["docker", "inspect", name], capture_output=True, check=False)
    assert inspected.returncode != 0


def test_real_engine_cancel_confirms_container_teardown(tmp_path):
    image = os.environ.get("METIS_TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("set METIS_TEST_SANDBOX_IMAGE to a built metis sandbox image ID")
    database, run_id = _run(tmp_path)
    configure(database, engine="docker", image=image, platform=None)
    target = CodexSession(database).context(run_id)["challenge"]["artifacts"][0]
    Sandbox(database)
    outcome = {}

    def execute():
        outcome.update(Sandbox(database).execute(run_id, SandboxRequest(
            target=target, mode="script", timeout=60, script="import time; time.sleep(60)\n")))

    thread = threading.Thread(target=execute)
    thread.start()
    deadline = time.monotonic() + 15
    worker = None
    while time.monotonic() < deadline:
        with sqlite3.connect(database) as db:
            row = db.execute("SELECT container_name FROM sandbox_workers WHERE run_id=?",
                             (run_id,)).fetchone()
        if row:
            worker = row[0]
            inspected = subprocess.run(["docker", "inspect", "--format", "{{.State.Running}}", worker],
                                       capture_output=True, check=False)
            if inspected.returncode == 0 and inspected.stdout.strip() == b"true":
                break
        time.sleep(0.05)
    assert worker is not None
    result = CodexSession(database).cancel(run_id)
    thread.join(timeout=15)
    assert not thread.is_alive()
    assert result["worker_teardown"]["status"] == "confirmed"
    assert CodexSession(database).context(run_id)["status"] == "cancelled"
    assert (outcome.get("cancelled") or outcome.get("error")
            or outcome.get("engine_exit_code") is not None)
    assert subprocess.run(["docker", "inspect", worker], capture_output=True,
                          check=False).returncode != 0


def test_real_engine_cli_cancel_confirms_container_teardown(tmp_path):
    image = os.environ.get("METIS_TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("set METIS_TEST_SANDBOX_IMAGE to a built metis sandbox image ID")
    database, run_id = _run(tmp_path)
    configure(database, engine="docker", image=image,
              platform=os.environ.get("METIS_TEST_SANDBOX_PLATFORM"))
    session = CodexSession(database)
    target = session.context(run_id)["challenge"]["artifacts"][0]
    initial_actions = session.context(run_id)["actions_remaining"]
    Sandbox(database)
    outcome = {}

    def execute():
        outcome.update(Sandbox(database).execute(run_id, SandboxRequest(
            target=target, mode="script", timeout=60,
            script="import time; time.sleep(60)\n")))

    thread = threading.Thread(target=execute)
    thread.start()
    worker = None
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with sqlite3.connect(database) as db:
                row = db.execute("SELECT container_name FROM sandbox_workers WHERE run_id=?",
                                 (run_id,)).fetchone()
            if row:
                worker = row[0]
                inspected = subprocess.run(
                    ["docker", "inspect", "--format", "{{.State.Running}}", worker],
                    capture_output=True, check=False, timeout=10)
                if inspected.returncode == 0 and inspected.stdout.strip() == b"true":
                    break
            time.sleep(0.05)
        assert worker is not None and inspected.returncode == 0
        assert inspected.stdout.strip() == b"true"

        cancelled = _metis_cli("codex", "--database", str(database), "cancel", run_id)
        assert cancelled.returncode == 0, cancelled.stderr
        result = json.loads(cancelled.stdout)
        assert result["worker_teardown"]["status"] == "confirmed"
        thread.join(timeout=15)
        assert not thread.is_alive()
        assert session.context(run_id)["status"] == "cancelled"
        assert session.context(run_id)["actions_remaining"] < initial_actions
        assert (outcome.get("cancelled") or outcome.get("error")
                or outcome.get("engine_exit_code") is not None)
        assert not any(event.status.value == "solved" for event in session.store.read(run_id))
        assert subprocess.run(["docker", "inspect", worker], capture_output=True,
                              check=False, timeout=10).returncode != 0
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT 1 FROM sandbox_workers WHERE run_id=?",
                              (run_id,)).fetchone() is None
    finally:
        if thread.is_alive():
            session.cancel(run_id)
            thread.join(timeout=15)
        if worker:
            subprocess.run(["docker", "rm", "-f", worker], capture_output=True,
                           check=False, timeout=30)


def test_agent_cancel_interrupts_long_artifact_intent(tmp_path, monkeypatch):
    image = os.environ.get("METIS_TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("set METIS_TEST_SANDBOX_IMAGE to a built metis sandbox image ID")
    from metis.core import codex_session

    database = tmp_path / "state" / "metis.sqlite"
    target_path = tmp_path / "challenge.txt"
    target_path.write_text("bounded sandbox cancellation target")
    run_id = CodexSession(database).intake(title="Agent cancellation", description="Synthetic local operation",
                                           paths=[target_path], categories=["crypto", "forensics"])["run_id"]
    configure(database, engine="docker", image=image, platform=os.environ.get("METIS_TEST_SANDBOX_PLATFORM"))
    Sandbox(database)  # initialize the worker registry before the intent thread starts
    session = CodexSession(database)
    target = session.context(run_id)["challenge"]["artifacts"][0]
    scheduler = AgentScheduler(database, FakeHost(script={
        role: lambda _assignment, _brief: {"state": "hang"}
        for role in ("crypto-specialist", "forensics-specialist")
    }, max_parallel=2))
    scheduler.configure(global_slots=2, per_run_slots=2)
    wave = scheduler.ledger.create_wave(run_id, mode="delegated")
    scheduler.enqueue(run_id, wave["wave_id"])
    scheduler.dispatch(run_id)
    job = next(item for item in scheduler.jobs(run_id) if item["state"] == "running")

    def run_long_tool(_root, _name, _tool, _options, **_kwargs):
        return Sandbox(database).execute(run_id, SandboxRequest(
            target=target, mode="script", timeout=300,
            script="import time; time.sleep(300)\n"), _reserved=True)

    monkeypatch.setattr(codex_session, "inspect_file", run_long_tool)
    errors = []
    def intent():
        try:
            scheduler.intent(run_id, job["assignment_id"], job["attempt_id"],
                             {"kind": "artifact", "tool": "text", "artifact": target})
        except ValueError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=intent)
    thread.start()
    deadline = time.monotonic() + 20
    worker = None
    while time.monotonic() < deadline:
        with sqlite3.connect(database) as db:
            row = db.execute("SELECT container_name FROM sandbox_workers WHERE run_id=?", (run_id,)).fetchone()
        if row:
            worker = row[0]
            inspected = subprocess.run(["docker", "inspect", "--format", "{{.State.Running}}", worker],
                                       capture_output=True, check=False)
            if inspected.returncode == 0 and inspected.stdout.strip() == b"true":
                break
        time.sleep(0.05)
    assert worker is not None and inspected is not None and inspected.returncode == 0
    assert inspected.stdout.strip() == b"true"

    cancelled = scheduler.cancel(assignment_id=job["assignment_id"])
    thread.join(timeout=20)
    assert not thread.is_alive() and errors
    assert cancelled[0]["state"] == "cancelled"
    assert subprocess.run(["docker", "inspect", worker], capture_output=True, check=False).returncode != 0
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM codex_active_operations WHERE run_id=?", (run_id,)
                          ).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM agent_actions WHERE assignment_id=?",
                          (job["assignment_id"],)).fetchone()[0] == 0


def test_real_engine_recovery_stops_orphaned_sandbox_before_resuming(tmp_path):
    image = os.environ.get("METIS_TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("set METIS_TEST_SANDBOX_IMAGE to a built metis sandbox image ID")
    database, run_id = _run(tmp_path)
    configure(database, engine="docker", image=image, platform=None)
    target = CodexSession(database).context(run_id)["challenge"]["artifacts"][0]
    Sandbox(database)
    outcome = {}

    def execute():
        outcome.update(Sandbox(database).execute(run_id, SandboxRequest(
            target=target, mode="script", timeout=60, script="import time; time.sleep(60)\n")))

    thread = threading.Thread(target=execute)
    thread.start()
    deadline = time.monotonic() + 15
    worker = None
    while time.monotonic() < deadline:
        with sqlite3.connect(database) as db:
            row = db.execute("SELECT container_name FROM sandbox_workers WHERE run_id=?",
                             (run_id,)).fetchone()
        if row:
            worker = row[0]
        inspected = (subprocess.run(["docker", "inspect", worker], capture_output=True, check=False)
                     if worker else None)
        if inspected and inspected.returncode == 0:
            break
        time.sleep(0.05)
    assert worker is not None and inspected is not None and inspected.returncode == 0
    recovered = CodexSession(database).recover(run_id)
    thread.join(timeout=15)
    assert not thread.is_alive()
    assert recovered["worker_teardown"]["status"] == "confirmed"
    assert recovered["status"] == "planning"
    assert not any(event.status.value == "solved" for event in CodexSession(database).store.read(run_id))
    assert outcome.get("cancelled") is True
    assert subprocess.run(["docker", "inspect", worker], capture_output=True,
                          check=False).returncode != 0


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="process-group termination requires POSIX")
def test_real_engine_separate_controller_recovers_orphaned_sandbox(tmp_path):
    image = os.environ.get("METIS_TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("set METIS_TEST_SANDBOX_IMAGE to a built metis sandbox image ID")
    database, run_id = _run(tmp_path)
    configure(database, engine="docker", image=image, platform=None)
    session = CodexSession(database)
    target = session.context(run_id)["challenge"]["artifacts"][0]
    initial_actions = session.context(run_id)["actions_remaining"]
    Sandbox(database)  # initialize persistent worker registry before controller A starts
    launch_code = textwrap.dedent(f"""
        from pathlib import Path
        from metis.core.ctf_sandbox import Sandbox, SandboxRequest
        Sandbox(Path({str(database)!r})).execute(
            {run_id!r}, SandboxRequest(target={target!r}, mode="script", timeout=300,
                                       script="import time; time.sleep(300)\\n"))
    """)
    controller_a = subprocess.Popen([sys.executable, "-c", launch_code],
                                    start_new_session=True, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
    worker = None
    before_recovery = None
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with sqlite3.connect(database) as db:
                row = db.execute("SELECT container_name FROM sandbox_workers WHERE run_id=?",
                                 (run_id,)).fetchone()
            if row:
                worker = row[0]
                inspected = subprocess.run(["docker", "inspect", "--format={{.State.Running}}", worker],
                                           capture_output=True, text=True, check=False, timeout=10)
                if inspected.returncode == 0 and inspected.stdout.strip() == "true":
                    break
            if controller_a.poll() is not None:
                raise AssertionError("controller A exited before its sandbox worker was running")
            time.sleep(0.05)
        assert worker is not None and inspected.returncode == 0 and inspected.stdout.strip() == "true", \
            "controller A did not start a live Docker worker"
        before_recovery = session.context(run_id)
        assert before_recovery["status"] == "executing"
        assert before_recovery["actions_remaining"] < initial_actions
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT 1 FROM sandbox_workers WHERE run_id=?", (run_id,)).fetchone()

        # Exercise the operator runbook's inspection commands while the worker is active.
        inspected = _metis_cli("inspect", "--database", str(database), run_id)
        assert inspected.returncode == 0, inspected.stderr
        assert json.loads(inspected.stdout.splitlines()[-1])["status"] == "executing"
        engine_status = _metis_cli("sandbox", "--database", str(database), "status")
        assert engine_status.returncode == 0, engine_status.stderr
        assert json.loads(engine_status.stdout)["engine_available"] is True

        os.killpg(controller_a.pid, signal.SIGKILL)
        controller_a.wait(timeout=10)
        orphan = subprocess.run(["docker", "inspect", "--format={{.State.Running}}", worker],
                                capture_output=True, text=True, check=False, timeout=10)
        assert orphan.returncode == 0 and orphan.stdout.strip() == "true", \
            "the sandbox did not survive controller A termination"

        recovered_process = _metis_cli("codex", "--database", str(database), "recover", run_id)
        assert recovered_process.returncode == 0, recovered_process.stderr
        recovered_json = json.loads(recovered_process.stdout)
        assert recovered_json["status"] == "planning"
        assert recovered_json["worker_teardown"]["status"] == "confirmed"
        after_recovery = session.context(run_id)
        assert after_recovery["actions_remaining"] == before_recovery["actions_remaining"]
        assert after_recovery["status"] == "planning"
        assert not any(event.status.value == "solved" for event in session.store.read(run_id))
        assert subprocess.run(["docker", "inspect", worker], capture_output=True,
                              check=False, timeout=10).returncode != 0
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT 1 FROM sandbox_workers WHERE run_id=?", (run_id,)).fetchone() is None

        final_inspection = _metis_cli("inspect", "--database", str(database), run_id)
        assert final_inspection.returncode == 0, final_inspection.stderr
        assert json.loads(final_inspection.stdout.splitlines()[-1])["status"] == "planning"
        board = _metis_cli("codex", "--database", str(database), "board")
        assert board.returncode == 0, board.stderr
        assert any(item["run_id"] == run_id for item in json.loads(board.stdout)["sessions"])

        repeated = _metis_cli("codex", "--database", str(database), "recover", run_id)
        assert repeated.returncode == 0, repeated.stderr
        assert json.loads(repeated.stdout)["worker_teardown"]["status"] == "not_running"
        assert session.context(run_id)["actions_remaining"] == before_recovery["actions_remaining"]
    finally:
        if controller_a.poll() is None:
            try:
                os.killpg(controller_a.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            controller_a.wait(timeout=10)
        if worker:
            subprocess.run(["docker", "rm", "-f", worker], capture_output=True,
                           check=False, timeout=30)


def _elf(machine: int) -> bytes:
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4], header[5] = 2, 1
    header[18:20] = machine.to_bytes(2, "little")
    return bytes(header)


def test_elf_arch_and_platform_defaults(monkeypatch):
    from metis.core import ctf_sandbox
    assert ctf_sandbox.elf_arch(_elf(0x3E)) == "x86_64"
    assert ctf_sandbox.elf_arch(_elf(0xB7)) == "aarch64"
    assert ctf_sandbox.elf_arch(b"#!/bin/sh\n" + bytes(64)) is None
    monkeypatch.setattr(ctf_sandbox.platform_module, "machine", lambda: "arm64")
    assert ctf_sandbox.default_platform() == "linux/arm64"
    monkeypatch.setattr(ctf_sandbox.platform_module, "machine", lambda: "x86_64")
    assert ctf_sandbox.default_platform() == "linux/amd64"


def test_foreign_architecture_target_is_emulated(tmp_path, engine):
    database = tmp_path / "state" / "metis.sqlite"
    x86 = tmp_path / "x86"
    x86.write_bytes(_elf(0x3E))
    arm = tmp_path / "arm"
    arm.write_bytes(_elf(0xB7))
    run_id = CodexSession(database).intake(title="t", description="d", paths=[x86, arm])["run_id"]
    configure(database, engine="docker", image=IMAGE, platform="linux/arm64")
    artifacts = CodexSession(database).context(run_id)["challenge"]["artifacts"]
    sandbox = Sandbox(database)
    foreign = sandbox.execute(run_id, SandboxRequest(target=artifacts[0]))
    assert foreign["target_arch"] == "x86_64" and foreign["emulation"] == "qemu-x86_64"
    native = sandbox.execute(run_id, SandboxRequest(target=artifacts[1]))
    assert native["target_arch"] == "aarch64" and native["emulation"] is None
    forced_off = sandbox.execute(run_id, SandboxRequest(target=artifacts[0], emulate="off"))
    assert forced_off["emulation"] is None
    with pytest.raises(ValueError):
        SandboxRequest(target=artifacts[0], emulate="mips")


def test_build_reports_stopped_engine(tmp_path, monkeypatch, capsys):
    from metis.core import ctf_sandbox
    monkeypatch.setattr(ctf_sandbox, "engine_available", lambda engine: False)
    monkeypatch.setattr(sys, "argv", ["metis", "sandbox", "--database", str(tmp_path / "s" / "m.sqlite"),
                                      "build"])
    with pytest.raises(SystemExit):
        main()
    assert "not running" in capsys.readouterr().err


def test_missing_cross_libc_and_ltrace_are_reported(tmp_path, engine):
    database = tmp_path / "state" / "metis.sqlite"
    x86 = tmp_path / "x86"
    x86.write_bytes(_elf(0x3E))
    run_id = CodexSession(database).intake(title="t", description="d", paths=[x86])["run_id"]
    configure(database, engine="docker", image=IMAGE, platform="linux/arm64")
    target = CodexSession(database).context(run_id)["challenge"]["artifacts"][0]
    result = Sandbox(database).execute(run_id, SandboxRequest(target=target))
    # The fake engine has no /usr/x86_64-linux-gnu, so the bootstrap must say so plainly.
    assert result["ok"] is False and "cross libc for x86_64" in result["stderr"]["text"]

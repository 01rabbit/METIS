"""Dynamic execution of challenge programs inside a disposable container.

Challenge binaries never run on the host. The controller streams the declared
run artifacts into a fresh container over stdin (no bind mounts, no ``docker
cp``), runs one bounded operation, and returns bounded output. The standard container has
no network, a read-only root filesystem, a size-limited executable tmpfs, no
capabilities, no privilege escalation, an unprivileged user, and CPU, memory and
PID limits. A fixed ZipCrypto worker profile raises its bounded memory and CPU
quotas while retaining the same isolation. On macOS, Docker Desktop/Colima/OrbStack
add a Linux VM boundary.

Container isolation is defense in depth, not a proof against kernel exploits;
use a dedicated VM for hostile competitions when that matters.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform as platform_module
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from pydantic import Field, field_validator

from metis.core.artifacts import artifact_stream
from metis.core.codex_session import CodexSession
from metis.core.contracts import Contract, RunStatus
from metis.core.resources import ResourceBroker
from metis.core.run_lock import operation_lock, run_lock

MODES = ("run", "strace", "ltrace", "gdb", "script")
MAX_INPUT = 64 * 1_048_576
MAX_STDIN = 1_048_576
MAX_STREAM = 262_144
IMAGE_PATTERN = re.compile(r"(?:[a-z0-9./_:-]+@sha256:[0-9a-f]{64}|sha256:[0-9a-f]{64})")
ROOT = Path(__file__).resolve().parents[3]
PLATFORM_PATTERN = re.compile(r"linux/(amd64|arm64|386|arm/v7)")
# ELF e_machine -> architecture name.
ELF_MACHINES = {0x3E: "x86_64", 0x03: "i386", 0xB7: "aarch64", 0x28: "arm"}
PLATFORM_ARCH = {"linux/amd64": "x86_64", "linux/386": "i386", "linux/arm64": "aarch64",
                 "linux/arm/v7": "arm"}
# QEMU user-mode emulator and cross sysroot installed in the bundled image.
EMULATORS = {"x86_64": ("qemu-x86_64", "/usr/x86_64-linux-gnu"),
             "i386": ("qemu-i386", "/usr/i686-linux-gnu"),
             "aarch64": ("qemu-aarch64", "/usr/aarch64-linux-gnu"),
             "arm": ("qemu-arm", "/usr/arm-linux-gnueabihf")}
EMULATE_CHOICES = ("auto", "off", *EMULATORS)


def elf_arch(content: bytes) -> str | None:
    """Return the architecture of a little-endian ELF file, or None if unknown."""
    if len(content) < 20 or content[:4] != b"\x7fELF" or content[5] != 1:
        return None
    return ELF_MACHINES.get(struct.unpack_from("<H", content, 18)[0])


def host_arch() -> str:
    machine = platform_module.machine().lower()
    return {"arm64": "aarch64", "amd64": "x86_64", "i686": "i386"}.get(machine, machine)


def default_platform() -> str:
    """Build for the host CPU so native targets can be debugged with ptrace."""
    return "linux/arm64" if host_arch() == "aarch64" else "linux/amd64"

# Runs inside the container as the unprivileged user. Reads a framed bundle on
# fd 0 with os.read (no buffering past the frame), writes files into /work, runs
# the requested operation with a timeout, and prints one JSON result line.
BOOTSTRAP = r'''
import base64, json, os, signal, struct, subprocess, sys, time
def take(n):
    out = bytearray()
    while len(out) < n:
        chunk = os.read(0, n - len(out))
        if not chunk:
            raise SystemExit("truncated bundle")
        out.extend(chunk)
    return bytes(out)
header = json.loads(take(struct.unpack(">I", take(4))[0]))
os.chdir("/work")
for item in header["files"]:
    data = take(item["size"])
    path = os.path.join("/work", item["name"])
    with open(path, "wb") as stream:
        stream.write(data)
    os.chmod(path, 0o755 if item.get("exec") else 0o644)
with open("/work/.stdin", "wb") as stream:
    stream.write(take(header["stdin_size"]))
mode, target, args = header["mode"], "./" + header["target"], header["args"]
trace = "/work/.trace"
emu = header.get("emulate")
prefix = [emu["qemu"], "-L", emu["sysroot"]] if emu else []
missing = None
if emu and not os.path.isdir(emu["sysroot"]):
    missing = "cross libc for " + emu["arch"] + " is not installed in this image (" + emu["sysroot"] + ")"
elif mode == "ltrace" and not emu and not os.path.exists("/usr/bin/ltrace"):
    missing = "ltrace is not packaged for this image architecture; use strace or gdb mode"
if missing:
    mode = "unavailable"

trace_from_stderr = False
background = None
program_log = "/work/.program"
if mode == "unavailable":
    command = ["sh", "-c", 'echo "$0" >&2; exit 2', missing]
elif mode == "run":
    command = [*prefix, target, *args]
elif mode == "strace" and emu:
    command = [*prefix, "-strace", target, *args]
    trace_from_stderr = True
elif mode == "strace":
    command = ["strace", "-f", "-s", "128", "-o", trace, target, *args]
elif mode == "ltrace" and emu:
    command = ["sh", "-c", "echo 'ltrace is unavailable under QEMU emulation; use strace or gdb mode' >&2; exit 2"]
elif mode == "ltrace":
    command = ["ltrace", "-f", "-s", "128", "-o", trace, target, *args]
elif mode == "gdb" and emu:
    # Emulated targets cannot be ptraced; debug through QEMU's gdb stub instead.
    port = "31337"
    stdin_file = open("/work/.stdin", "rb")
    log = open(program_log, "wb")
    background = subprocess.Popen([*prefix, "-g", port, target, *args], stdin=stdin_file,
                                  stdout=log, stderr=subprocess.STDOUT)
    time.sleep(0.3)
    command = ["gdb-multiarch", "-q", "-nx", "-batch", "-ex", "set pagination off",
               "-ex", "set confirm off", "-ex", "set sysroot " + emu["sysroot"],
               "-ex", "file " + target, "-ex", "target remote 127.0.0.1:" + port]
    for line in header["gdb"]:
        word = line.strip().split(" ", 1)[0]
        if word in {"run", "r"}:
            line = "continue"
        elif word == "start":
            command += ["-ex", "tbreak main"]
            line = "continue"
        command += ["-ex", line]
elif mode == "gdb":
    command = ["gdb", "-q", "-nx", "-batch", "-ex", "set pagination off",
               "-ex", "set confirm off", "-ex", "set startup-with-shell off"]
    for line in header["gdb"]:
        command += ["-ex", line]
    command += ["--args", target, *args]
else:
    command = [header["interpreter"], "./.metis-script", *args]
env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/work",
       "LANG": "C.UTF-8", "TERM": "dumb", "PWNLIB_NOTERM": "1", "METIS_TARGET": target,
       "METIS_STDIN": "/work/.stdin", "METIS_RUNNER": " ".join(prefix),
       "METIS_TARGET_ARCH": header.get("target_arch") or ""}
def oom_kills():
    try:
        with open("/sys/fs/cgroup/memory.events") as stream:
            fields = dict(line.split() for line in stream)
        return int(fields.get("oom_kill", "0"))
    except (OSError, ValueError):
        return None
oom_before = oom_kills()
started = time.monotonic()
timed_out = False
with open("/work/.stdin", "rb") as stdin:
    try:
        process = subprocess.Popen(command, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=env, start_new_session=True)
        try:
            out, err = process.communicate(timeout=header["timeout"])
            code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out, code = True, None
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = process.communicate()
    except OSError as exc:
        code, out, err = 127, b"", str(exc).encode()
program = b""
if background is not None:
    try:
        background.wait(timeout=2)
    except subprocess.TimeoutExpired:
        background.kill()
        background.wait()
    with open(program_log, "rb") as stream:
        program = stream.read()
limit = header["max_stream"]
oom_after = oom_kills()
traced = b""
if trace_from_stderr:
    traced, err = err, b""
elif os.path.exists(trace):
    with open(trace, "rb") as stream:
        traced = stream.read(limit + 1)
def pack(data):
    return {"b64": base64.b64encode(data[:limit]).decode(), "size": len(data), "truncated": len(data) > limit}
sys.stdout.write("\n" + json.dumps({"exit_code": code, "timed_out": timed_out,
    "elapsed": round(time.monotonic() - started, 3), "stdout": pack(out), "stderr": pack(err),
    "trace": pack(traced), "program": pack(program),
    "memory_limit_exceeded": (oom_before is not None and oom_after is not None and oom_after > oom_before)}) + "\n")
'''


class SandboxRequest(Contract):
    target: str = Field(min_length=1, max_length=512)
    mode: str = "run"
    args: list[str] = Field(default_factory=list, max_length=64)
    extra: list[str] = Field(default_factory=list, max_length=16)
    stdin: bytes = Field(default=b"", max_length=MAX_STDIN)
    gdb: list[str] = Field(default_factory=list, max_length=128)
    script: str | None = Field(default=None, max_length=262_144)
    interpreter: str = "python3"
    timeout: int = Field(default=20, ge=1, le=300)
    emulate: str = "auto"

    @field_validator("emulate")
    @classmethod
    def known_emulation(cls, value: str) -> str:
        if value not in EMULATE_CHOICES:
            raise ValueError("unsupported emulation choice")
        return value

    @field_validator("mode")
    @classmethod
    def known_mode(cls, value: str) -> str:
        if value not in MODES:
            raise ValueError("unsupported sandbox mode")
        return value

    @field_validator("interpreter")
    @classmethod
    def known_interpreter(cls, value: str) -> str:
        if value not in {"python3", "sh", "bash"}:
            raise ValueError("unsupported script interpreter")
        return value

    @field_validator("args", "gdb")
    @classmethod
    def bounded_strings(cls, values: list[str]) -> list[str]:
        if any(len(value) > 4096 or "\x00" in value for value in values):
            raise ValueError("argument too long or contains NUL")
        return values


def _config_path(database: Path) -> Path:
    return database.parent / "sandbox.json"


def load_config(database: Path) -> dict[str, Any]:
    path = _config_path(database)
    if not path.is_file():
        return {}
    config = json.loads(path.read_text())
    return config if isinstance(config, dict) else {}


def _engine_environment() -> dict[str, str]:
    # Allow the user's local Docker context but never a remote TCP daemon.
    environment = dict(os.environ)
    if environment.get("DOCKER_HOST", "").startswith(("tcp:", "ssh:", "http")):
        environment.pop("DOCKER_HOST")
    return environment


def _remove_container(engine: str, name: str) -> dict[str, Any]:
    try:
        removed = subprocess.run([engine, "rm", "-f", name], capture_output=True,
                                 timeout=30, check=False, env=_engine_environment())
        inspected = subprocess.run([engine, "inspect", name], capture_output=True,
                                   timeout=10, check=False, env=_engine_environment())
        if inspected.returncode == 0:
            return {"status": "unknown", "reason": "container still exists after removal"}
        detail = inspected.stderr.lower()
        if b"no such object" in detail or b"no such container" in detail:
            return {"status": "confirmed"}
        if removed.returncode:
            return {"status": "unknown", "reason": "container removal command failed"}
        return {"status": "unknown", "reason": "container absence could not be confirmed"}
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "unknown", "reason": "container teardown could not be confirmed"}


def cancel_registered_worker(database: Path, run_id: str) -> dict[str, Any]:
    """Stop the registered per-run worker; callers serialize this with run_lock."""
    with sqlite3.connect(database) as db:
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sandbox_workers'")
        if not table.fetchone():
            return {"status": "not_running"}
        row = db.execute("SELECT engine, container_name FROM sandbox_workers WHERE run_id=?",
                         (run_id,)).fetchone()
    if row is None:
        return {"status": "not_running"}
    result = _remove_container(*row)
    if result["status"] == "confirmed":
        with sqlite3.connect(database) as db:
            db.execute("DELETE FROM sandbox_workers WHERE run_id=? AND container_name=?",
                       (run_id, row[1]))
    return result


def engine_check(engine: str) -> tuple[bool, str | None]:
    """Return (reachable, reason). The reason explains a failure for diagnosis."""
    if engine not in {"docker", "podman"}:
        return False, "unsupported engine"
    if shutil.which(engine) is None:
        return False, engine + " CLI not found on PATH"
    try:
        result = subprocess.run([engine, "version", "--format", "{{json .Server.Version}}"],
                                capture_output=True, timeout=20, check=False, env=_engine_environment())
    except subprocess.TimeoutExpired:
        return False, engine + " did not answer within 20s (engine starting or sleeping?)"
    except OSError as exc:
        return False, type(exc).__name__ + ": " + str(exc)[:200]
    if result.returncode == 0:
        return True, None
    message = result.stderr.decode(errors="replace").strip().splitlines()
    return False, (message[-1] if message else f"exit status {result.returncode}")[:300]


_SOCKET_PATH = re.compile(r"unix://(/[^\s\"'?]+)|(/[^\s\"'?:]+\.sock)\b")
SANDBOX_SOCKET_HINT = ("the engine socket exists and is yours, so this is likely Claude Code's own Bash "
                       "sandbox blocking it; run `.venv/bin/metis sandbox status` as an excluded command "
                       "(see integrations/claude-code/README.md)")


def socket_permission_hint(reason: str | None) -> str | None:
    """Diagnostic only: spot a 'permission denied' on a socket this user owns."""
    if not reason or "permission denied" not in reason.lower():
        return None
    found = _SOCKET_PATH.search(reason)
    if not found:
        return None
    try:
        info = os.stat(found.group(1) or found.group(2))
    except OSError:
        return None
    if info.st_uid != os.getuid() and not (info.st_mode & 0o006):
        return None
    return SANDBOX_SOCKET_HINT


def image_present(engine: str, image: str | None) -> bool | None:
    """Whether the recorded image exists in this engine (None when it cannot be checked)."""
    if not image:
        return None
    try:
        result = subprocess.run([engine, "image", "inspect", "--format", "{{.Id}}", image],
                                capture_output=True, timeout=20, check=False, env=_engine_environment())
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode == 0


def engine_available(engine: str) -> bool:
    return engine_check(engine)[0]


def build_image(database: Path, *, engine: str = "docker", platform: str | None = "auto",
                context: Path | None = None) -> dict[str, Any]:
    """Build the bundled sandbox image locally and record its immutable image ID.

    ``auto`` builds for the host CPU: native targets get real ptrace (gdb/strace/
    ltrace) and foreign-architecture targets run through QEMU user-mode emulation.
    """
    if engine not in {"docker", "podman"}:
        raise ValueError("engine must be docker or podman")
    if platform == "auto":
        platform = default_platform()
    if platform is not None and not PLATFORM_PATTERN.fullmatch(platform):
        raise ValueError("unsupported platform")
    context = context or ROOT / "sandbox"
    if not (context / "Dockerfile").is_file():
        raise ValueError("sandbox Dockerfile not found")
    if not engine_available(engine):
        raise ValueError(engine + " is not running or not installed; start Docker Desktop, OrbStack, "
                         "Colima or Podman and retry")
    tag = "metis-sandbox:local"
    command = [engine, "build", "-t", tag, *(["--platform", platform] if platform else []), str(context)]
    subprocess.run(command, check=True, env=_engine_environment(), timeout=3600)
    inspected = subprocess.run([engine, "image", "inspect", "--format", "{{.Id}}", tag], check=True,
                               capture_output=True, text=True, env=_engine_environment(), timeout=60)
    image = inspected.stdout.strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("could not determine immutable image ID")
    return configure(database, engine=engine, image=image, platform=platform)


def configure(database: Path, *, engine: str, image: str, platform: str | None) -> dict[str, Any]:
    if engine not in {"docker", "podman"} or not IMAGE_PATTERN.fullmatch(image):
        raise ValueError("sandbox image must be an immutable sha256 image ID or digest reference")
    if platform is not None and not PLATFORM_PATTERN.fullmatch(platform):
        raise ValueError("unsupported platform")
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = {"engine": engine, "image": image, "platform": platform,
              "arch": PLATFORM_ARCH.get(platform or "", host_arch())}
    path = _config_path(database)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(config, stream)
    return {"configured": True, **config}


def status(database: Path) -> dict[str, Any]:
    config = load_config(database)
    engine = config.get("engine", "docker")
    reachable, reason = engine_check(engine)
    present = image_present(engine, config.get("image")) if reachable else None
    hint = None
    if not config.get("image") or present is False:
        hint = "run `.venv/bin/metis sandbox build` (images are per machine and per engine)"
    if not reachable:
        hint = socket_permission_hint(reason) or hint
    return {"configured": bool(config.get("image")) and present is not False, "engine": engine,
            "engine_available": reachable, "engine_error": reason, "image": config.get("image"),
            "image_present": present, "hint": hint,
            "platform": config.get("platform"), "arch": config.get("arch"), "modes": list(MODES),
            "emulation": "QEMU user-mode for foreign-architecture ELF targets (gdb via gdb stub)",
            "host_execution": False, "network": "none"}


def _bundle(header: dict[str, Any], files: list[tuple[str, bytes]], stdin: bytes) -> bytes:
    encoded = json.dumps(header).encode()
    parts = [struct.pack(">I", len(encoded)), encoded]
    parts.extend(content for _, content in files)
    parts.append(stdin)
    return b"".join(parts)


def _unpack(blob: dict[str, Any]) -> dict[str, Any]:
    data = base64.b64decode(blob["b64"])
    output: dict[str, Any] = {"size": blob["size"], "truncated": blob["truncated"],
                              "sha256": hashlib.sha256(data).hexdigest()}
    try:
        output["text"] = data.decode("utf-8")
    except UnicodeDecodeError:
        output["text"] = data.decode("utf-8", errors="replace")
        output["hex"] = data[:16_384].hex()
    return output


class Sandbox:
    def __init__(self, database: Path, *, engine: str | None = None, image: str | None = None,
                 platform: str | None = None):
        config = load_config(database)
        self.session = CodexSession(database)
        self.engine = engine or config.get("engine", "docker")
        self.image = image or config.get("image")
        self.platform = platform if platform is not None else config.get("platform")
        self.arch = config.get("arch") or PLATFORM_ARCH.get(self.platform or "", host_arch())
        if self.engine not in {"docker", "podman"}:
            raise ValueError("engine must be docker or podman")
        if not isinstance(self.image, str) or not IMAGE_PATTERN.fullmatch(self.image):
            raise ValueError("sandbox is not configured; run `metis sandbox build` or `metis sandbox configure`")
        self.image_id: str = self.image
        with sqlite3.connect(database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS sandbox_workers (
                run_id TEXT PRIMARY KEY, engine TEXT NOT NULL, container_name TEXT NOT NULL,
                started REAL NOT NULL)""")

    def command(self, name: str, *, profile: str = "standard") -> list[str]:
        if profile not in {"standard", "zipcrypto", "zipcrypto_test_lowmem"}:
            raise ValueError("unsupported sandbox resource profile")
        memory, cpus, ipc = ({"zipcrypto": ("2g", "4", "private"),
                              "zipcrypto_test_lowmem": ("128m", "4", "private")}.get(
                                  profile, ("512m", "1", "none")))
        return [self.engine, "create", *( ["--rm"] if profile == "standard" else []), "-i", "--name", name,
                "--pull=never",
                *(["--platform", self.platform] if self.platform else []),
                "--network=none", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--pids-limit=128", f"--memory={memory}",
                f"--memory-swap={memory}", f"--cpus={cpus}", "--user=65534:65534", f"--ipc={ipc}",
                "--tmpfs=/work:rw,exec,nosuid,nodev,size=256m,mode=1777",
                "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
                "--workdir=/work", "--log-driver=none", "--env=HOME=/work",
                "--entrypoint=python3", self.image_id, "-I", "-c", BOOTSTRAP]

    def _files(self, run_id: str, request: SandboxRequest) -> list[tuple[str, bytes]]:
        context = self.session.context(run_id)
        declared = set(context["challenge"]["artifacts"])
        root = self.session.artifact_root(run_id)
        names = [request.target, *request.extra]
        if root is None or any(name not in declared for name in names) or len(set(names)) != len(names):
            raise ValueError("sandbox inputs must be distinct declared run artifacts")
        files: list[tuple[str, bytes]] = []
        total = 0
        used: set[str] = set()
        for name in names:
            with artifact_stream(root, name, max_bytes=MAX_INPUT) as stream:
                content = stream.read(MAX_INPUT + 1)
            total += len(content)
            if total > MAX_INPUT:
                raise ValueError("sandbox input exceeds total limit")
            basename = PurePosixPath(name).name
            # Present distribution names without the intake index (e.g. libc.so.6).
            visible = re.sub(r"^[0-9]{2}-", "", basename) or basename
            visible = re.sub(r"[^\w.+-]", "_", visible)[:80]
            if visible in used or visible.startswith(".metis"):
                visible = uuid4().hex[:8] + "-" + visible
            used.add(visible)
            files.append((visible, content))
        return files

    def execute(self, run_id: str, request: SandboxRequest, *, _reserved: bool = False,
                _profile: str = "standard", _operation_id: str | None = None) -> dict[str, Any]:
        # Recovery can interrupt this lock, but another sandbox/artifact call
        # waits until the old caller observes its revoked operation identity.
        # A configured `sandbox` capacity bounds containers across runs and swarm workers.
        with ResourceBroker(self.session.database).lease(
                "sandbox-" + run_id[:64], {"sandbox": 1}, ttl=max(900, request.timeout + 300), wait=300,
                purpose="sandbox " + request.mode), operation_lock(self.session.database, run_id):
            operation_id = _operation_id
            if not _reserved:
                operation_id = uuid4().hex
            elif operation_id is None:
                raise ValueError("reserved sandbox execution requires an operation identity")
            try:
                return self._execute(run_id, request, _reserved=_reserved, _profile=_profile,
                                     _operation_id=operation_id)
            finally:
                if not _reserved:
                    with run_lock(self.session.database, run_id), sqlite3.connect(self.session.database) as db:
                        if not db.execute("SELECT 1 FROM sandbox_workers WHERE run_id=?", (run_id,)).fetchone():
                            db.execute("DELETE FROM codex_active_operations WHERE run_id=? AND operation_id=?",
                                       (run_id, operation_id))

    def _execute(self, run_id: str, request: SandboxRequest, *, _reserved: bool,
                 _profile: str, _operation_id: str | None) -> dict[str, Any]:
        request = SandboxRequest.model_validate(request.model_dump())
        if request.mode == "script" and not request.script:
            raise ValueError("script mode requires a script")
        files = self._files(run_id, request)
        target_arch = elf_arch(files[0][1][:64])
        if request.emulate == "auto":
            chosen = target_arch if target_arch and target_arch != self.arch else None
        else:
            chosen = None if request.emulate == "off" else request.emulate
        emulate = ({"arch": chosen, "qemu": EMULATORS[chosen][0], "sysroot": EMULATORS[chosen][1]}
                   if chosen else None)
        if request.script is not None:
            files.append((".metis-script", request.script.encode()))
        header = {"files": [{"name": name, "size": len(content), "exec": index == 0}
                            for index, (name, content) in enumerate(files)],
                  "stdin_size": len(request.stdin), "mode": request.mode, "target": files[0][0],
                  "args": request.args, "gdb": request.gdb, "interpreter": request.interpreter,
                  "timeout": request.timeout, "max_stream": MAX_STREAM, "emulate": emulate,
                  "target_arch": target_arch}
        bundle = _bundle(header, files, request.stdin)
        if not _reserved:
            with run_lock(self.session.database, run_id):
                with sqlite3.connect(self.session.database) as db:
                    if db.execute("SELECT 1 FROM codex_active_operations WHERE run_id=?", (run_id,)).fetchone():
                        raise ValueError("run has an unreconciled active operation")
                self.session._reserve(run_id, "sandboxed_dynamic_execution", mode=request.mode,
                                      target=request.target,
                                      input_sha256=hashlib.sha256(bundle).hexdigest())
                with sqlite3.connect(self.session.database) as db:
                    db.execute("INSERT INTO codex_active_operations "
                               "(run_id,operation_id,cancel_requested,started) VALUES (?,?,0,?)",
                               (run_id, _operation_id, time.time()))
        name = "metis-sandbox-" + uuid4().hex[:16]
        started = time.monotonic()
        result: dict[str, Any]
        oom_killed = False
        phase = "container-create"
        registered = False
        try:
            with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
                # Publish the worker before launch while holding the same per-run
                # lock used by cancel(). Once cancel returns from this lock it can
                # always identify the container that may be executing.
                with run_lock(self.session.database, run_id):
                    with sqlite3.connect(self.session.database) as db:
                        active = db.execute("SELECT operation_id,cancel_requested FROM codex_active_operations "
                                            "WHERE run_id=?", (run_id,)).fetchone()
                    if (active is None or active != (_operation_id, 0)
                            or self.session.context(run_id)["status"] != RunStatus.EXECUTING.value):
                        return {"run_id": run_id, "mode": request.mode, "ok": False,
                                "error": "cancelled before sandbox launch", "cancelled": True}
                    with sqlite3.connect(self.session.database) as db:
                        db.execute("INSERT INTO sandbox_workers VALUES (?, ?, ?, ?)",
                                   (run_id, self.engine, name, time.time()))
                    registered = True
                    created = subprocess.run(self.command(name, profile=_profile), capture_output=True,
                                             timeout=60, check=False, env=_engine_environment())
                    if created.returncode:
                        error.write(created.stderr)
                        completed: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess(
                            created.args, created.returncode)
                        process = None
                    else:
                        phase = "engine-attach"
                        # `create` completes only after the named container exists.
                        # Starting that existing name avoids a cancel/create race.
                        process = subprocess.Popen(
                            [self.engine, "start", "--attach", "--interactive", name],
                            stdin=subprocess.PIPE, stdout=output, stderr=error,
                            env=_engine_environment())
                if process is not None:
                    try:
                        process.communicate(input=bundle, timeout=request.timeout + 60)
                        completed = subprocess.CompletedProcess(process.args, process.returncode or 0)
                    except subprocess.TimeoutExpired:
                        self._remove_worker(name)
                        process.communicate()
                        raise
                    phase = "workload-completed"
                if _profile.startswith("zipcrypto"):
                    phase = "oom-inspection"
                    inspected = subprocess.run(
                        [self.engine, "inspect", "--format={{.State.OOMKilled}}", name],
                        capture_output=True, timeout=10, check=False, env=_engine_environment())
                    oom_killed = inspected.returncode == 0 and inspected.stdout.strip().lower() == b"true"
                    phase = "result-collection"
                output.seek(0)
                raw = output.read(8 * MAX_STREAM)
                error.seek(0)
                engine_error = error.read(4096).decode(errors="replace")
            line = raw.rstrip(b"\n").rsplit(b"\n", 1)[-1] if raw else b""
            try:
                payload = json.loads(line)
                result = {"ok": payload["exit_code"] == 0 and not payload["timed_out"],
                          "exit_code": payload["exit_code"], "timed_out": payload["timed_out"],
                          "memory_limit_exceeded": (payload.get("memory_limit_exceeded", False)
                                                     or oom_killed),
                          "elapsed": payload["elapsed"], "stdout": _unpack(payload["stdout"]),
                          "stderr": _unpack(payload["stderr"])}
                if request.mode in {"strace", "ltrace"}:
                    result["trace"] = _unpack(payload["trace"])
                if payload.get("program", {}).get("size"):
                    result["program_output"] = _unpack(payload["program"])
                if payload["exit_code"] is not None and payload["exit_code"] < 0:
                    result["signal"] = -payload["exit_code"]
            except (ValueError, KeyError, TypeError):
                result = ({"ok": False, "memory_limit_exceeded": True, "exit_code": completed.returncode}
                          if oom_killed else
                          {"ok": False, "error": "sandbox engine failed", "engine_exit_code": completed.returncode,
                           "engine_stderr": engine_error[-1024:]})
        except subprocess.TimeoutExpired:
            subprocess.run([self.engine, "rm", "-f", name], capture_output=True, timeout=30, check=False,
                           env=_engine_environment())
            result = {"ok": False, "error": "sandbox engine timeout", "timed_out": False,
                      "engine_timed_out": True, "failure_stage": phase}
        except OSError as exc:
            result = {"ok": False, "error": "sandbox engine unavailable: " + type(exc).__name__}
        finally:
            # Keep the persistent record until removal and absence are confirmed.
            # Recovery and cancellation use the same lock, so neither can miss a
            # worker whose teardown is still uncertain.
            if registered:
                with run_lock(self.session.database, run_id):
                    cleanup = _remove_container(self.engine, name)
                    if cleanup["status"] != "confirmed":
                        # Preserve the prior exception when one is propagating;
                        # never include untrusted workload output in this error.
                        prior = sys.exception()
                        status = ("workload_completed" if result.get("ok") else
                                  "workload_timed_out" if result.get("engine_timed_out") else
                                  "workload_memory_limit" if result.get("memory_limit_exceeded") else
                                  "workload_failed") if "result" in locals() else "workload_unknown"
                        raise RuntimeError(
                            f"sandbox cleanup could not be confirmed ({status})") from prior
                    with sqlite3.connect(self.session.database) as db:
                        db.execute("DELETE FROM sandbox_workers WHERE run_id=? AND container_name=?",
                                   (run_id, name))
        if not _reserved:
            with run_lock(self.session.database, run_id):
                current_status = self.session.context(run_id)["status"]
                with sqlite3.connect(self.session.database) as db:
                    active = db.execute("SELECT operation_id,cancel_requested FROM codex_active_operations "
                                        "WHERE run_id=?", (run_id,)).fetchone()
                if current_status == RunStatus.CANCELLED.value:
                    result = {"ok": False, "cancelled": True, "error": "sandbox worker cancelled"}
                elif (current_status != RunStatus.EXECUTING.value
                      or active != (_operation_id, 0)):
                    result = {"ok": False, "cancelled": True,
                              "error": "sandbox result discarded after controller recovery"}
                else:
                    self.session._emit(run_id, RunStatus.OBSERVING, tool_ok=str(result["ok"]).lower(),
                                       exit_code=str(result.get("exit_code")),
                                       elapsed=str(round(time.monotonic() - started, 3)))
                    self.session._emit(run_id, RunStatus.REPLANNING)
                    self.session._emit(run_id, RunStatus.PLANNING)
        files_note = [name for name, _ in files if name != ".metis-script"]
        return {"run_id": run_id, "mode": request.mode, "files_in_sandbox": files_note,
                "isolation": {"engine": self.engine, "network": "none", "host_mounts": False,
                              "image": self.image, "platform": self.platform,
                              "resource_profile": _profile},
                "target_arch": target_arch,
                "emulation": (emulate["qemu"] if emulate else None),
                "output_is_untrusted": True, **result}

    def _remove_worker(self, name: str) -> dict[str, Any]:
        return _remove_container(self.engine, name)


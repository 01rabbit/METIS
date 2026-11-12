"""Restricted local-fixture transforms; no arbitrary commands or network tools."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from uuid import uuid4

from pydantic import Field

from metis.core.contracts import Contract

TOOLS = frozenset({"base64_decode", "hex_decode", "sha256"})
RESOURCE_GUARD = r'''
import json, sys
from pathlib import Path
try:
    root = Path("/sys/fs/cgroup")
    memory = int((root / "memory.max").read_text())
    pids = int((root / "pids.max").read_text())
    quota, period = map(int, (root / "cpu.max").read_text().split())
    bounded = 0 < memory <= 67108864 and 0 < pids <= 32 and 0 < quota / period <= 0.5
except (OSError, ValueError, ZeroDivisionError):
    bounded = False
if not bounded:
    print(json.dumps({"ok": False, "output": "resource isolation unavailable"}))
    sys.exit(0)
'''
WORKER = r'''
import base64, hashlib, json, sys
request = json.load(sys.stdin)
tool, data = request["tool"], request["data"]
try:
    if tool == "base64_decode":
        result = base64.b64decode(data, validate=True).decode("utf-8")
    elif tool == "hex_decode":
        result = bytes.fromhex(data).decode("utf-8")
    elif tool == "sha256":
        result = hashlib.sha256(data.encode()).hexdigest()
    else:
        raise ValueError("unsupported tool")
    print(json.dumps({"ok": True, "output": result}))
except (ValueError, UnicodeError):
    print(json.dumps({"ok": False, "output": "invalid transform input"}))
'''


class ToolRequest(Contract):
    tool: str
    data: str = Field(max_length=65_536)


class ToolResult(Contract):
    ok: bool
    output: str


class FixtureRuntime:
    """Controller-owned runner; image must be a trusted, digest-pinned Python image.

    Container isolation is defense in depth, not a proven kernel exploit boundary.
    Never use this runner for arbitrary binaries. Host paths are never mounted.
    """

    def __init__(self, image: str, *, timeout_seconds: int = 10):
        if not re.fullmatch(r"[a-z0-9./_-]+@sha256:[0-9a-f]{64}", image):
            raise ValueError("sandbox image must be pinned by repository digest")
        if not 1 <= timeout_seconds <= 60:
            raise ValueError("runtime timeout must be between 1 and 60 seconds")
        self.image = image
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _environment() -> dict[str, str]:
        # Retain registry configuration but never redirect to a remote daemon.
        return {key: value for key, value in os.environ.items() if key not in {
            "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        }}

    @classmethod
    def isolation_available(cls, *, timeout_seconds: float = 5) -> bool:
        try:
            result = subprocess.run(
                ["docker", "--host=unix:///var/run/docker.sock", "info", "--format",
                 '{{json .CgroupDriver}} {{json .CgroupVersion}}'],
                capture_output=True, check=False, timeout=timeout_seconds, env=cls._environment(),
            )
            parts = result.stdout.decode().strip().split()
            return (result.returncode == 0 and len(parts) == 2
                    and json.loads(parts[0]) in {"systemd", "cgroupfs"}
                    and str(json.loads(parts[1])) == "2")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False

    def execute(self, request: ToolRequest, *, timeout_seconds: float | None = None) -> ToolResult:
        # Validate again at the trust boundary, even for model_construct callers.
        request = ToolRequest.model_validate(request.model_dump())
        if request.tool not in TOOLS:
            return ToolResult(ok=False, output="tool denied")
        limit = self.timeout_seconds if timeout_seconds is None else min(
            self.timeout_seconds, timeout_seconds,
        )
        if limit <= 0:
            return ToolResult(ok=False, output="tool timeout")
        deadline = time.monotonic() + limit
        if not self.isolation_available(timeout_seconds=min(5, limit)):
            raise RuntimeError("cgroup v2 resource isolation unavailable")
        name = "metis-fixture-" + uuid4().hex
        prefix = ["docker", "--host=unix:///var/run/docker.sock"]
        command = [*prefix, "create", "--name", name, "--pull=never", "-i",
                   "--network=none", "--read-only", "--cap-drop=ALL",
                   "--security-opt=no-new-privileges", "--pids-limit=32",
                   "--memory=64m", "--memory-swap=64m", "--cpus=0.5",
                   "--user=65534:65534", "--log-driver=none",
                   "--env=HTTP_PROXY=", "--env=HTTPS_PROXY=", "--env=ALL_PROXY=",
                   "--env=http_proxy=", "--env=https_proxy=", "--env=all_proxy=",
                   "--entrypoint=python", self.image, "-I", "-c", RESOURCE_GUARD + WORKER]
        environment = self._environment()
        creation_timed_out = False
        try:
            # Complete creation before starting a deadline-bound worker. Killing
            # `docker run` mid-create can otherwise race removal and leak a late
            # container after cleanup reported "not found".
            try:
                created = subprocess.run(
                    command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=max(0.001, min(30, deadline - time.monotonic())),
                    check=False, env=environment,
                )
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                creation_timed_out = True
                raise RuntimeError("container creation outcome unknown; inspect runtime") from None
            if created.returncode:
                return ToolResult(ok=False, output="isolated runtime unavailable")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return ToolResult(ok=False, output="tool timeout")
            with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
                completed = subprocess.run(
                    [*prefix, "start", "-ai", name],
                    input=request.model_dump_json().encode(), stdout=output,
                    stderr=error, timeout=remaining, check=False, env=environment,
                )
                if completed.returncode:
                    return ToolResult(ok=False, output="isolated tool failed")
                output.seek(0)
                payload = output.read(1_048_577)
                if len(payload) > 1_048_576:
                    return ToolResult(ok=False, output="tool output limit exceeded")
                result = ToolResult.model_validate_json(payload)
                if not result.ok and result.output == "resource isolation unavailable":
                    raise RuntimeError("container resource enforcement could not be confirmed")
                return result
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, output="tool timeout")
        except (OSError, ValueError):
            return ToolResult(ok=False, output="isolated runtime unavailable")
        finally:
            # A killed Docker client does not imply its container was killed.
            try:
                cleanup = subprocess.run(
                    [*prefix, "rm", "-f", name], stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE, timeout=5, check=False, env=environment,
                )
                if cleanup.returncode and b"no such container" not in cleanup.stderr.lower():
                    raise RuntimeError("sandbox cleanup could not be confirmed")
                if creation_timed_out:
                    raise RuntimeError("container creation outcome unknown; inspect runtime")
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError("sandbox cleanup could not be confirmed") from exc

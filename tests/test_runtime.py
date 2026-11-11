import os
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest

import metis.core.runtime as runtime_module
from metis.core.runtime import FixtureRuntime, ToolRequest

IMAGE = "python@sha256:" + "a" * 64


@pytest.mark.parametrize("image", ["python:3.12", "--privileged", "python@sha256:bad"])
def test_runtime_rejects_unpinned_images(image):
    with pytest.raises(ValueError):
        FixtureRuntime(image)


def test_unknown_tool_is_denied_without_starting_process(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("no process may be started")

    monkeypatch.setattr(runtime_module.subprocess, "run", forbidden)
    result = FixtureRuntime(IMAGE).execute(ToolRequest(tool="shell", data="echo unsafe"))
    assert not result.ok
    assert result.output == "tool denied"


def test_daemon_selectors_are_cleared_without_dropping_registry_config(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://unrelated.example:2375")
    monkeypatch.setenv("DOCKER_CONFIG", "/tmp/test-registry-config")
    environment = FixtureRuntime._environment()
    assert "DOCKER_HOST" not in environment
    assert environment["DOCKER_CONFIG"] == "/tmp/test-registry-config"


def test_unenforced_resources_are_rejected_before_container_creation(monkeypatch):
    monkeypatch.setattr(FixtureRuntime, "isolation_available", lambda *args, **kwargs: False)

    def forbidden(*args, **kwargs):
        raise AssertionError("must not start a container without enforceable quotas")

    monkeypatch.setattr(runtime_module.subprocess, "run", forbidden)
    with pytest.raises(RuntimeError, match="resource isolation unavailable"):
        FixtureRuntime(IMAGE).execute(ToolRequest(tool="sha256", data="test"))


@pytest.fixture
def container_runtime():
    image = os.environ.get("METIS_TEST_DOCKER_IMAGE")
    if not image:
        if os.environ.get("METIS_REQUIRE_DOCKER_TESTS") == "1":
            pytest.fail("required Docker image configuration missing")
        pytest.skip("set METIS_TEST_DOCKER_IMAGE to a locally available pinned Python image")
    if not FixtureRuntime.isolation_available():
        if os.environ.get("METIS_REQUIRE_DOCKER_TESTS") == "1":
            pytest.fail("required Docker cgroup v2 resource enforcement unavailable")
        pytest.skip("environment lacks enforced cgroup v2 quotas; runtime fails closed")
    return FixtureRuntime(image, timeout_seconds=30)


@pytest.mark.parametrize(("tool", "data", "expected"), [
    ("base64_decode", "Zml4dHVyZQ==", "fixture"),
    ("hex_decode", "66697874757265", "fixture"),
    ("sha256", "fixture", "f16d05ec6b29248d2c61adb1e9263f78e4f7bace1b955014a2d17872cfe4064d"),
])
def test_isolated_fixture_transforms(container_runtime, tool, data, expected):
    result = container_runtime.execute(ToolRequest(tool=tool, data=data))
    assert result.ok, result.output
    assert result.output == expected


def test_invalid_transform_input_is_a_result_not_crash(container_runtime):
    result = container_runtime.execute(ToolRequest(tool="base64_decode", data="!!!"))
    assert not result.ok
    assert result.output == "invalid transform input"


def test_container_cannot_access_oracle_or_host_resources(
    container_runtime, monkeypatch, tmp_path,
):
    oracle = tmp_path / "hidden-oracle"
    oracle.write_text("test-only-held-out-answer")
    monkeypatch.setenv("METIS_TEST_PRIVATE", "not-for-solver")
    # A trusted test probe replaces the fixed worker, never a challenge-supplied script.
    probe = '''
import json, os, socket
from pathlib import Path
checks = []
checks.append(not Path(ORACLE).exists())
checks.append(not Path("/var/run/docker.sock").exists())
checks.append(os.getuid() == 65534)
checks.append("METIS_TEST_PRIVATE" not in os.environ)
try:
    Path("/write-test").write_text("no")
    checks.append(False)
except OSError:
    checks.append(True)
try:
    socket.create_connection(("192.0.2.1", 80), timeout=0.2).close()
    checks.append(False)
except OSError:
    checks.append(True)
print(json.dumps({"ok": all(checks), "output": json.dumps(checks)}))
'''.replace("ORACLE", repr(str(oracle)))
    monkeypatch.setattr(runtime_module, "WORKER", probe)
    result = container_runtime.execute(ToolRequest(tool="sha256", data="probe"))
    assert result.ok, result.output


def test_timeout_removes_container(container_runtime, monkeypatch):
    identifier = uuid4().hex
    monkeypatch.setattr(runtime_module, "uuid4", lambda: SimpleNamespace(hex=identifier))
    monkeypatch.setattr(runtime_module, "WORKER", "import time; time.sleep(30)")
    container_runtime.timeout_seconds = 5
    result = container_runtime.execute(ToolRequest(tool="sha256", data="timeout"))
    assert not result.ok
    assert result.output == "tool timeout"
    inspected = subprocess.run(
        ["docker", "--host=unix:///var/run/docker.sock", "inspect",
         "metis-fixture-" + identifier], capture_output=True, check=False,
        timeout=5, env=container_runtime._environment(),
    )
    assert inspected.returncode != 0
    assert b"no such object" in inspected.stderr.lower()

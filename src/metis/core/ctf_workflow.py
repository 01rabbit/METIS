"""Seeded declarative analysis workflows for local, sandbox-only research trials.

Generated plans contain only bounded transforms already implemented by the
workflow runner. They cannot add tools, policy, verifier behavior, code, or
filesystem paths.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, ValidationError

from metis.core.artifacts import artifact_stream
from metis.core.codex_session import CodexSession
from metis.core.contracts import Contract
from metis.core.ctf_artifacts import ARTIFACT_TOOLS
from metis.core.ctf_sandbox import Sandbox, SandboxRequest

WorkflowTool = Literal["base32_decode", "base64_decode", "hex_decode"]
WORKFLOW_TOOLS = frozenset({"base32_decode", "base64_decode", "hex_decode"})
MAX_WORKFLOW_STEPS = 4
MAX_WORKFLOW_OUTPUT = 65_536
if not WORKFLOW_TOOLS <= ARTIFACT_TOOLS:
    raise RuntimeError("workflow tools must be a subset of the existing artifact tool registry")


class WorkflowStep(Contract):
    tool: WorkflowTool


class WorkflowCandidate(Contract):
    schema_version: Literal[1] = 1
    input_artifact: str = Field(min_length=1, max_length=128,
                                pattern=r"^[A-Za-z0-9_.+-]+$")
    steps: list[WorkflowStep] = Field(min_length=1, max_length=MAX_WORKFLOW_STEPS)


@dataclass(frozen=True)
class SeededWorkflowTrial:
    """The challenge and plan are agent-visible; the oracle digest is host-only."""

    challenge: bytes
    workflow_json: bytes
    oracle_sha256: str
    challenge_sha256: str


def generate_seeded_workflow(seed: int) -> SeededWorkflowTrial:
    """Generate a reproducible two-family local fixture and declarative plan.

    The answer is derived from ``seed`` but is returned only as a one-way
    commitment. Callers must keep ``oracle_sha256`` outside the run artifacts.
    """
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 0xFFFFFFFF:
        raise ValueError("seed must be an unsigned 32-bit integer")
    material = hashlib.sha256(f"metis-p6-workflow-v1:{seed}".encode()).hexdigest()[:24]
    answer = f"CTF{{{material}}}".encode("ascii")
    if seed & 1:
        encoded = base64.b64encode(answer.hex().encode("ascii"))
        steps: list[WorkflowTool] = ["base64_decode", "hex_decode"]
    else:
        encoded = base64.b32encode(base64.b64encode(answer))
        steps = ["base32_decode", "base64_decode"]
    workflow = WorkflowCandidate(input_artifact="challenge.txt",
                                 steps=[WorkflowStep(tool=tool) for tool in steps])
    workflow_json = (workflow.model_dump_json() + "\n").encode("utf-8")
    return SeededWorkflowTrial(challenge=encoded, workflow_json=workflow_json,
                               oracle_sha256=hashlib.sha256(answer).hexdigest(),
                               challenge_sha256=hashlib.sha256(encoded).hexdigest())


def validate_workflow(raw: bytes | str, *, input_artifact: str) -> WorkflowCandidate:
    """Validate a plan against one declared input artifact before sandboxing."""
    try:
        workflow = WorkflowCandidate.model_validate_json(raw)
    except ValidationError as exc:
        raise ValueError("workflow candidate violates the fixed schema") from exc
    if workflow.input_artifact != input_artifact:
        raise ValueError("workflow input must name the selected declared artifact")
    if any(step.tool not in WORKFLOW_TOOLS for step in workflow.steps):
        raise ValueError("workflow contains an unregistered tool")
    return workflow


def sandbox_runner_script() -> str:
    """Return the fixed interpreter used inside METIS's isolated container."""
    return r'''import base64, hashlib, json, os, pathlib, sys

MAX_BYTES = 65536
ALLOWED = {"base32_decode", "base64_decode", "hex_decode"}
if len(sys.argv) != 2:
    raise SystemExit("expected one workflow artifact")
workflow_name = sys.argv[1]
if pathlib.PurePath(workflow_name).name != workflow_name or workflow_name.startswith("."):
    raise SystemExit("invalid workflow artifact name")
workflow_path = pathlib.Path(workflow_name)
payload = json.loads(workflow_path.read_text(encoding="utf-8"))
if set(payload) != {"schema_version", "input_artifact", "steps"} or payload["schema_version"] != 1:
    raise SystemExit("unsupported workflow schema")
target_path = pathlib.Path(os.environ["METIS_TARGET"])
target = target_path.name
if payload["input_artifact"] != target or target_path.is_absolute() or len(target_path.parts) != 1:
    raise SystemExit("workflow input does not match the declared target")
steps = payload["steps"]
if not isinstance(steps, list) or not 1 <= len(steps) <= 4:
    raise SystemExit("workflow step count exceeds limits")
value = target_path.read_bytes()
if len(value) > MAX_BYTES:
    raise SystemExit("workflow input exceeds limits")
for step in steps:
    if not isinstance(step, dict) or set(step) != {"tool"} or step["tool"] not in ALLOWED:
        raise SystemExit("workflow step is not allowlisted")
    if step["tool"] == "base32_decode":
        value = base64.b32decode(value, casefold=False)
    elif step["tool"] == "base64_decode":
        value = base64.b64decode(value, validate=True)
    else:
        value = bytes.fromhex(value.decode("ascii"))
    if len(value) > MAX_BYTES:
        raise SystemExit("workflow output exceeds limits")
print(json.dumps({"schema_version": 1, "steps": len(steps), "output_bytes": len(value),
                  "sha256": hashlib.sha256(value).hexdigest()}, sort_keys=True))
'''


def run_workflow_in_sandbox(database: Path, run_id: str, *, target: str,
                            workflow_artifact: str, timeout: int = 20) -> dict[str, Any]:
    """Run a validated plan on declared artifacts; return only a digest and bounds."""
    if not 1 <= timeout <= 300:
        raise ValueError("workflow timeout must be 1..300 seconds")
    session = CodexSession(database)
    context = session.context(run_id)
    declared = set(context["challenge"].get("artifacts", []))
    if target not in declared or workflow_artifact not in declared or target == workflow_artifact:
        raise ValueError("workflow inputs must be distinct declared run artifacts")
    root = session.artifact_root(run_id)
    if root is None:
        raise ValueError("workflow run has no artifact directory")
    with artifact_stream(root, workflow_artifact, max_bytes=65_536) as stream:
        workflow_bytes = stream.read(65_537)
    target_visible = _visible_artifact_name(target)
    workflow_visible = _visible_artifact_name(workflow_artifact)
    if target_visible == workflow_visible or target_visible.startswith(".metis") \
            or workflow_visible.startswith(".metis") or workflow_visible == ".metis-script":
        raise ValueError("workflow artifact names collide in the sandbox")
    workflow = validate_workflow(workflow_bytes, input_artifact=target_visible)
    result = Sandbox(database).execute(
        run_id,
        SandboxRequest(target=target, mode="script", extra=[workflow_artifact],
                       args=[workflow_visible], script=sandbox_runner_script(),
                       interpreter="python3", timeout=timeout, emulate="off"),
    )
    if not result.get("ok"):
        return {"ok": False, "steps": len(workflow.steps), "sandbox": result}
    stdout = result.get("stdout", {}).get("text", "")
    try:
        observed = json.loads(stdout)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "sandbox workflow output was not valid JSON", "sandbox": result}
    if (set(observed) != {"schema_version", "steps", "output_bytes", "sha256"}
            or observed.get("schema_version") != 1
            or observed.get("steps") != len(workflow.steps)
            or not isinstance(observed.get("output_bytes"), int)
            or isinstance(observed.get("output_bytes"), bool)
            or not 0 <= observed["output_bytes"] <= MAX_WORKFLOW_OUTPUT
            or not re.fullmatch(r"[0-9a-f]{64}", str(observed.get("sha256", "")))):
        return {"ok": False, "reason": "sandbox workflow result failed schema validation", "sandbox": result}
    return {"ok": True, "workflow_sha256": hashlib.sha256(workflow_bytes).hexdigest(),
            "steps": observed["steps"], "output_bytes": observed["output_bytes"],
            "output_sha256": observed["sha256"],
            "sandbox": {"engine": result["isolation"]["engine"],
                        "image": result["isolation"]["image"],
                        "network": result["isolation"]["network"],
                        "host_mounts": result["isolation"]["host_mounts"]}}


def verify_workflow_digest(result: Mapping[str, Any], oracle_sha256: str) -> bool:
    """Compare a sandbox digest with a host-only commitment; never reveal the answer."""
    if not re.fullmatch(r"[0-9a-f]{64}", oracle_sha256):
        raise ValueError("oracle commitment must be a lowercase SHA-256 digest")
    return result.get("ok") is True and secrets.compare_digest(
        str(result.get("output_sha256", "")), oracle_sha256)


def _visible_artifact_name(name: str) -> str:
    basename = PurePosixPath(name).name
    visible = re.sub(r"^[0-9]{2}-", "", basename) or basename
    visible = re.sub(r"[^\w.+-]", "_", visible)[:80]
    if visible.startswith(".metis"):
        visible = "artifact-" + visible[:72]
    return visible

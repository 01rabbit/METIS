"""Seeded declarative analysis workflows for local, sandbox-only research trials.

Generated plans contain only bounded transforms already implemented by the
workflow runner. They cannot add tools, policy, verifier behavior, code, or
filesystem paths.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import secrets
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, ValidationError

from metis.core.artifacts import artifact_stream
from metis.core.codex_session import CodexSession
from metis.core.contracts import Contract
from metis.core.ctf_artifacts import ARTIFACT_TOOLS
from metis.core.ctf_sandbox import Sandbox, SandboxRequest

WorkflowTool = Literal["base32_decode", "base64_decode", "hex_decode", "rot13_decode"]
BASE_WORKFLOW_TOOLS = frozenset({"base32_decode", "base64_decode", "hex_decode"})
WORKFLOW_TOOLS = BASE_WORKFLOW_TOOLS | {"rot13_decode"}
MAX_WORKFLOW_STEPS = 4
MAX_WORKFLOW_OUTPUT = 16_384
ROT13_IMPLEMENTATION = (
    'value = value.translate(bytes.maketrans('
    'b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz", '
    'b"NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm"))'
)
if not BASE_WORKFLOW_TOOLS <= ARTIFACT_TOOLS:
    raise RuntimeError("workflow tools must be a subset of the existing artifact tool registry")


class WorkflowStep(Contract):
    tool: WorkflowTool


class WorkflowCandidate(Contract):
    schema_version: Literal[1] = 1
    input_artifact: str = Field(min_length=1, max_length=128,
                                pattern=r"^[A-Za-z0-9_.+-]+$")
    steps: list[WorkflowStep] = Field(min_length=1, max_length=MAX_WORKFLOW_STEPS)


def _capability_descriptor(tool: str) -> dict[str, Any]:
    """Return the immutable descriptor whose digest an operator approves."""
    if tool != "rot13_decode":
        raise ValueError("unknown review-gated workflow capability")
    return {"schema_version": 1, "id": tool, "version": 1,
            "implementation_sha256": hashlib.sha256(ROT13_IMPLEMENTATION.encode("ascii")).hexdigest(),
            "max_input_bytes": 65_536, "max_output_bytes": MAX_WORKFLOW_OUTPUT}


def capability_digest(tool: str) -> str:
    descriptor = _capability_descriptor(tool)
    canonical = json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def capability_review_details(tool: str) -> dict[str, Any]:
    """Return the exact public descriptor shown before operator confirmation."""
    return {"descriptor": _capability_descriptor(tool), "capability_sha256": capability_digest(tool)}


class WorkflowCapabilityApprovals:
    """Append-only per-run operator approvals; proposals never grant capabilities."""

    def __init__(self, database: Path):
        self.database = database
        database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database, timeout=10) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS workflow_capability_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                capability_version INTEGER NOT NULL,
                capability_sha256 TEXT NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('approve', 'revoke')),
                reviewer TEXT NOT NULL,
                timestamp TEXT NOT NULL)""")
            db.execute("""CREATE INDEX IF NOT EXISTS workflow_reviews_by_run
                         ON workflow_capability_reviews(run_id, capability_id, id)""")
            for operation in ("UPDATE", "DELETE"):
                db.execute(f"""CREATE TRIGGER IF NOT EXISTS deny_workflow_reviews_{operation.lower()}
                    BEFORE {operation} ON workflow_capability_reviews BEGIN
                    SELECT RAISE(ABORT, 'workflow review history is append-only'); END""")

    def record(self, run_id: str, tool: str, *, decision: str, reviewer: str,
               expected_digest: str) -> dict[str, Any]:
        descriptor = _capability_descriptor(tool)
        current_digest = capability_digest(tool)
        if expected_digest != current_digest:
            raise ValueError("workflow capability changed after review; inspect it again")
        if decision not in {"approve", "revoke"}:
            raise ValueError("review decision must be approve or revoke")
        reviewer = reviewer.strip()
        if not reviewer or len(reviewer) > 128 or any(ord(char) < 32 for char in reviewer):
            raise ValueError("reviewer identity is required and must be printable")
        with sqlite3.connect(self.database, timeout=10) as db:
            # A review is valid only for a real, intact METIS run in this database.
            from metis.core.store import RunStore
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():
                raise ValueError("workflow review requires an existing run")
            if not RunStore(self.database, read_only=True).read(run_id):
                raise ValueError("workflow review requires an existing run")
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("""INSERT INTO workflow_capability_reviews
                (run_id, capability_id, capability_version, capability_sha256,
                 decision, reviewer, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run_id, tool, descriptor["version"], current_digest, decision,
                 reviewer, datetime.now(UTC).isoformat()))
            review_id = cursor.lastrowid
        return {"review_id": review_id, "run_id": run_id, "capability": tool,
                "decision": decision, "capability_sha256": current_digest,
                "reviewer": reviewer}

    def status(self, run_id: str) -> dict[str, Any]:
        from metis.core.store import RunStore
        with sqlite3.connect(self.database, timeout=10) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():
                raise ValueError("workflow review requires an existing run")
        if not RunStore(self.database, read_only=True).read(run_id):
            raise ValueError("workflow review requires an existing run")
        with sqlite3.connect(self.database, timeout=10) as db:
            rows = db.execute("""SELECT id, capability_id, capability_version,
                capability_sha256, decision, reviewer, timestamp
                FROM workflow_capability_reviews WHERE run_id=? ORDER BY id""", (run_id,)).fetchall()
        return {"run_id": run_id, "approved_tools": sorted(self.approved_tools(run_id)),
                "reviews": [{"review_id": row[0], "capability": row[1], "version": row[2],
                             "capability_sha256": row[3], "decision": row[4],
                             "reviewer": row[5], "timestamp": row[6]} for row in rows]}

    def approved_tools(self, run_id: str) -> frozenset[str]:
        with sqlite3.connect(self.database, timeout=10) as db:
            rows = db.execute("""SELECT capability_id, capability_version,
                capability_sha256, decision FROM workflow_capability_reviews
                WHERE run_id=? ORDER BY id""", (run_id,)).fetchall()
        latest: dict[str, tuple[int, str, str]] = {}
        for capability, version, digest, decision in rows:
            latest[str(capability)] = (int(version), str(digest), str(decision))
        allowed = set(BASE_WORKFLOW_TOOLS)
        for capability, (version, digest, decision) in latest.items():
            if (decision == "approve" and capability in WORKFLOW_TOOLS
                    and version == _capability_descriptor(capability)["version"]
                    and digest == capability_digest(capability)):
                allowed.add(capability)
        return frozenset(allowed)


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


def validate_workflow(raw: bytes | str, *, input_artifact: str,
                      approved_tools: frozenset[str] = BASE_WORKFLOW_TOOLS) -> WorkflowCandidate:
    """Validate a plan against one declared input artifact before sandboxing."""
    try:
        workflow = WorkflowCandidate.model_validate_json(raw)
    except ValidationError as exc:
        raise ValueError("workflow candidate violates the fixed schema") from exc
    if workflow.input_artifact != input_artifact:
        raise ValueError("workflow input must name the selected declared artifact")
    if any(step.tool not in approved_tools for step in workflow.steps):
        raise ValueError("workflow contains an unregistered tool")
    return workflow


def sandbox_runner_script(*, approved_tools: frozenset[str] = BASE_WORKFLOW_TOOLS) -> str:
    """Return the fixed interpreter used inside METIS's isolated container."""
    if not approved_tools <= WORKFLOW_TOOLS or not BASE_WORKFLOW_TOOLS <= approved_tools:
        raise ValueError("sandbox workflow tools are not an approved fixed capability set")
    script = r'''import base64, hashlib, json, os, pathlib, sys

MAX_INPUT_BYTES = 65536
MAX_OUTPUT_BYTES = 16384
ALLOWED = __ALLOWED_TOOLS__
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
if len(value) > MAX_INPUT_BYTES:
    raise SystemExit("workflow input exceeds limits")
for step in steps:
    if not isinstance(step, dict) or set(step) != {"tool"} or step["tool"] not in ALLOWED:
        raise SystemExit("workflow step is not allowlisted")
    if step["tool"] == "base32_decode":
        value = base64.b32decode(value, casefold=False)
    elif step["tool"] == "base64_decode":
        value = base64.b64decode(value, validate=True)
    elif step["tool"] == "hex_decode":
        value = bytes.fromhex(value.decode("ascii"))
    elif step["tool"] == "rot13_decode":
        __ROT13_IMPLEMENTATION__
    else:
        raise SystemExit("workflow step is not allowlisted")
    if len(value) > MAX_OUTPUT_BYTES:
        raise SystemExit("workflow output exceeds limits")
print(json.dumps({"schema_version": 1, "steps": len(steps), "output_bytes": len(value),
                  "sha256": hashlib.sha256(value).hexdigest(),
                  "output_b64": base64.b64encode(value).decode("ascii")}, sort_keys=True))
'''
    allowed = json.dumps(sorted(approved_tools), separators=(",", ":"))
    return (script.replace("__ALLOWED_TOOLS__", f"set({allowed})")
            .replace("__ROT13_IMPLEMENTATION__", ROT13_IMPLEMENTATION))


def run_workflow_in_sandbox(database: Path, run_id: str, *, target: str,
                            workflow_artifact: str, timeout: int = 20) -> dict[str, Any]:
    """Run a validated plan and register its bounded, untrusted output as a derived artifact."""
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
    approved_tools = WorkflowCapabilityApprovals(database).approved_tools(run_id)
    workflow = validate_workflow(workflow_bytes, input_artifact=target_visible,
                                 approved_tools=approved_tools)
    result = Sandbox(database).execute(
        run_id,
        SandboxRequest(target=target, mode="script", extra=[workflow_artifact],
                       args=[workflow_visible], script=sandbox_runner_script(approved_tools=approved_tools),
                       interpreter="python3", timeout=timeout, emulate="off"),
    )
    if not result.get("ok"):
        return {"ok": False, "steps": len(workflow.steps), "sandbox": result}
    isolation = result.get("isolation")
    if (not isinstance(isolation, dict) or not isinstance(isolation.get("engine"), str)
            or not isinstance(isolation.get("image"), str) or isolation.get("network") != "none"
            or isolation.get("host_mounts") is not False):
        return {"ok": False, "reason": "sandbox isolation metadata failed validation", "sandbox": result}
    stdout_result = result.get("stdout")
    stdout = stdout_result.get("text") if isinstance(stdout_result, dict) else None
    if not isinstance(stdout, str):
        return {"ok": False, "reason": "sandbox workflow output was not text", "sandbox": result}
    try:
        observed, output = _validate_workflow_output(stdout, expected_steps=len(workflow.steps))
    except ValueError as exc:
        return {"ok": False, "reason": str(exc), "sandbox": result}
    output_digest = hashlib.sha256(output).hexdigest()
    output_artifact = session.store_artifact(run_id, output, directory_name=".metis-derived", suffix=".bin")
    return {"ok": True, "workflow_sha256": hashlib.sha256(workflow_bytes).hexdigest(),
            "steps": observed["steps"], "output_bytes": observed["output_bytes"],
            "output_sha256": output_digest, "output_artifact": output_artifact,
            "output_is_untrusted": True,
            "sandbox": {"engine": isolation["engine"], "image": isolation["image"],
                        "network": isolation["network"], "host_mounts": isolation["host_mounts"]}}


def _validate_workflow_output(stdout: str, *, expected_steps: int) -> tuple[dict[str, Any], bytes]:
    """Validate bounded worker output and its self-reported digest before registration."""
    try:
        observed = json.loads(stdout)
    except (TypeError, ValueError) as exc:
        raise ValueError("sandbox workflow output was not valid JSON") from exc
    if (not isinstance(observed, dict)
            or set(observed) != {"schema_version", "steps", "output_bytes", "sha256", "output_b64"}
            or type(observed.get("schema_version")) is not int or observed["schema_version"] != 1
            or type(observed.get("steps")) is not int
            or observed["steps"] != expected_steps
            or type(observed.get("output_bytes")) is not int
            or not 0 <= observed["output_bytes"] <= MAX_WORKFLOW_OUTPUT
            or not re.fullmatch(r"[0-9a-f]{64}", str(observed.get("sha256", "")))
            or not isinstance(observed.get("output_b64"), str)):
        raise ValueError("sandbox workflow result failed schema validation")
    encoded = observed["output_b64"]
    if len(encoded) > 4 * ((MAX_WORKFLOW_OUTPUT + 2) // 3):
        raise ValueError("sandbox workflow output exceeds limits")
    try:
        output = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise ValueError("sandbox workflow output encoding is invalid") from exc
    if (base64.b64encode(output).decode("ascii") != encoded
            or len(output) != observed["output_bytes"]
            or len(output) > MAX_WORKFLOW_OUTPUT):
        raise ValueError("sandbox workflow output length or encoding is invalid")
    if hashlib.sha256(output).hexdigest() != observed["sha256"]:
        raise ValueError("sandbox workflow output digest mismatch")
    return observed, output


def verify_workflow_digest(result: Mapping[str, Any], oracle_sha256: str) -> bool:
    """Compare a sandbox digest with a host-only commitment; never reveal the answer."""
    if not re.fullmatch(r"[0-9a-f]{64}", oracle_sha256):
        raise ValueError("oracle commitment must be a lowercase SHA-256 digest")
    if (result.get("ok") is not True or not isinstance(result.get("output_artifact"), str)
            or result.get("output_is_untrusted") is not True):
        return False
    return secrets.compare_digest(str(result.get("output_sha256", "")), oracle_sha256)


def replay_workflow_in_sandbox(database: Path, run_id: str, *, target: str,
                               workflow_artifact: str, timeout: int = 20,
                               oracle_sha256: str | None = None) -> dict[str, Any]:
    """Run one declared workflow twice and compare bounded, isolated results.

    Both outputs remain registered as untrusted run-derived artifacts. Neither
    their bytes nor their digests are returned by this review projection.
    """
    if oracle_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", oracle_sha256):
        raise ValueError("oracle commitment must be a lowercase SHA-256 digest")
    first = run_workflow_in_sandbox(database, run_id, target=target,
                                    workflow_artifact=workflow_artifact, timeout=timeout)
    if first.get("ok") is not True:
        return {"ok": False, "reproducible": False, "reason": "first sandbox run failed"}
    second = run_workflow_in_sandbox(database, run_id, target=target,
                                     workflow_artifact=workflow_artifact, timeout=timeout)
    if second.get("ok") is not True:
        return {"ok": False, "reproducible": False, "reason": "second sandbox run failed"}
    comparable = ("workflow_sha256", "steps", "output_bytes", "output_sha256", "sandbox")
    reproducible = all(first.get(key) == second.get(key) for key in comparable)
    oracle_match = (None if oracle_sha256 is None else
                    reproducible and verify_workflow_digest(first, oracle_sha256)
                    and verify_workflow_digest(second, oracle_sha256))
    return {"ok": reproducible and oracle_match is not False,
            "reproducible": reproducible,
            "oracle_match": oracle_match, "steps": first.get("steps") if reproducible else None,
            "output_bytes": first.get("output_bytes") if reproducible else None,
            "reason": None if reproducible else "sandbox runs differ"}


def _visible_artifact_name(name: str) -> str:
    basename = PurePosixPath(name).name
    visible = re.sub(r"^[0-9]{2}-", "", basename) or basename
    visible = re.sub(r"[^\w.+-]", "_", visible)[:80]
    if visible.startswith(".metis"):
        visible = "artifact-" + visible[:72]
    return visible

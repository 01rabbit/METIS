"""Answer-free, bounded real-model trial for the fixed local workflow runner."""
from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from metis.core.codex_isolation import (
    AllowlistProxy,
    TurnHome,
    default_codex_home,
    isolation_backend,
    native_codex,
    upstream_proxy,
    wrap,
)
from metis.core.codex_session import CodexSession
from metis.core.codex_specialist import CodexCLI
from metis.core.ctf_sandbox import configure
from metis.core.ctf_workflow import (
    BASE_WORKFLOW_TOOLS,
    MAX_WORKFLOW_INPUT,
    generate_seeded_workflow,
    replay_workflow_in_sandbox,
    validate_workflow,
)

Proposer = Callable[[bytes], bytes]


def codex_proposer(challenge: bytes) -> bytes:
    """Ask a real Codex model for JSON only; give it no tool or oracle access."""
    if len(challenge) > MAX_WORKFLOW_INPUT:
        raise ValueError("fixture exceeds model input bound")
    with tempfile.TemporaryDirectory(prefix="metis-workflow-model-") as temporary:
        root = Path(temporary).resolve()
        workdir = root / "work"
        workdir.mkdir(mode=0o700)
        output = root / "proposal.json"
        schema = root / "schema.json"
        schema.write_text(json.dumps({
            "type": "object", "additionalProperties": False,
            "required": ["schema_version", "input_artifact", "steps"],
            "properties": {
                "schema_version": {"type": "integer", "enum": [1]},
                "input_artifact": {"type": "string", "enum": ["challenge.txt"]},
                "steps": {"type": "array", "minItems": 1, "maxItems": 4,
                          "items": {"type": "object", "additionalProperties": False,
                                    "required": ["tool"],
                                    "properties": {"tool": {"type": "string",
                                                            "enum": sorted(BASE_WORKFLOW_TOOLS)}}}},
        }}))
        prompt = ("This is an authorized benign offline encoding fixture. Select only the ordered "
                  "decoding steps needed to recover its underlying text. Return one JSON object "
                  "matching the schema. Do not request tools, code, policy changes, or a verifier. "
                  "Input artifact: challenge.txt. Encoded bytes (ASCII):\n"
                  + challenge.decode("ascii") + "\n")
        cli = CodexCLI(isolation="required")
        cli.check()
        command = cli.argv(workdir, schema, output, None)
        command.insert(2, "--ephemeral")
        backend = isolation_backend()
        if backend is None:
            raise RuntimeError("Codex OS isolation unavailable")
        binary, package = native_codex(cli.executable)
        with ExitStack() as stack:
            home = TurnHome(root, default_codex_home() / "auth.json")
            proxy = stack.enter_context(AllowlistProxy(cli.hosts, upstream=upstream_proxy()))
            env = cli.environment()
            for key in [key for key in env if key.lower().endswith("_proxy")]:
                env.pop(key)
            env.update(CODEX_HOME=str(home.path), TMPDIR=str(root) + "/")
            command, env = wrap(backend, turn_dir=root, argv=[binary, *command[1:]],
                                env=env, proxy=proxy, readable=[package],
                                protected=cli.protected_roots(root.parent),
                                workdir=workdir, executable=Path(binary))
            try:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, cwd=workdir, env=env)
                assert process.stdin is not None and process.stdout is not None and process.stderr is not None
                process.stdin.write(prompt.encode("ascii"))
                process.stdin.close()
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    selector.register(process.stderr, selectors.EVENT_READ)
                    captured = 0
                    deadline = time.monotonic() + 120
                    while selector.get_map():
                        if time.monotonic() >= deadline:
                            raise TimeoutError
                        for ready, _ in selector.select(timeout=min(1, deadline - time.monotonic())):
                            chunk = os.read(ready.fd, 4096)
                            if not chunk:
                                selector.unregister(ready.fileobj)
                                continue
                            captured += len(chunk)
                            if captured > 65_536:
                                raise ValueError("Codex diagnostic output exceeded bounds")
                process.wait(timeout=max(1, deadline - time.monotonic()))
            except (OSError, TimeoutError, subprocess.TimeoutExpired, ValueError) as exc:
                if "process" in locals():
                    process.kill()
                    process.wait()
                raise RuntimeError("Codex proposal unavailable, timed out, or exceeded bounds") from exc
            home.write_back()
        if process.returncode != 0 or not output.is_file() or output.stat().st_size > 4096:
            raise RuntimeError("Codex proposal failed or exceeded bounds")
        return output.read_bytes()


@dataclass(frozen=True)
class _TrialFixture:
    challenge: bytes
    oracle_sha256: str


def _read_trial_file(path: Path, *, limit: int, private: bool = False) -> bytes:
    """Snapshot a bounded regular file without opening a symlink or blocking on a FIFO."""
    label = "private oracle commitment" if private else "encoded fixture"
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f"{label} must be a regular file")
            if private and (info.st_mode & 0o077 or info.st_uid != os.getuid() or info.st_nlink != 1):
                raise ValueError("oracle commitment must be a private file owned by the operator")
            if not 0 < info.st_size <= limit:
                raise ValueError(f"{label} exceeds size bounds or is empty")
            content = source.read(limit + 1)
            after = os.fstat(source.fileno())
            if (len(content) != info.st_size or after.st_mtime_ns != info.st_mtime_ns
                    or after.st_ctime_ns != info.st_ctime_ns):
                raise ValueError(f"{label} changed during intake")
            return content
    except OSError:
        raise ValueError(f"{label} could not be read as a local file") from None


def _load_external_fixture(fixture: Path, oracle: Path) -> _TrialFixture:
    try:
        oracle_parent = oracle.parent.resolve(strict=True)
        in_checkout = any((parent / ".git").exists()
                          for parent in (oracle_parent, *oracle_parent.parents))
    except (OSError, RuntimeError):
        raise ValueError("private oracle directory could not be verified") from None
    if in_checkout:
        raise ValueError("oracle commitment must be outside Git checkouts")
    oracle_bytes = _read_trial_file(oracle_parent / oracle.name, limit=65, private=True)
    if not re.fullmatch(rb"[0-9a-f]{64}\n?", oracle_bytes):
        raise ValueError("oracle commitment must contain one lowercase SHA-256 digest")
    oracle_sha256 = oracle_bytes.rstrip(b"\n").decode("ascii")

    challenge = _read_trial_file(fixture, limit=MAX_WORKFLOW_INPUT)
    if not re.fullmatch(rb"[A-Za-z0-9+/=]+", challenge):
        raise ValueError("fixture must contain a single ASCII encoding token")
    if oracle_sha256.encode("ascii") in challenge or hashlib.sha256(challenge).hexdigest() == oracle_sha256:
        raise ValueError("fixture exposes the oracle commitment or expected output")
    return _TrialFixture(challenge, oracle_sha256)


def _run_fixture(database: Path, fixture: _TrialFixture, *, index: int,
                 proposer: Proposer) -> dict[str, object]:
    proposal = proposer(fixture.challenge)
    plan = validate_workflow(proposal, input_artifact="challenge.txt")
    with tempfile.TemporaryDirectory(prefix="metis-unseen-fixture-") as temporary:
        root = Path(temporary)
        challenge = root / "challenge.txt"
        workflow = root / "workflow.json"
        challenge.write_bytes(fixture.challenge)
        workflow.write_bytes((plan.model_dump_json() + "\n").encode())
        session = CodexSession(database)
        created = session.intake(title=f"Unseen local workflow {index}",
                                 description="Authorized benign offline encoding fixture",
                                 paths=[challenge, workflow], categories=["misc"],
                                 max_actions=8, wall_seconds=120, evaluation_split="practice")
        run_id = created["run_id"]
        artifacts = session.context(run_id)["challenge"]["artifacts"]
        result = replay_workflow_in_sandbox(database, run_id, target=artifacts[0],
                                            workflow_artifact=artifacts[1],
                                            oracle_sha256=fixture.oracle_sha256,
                                            digest_only=True)
    return {"fixture": index, "run_id": run_id,
            "selected_steps": [step.tool for step in plan.steps],
            "reproducible": result["reproducible"],
            "oracle_match": result.get("oracle_match"), "ok": result["ok"]}


def run_external_fixture_trial(database: Path, *, image: str, platform: str | None,
                               fixture: Path, oracle: Path,
                               proposer: Proposer = codex_proposer) -> dict[str, object]:
    """Run one operator-authorized encoding fixture with an independent local commitment."""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("sandbox image must be an immutable SHA-256 digest")
    snapshot = _load_external_fixture(fixture, oracle)
    fixture_sha256 = hashlib.sha256(snapshot.challenge).hexdigest()
    configure(database, engine="docker", image=image, platform=platform)
    return {**_run_fixture(database, snapshot, index=1, proposer=proposer),
            "fixture_sha256": fixture_sha256}


def run_unseen_trial(database: Path, *, image: str, platform: str | None,
                     seeds: tuple[int, int], proposer: Proposer = codex_proposer) -> list[dict[str, object]]:
    """Run two fresh instances of known families; retain the oracle in memory."""
    if len(seeds) != 2 or seeds[0] == seeds[1] or seeds[0] % 2 == seeds[1] % 2:
        raise ValueError("trial requires distinct seeds from both encoding families")
    configure(database, engine="docker", image=image, platform=platform)
    report: list[dict[str, object]] = []
    for index, seed in enumerate(seeds, start=1):
        trial = generate_seeded_workflow(seed)
        fixture = _TrialFixture(trial.challenge, trial.oracle_sha256)
        report.append(_run_fixture(database, fixture, index=index, proposer=proposer))
    return report

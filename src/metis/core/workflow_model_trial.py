"""Answer-free, bounded real-model trial for the fixed local workflow runner."""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import selectors
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field

from metis.core.codex_isolation import (
    SYSTEM_RO,
    AllowlistProxy,
    TurnHome,
    default_codex_home,
    isolation_backend,
    native_codex,
    python_roots,
    upstream_proxy,
    wrap,
)
from metis.core.codex_session import CodexSession
from metis.core.codex_specialist import CodexCLI
from metis.core.ctf_sandbox import PLATFORM_PATTERN, configure
from metis.core.ctf_workflow import (
    BASE_WORKFLOW_TOOLS,
    MAX_WORKFLOW_INPUT,
    WorkflowCandidate,
    generate_seeded_workflow,
    replay_workflow_in_sandbox,
    validate_workflow,
)

Proposer = Callable[[bytes], bytes]
MAX_TRIAL_CASES = 32
MAX_TRIAL_MANIFEST_BYTES = 65_536


class TrialCaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    case_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    fixture: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    oracle: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")


class TrialManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: int = Field(ge=1, le=1)
    cases: list[TrialCaseSpec] = Field(min_length=1, max_length=MAX_TRIAL_CASES)


class TrialCaseResult(TypedDict):
    case_id: str
    ok: bool
    reproducible: bool
    oracle_match: bool
    selected_steps: list[str]
    failure: str | None


class TrialBatchSummary(TypedDict):
    total: int
    passed: int
    failed: int
    pass_rate: float


class TrialBatchReport(TypedDict):
    cases: list[TrialCaseResult]
    summary: TrialBatchSummary


@dataclass(frozen=True)
class _LoadedTrialCase:
    case_id: str
    fixture: _TrialFixture


def _exchange_proposal(process: subprocess.Popen[bytes], prompt: bytes, *,
                       timeout: float = 120, output_limit: int = 65_536) -> None:
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    deadline = time.monotonic() + timeout
    pending = memoryview(prompt)
    captured = 0
    try:
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE)
            selector.register(process.stdout, selectors.EVENT_READ)
            selector.register(process.stderr, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                for ready, event in selector.select(remaining):
                    if event == selectors.EVENT_WRITE:
                        try:
                            written = os.write(ready.fd, pending[:4096])
                        except BlockingIOError:
                            continue
                        pending = pending[written:]
                        if not pending:
                            selector.unregister(ready.fileobj)
                            process.stdin.close()
                    else:
                        chunk = os.read(ready.fd, 4096)
                        if not chunk:
                            selector.unregister(ready.fileobj)
                        captured += len(chunk)
                        if captured > output_limit:
                            raise ValueError("Codex diagnostic output exceeded bounds")
        process.wait(timeout=max(0, deadline - time.monotonic()))
    except (OSError, TimeoutError, subprocess.TimeoutExpired, ValueError):
        process.kill()
        process.wait()
        raise RuntimeError("Codex proposal unavailable, timed out, or exceeded bounds") from None


def codex_proposer(challenge: bytes, *, oracle_directory: Path | None = None) -> bytes:
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
        protected = cli.protected_roots(root.parent)
        if oracle_directory is not None:
            readable = [package, root]
            if backend == "bwrap":
                readable.extend(Path(path) for path in SYSTEM_RO)
                readable.extend(python_roots())
            if any(oracle_directory.is_relative_to(path.resolve()) for path in readable):
                raise ValueError("oracle directory overlaps a model-readable mount")
            protected = [*protected, oracle_directory]
        with ExitStack() as stack:
            home = TurnHome(root, default_codex_home() / "auth.json")
            proxy = stack.enter_context(AllowlistProxy(cli.hosts, upstream=upstream_proxy()))
            env = cli.environment()
            for key in [key for key in env if key.lower().endswith("_proxy")]:
                env.pop(key)
            env.update(CODEX_HOME=str(home.path), TMPDIR=str(root) + "/")
            command, env = wrap(backend, turn_dir=root, argv=[binary, *command[1:]],
                                env=env, proxy=proxy, readable=[package],
                                protected=protected,
                                workdir=workdir, executable=Path(binary))
            with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, cwd=workdir, env=env) as process:
                _exchange_proposal(process, prompt.encode("ascii"))
            home.write_back()
        if process.returncode != 0 or not output.is_file() or output.stat().st_size > 4096:
            raise RuntimeError("Codex proposal failed or exceeded bounds")
        return output.read_bytes()


@dataclass(frozen=True)
class _TrialFixture:
    challenge: bytes
    oracle_sha256: str


def _reject_acl_grants(descriptor: int, *, label: str) -> None:
    """A Darwin extended ACL can grant privileges beyond the POSIX mode."""
    if sys.platform != "darwin":
        return
    acl_type_extended = 0x100
    acl_first_entry, acl_next_entry = 0, -1
    acl_extended_deny = 2
    unverified = f"{label} extended ACL could not be verified"
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        get_acl, get_entry = libc.acl_get_fd_np, libc.acl_get_entry
        get_tag, free_acl = libc.acl_get_tag_type, libc.acl_free
    except (AttributeError, OSError):
        raise ValueError(unverified) from None

    get_acl.argtypes = [ctypes.c_int, ctypes.c_int]
    get_acl.restype = ctypes.c_void_p
    get_entry.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
    get_tag.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    free_acl.argtypes = [ctypes.c_void_p]
    acl = get_acl(descriptor, acl_type_extended)
    if not acl:
        if ctypes.get_errno() == errno.ENOENT:  # Darwin indicates an absent ACL.
            return
        raise ValueError(unverified)
    try:
        entry = ctypes.c_void_p()
        selector = acl_first_entry
        while get_entry(acl, selector, ctypes.byref(entry)) == 0:
            tag = ctypes.c_int()
            if get_tag(entry, ctypes.byref(tag)) != 0:
                raise ValueError(unverified)
            if tag.value != acl_extended_deny:
                raise ValueError(f"{label} must have no extended ACL grants")
            selector = acl_next_entry
        if ctypes.get_errno() != errno.EINVAL:  # Darwin signals the end of the list.
            raise ValueError(unverified)
    finally:
        free_acl(acl)


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
            if private:
                _reject_acl_grants(source.fileno(), label=label)
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


def _directory_outside_checkout(path: Path, *, label: str) -> Path:
    try:
        directory = path.resolve(strict=True)
        trusted_uids = {0, os.getuid()}
        # Validate root first. A sticky shared directory protects a child name only
        # when the directory and the child both have trusted owners.
        for parent in (*reversed(directory.parents), directory):
            info = parent.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in trusted_uids
                    or info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
                raise ValueError(f"{label} must have trusted directory ancestry")
            if sys.platform == "darwin":
                descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    if not os.path.samestat(info, os.fstat(descriptor)):
                        raise ValueError(f"{label} changed during ancestry checks")
                    _reject_acl_grants(descriptor, label=label)
                    if not os.path.samestat(info, parent.lstat()):
                        raise ValueError(f"{label} changed during ancestry checks")
                finally:
                    os.close(descriptor)
            if os.path.lexists(parent / ".git"):
                raise ValueError(f"{label} must be outside Git checkouts")
    except (OSError, RuntimeError):
        raise ValueError(f"{label} could not be verified") from None
    return directory


def _load_external_fixture(fixture: Path, oracle: Path) -> _TrialFixture:
    oracle_bytes = _read_trial_file(oracle, limit=65, private=True)
    if not re.fullmatch(rb"[0-9a-f]{64}\n?", oracle_bytes):
        raise ValueError("oracle commitment must contain one lowercase SHA-256 digest")
    oracle_sha256 = oracle_bytes.rstrip(b"\n").decode("ascii")

    challenge = _read_trial_file(fixture, limit=MAX_WORKFLOW_INPUT)
    if not re.fullmatch(rb"[A-Za-z0-9+/=]+", challenge):
        raise ValueError("fixture must contain a single ASCII encoding token")
    if oracle_sha256.encode("ascii") in challenge or hashlib.sha256(challenge).hexdigest() == oracle_sha256:
        raise ValueError("fixture exposes the oracle commitment or expected output")
    return _TrialFixture(challenge, oracle_sha256)


def _read_private_manifest(path: Path) -> tuple[bytes, Path]:
    """Read a bounded private manifest without following aliases or leaking its path."""
    try:
        parent = _directory_outside_checkout(path.parent, label="trial manifest directory")
        info = parent.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("trial manifest directory must be owner-only")
        descriptor = os.open(parent / path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or before.st_mode & 0o077 or before.st_nlink != 1
                    or not 0 < before.st_size <= MAX_TRIAL_MANIFEST_BYTES):
                raise ValueError("trial manifest must be a bounded private regular file")
            _reject_acl_grants(source.fileno(), label="trial manifest")
            payload = source.read(MAX_TRIAL_MANIFEST_BYTES + 1)
            after = os.fstat(source.fileno())
            if (len(payload) != before.st_size or after.st_mtime_ns != before.st_mtime_ns
                    or after.st_ctime_ns != before.st_ctime_ns):
                raise ValueError("trial manifest changed during intake")
        return payload, parent
    except OSError:
        raise ValueError("trial manifest could not be read safely") from None


def _load_trial_manifest(path: Path) -> tuple[tuple[_LoadedTrialCase, ...], Path]:
    """Snapshot and validate every manifest input before any run or proposal starts."""
    raw, parent = _read_private_manifest(path)
    try:
        manifest = TrialManifest.model_validate_json(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("trial manifest is malformed or violates the fixed schema") from None
    ids = [case.case_id for case in manifest.cases]
    names = [name for case in manifest.cases for name in (case.fixture, case.oracle)]
    if len(set(ids)) != len(ids):
        raise ValueError("trial manifest contains duplicate case IDs")
    if len(set(names)) != len(names):
        raise ValueError("trial manifest contains duplicate input paths")
    for name in names:
        candidate = Path(name)
        if (candidate.is_absolute() or candidate.name != name or name in {".", ".."}
                or "\\" in name or "/" in name):
            raise ValueError("trial manifest paths must be unique sibling filenames")

    loaded: list[_LoadedTrialCase] = []
    fixture_digests: set[str] = set()
    for case in sorted(manifest.cases, key=lambda item: item.case_id):
        fixture_path = parent / case.fixture
        oracle_path = parent / case.oracle
        snapshot = _load_external_fixture(fixture_path, oracle_path)
        fixture_digest = hashlib.sha256(snapshot.challenge).hexdigest()
        if fixture_digest in fixture_digests:
            raise ValueError("trial manifest contains duplicate fixture content")
        fixture_digests.add(fixture_digest)
        loaded.append(_LoadedTrialCase(case_id=case.case_id, fixture=snapshot))
    commitments = {item.fixture.oracle_sha256 for item in loaded}
    commitment_digests = {item.fixture.oracle_sha256 for item in loaded}
    if any(any(commitment.encode("ascii") in item.fixture.challenge
               for commitment in commitments)
           or hashlib.sha256(item.fixture.challenge).hexdigest() in commitment_digests
           for item in loaded):
        raise ValueError("trial manifest fixture exposes a case oracle commitment or answer")
    return tuple(loaded), parent


def run_external_fixture_manifest_trial(database: Path, *, image: str, platform: str | None,
                                        manifest: Path,
                                        proposer: Proposer | None = None) -> TrialBatchReport:
    """Run a bounded answer-free batch; intake of all cases precedes side effects."""
    if sys.platform not in {"darwin", "linux"}:
        raise ValueError("external fixture intake requires macOS or Linux")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("sandbox image must be an immutable SHA-256 digest")
    if platform is not None and not PLATFORM_PATTERN.fullmatch(platform):
        raise ValueError("unsupported platform")

    cases, oracle_directory = _load_trial_manifest(manifest)
    workspace_parent = _directory_outside_checkout(database.parent.parent,
                                                    label="run workspace parent")
    if database.name.casefold() in {"", "..", "sandbox.json"} or database.parent.name in {"", ".."}:
        raise ValueError("database must name a file in a new private run directory")
    workspace = workspace_parent / database.parent.name
    try:
        workspace.mkdir(mode=0o700)
    except OSError:
        raise ValueError("database requires a new private run directory") from None

    run_database = workspace / database.name
    try:
        configure(run_database, engine="docker", image=image, platform=platform)
    except Exception:  # noqa: BLE001 - configuration errors may include private paths
        raise RuntimeError("multi-case sandbox configuration failed") from None
    model_proposer = proposer or partial(codex_proposer,
                                         oracle_directory=oracle_directory)
    rows: list[TrialCaseResult] = []
    for case in cases:
        row: TrialCaseResult = {"case_id": case.case_id, "ok": False,
                                "reproducible": False, "oracle_match": False,
                                "selected_steps": [], "failure": "proposal"}
        try:
            proposal = model_proposer(case.fixture.challenge)
        except Exception:  # noqa: BLE001 - provider/isolation errors can carry private data
            raise RuntimeError("multi-case proposal infrastructure failed") from None
        try:
            plan = validate_workflow(proposal, input_artifact="challenge.txt")
        except ValueError:
            row["failure"] = "invalid_proposal"
            rows.append(row)
            continue
        try:
            result = _execute_workflow(run_database, case.fixture, plan,
                                       index=len(rows) + 1)
            selected_steps = result["selected_steps"]
            if not isinstance(selected_steps, list) or not all(
                    isinstance(step, str) for step in selected_steps):
                raise ValueError("trial result has an invalid workflow projection")
            ok_value = result.get("ok")
            reproducible_value = result.get("reproducible")
            oracle_match_value = result.get("oracle_match", False)
            if oracle_match_value is None:
                oracle_match_value = False
            if (not isinstance(ok_value, bool) or not isinstance(reproducible_value, bool)
                    or not isinstance(oracle_match_value, bool)):
                raise TypeError("trial result has invalid status values")
            row.update({"ok": ok_value,
                        "reproducible": reproducible_value,
                        "oracle_match": oracle_match_value,
                        "selected_steps": selected_steps,
                        "failure": None if result["ok"] else "replay"})
        except Exception:  # noqa: BLE001 - sandbox/storage failures are not model outcomes
            raise RuntimeError("multi-case sandbox or run infrastructure failed") from None
        rows.append(row)

    passed = sum(bool(row["ok"]) for row in rows)
    summary: TrialBatchSummary = {"total": len(rows), "passed": passed,
                                  "failed": len(rows) - passed,
                                  "pass_rate": passed / len(rows)}
    return {"cases": rows, "summary": summary}


def _run_fixture(database: Path, fixture: _TrialFixture, *, index: int,
                 proposer: Proposer) -> dict[str, object]:
    proposal = proposer(fixture.challenge)
    plan = validate_workflow(proposal, input_artifact="challenge.txt")
    return _execute_workflow(database, fixture, plan, index=index)


def _execute_workflow(database: Path, fixture: _TrialFixture, plan: WorkflowCandidate, *,
                      index: int) -> dict[str, object]:
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
                               proposer: Proposer | None = None) -> dict[str, object]:
    """Run one operator-authorized encoding fixture with an independent local commitment."""
    if sys.platform not in {"darwin", "linux"}:
        raise ValueError("external fixture intake requires macOS or Linux")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("sandbox image must be an immutable SHA-256 digest")
    if platform is not None and not PLATFORM_PATTERN.fullmatch(platform):
        raise ValueError("unsupported platform")
    oracle_parent = _directory_outside_checkout(oracle.parent, label="private oracle directory")
    oracle_info = oracle_parent.stat()
    if oracle_info.st_uid != os.getuid() or oracle_info.st_mode & 0o077:
        raise ValueError("oracle commitment must be in an owner-only directory")
    snapshot = _load_external_fixture(fixture, oracle_parent / oracle.name)
    fixture_sha256 = hashlib.sha256(snapshot.challenge).hexdigest()

    workspace_parent = _directory_outside_checkout(database.parent.parent, label="run workspace parent")
    if database.name.casefold() in {"", "..", "sandbox.json"} or database.parent.name in {"", ".."}:
        raise ValueError("database must name a file in a new private run directory")
    workspace = workspace_parent / database.parent.name
    try:
        workspace.mkdir(mode=0o700)
    except OSError:
        raise ValueError("database requires a new private run directory") from None

    run_database = workspace / database.name
    configure(run_database, engine="docker", image=image, platform=platform)
    model_proposer = proposer or partial(codex_proposer, oracle_directory=oracle_parent)
    return {**_run_fixture(run_database, snapshot, index=1, proposer=model_proposer),
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

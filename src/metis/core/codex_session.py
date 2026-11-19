"""Codex supplies reasoning; these commands provide bounded data tools and evidence."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import stat
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from metis.core.artifacts import artifact_stream
from metis.core.contracts import ChallengeManifest, RunEvent, RunStatus
from metis.core.ctf_artifacts import (
    ARTIFACT_ERRORS,
    ARTIFACT_TOOLS,
    DERIVE_TOOLS,
    MAX_FILE,
    inspect_file,
)
from metis.core.ctf_tools import DATA_TOOLS, transform
from metis.core.ctf_triage import triage
from metis.core.run_lock import locked, operation_lock, run_lock
from metis.core.runtime import ToolRequest
from metis.core.store import RunStore

NATIVE_TOOLS = DATA_TOOLS


def _artifact_evidence(tool: str, output: dict) -> dict[str, str]:
    """Project sensitive artifact results into small, domain-level audit facts."""
    detail = {"tool_ok": str(output.get("ok") is True).lower(), "artifact_tool": tool}
    result = output.get("result")
    if not isinstance(result, dict):
        return detail

    def add(key: str, value: object) -> None:
        if isinstance(value, (str, int, float, bool)):
            detail[key] = str(value)[:80]

    if tool == "infozip_seed":
        add("found", result.get("found"))
        if result.get("reason") in {"too_few_members", "no_time_hint", "work_exceeds_budget", "no_seed_in_range"}:
            add("reason", result["reason"])
        if result.get("generator") in {"glibc", "msvc"}:
            add("generator", result["generator"])
        if result.get("salt") in {"pid", "pi"}:
            add("salt", result["salt"])
        for key in ("members", "matched_leaked_bytes", "tried_seeds", "seconds"):
            add(key, result.get(key))
    elif tool == "zipcrypto_attack":
        add("found", result.get("found"))
        if result.get("reason") in {"not_enough_plaintext", "plaintext_outside_ciphertext", "work_exceeds_budget", "no_solution"}:
            add("reason", result["reason"])
        if result.get("stage") in {"z-reduction", "key-search"}:
            add("stage", result["stage"])
        for key in ("tried", "workers", "seconds"):
            add(key, result.get(key))
    elif tool in {"zipcrypto_stay_scan", "zipcrypto_stay_stage2", "zipcrypto_stay_recover"}:
        for key in ("next_index", "complete", "scanned", "hits_count", "seconds"):
            add(key, result.get(key))
        if tool == "zipcrypto_stay_recover":
            for key in ("next_product", "next_extra", "product_count", "keys_count"):
                add(key, result.get(key))
        if result.get("reason") in {"work_exceeds_budget", "memory_limit_exceeded", "isolation_unavailable",
                                     "worker_failed", "header_observation_mismatch",
                                     "observation_count_mismatch"}:
            add("reason", result["reason"])
        if result.get("stage") in {"sandbox-timeout", "sandbox-oom", "cgroup-check",
                                    "worker-output", "input-validation", "stay-first-stage-scan"}:
            add("stage", result["stage"])
    elif tool == "zipcrypto_decrypt":
        add("crc_ok", result.get("crc_ok"))
        add("plaintext_bytes", result.get("size"))
        add("stay_header_ok", result.get("stay_header_ok"))
    elif tool == "zipcrypto_info":
        members = result.get("members")
        add("member_count", len(members) if isinstance(members, list) else None)
        add("encrypted_members", result.get("encrypted_members"))
    return detail


class CodexSession:
    def __init__(self, database: Path):
        database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database = database
        created = not database.exists()
        self.store = RunStore(database)
        if created:
            database.chmod(0o600)
        with sqlite3.connect(database, timeout=30) as db:
            # Several swarm workers share this database; WAL lets readers and one
            # writer proceed concurrently (the setting persists in the file).
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS codex_sessions (
                run_id TEXT PRIMARY KEY, manifest TEXT NOT NULL, commitment TEXT,
                started REAL NOT NULL, max_actions INTEGER NOT NULL,
                wall_seconds INTEGER NOT NULL)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(codex_sessions)")}
            if "artifact_root" not in columns:
                db.execute("ALTER TABLE codex_sessions ADD COLUMN artifact_root TEXT")
            # Older databases stored absolute artifact roots; store them relative to the
            # state directory so the whole checkout can be moved or copied.
            base = database.parent.resolve()
            for run_id, stored in db.execute(
                    "SELECT run_id, artifact_root FROM codex_sessions WHERE artifact_root LIKE '/%'").fetchall():
                path = Path(stored)
                if path.is_relative_to(base):
                    db.execute("UPDATE codex_sessions SET artifact_root=? WHERE run_id=?",
                               (path.relative_to(base).as_posix(), run_id))
                elif not path.exists() and (base / path.name).is_dir():
                    # The checkout was moved: the snapshot now lives beside the database.
                    db.execute("UPDATE codex_sessions SET artifact_root=? WHERE run_id=?", (path.name, run_id))
            if "activated" not in columns:
                # The wall-clock budget starts at the first action, not at intake, so a
                # portfolio opened at once does not expire together.
                db.execute("ALTER TABLE codex_sessions ADD COLUMN activated REAL")
            if "evaluation_split" not in columns:
                # Unknown/unlisted sessions are treated conservatively by MUNIN retrieval.
                db.execute("ALTER TABLE codex_sessions ADD COLUMN evaluation_split TEXT NOT NULL DEFAULT 'unlisted'")
            db.execute("""CREATE TABLE IF NOT EXISTS codex_active_operations (
                run_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, assignment_id TEXT,
                attempt_id TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0, started REAL NOT NULL)""")

    def _emit(self, run_id: str, status: RunStatus, **detail: str) -> int:
        events = self.store.read(run_id)
        sequence = len(events)
        self.store.append(RunEvent(run_id=run_id, sequence=sequence, status=status, detail=detail))
        return sequence

    def start(self, manifest: ChallengeManifest, *, commitment: str | None = None,
              max_actions: int = 40, wall_seconds: int = 1200,
              artifact_root: Path | None = None,
              evaluation_split: str = "unlisted") -> dict:
        manifest = ChallengeManifest.model_validate(manifest.model_dump())
        if manifest.artifacts and artifact_root is None:
            raise ValueError("artifact root is required for file challenges")
        root = str(artifact_root.resolve(strict=True)) if artifact_root is not None else None
        if root is not None and not Path(root).is_dir():
            raise ValueError("artifact root must be a directory")
        if root is not None and Path(root).is_relative_to(self.database.parent.resolve()):
            root = Path(root).relative_to(self.database.parent.resolve()).as_posix()
        if commitment is not None and not re.fullmatch(r"[0-9a-f]{64}", commitment):
            raise ValueError("invalid SHA-256 verification commitment")
        if evaluation_split not in {"practice", "competition", "heldout", "unlisted"}:
            raise ValueError("evaluation_split must be practice, competition, heldout or unlisted")
        if not 1 <= max_actions <= 1000 or not 1 <= wall_seconds <= 86_400:
            raise ValueError("invalid session budget")
        run_id = uuid4().hex
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO codex_sessions "
                       "(run_id, manifest, commitment, started, max_actions, wall_seconds, artifact_root, "
                       "evaluation_split) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
                run_id, manifest.model_dump_json(), commitment, time.time(),
                max_actions, wall_seconds, root, evaluation_split,
            ))
        for state in (RunStatus.NEW, RunStatus.VALIDATED, RunStatus.CLASSIFIED, RunStatus.PLANNING):
            self._emit(run_id, state)
        return self.context(run_id)

    def _session(self, run_id: str) -> tuple:
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT manifest, commitment, started, max_actions, wall_seconds "
                             "FROM codex_sessions WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Codex session not found")
        return row

    def context(self, run_id: str) -> dict:
        manifest, commitment, _started, max_actions, wall_seconds = self._session(run_id)
        events = self.store.read(run_id)
        used = sum(event.status == RunStatus.EXECUTING for event in events)
        with sqlite3.connect(self.database) as db:
            activated = db.execute("SELECT activated FROM codex_sessions WHERE run_id=?", (run_id,)).fetchone()[0]
            evaluation_split = db.execute(
                "SELECT evaluation_split FROM codex_sessions WHERE run_id=?", (run_id,)
            ).fetchone()[0]
        clock = activated if activated is not None else time.time()
        return {
            "run_id": run_id, "status": events[-1].status.value,
            "challenge": json.loads(manifest), "tools": sorted(NATIVE_TOOLS),
            "evaluation_split": evaluation_split,
            "artifact_tools": sorted(ARTIFACT_TOOLS),
            "triage": triage(ChallengeManifest.model_validate_json(manifest)),
            "network_tools": self._network_tools(run_id),
            "verification_available": commitment is not None,
            "actions_remaining": max(0, max_actions - used),
            "seconds_remaining": max(0, round(clock + wall_seconds - time.time())),
            "budget": {"max_actions": max_actions, "wall_seconds": wall_seconds,
                       "clock_started": activated is not None},
        }

    def _network_tools(self, run_id: str) -> list[dict]:
        with sqlite3.connect(self.database) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='remote_endpoints'"
                              ).fetchone():
                return []
            rows = db.execute("SELECT idx,host,port,tls FROM remote_endpoints WHERE run_id=? ORDER BY idx",
                              (run_id,)).fetchall()
        return [{"index": idx, "host": host, "port": port, "tls": bool(tls),
                 "operations": ["remote exchange", "remote pipe"]} for idx, host, port, tls in rows]

    def _reserve(self, run_id: str, operation: str, **detail: str) -> None:
        context = self.context(run_id)
        if context["status"] != RunStatus.PLANNING.value:
            raise ValueError("session is not awaiting a decision")
        if not context["actions_remaining"] or not context["seconds_remaining"]:
            self._emit(run_id, RunStatus.EXHAUSTED, reason="budget_limit")
            raise ValueError("session budget exhausted")
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE codex_sessions SET activated=? WHERE run_id=? AND activated IS NULL",
                       (time.time(), run_id))
        self._emit(run_id, RunStatus.EXECUTING, operation=operation, **detail)

    @locked
    def extend(self, run_id: str, *, actions: int = 0, seconds: int = 0) -> dict:
        """Operator-approved budget extension; also resumes a budget-exhausted run.

        Keeps the run identity, attempt history and duplicate-candidate protection,
        which reopening the problem as a new run would lose.
        """
        _, _, _, max_actions, wall_seconds = self._session(run_id)
        if actions < 0 or not 0 <= seconds <= 86_400 or not (actions or seconds):
            raise ValueError("extension must add actions and/or 0-86400 seconds")
        with sqlite3.connect(self.database) as db:
            activated = db.execute("SELECT activated FROM codex_sessions WHERE run_id=?", (run_id,)).fetchone()[0]
        # Time already spent past the old limit is forgiven: `seconds` means "this
        # much more from now", which is what an operator expects after expiry.
        elapsed = time.time() - activated if activated is not None else 0.0
        used = sum(event.status == RunStatus.EXECUTING for event in self.store.read(run_id))
        new_seconds = int(max(wall_seconds, elapsed)) + seconds
        new_actions = max(max_actions, used) + actions
        if new_actions - used > 2000:
            raise ValueError("extension exceeds the hard action ceiling")
        events = self.store.read(run_id)
        status = events[-1].status
        if status not in {RunStatus.PLANNING, RunStatus.EXHAUSTED}:
            raise ValueError("only planning or budget-exhausted runs can be extended")
        if status == RunStatus.EXHAUSTED and events[-1].detail.get("reason") != "budget_limit":
            raise ValueError("run was not stopped by its budget")
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE codex_sessions SET max_actions=?, wall_seconds=? WHERE run_id=?",
                       (new_actions, new_seconds, run_id))
        if status == RunStatus.EXHAUSTED:
            self._emit(run_id, RunStatus.PLANNING, reason="operator_budget_extension")
        return self.context(run_id)

    @locked
    def act(self, run_id: str, request: ToolRequest) -> dict:
        request = ToolRequest.model_validate(request.model_dump())
        request.data.encode()  # Reject invalid Unicode before changing session state.
        self._reserve(run_id, "native_data_transform",
                      tool=request.tool if request.tool in NATIVE_TOOLS else "denied",
                      request_sha256=hashlib.sha256(request.model_dump_json().encode()).hexdigest())
        result = transform(request)
        evidence_sequence = self._emit(run_id, RunStatus.OBSERVING, tool_ok=str(result.ok).lower())
        self._emit(run_id, RunStatus.REPLANNING)
        self._emit(run_id, RunStatus.PLANNING)
        # Return data to Codex, but never persist decoded answers in evidence.
        return {"run_id": run_id, **result.model_dump(), "_evidence_sequence": evidence_sequence}

    @locked
    def submit(self, run_id: str, candidate: str) -> dict:
        if len(candidate.encode()) > 65_536:
            raise ValueError("candidate exceeds limit")
        self._reserve(run_id, "submit_candidate")
        self._emit(run_id, RunStatus.OBSERVING)
        self._emit(run_id, RunStatus.VERIFYING)
        commitment = self._session(run_id)[1]
        accepted = commitment is not None and hmac.compare_digest(
            hashlib.sha256(candidate.encode()).hexdigest(), commitment,
        )
        if accepted:
            self._emit(run_id, RunStatus.SOLVED, verification="local_sha256_commitment")
        else:
            self._emit(run_id, RunStatus.REPLANNING, reason="candidate_unverified")
            self._emit(run_id, RunStatus.PLANNING)
        return {"run_id": run_id, "verified": accepted, "status": self.context(run_id)["status"]}

    def artifact(self, run_id: str, name: str, tool: str, options: dict | None = None, *,
                 _owner: tuple[str, str] | None = None, _retain_operation: bool = False) -> dict:
        operation_id = uuid4().hex
        with operation_lock(self.database, run_id):
            with run_lock(self.database, run_id):
                manifest = ChallengeManifest.model_validate_json(self._session(run_id)[0])
                if name not in manifest.artifacts or tool not in ARTIFACT_TOOLS:
                    raise ValueError("artifact or operation is outside the declared scope")
                root = self.artifact_root(run_id)
                if root is None:
                    raise ValueError("no artifact root registered")
                if _owner is not None:
                    with sqlite3.connect(self.database) as db:
                        job = db.execute("SELECT state,attempt_id,deadline FROM agent_jobs "
                                         "WHERE assignment_id=?", (_owner[0],)).fetchone()
                    if job is None or job[:2] != ("running", _owner[1]):
                        raise ValueError("assignment ended before its artifact operation started")
                    if job[2] and time.time() > job[2]:
                        raise ValueError("assignment deadline expired before its artifact operation started")
                self._reserve(run_id, "read_only_artifact_analysis", tool=tool)
                with sqlite3.connect(self.database) as db:
                    db.execute("INSERT OR REPLACE INTO codex_active_operations "
                               "(run_id,operation_id,assignment_id,attempt_id,cancel_requested,started) "
                               "VALUES (?,?,?,?,0,?)", (run_id, operation_id,
                                                         _owner[0] if _owner else None,
                                                         _owner[1] if _owner else None, time.time()))
            try:
                zipcrypto_runner = None
                if tool == "zipcrypto_attack":
                    from metis.core.ctf_zipcrypto_worker import run_zipcrypto_attack
                    def zipcrypto_runner(data, settings):
                        return run_zipcrypto_attack(self.database, run_id, name, settings,
                                                    _operation_id=operation_id)
                elif tool == "zipcrypto_stay_scan":
                    from metis.core.ctf_zipcrypto_worker import run_zipcrypto_stay_scan
                    def zipcrypto_runner(data, settings):
                        return run_zipcrypto_stay_scan(self.database, run_id, name, settings,
                                                       _operation_id=operation_id)
                elif tool == "zipcrypto_stay_stage2":
                    from metis.core.ctf_zipcrypto_worker import run_zipcrypto_stay_stage2
                    def zipcrypto_runner(data, settings):
                        return run_zipcrypto_stay_stage2(self.database, run_id, name, settings,
                                                         _operation_id=operation_id)
                elif tool == "zipcrypto_stay_recover":
                    from metis.core.ctf_zipcrypto_worker import run_zipcrypto_stay_recover
                    def zipcrypto_runner(data, settings):
                        return run_zipcrypto_stay_recover(self.database, run_id, name, settings,
                                                          _operation_id=operation_id)
                result = inspect_file(root, name, tool, options, zipcrypto_runner=zipcrypto_runner)
                output = {"run_id": run_id, "ok": True, "result": result, "_tool": tool}
            except ARTIFACT_ERRORS as exc:
                output = {"run_id": run_id, "ok": False, "error": "artifact rejected or unsupported",
                          "error_type": type(exc).__name__, "_tool": tool}
                if type(exc) in (ValueError, TypeError):
                    output["detail"] = str(exc).splitlines()[0][:200] if str(exc) else ""
            except BaseException:
                self._finish_artifact_operation(run_id, operation_id, {"ok": False})
                raise
            return self._finish_artifact_operation(run_id, operation_id, output,
                                                  retain=_retain_operation and output.get("ok") is True)

    def _finish_artifact_operation(self, run_id: str, operation_id: str, output: dict,
                                   *, retain: bool = False) -> dict:
        with run_lock(self.database, run_id):
            with sqlite3.connect(self.database) as db:
                row = db.execute("SELECT cancel_requested FROM codex_active_operations "
                                  "WHERE run_id=? AND operation_id=?", (run_id, operation_id)).fetchone()
                if not retain or row is None or row[0]:
                    db.execute("DELETE FROM codex_active_operations WHERE run_id=? AND operation_id=?",
                               (run_id, operation_id))
            if row is None or row[0] or self.context(run_id)["status"] != RunStatus.EXECUTING.value:
                if self.context(run_id)["status"] == RunStatus.EXECUTING.value:
                    self._emit(run_id, RunStatus.OBSERVING, tool_ok="false", cancelled="true")
                    self._emit(run_id, RunStatus.REPLANNING)
                    self._emit(run_id, RunStatus.PLANNING)
                return {"run_id": run_id, "ok": False, "cancelled": True,
                        "error": "artifact result discarded after cancellation or recovery"}
            evidence_sequence = self._emit(run_id, RunStatus.OBSERVING,
                                           **_artifact_evidence(output.get("_tool", "unknown"), output))
            self._emit(run_id, RunStatus.REPLANNING)
            self._emit(run_id, RunStatus.PLANNING)
            return {key: value for key, value in output.items() if key != "_tool"} | {
                "_evidence_sequence": evidence_sequence}

    def cancel_active_operation(self, run_id: str, assignment_id: str, attempt_id: str) -> dict:
        """Request cancellation of this assignment's active artifact operation."""
        with run_lock(self.database, run_id):
            with sqlite3.connect(self.database) as db:
                row = db.execute("SELECT operation_id FROM codex_active_operations WHERE run_id=? "
                                 "AND assignment_id=? AND attempt_id=?", (run_id, assignment_id,
                                                                           attempt_id)).fetchone()
                if row is None:
                    return {"status": "not_running"}
                db.execute("UPDATE codex_active_operations SET cancel_requested=1 WHERE run_id=? "
                           "AND operation_id=?", (run_id, row[0]))
            from metis.core.ctf_sandbox import cancel_registered_worker
            teardown = cancel_registered_worker(self.database, run_id)
            return {"status": "requested", "worker_teardown": teardown}

    def intake(self, *, title: str, description: str, paths: list[Path],
               categories: list[str] | None = None, commitment: str | None = None,
               max_actions: int = 80, wall_seconds: int = 3600,
               evaluation_split: str = "unlisted") -> dict:
        if len(paths) > 32 or len(description.encode()) > 65_536:
            raise ValueError("intake limit exceeded")
        workspace = Path(tempfile.mkdtemp(prefix=".metis-artifacts-", dir=self.database.parent))
        try:
            copied = []
            total = 0
            for index, supplied in enumerate(paths):
                # The user named these paths explicitly; resolve OS-level symlinks such as
                # macOS /tmp -> /private/tmp. The target must still be a bounded regular file.
                path = supplied.resolve(strict=True)
                name = f"{index:02d}-" + re.sub(r"[^\w.-]", "_", supplied.name)[:40]
                descriptor = os.open(workspace / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with (os.fdopen(descriptor, "wb") as stream,
                      artifact_stream(path.parent, path.name, max_bytes=MAX_FILE) as source):
                    consumed = 0
                    while chunk := source.read(1_048_576):
                        consumed += len(chunk)
                        total += len(chunk)
                        if consumed > MAX_FILE or total > 512 * 1024 * 1024:
                            raise ValueError("intake exceeds file or total byte limit")
                        stream.write(chunk)
                copied.append(name)
            identity = "ctf-" + uuid4().hex
            manifest = ChallengeManifest.model_validate({
                "challenge_id": identity, "title": title, "description": description,
                "categories": categories or [], "artifacts": copied,
                "scope": {"authorized": True, "granted_by": "explicit-user-intake",
                          "challenge_id": identity},
            })
            return self.start(manifest, artifact_root=workspace, commitment=commitment,
                              max_actions=max_actions, wall_seconds=wall_seconds,
                              evaluation_split=evaluation_split)
        except (OSError, ValueError):
            shutil.rmtree(workspace)
            raise

    def derive(self, run_id: str, name: str, tool: str, options: dict | None = None, *,
               _owner: tuple[str, str] | None = None, _defer_store: bool = False) -> dict:
        if tool not in DERIVE_TOOLS:
            raise ValueError("only bounded archive decoding can derive an artifact")
        with operation_lock(self.database, run_id):
            observation = self.artifact(run_id, name, tool, options, _owner=_owner, _retain_operation=True)
            if not observation["ok"]:
                return observation
            try:
                content = base64.b64decode(observation["result"]["base64"], validate=True)
                if len(content) > 1_048_576:
                    raise ValueError("derived artifact exceeds one MiB")
                with run_lock(self.database, run_id):
                    with sqlite3.connect(self.database) as db:
                        active = db.execute("SELECT operation_id,cancel_requested FROM codex_active_operations "
                                             "WHERE run_id=?", (run_id,)).fetchone()
                    if (active is None or active[1]
                            or self.context(run_id)["status"] != RunStatus.PLANNING.value):
                        return {"run_id": run_id, "ok": False, "cancelled": True,
                                "error": "derived output discarded after cancellation"}
                    if _defer_store:
                        return {"run_id": run_id, "ok": True,
                                "_derived_content": base64.b64encode(content).decode("ascii"),
                                "_derived_suffix": _suffix(content), "size": len(content),
                                "sha256": hashlib.sha256(content).hexdigest(),
                                "_evidence_sequence": observation["_evidence_sequence"]}
                    relative = self.store_artifact(run_id, content, suffix=_suffix(content))
                    with sqlite3.connect(self.database) as db:
                        db.execute("DELETE FROM codex_active_operations WHERE run_id=? AND operation_id=?",
                                   (run_id, active[0]))
                return {"run_id": run_id, "ok": True, "artifact": relative,
                        "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
                        "_evidence_sequence": observation["_evidence_sequence"]}
            finally:
                with sqlite3.connect(self.database) as db:
                    db.execute("DELETE FROM codex_active_operations WHERE run_id=? AND assignment_id IS ? "
                               "AND attempt_id IS ?", (run_id, _owner[0] if _owner else None,
                                                        _owner[1] if _owner else None))

    def artifact_root(self, run_id: str) -> Path | None:
        """Snapshot directory of a run; relative roots live beside the database."""
        self._session(run_id)
        with sqlite3.connect(self.database) as db:
            root = db.execute("SELECT artifact_root FROM codex_sessions WHERE run_id=?",
                              (run_id,)).fetchone()[0]
        if root is None:
            return None
        path = Path(root)
        return path if path.is_absolute() else self.database.parent.resolve() / path

    @locked
    def store_artifact(self, run_id: str, content: bytes, *, directory_name: str = ".metis-derived",
                       suffix: str = ".bin") -> str:
        """Write controller-produced bytes into the run snapshot and declare them in scope."""
        if len(content) > MAX_FILE or not re.fullmatch(r"\.metis-[a-z]{1,16}", directory_name) \
                or not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
            raise ValueError("invalid controller artifact")
        root = self.artifact_root(run_id)
        if root is None:
            raise ValueError("no artifact root registered")
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                os.mkdir(directory_name, mode=0o700, dir_fd=directory)
            except FileExistsError:
                pass
            output_directory = os.open(directory_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                       dir_fd=directory)
        finally:
            os.close(directory)
        filename = uuid4().hex + suffix
        try:
            descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=output_directory)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
        finally:
            os.close(output_directory)
        relative = directory_name + "/" + filename
        manifest = ChallengeManifest.model_validate_json(self._session(run_id)[0])
        data = manifest.model_dump()
        data["artifacts"] = [*manifest.artifacts, relative]
        updated = ChallengeManifest.model_validate(data)
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE codex_sessions SET manifest=? WHERE run_id=?",
                       (updated.model_dump_json(), run_id))
        return relative

    def purge_derived(self, run_id: str, *, apply: bool = False) -> dict[str, object]:
        """Dry-run or remove only generated `.metis-derived` files for a terminal run.

        Files are unlinked before their manifest entries are removed. If the process
        stops between those steps, a retry treats already-missing registered files
        as complete and finishes the manifest update.
        """
        with operation_lock(self.database, run_id), run_lock(self.database, run_id):
            events = self.store.read(run_id)
            if not events:
                raise ValueError("run not found")
            # Age alone does not make a run disposable. PLANNING can accept the
            # next action; EXHAUSTED can be extended by the operator. Check the
            # allowlist while holding both run locks, before any unlink.
            if events[-1].status not in {RunStatus.SOLVED, RunStatus.CANCELLED,
                                        RunStatus.ERROR, RunStatus.POLICY_DENIED}:
                raise ValueError("run must be terminal before derived artifact purge")

            with sqlite3.connect(self.database) as db:
                tables = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                active_operations = (db.execute(
                    "SELECT 1 FROM codex_active_operations WHERE run_id=? LIMIT 1", (run_id,),
                ).fetchone() if "codex_active_operations" in tables else None)
                active_workers = (db.execute(
                    "SELECT 1 FROM sandbox_workers WHERE run_id=? LIMIT 1", (run_id,),
                ).fetchone() if "sandbox_workers" in tables else None)
                active_jobs = (db.execute(
                    "SELECT 1 FROM agent_jobs WHERE run_id=? AND state IN ('queued','running','unknown') LIMIT 1",
                    (run_id,),
                ).fetchone() if "agent_jobs" in tables else None)
            if active_operations or active_workers or active_jobs:
                raise ValueError("run has active operations or workers")

            manifest_text = self._session(run_id)[0]
            manifest = ChallengeManifest.model_validate_json(manifest_text)
            derived_paths = sorted(path for path in manifest.artifacts
                                   if path.startswith(".metis-derived/"))
            expected_names: set[str] = set()
            for path in derived_paths:
                name = path.removeprefix(".metis-derived/")
                if ("/" in name or not re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]{1,8}", name)):
                    raise ValueError("registered derived artifact path is unexpected")
                expected_names.add(name)
            if len(expected_names) != len(derived_paths):
                raise ValueError("registered derived artifact path is duplicated")

            root = self.artifact_root(run_id)
            if root is None:
                if expected_names:
                    raise ValueError("run has no registered artifact root")
                return {"run_id": run_id, "applied": apply, "files": [], "bytes": 0}
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            derived_fd: int | None = None
            entries: list[dict[str, str | int]]
            try:
                try:
                    derived_fd = os.open(".metis-derived", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                         dir_fd=root_fd)
                except FileNotFoundError:
                    entries = [
                        {"path": path, "state": "missing", "size": 0} for path in derived_paths
                    ]
                    derived_exists = False
                else:
                    names = set(os.listdir(derived_fd))
                    if names - expected_names:
                        raise ValueError("derived directory contains unregistered entries")
                    entries = []
                    for path in derived_paths:
                        name = path.removeprefix(".metis-derived/")
                        try:
                            file_stat = os.stat(name, dir_fd=derived_fd, follow_symlinks=False)
                        except FileNotFoundError:
                            entries.append({"path": path, "state": "missing", "size": 0})
                            continue
                        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
                            raise ValueError("derived artifact is not a private regular file")
                        entries.append({"path": path, "state": "present", "size": file_stat.st_size})
                    derived_exists = True

                total_bytes = sum(int(item["size"]) for item in entries)
                if not apply:
                    return {"run_id": run_id, "applied": False, "files": entries, "bytes": total_bytes}

                if derived_exists and derived_fd is not None:
                    for item in entries:
                        if item["state"] == "present":
                            os.unlink(str(item["path"]).removeprefix(".metis-derived/"),
                                      dir_fd=derived_fd)
                            item["state"] = "deleted"
                    os.fsync(derived_fd)

                data = manifest.model_dump()
                data["artifacts"] = [path for path in manifest.artifacts
                                     if not path.startswith(".metis-derived/")]
                updated = ChallengeManifest.model_validate(data)
                with sqlite3.connect(self.database) as db:
                    db.execute("UPDATE codex_sessions SET manifest=? WHERE run_id=?",
                               (updated.model_dump_json(), run_id))
                return {"run_id": run_id, "applied": True, "files": entries, "bytes": total_bytes,
                        "manifest_entries_removed": len(derived_paths)}
            finally:
                if derived_fd is not None:
                    os.close(derived_fd)
                os.close(root_fd)

    @locked
    def add_file(self, run_id: str, supplied: Path) -> dict:
        """Add a user-supplied file (e.g. downloaded in the browser) to a run's snapshot."""
        path = supplied.resolve(strict=True)
        if not path.is_file():
            raise ValueError("add-file requires a regular file")
        root = self.artifact_root(run_id)
        if root is None:
            raise ValueError("no artifact root registered")
        name = re.sub(r"[^\w.-]", "_", supplied.name)[:60].lstrip(".") or "added.bin"
        directory = root / ".metis-added"
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink():
            raise ValueError("invalid snapshot directory")
        target = directory / name
        stem, suffix, counter = target.stem, target.suffix, 1
        while target.exists():
            counter += 1
            target = directory / f"{stem}-{counter}{suffix}"
        digest = hashlib.sha256()
        size = 0
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with (os.fdopen(descriptor, "wb") as stream,
                  artifact_stream(path.parent, path.name, max_bytes=MAX_FILE) as source):
                while chunk := source.read(1_048_576):
                    size += len(chunk)
                    if size > MAX_FILE:
                        raise ValueError("file exceeds the artifact limit")
                    digest.update(chunk)
                    stream.write(chunk)
        except (OSError, ValueError):
            target.unlink(missing_ok=True)
            raise
        relative = ".metis-added/" + target.name
        manifest = ChallengeManifest.model_validate_json(self._session(run_id)[0])
        data = manifest.model_dump()
        data["artifacts"] = [*manifest.artifacts, relative]
        updated = ChallengeManifest.model_validate(data)
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE codex_sessions SET manifest=? WHERE run_id=?",
                       (updated.model_dump_json(), run_id))
        return {"run_id": run_id, "ok": True, "artifact": relative, "size": size,
                "sha256": digest.hexdigest()}

    @locked
    def cancel(self, run_id: str) -> dict:
        context = self.context(run_id)
        worker = {"status": "not_running"}
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE codex_active_operations SET cancel_requested=1 WHERE run_id=?", (run_id,))
        if context["status"] not in {RunStatus.SOLVED.value, RunStatus.EXHAUSTED.value,
                                     RunStatus.ERROR.value, RunStatus.CANCELLED.value,
                                     RunStatus.POLICY_DENIED.value}:
            self._emit(run_id, RunStatus.CANCELLED)
        # The sandbox registers its container under this same run lock before
        # launch. Keep the lock while removing it so recovery cannot race teardown.
        from metis.core.ctf_sandbox import cancel_registered_worker
        worker = cancel_registered_worker(self.database, run_id)
        return self.context(run_id) | {"worker_teardown": worker}

    @locked
    def recover(self, run_id: str) -> dict:
        self._session(run_id)
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE codex_active_operations SET cancel_requested=1 WHERE run_id=?", (run_id,))
        # After a controller restart, never resume a run while its previous
        # sandbox might still be executing. An unconfirmed engine response is
        # a hard recovery stop; the operator must reconcile the worker first.
        from metis.core.ctf_sandbox import cancel_registered_worker
        worker = cancel_registered_worker(self.database, run_id)
        if worker["status"] == "unknown":
            raise RuntimeError("recovery blocked: sandbox worker teardown is unknown")
        # Revocation is persistent: an old caller must present its original ID
        # at launch/finalization and cannot adopt a later operation's identity.
        with sqlite3.connect(self.database) as db:
            db.execute("DELETE FROM codex_active_operations WHERE run_id=?", (run_id,))
        events = self.store.read(run_id)
        if not events:
            self._emit(run_id, RunStatus.NEW)
            events = self.store.read(run_id)
        status = events[-1].status
        routes = {
            RunStatus.NEW: (RunStatus.VALIDATED, RunStatus.CLASSIFIED, RunStatus.PLANNING),
            RunStatus.VALIDATED: (RunStatus.CLASSIFIED, RunStatus.PLANNING),
            RunStatus.CLASSIFIED: (RunStatus.PLANNING,),
            RunStatus.EXECUTING: (RunStatus.OBSERVING, RunStatus.REPLANNING, RunStatus.PLANNING),
            RunStatus.OBSERVING: (RunStatus.REPLANNING, RunStatus.PLANNING),
            RunStatus.VERIFYING: (RunStatus.REPLANNING, RunStatus.PLANNING),
            RunStatus.REPLANNING: (RunStatus.PLANNING,),
        }
        for state in routes.get(status, ()):
            self._emit(run_id, state, reason="interrupted_operation_discarded")
        context = self.context(run_id)
        if context["status"] == "planning" and (
            not context["actions_remaining"] or not context["seconds_remaining"]
        ):
            self._emit(run_id, RunStatus.EXHAUSTED, reason="budget_limit")
        return self.context(run_id) | {"worker_teardown": worker}

    def board(self, limit: int = 30) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError("board limit must be between 1 and 100")
        with sqlite3.connect(self.database) as db:
            ids = db.execute("SELECT run_id FROM codex_sessions ORDER BY started DESC LIMIT ?",
                             (limit,)).fetchall()
        output = []
        for (run_id,) in ids:
            try:
                context = self.context(run_id)
                output.append({key: context[key] for key in
                               ("run_id", "status", "actions_remaining", "seconds_remaining")} |
                              {"title": context["challenge"]["title"],
                               "categories": context["challenge"]["categories"]})
            except IndexError:
                output.append({"run_id": run_id, "status": "incomplete_start", "recoverable": True})
        return output

    def demo(self) -> list[dict]:
        contexts = []
        for category, encoding in (("crypto", "base64"), ("misc", "hex")):
            answer = "METIS{" + secrets.token_hex(16) + "}"
            payload = (base64.b64encode(answer.encode()).decode() if encoding == "base64"
                       else answer.encode().hex())
            identity = "codex-demo-" + secrets.token_hex(4)
            manifest = ChallengeManifest.model_validate({
                "challenge_id": identity, "title": f"Local {encoding} puzzle",
                "description": f"Decode the {encoding} data and submit its exact UTF-8 text: {payload}",
                "categories": [category],
                "scope": {"authorized": True, "granted_by": "local-demo-generator",
                          "challenge_id": identity},
            })
            contexts.append(self.start(manifest, commitment=hashlib.sha256(answer.encode()).hexdigest(),
                                       evaluation_split="practice"))
        return contexts


def _suffix(content: bytes) -> str:
    """Keep a recognisable extension so viewers and parsers pick the right format."""
    for magic, suffix in ((b"\xff\xd8\xff", ".jpg"), (b"\x89PNG\r\n\x1a\n", ".png"), (b"GIF8", ".gif"),
                          (b"PK\x03\x04", ".zip"), (b"%PDF", ".pdf"), (b"\x1f\x8b", ".gz")):
        if content.startswith(magic):
            return suffix
    return ".bin"

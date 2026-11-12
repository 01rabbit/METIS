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
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from metis.core.artifacts import artifact_stream
from metis.core.contracts import ChallengeManifest, RunEvent, RunStatus
from metis.core.ctf_artifacts import ARTIFACT_ERRORS, ARTIFACT_TOOLS, MAX_FILE, inspect_file
from metis.core.ctf_tools import DATA_TOOLS, transform
from metis.core.ctf_triage import triage
from metis.core.runtime import ToolRequest
from metis.core.store import RunStore

NATIVE_TOOLS = DATA_TOOLS


class CodexSession:
    def __init__(self, database: Path):
        database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database = database
        created = not database.exists()
        self.store = RunStore(database)
        if created:
            database.chmod(0o600)
        with sqlite3.connect(database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS codex_sessions (
                run_id TEXT PRIMARY KEY, manifest TEXT NOT NULL, commitment TEXT,
                started REAL NOT NULL, max_actions INTEGER NOT NULL,
                wall_seconds INTEGER NOT NULL)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(codex_sessions)")}
            if "artifact_root" not in columns:
                db.execute("ALTER TABLE codex_sessions ADD COLUMN artifact_root TEXT")

    def _emit(self, run_id: str, status: RunStatus, **detail: str) -> None:
        events = self.store.read(run_id)
        self.store.append(RunEvent(run_id=run_id, sequence=len(events),
                                   status=status, detail=detail))

    def start(self, manifest: ChallengeManifest, *, commitment: str | None = None,
              max_actions: int = 40, wall_seconds: int = 1200,
              artifact_root: Path | None = None) -> dict:
        manifest = ChallengeManifest.model_validate(manifest.model_dump())
        if manifest.artifacts and artifact_root is None:
            raise ValueError("artifact root is required for file challenges")
        root = str(artifact_root.resolve(strict=True)) if artifact_root is not None else None
        if root is not None and not Path(root).is_dir():
            raise ValueError("artifact root must be a directory")
        if commitment is not None and not re.fullmatch(r"[0-9a-f]{64}", commitment):
            raise ValueError("invalid SHA-256 verification commitment")
        if not 1 <= max_actions <= 1000 or not 1 <= wall_seconds <= 86_400:
            raise ValueError("invalid session budget")
        run_id = uuid4().hex
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO codex_sessions "
                       "(run_id, manifest, commitment, started, max_actions, wall_seconds, artifact_root) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)", (
                run_id, manifest.model_dump_json(), commitment, time.time(),
                max_actions, wall_seconds, root,
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
        manifest, commitment, started, max_actions, wall_seconds = self._session(run_id)
        events = self.store.read(run_id)
        used = sum(event.status == RunStatus.EXECUTING for event in events)
        return {
            "run_id": run_id, "status": events[-1].status.value,
            "challenge": json.loads(manifest), "tools": sorted(NATIVE_TOOLS),
            "artifact_tools": sorted(ARTIFACT_TOOLS),
            "triage": triage(ChallengeManifest.model_validate_json(manifest)),
            "network_tools": [],
            "verification_available": commitment is not None,
            "actions_remaining": max(0, max_actions - used),
            "seconds_remaining": max(0, round(started + wall_seconds - time.time())),
        }

    def _reserve(self, run_id: str, operation: str, **detail: str) -> None:
        context = self.context(run_id)
        if context["status"] != RunStatus.PLANNING.value:
            raise ValueError("session is not awaiting a decision")
        if not context["actions_remaining"] or not context["seconds_remaining"]:
            self._emit(run_id, RunStatus.EXHAUSTED, reason="budget_limit")
            raise ValueError("session budget exhausted")
        self._emit(run_id, RunStatus.EXECUTING, operation=operation, **detail)

    def act(self, run_id: str, request: ToolRequest) -> dict:
        request = ToolRequest.model_validate(request.model_dump())
        request.data.encode()  # Reject invalid Unicode before changing session state.
        self._reserve(run_id, "native_data_transform",
                      tool=request.tool if request.tool in NATIVE_TOOLS else "denied",
                      request_sha256=hashlib.sha256(request.model_dump_json().encode()).hexdigest())
        result = transform(request)
        self._emit(run_id, RunStatus.OBSERVING, tool_ok=str(result.ok).lower())
        self._emit(run_id, RunStatus.REPLANNING)
        self._emit(run_id, RunStatus.PLANNING)
        # Return data to Codex, but never persist decoded answers in evidence.
        return {"run_id": run_id, **result.model_dump()}

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

    def artifact(self, run_id: str, name: str, tool: str, options: dict | None = None) -> dict:
        manifest = ChallengeManifest.model_validate_json(self._session(run_id)[0])
        if name not in manifest.artifacts or tool not in ARTIFACT_TOOLS:
            raise ValueError("artifact or operation is outside the declared scope")
        with sqlite3.connect(self.database) as db:
            root = db.execute("SELECT artifact_root FROM codex_sessions WHERE run_id=?",
                              (run_id,)).fetchone()[0]
        if root is None:
            raise ValueError("no artifact root registered")
        self._reserve(run_id, "read_only_artifact_analysis", tool=tool)
        try:
            result = inspect_file(Path(root), name, tool, options)
            output = {"run_id": run_id, "ok": True, "result": result}
        except ARTIFACT_ERRORS as exc:
            output = {"run_id": run_id, "ok": False, "error": "artifact rejected or unsupported",
                      "error_type": type(exc).__name__}
        self._emit(run_id, RunStatus.OBSERVING, tool_ok=str(output["ok"]).lower())
        self._emit(run_id, RunStatus.REPLANNING)
        self._emit(run_id, RunStatus.PLANNING)
        return output

    def intake(self, *, title: str, description: str, paths: list[Path],
               categories: list[str] | None = None, commitment: str | None = None,
               max_actions: int = 80, wall_seconds: int = 3600) -> dict:
        if len(paths) > 32 or len(description.encode()) > 65_536:
            raise ValueError("intake limit exceeded")
        workspace = Path(tempfile.mkdtemp(prefix=".metis-artifacts-", dir=self.database.parent))
        try:
            copied = []
            total = 0
            for index, path in enumerate(paths):
                name = f"{index:02d}-" + re.sub(r"[^\w.-]", "_", path.name)[:40]
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
                              max_actions=max_actions, wall_seconds=wall_seconds)
        except (OSError, ValueError):
            shutil.rmtree(workspace)
            raise

    def derive(self, run_id: str, name: str, tool: str, options: dict | None = None) -> dict:
        if tool not in {"zip_read", "tar_read", "gzip", "zlib", "bzip2", "xz",
                        "base64_decode", "base32_decode", "hex_decode"}:
            raise ValueError("only bounded archive decoding can derive an artifact")
        observation = self.artifact(run_id, name, tool, options)
        if not observation["ok"]:
            return observation
        content = base64.b64decode(observation["result"]["base64"], validate=True)
        if len(content) > 1_048_576:
            raise ValueError("derived artifact exceeds one MiB")
        with sqlite3.connect(self.database) as db:
            root = db.execute("SELECT artifact_root FROM codex_sessions WHERE run_id=?",
                              (run_id,)).fetchone()[0]
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                os.mkdir(".metis-derived", mode=0o700, dir_fd=directory)
            except FileExistsError:
                pass
            output_directory = os.open(".metis-derived", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                       dir_fd=directory)
        finally:
            os.close(directory)
        filename = uuid4().hex + ".bin"
        try:
            descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=output_directory)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
        finally:
            os.close(output_directory)
        relative = ".metis-derived/" + filename
        manifest = ChallengeManifest.model_validate_json(self._session(run_id)[0])
        data = manifest.model_dump()
        data["artifacts"] = [*manifest.artifacts, relative]
        updated = ChallengeManifest.model_validate(data)
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE codex_sessions SET manifest=? WHERE run_id=?",
                       (updated.model_dump_json(), run_id))
        return {"run_id": run_id, "ok": True, "artifact": relative,
                "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}

    def cancel(self, run_id: str) -> dict:
        context = self.context(run_id)
        if context["status"] not in {RunStatus.SOLVED.value, RunStatus.EXHAUSTED.value,
                                     RunStatus.ERROR.value, RunStatus.CANCELLED.value,
                                     RunStatus.POLICY_DENIED.value}:
            self._emit(run_id, RunStatus.CANCELLED)
        return self.context(run_id)

    def recover(self, run_id: str) -> dict:
        self._session(run_id)
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
        return self.context(run_id)

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
            contexts.append(self.start(manifest, commitment=hashlib.sha256(answer.encode()).hexdigest()))
        return contexts

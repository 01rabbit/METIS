"""Codex supplies reasoning; these commands provide bounded data tools and evidence."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from metis.core.contracts import ChallengeManifest, RunEvent, RunStatus
from metis.core.runtime import ToolRequest, ToolResult
from metis.core.store import RunStore

NATIVE_TOOLS = frozenset({"base64_decode", "hex_decode", "sha256"})


def transform(request: ToolRequest) -> ToolResult:
    """Only bounded builtin data transforms. Never interpret data as code or a path."""
    request = ToolRequest.model_validate(request.model_dump())
    if request.tool not in NATIVE_TOOLS:
        return ToolResult(ok=False, output="tool denied")
    if len(request.data.encode()) > 65_536:
        return ToolResult(ok=False, output="input exceeds limit")
    try:
        if request.tool == "base64_decode":
            output = base64.b64decode(request.data, validate=True).decode()
        elif request.tool == "hex_decode":
            output = bytes.fromhex(request.data).decode()
        else:
            output = hashlib.sha256(request.data.encode()).hexdigest()
    except (ValueError, UnicodeError, binascii.Error):
        return ToolResult(ok=False, output="invalid transform input")
    return ToolResult(ok=True, output=output)


class CodexSession:
    def __init__(self, database: Path):
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

    def _emit(self, run_id: str, status: RunStatus, **detail: str) -> None:
        events = self.store.read(run_id)
        self.store.append(RunEvent(run_id=run_id, sequence=len(events),
                                   status=status, detail=detail))

    def start(self, manifest: ChallengeManifest, *, commitment: str | None = None,
              max_actions: int = 40, wall_seconds: int = 1200) -> dict:
        manifest = ChallengeManifest.model_validate(manifest.model_dump())
        if manifest.artifacts or manifest.scope.allowed_endpoints:
            raise ValueError("Codex data-tool sessions accept inline local puzzles only")
        if commitment is not None and not re.fullmatch(r"[0-9a-f]{64}", commitment):
            raise ValueError("invalid SHA-256 verification commitment")
        if not 1 <= max_actions <= 1000 or not 1 <= wall_seconds <= 86_400:
            raise ValueError("invalid session budget")
        run_id = uuid4().hex
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO codex_sessions VALUES (?, ?, ?, ?, ?, ?)", (
                run_id, manifest.model_dump_json(), commitment, time.time(),
                max_actions, wall_seconds,
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
            "verification_available": commitment is not None,
            "actions_remaining": max(0, max_actions - used),
            "seconds_remaining": max(0, round(started + wall_seconds - time.time())),
        }

    def _reserve(self, run_id: str, operation: str) -> None:
        context = self.context(run_id)
        if context["status"] != RunStatus.PLANNING.value:
            raise ValueError("session is not awaiting a decision")
        if not context["actions_remaining"] or not context["seconds_remaining"]:
            self._emit(run_id, RunStatus.EXHAUSTED, reason="budget_limit")
            raise ValueError("session budget exhausted")
        self._emit(run_id, RunStatus.EXECUTING, operation=operation)

    def act(self, run_id: str, request: ToolRequest) -> dict:
        request = ToolRequest.model_validate(request.model_dump())
        request.data.encode()  # Reject invalid Unicode before changing session state.
        self._reserve(run_id, "native_data_transform")
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

    def cancel(self, run_id: str) -> dict:
        context = self.context(run_id)
        if context["status"] == RunStatus.PLANNING.value:
            self._emit(run_id, RunStatus.CANCELLED)
        return self.context(run_id)

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

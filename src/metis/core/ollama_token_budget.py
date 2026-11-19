"""Conservative, persistent token admission for a pinned local Ollama model.

Only raw text is accepted. Reservations are charged in full until the server
reports complete usage; an interrupted request is never refunded on restart.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from metis.core.run_lock import run_lock


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TokenBudget:
    """Atomic per-run reservations shared by parallel specialist processes."""

    def __init__(self, database: Path, run_id: str, limit: int):
        if not 1 <= limit <= 10_000_000:
            raise ValueError("invalid token limit")
        self.database, self.run_id, self.limit = database, run_id, limit

    @staticmethod
    def _table(db: sqlite3.Connection) -> None:
        db.execute("CREATE TABLE IF NOT EXISTS ollama_token_reservations ("
                   "id TEXT PRIMARY KEY, run_id TEXT NOT NULL, token_limit INTEGER NOT NULL, "
                   "reserved INTEGER NOT NULL, used INTEGER, state TEXT NOT NULL, "
                   "reported_input INTEGER, reported_output INTEGER, "
                   "prompt_sha256 TEXT NOT NULL, model_digest TEXT NOT NULL)")

    def reserve(self, amount: int, prompt_sha256: str, model_digest: str) -> str:
        if amount <= 0 or amount > self.limit:
            raise ValueError("request exceeds held-out token limit")
        with run_lock(self.database, self.run_id), sqlite3.connect(self.database) as db:
                db.execute("BEGIN IMMEDIATE")
                self._table(db)
                rows = db.execute("SELECT token_limit,reserved,used,state FROM ollama_token_reservations "
                                  "WHERE run_id=?", (self.run_id,)).fetchall()
                if any(row[0] != self.limit for row in rows):
                    raise ValueError("held-out token limit changed after first reservation")
                if any(row[3] == "invalid" for row in rows):
                    raise ValueError("held-out token ledger is invalid")
                charged = sum(row[2] if row[3] == "settled" else row[1] for row in rows)
                if charged + amount > self.limit:
                    raise ValueError("held-out token budget exhausted")
                reservation = uuid.uuid4().hex
                db.execute("INSERT INTO ollama_token_reservations VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (reservation, self.run_id, self.limit, amount, None, "reserved", None, None,
                            prompt_sha256, model_digest))
                return reservation

    def settle(self, reservation: str, used: int | None, *, valid: bool,
               reported_input: int | None = None, reported_output: int | None = None) -> None:
        with run_lock(self.database, self.run_id):
            with sqlite3.connect(self.database) as db:
                db.execute("BEGIN IMMEDIATE")
                self._table(db)
                row = db.execute("SELECT reserved,state FROM ollama_token_reservations "
                                 "WHERE id=? AND run_id=?", (reservation, self.run_id)).fetchone()
                if row is None or row[1] != "reserved":
                    raise ValueError("unknown or already settled token reservation")
                good = valid and type(used) is int and 0 <= used <= row[0]
                db.execute("UPDATE ollama_token_reservations SET state=?,used=?,"
                           "reported_input=?,reported_output=? WHERE id=?",
                           ("settled" if good else "invalid", used if good else None,
                            reported_input if type(reported_input) is int else None,
                            reported_output if type(reported_output) is int else None, reservation))
            if not good:
                raise ValueError("model usage missing or exceeds reserved tokens")


class PinnedOllama:
    """A raw-text local model request with exact pre-count and bounded output."""

    def __init__(self, *, model: str, model_digest: str, manifest: Path,
                 gguf: Path, gguf_sha256: str,
                 tokenizer: Path, tokenizer_sha256: str, context_tokens: int,
                 endpoint: str = "http://127.0.0.1:11434"):
        if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", model):
            raise ValueError("invalid model tag")
        if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in
               (model_digest, gguf_sha256, tokenizer_sha256)):
            raise ValueError("invalid digest")
        if endpoint != "http://127.0.0.1:11434":
            raise ValueError("only the local Ollama endpoint is allowed")
        if not 1 <= context_tokens <= 262_144:
            raise ValueError("invalid context size")
        if file_sha256(gguf) != gguf_sha256 or file_sha256(tokenizer) != tokenizer_sha256:
            raise ValueError("model or tokenizer file does not match pin")
        if manifest.stat().st_size > 1_000_000:
            raise ValueError("Ollama manifest does not match model digest")
        manifest_bytes = manifest.read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != model_digest:
            raise ValueError("Ollama manifest does not match model digest")
        manifest_data = json.loads(manifest_bytes)
        if not isinstance(manifest_data, dict) or not isinstance(manifest_data.get("layers"), list):
            raise TypeError("invalid Ollama manifest")
        layers = manifest_data["layers"]
        if any(not isinstance(row, dict) for row in layers):
            raise ValueError("invalid Ollama manifest layers")
        model_layers = [row for row in layers if row.get("mediaType") == "application/vnd.ollama.image.model"]
        if len(model_layers) != 1 or model_layers[0].get("digest") != "sha256:" + gguf_sha256:
            raise ValueError("pinned GGUF is not the Ollama manifest's model layer")
        self.model, self.model_digest, self.gguf = model, model_digest, gguf
        self.tokenizer, self.context_tokens, self.endpoint = tokenizer, context_tokens, endpoint
        self.manifest = manifest
        self.tokenizer_sha256 = tokenizer_sha256
        self.gguf_sha256 = gguf_sha256

    def _tags(self) -> list[dict[str, Any]]:
        with urllib.request.urlopen(self.endpoint + "/api/tags", timeout=10) as reply:
            return json.load(reply)["models"]

    def verify_model(self) -> None:
        if (file_sha256(self.manifest) != self.model_digest or
                file_sha256(self.gguf) != self.gguf_sha256 or
                file_sha256(self.tokenizer) != self.tokenizer_sha256):
            raise ValueError("pinned model or tokenizer changed")
        matches = [row for row in self._tags() if row.get("name") == self.model]
        if len(matches) != 1 or matches[0].get("digest") != self.model_digest:
            raise ValueError("Ollama model tag differs from pinned manifest")

    def count(self, prompt: str) -> int:
        encoded = prompt.encode("utf-8")
        if not encoded or len(encoded) > 64_000:
            raise ValueError("raw prompt must contain 1-64000 UTF-8 bytes")
        result = subprocess.run([str(self.tokenizer), "-m", str(self.gguf), "--stdin", "--show-count"],
                                input=encoded, capture_output=True, timeout=30, check=True)
        match = re.search(rb"Total number of tokens: ([0-9]+)\s*$", result.stdout)
        if match is None:
            raise ValueError("tokenizer did not return a count")
        return int(match.group(1))

    def generate(self, prompt: str, *, output_cap: int, budget: TokenBudget,
                 response_schema: dict[str, Any] | None = None,
                 timeout: float = 300.0) -> dict[str, Any]:
        if not 1 <= output_cap <= 4096:
            raise ValueError("output cap must be positive and bounded")
        self.verify_model()
        input_count = self.count(prompt)
        if input_count + output_cap > self.context_tokens:
            raise ValueError("request exceeds pinned context size")
        reservation = budget.reserve(input_count + output_cap,
                                     hashlib.sha256(prompt.encode()).hexdigest(), self.model_digest)
        try:
            # No chat endpoint, template, images, tools, context reuse, or stream.
            payload: dict[str, Any] = {"model": self.model, "prompt": prompt, "raw": True,
                                       "stream": False, "options": {"num_predict": output_cap,
                                                                       "num_ctx": self.context_tokens}}
            if response_schema is not None:
                payload["format"] = response_schema
            request = urllib.request.Request(self.endpoint + "/api/generate",
                     json.dumps(payload).encode(),
                     {"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=timeout) as reply:
                result = json.load(reply)
            if not isinstance(result, dict):
                raise TypeError("Ollama response is not an object")
        except BaseException:
            # A request may have reached the model. Keep the full reservation
            # charged and block the run after an unknown response.
            try:
                budget.settle(reservation, None, valid=False)
            except ValueError as exc:
                if str(exc) != "model usage missing or exceeds reserved tokens":
                    raise
            raise
        actual_input, actual_output = result.get("prompt_eval_count"), result.get("eval_count")
        valid = (type(actual_input) is int and type(actual_output) is int and
                 actual_input == input_count and 0 <= actual_output <= output_cap and
                 result.get("done") is True and isinstance(result.get("response"), str))
        measured: int | None = None
        if valid:
            assert isinstance(actual_input, int) and isinstance(actual_output, int)
            measured = actual_input + actual_output
        budget.settle(reservation, measured, valid=valid,
                      reported_input=actual_input, reported_output=actual_output)
        if not valid:
            raise ValueError("Ollama usage differs from pinned token admission")
        return result


class OllamaSpecialist:
    """Experimental tool-free specialist; mutable tags prohibit hard-cap studies."""

    model_turn_budget_enforced = True
    # Ollama dispatches by mutable tag. A concurrent tag swap can defeat the
    # pre-count before post-call reconciliation; keep real held-out calls closed.
    hard_token_budget_enforced = False

    def __init__(self, database: Path, run_id: str, engine: PinnedOllama, output_cap: int):
        from metis.evaluation.heldout_arm import binding

        bound = binding(database, run_id)
        if bound is None or bound.get("prompt_text") is None:
            raise ValueError("Ollama specialist requires a bound real-model held-out run")
        if bound["model_pin"] != engine.model:
            raise ValueError("Ollama model differs from bound protocol")
        self.engine, self.output_cap = engine, output_cap
        self.budget = TokenBudget(database, run_id, bound["budget"]["tokens"])

    def run(self, prompt: str, *, model: str | None, timeout: float,
            should_stop: Any = None, images: Any = None) -> Any:
        from metis.core.codex_specialist import DECISION_SCHEMA, CodexTurn

        if model != self.engine.model or images:
            return CodexTurn(returncode=1, message=None,
                             stderr_tail="Ollama specialist accepts only the pinned text model")
        if should_stop is not None and should_stop():
            return CodexTurn(returncode=1, message=None, stopped=True, stderr_tail="run stopped")
        try:
            result = self.engine.generate(prompt, output_cap=self.output_cap, budget=self.budget,
                                          response_schema=DECISION_SCHEMA, timeout=timeout)
        except (OSError, ValueError, TypeError, TimeoutError, json.JSONDecodeError) as exc:
            return CodexTurn(returncode=1, message=None, stderr_tail=str(exc)[:160],
                             isolation={"mode": "local-ollama-raw", "auth": "none"})
        return CodexTurn(returncode=0, message=result.get("response"),
                         usage={"input_tokens": result["prompt_eval_count"],
                                "output_tokens": result["eval_count"],
                                "cached_input_tokens": 0, "reasoning_output_tokens": 0},
                         isolation={"mode": "local-ollama-raw", "auth": "none"})

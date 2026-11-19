"""Token reservations and admission failure paths; no model or CTF calls."""
import hashlib
import io
import json
import multiprocessing
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from metis.core.ollama_token_budget import OllamaSpecialist, PinnedOllama, TokenBudget


def process_claim(database: str, result: multiprocessing.Queue) -> None:
    try:
        TokenBudget(Path(database), "run-1", 10).reserve(6, "p", "m")
        result.put(True)
    except ValueError:
        result.put(False)


def test_parallel_reservations_never_exceed_shared_cap(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite"
    def claim(_: int) -> bool:
        try:
            TokenBudget(database, "run-1", 10).reserve(6, "p", "m")
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(claim, range(2))) == 1
    # Reopening the database does not release a request whose process vanished.
    with pytest.raises(ValueError, match="exhausted"):
        TokenBudget(database, "run-1", 10).reserve(5, "p", "m")


def test_processes_share_one_persistent_cap(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    result = context.Queue()
    database = str(tmp_path / "state.sqlite")
    workers = [context.Process(target=process_claim, args=(database, result)) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)
        assert worker.exitcode == 0
    assert sorted([result.get(timeout=1), result.get(timeout=1)]) == [False, True]


def test_settlement_refunds_only_measured_usage_and_invalid_blocks(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite"
    budget = TokenBudget(database, "run-1", 10)
    first = budget.reserve(8, "p", "m")
    budget.settle(first, 3, valid=True)
    second = budget.reserve(7, "q", "m")
    with pytest.raises(ValueError, match="missing or exceeds"):
        budget.settle(second, 8, valid=True)
    with pytest.raises(ValueError, match="invalid"):
        TokenBudget(database, "run-1", 10).reserve(1, "r", "m")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT state FROM ollama_token_reservations WHERE id=?", (second,)).fetchone() == (
            "invalid",)


class Reply(io.BytesIO):
    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *_):  # type: ignore[no-untyped-def]
        self.close()


def engine(tmp_path: Path) -> PinnedOllama:
    gguf = tmp_path / "model.gguf"
    tokenizer = tmp_path / "tokenizer"
    manifest = tmp_path / "manifest"
    gguf.write_bytes(b"model")
    tokenizer.write_bytes(b"tokenizer")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    manifest.write_text(json.dumps({"layers": [{"mediaType": "application/vnd.ollama.image.model",
                                                "digest": "sha256:" + digest(gguf)}]}))
    return PinnedOllama(model="gemma4:12b", model_digest=digest(manifest), manifest=manifest,
                        gguf=gguf, gguf_sha256=digest(gguf), tokenizer=tokenizer,
                        tokenizer_sha256=digest(tokenizer), context_tokens=128)


def test_raw_request_reserves_before_dispatch_and_reconciles(tmp_path: Path, monkeypatch) -> None:
    pinned = engine(tmp_path)
    monkeypatch.setattr(pinned, "count", lambda prompt: 4)
    budget = TokenBudget(tmp_path / "state.sqlite", "run-1", 10)
    requests = []
    def reply(request, timeout):  # type: ignore[no-untyped-def]
        if isinstance(request, str):
            return Reply(json.dumps({"models": [{"name": pinned.model, "digest": pinned.model_digest}]}).encode())
        payload = json.loads(request.data)
        requests.append(payload)
        with sqlite3.connect(budget.database) as db:
            assert db.execute("SELECT reserved,state FROM ollama_token_reservations").fetchone() == (6, "reserved")
        return Reply(json.dumps({"done": True, "response": "OK", "prompt_eval_count": 4,
                                 "eval_count": 1}).encode())
    monkeypatch.setattr("metis.core.ollama_token_budget.urllib.request.urlopen", reply)
    result = pinned.generate("Reply OK.", output_cap=2, budget=budget)
    assert result["response"] == "OK"
    assert requests[0]["raw"] is True and requests[0]["stream"] is False
    assert requests[0]["options"]["num_predict"] == 2
    with sqlite3.connect(budget.database) as db:
        assert db.execute("SELECT used,state FROM ollama_token_reservations").fetchone() == (5, "settled")


@pytest.mark.parametrize("reply", [
    {"done": True, "prompt_eval_count": 3, "eval_count": 1},
    {"done": True, "prompt_eval_count": 4, "eval_count": 3},
    {"done": True, "prompt_eval_count": 4},
    [],
])
def test_usage_mismatch_blocks_future_dispatch(tmp_path: Path, monkeypatch, reply: object) -> None:
    pinned = engine(tmp_path)
    monkeypatch.setattr(pinned, "count", lambda prompt: 4)
    budget = TokenBudget(tmp_path / "state.sqlite", "run-1", 10)
    def server(request, timeout):  # type: ignore[no-untyped-def]
        if isinstance(request, str):
            return Reply(json.dumps({"models": [{"name": pinned.model, "digest": pinned.model_digest}]}).encode())
        return Reply(json.dumps(reply).encode())
    monkeypatch.setattr("metis.core.ollama_token_budget.urllib.request.urlopen", server)
    with pytest.raises((ValueError, TypeError)):
        pinned.generate("Reply OK.", output_cap=2, budget=budget)
    with pytest.raises(ValueError, match="invalid"):
        budget.reserve(1, "p", "m")
    if isinstance(reply, dict):
        with sqlite3.connect(budget.database) as db:
            assert db.execute("SELECT reported_input,reported_output FROM ollama_token_reservations").fetchone() == (
                reply.get("prompt_eval_count"), reply.get("eval_count"))


def test_changed_tag_rejected_before_token_reservation(tmp_path: Path, monkeypatch) -> None:
    pinned = engine(tmp_path)
    monkeypatch.setattr(pinned, "_tags", lambda: [{"name": pinned.model, "digest": "b" * 64}])
    with pytest.raises(ValueError, match="differs"):
        pinned.generate("Reply OK.", output_cap=2,
                        budget=TokenBudget(tmp_path / "state.sqlite", "run-1", 10))
    assert not (tmp_path / "state.sqlite").exists()


def test_unknown_server_response_stays_charged_and_blocks(tmp_path: Path, monkeypatch) -> None:
    pinned = engine(tmp_path)
    monkeypatch.setattr(pinned, "count", lambda prompt: 4)
    budget = TokenBudget(tmp_path / "state.sqlite", "run-1", 10)
    def server(request, timeout):  # type: ignore[no-untyped-def]
        if isinstance(request, str):
            return Reply(json.dumps({"models": [{"name": pinned.model, "digest": pinned.model_digest}]}).encode())
        raise TimeoutError("server response unavailable")
    monkeypatch.setattr("metis.core.ollama_token_budget.urllib.request.urlopen", server)
    with pytest.raises(TimeoutError):
        pinned.generate("Reply OK.", output_cap=2, budget=budget)
    with pytest.raises(ValueError, match="invalid"):
        TokenBudget(budget.database, "run-1", 10).reserve(1, "p", "m")


def test_mutable_ollama_tag_cannot_unlock_heldout_dispatch(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    from metis.core.codex_specialist import run_assignment

    assert OllamaSpecialist.hard_token_budget_enforced is False
    scheduler = SimpleNamespace(database=tmp_path / "state.sqlite",
                                config=lambda: {"catalog": [], "current_model": "gemma4:12b"})
    job = {"run_id": "run-1", "attempt_id": "attempt-1", "state": "running", "model": None}
    monkeypatch.setattr("metis.core.codex_specialist._job", lambda *args: job)
    monkeypatch.setattr("metis.evaluation.heldout_arm.binding", lambda *args: {
        "model_pin": "gemma4:12b", "prompt_text": "fixed prompt"})
    runner = SimpleNamespace(hard_token_budget_enforced=OllamaSpecialist.hard_token_budget_enforced,
                             run=lambda *args, **kwargs: pytest.fail("model dispatch must not occur"))
    with pytest.raises(ValueError, match="token cap is not enforceable"):
        run_assignment(scheduler, "run-1", "assignment-1", "attempt-1", runner)

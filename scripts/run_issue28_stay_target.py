"""Bounded, resumable Stage 2 experiment on the registered ksnctf #39 run.

This task-specific runner never prints candidate indices, keys, headers, or
plaintext. Run it only with the previously authorized official run and archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

from metis.core import ctf_zipcrypto as zc
from metis.core.codex_session import CodexSession

RUN_ID = "0045b063168045c289eaef276dab21c2"
ARTIFACT = "01-00-flag.zip"
ARCHIVE_SHA256 = "ff663a29abc5f0ded2c3456bc731b1b21329eb95914286733c40364624e5d8f5"
PROBE_WINDOW = 1 << 20
STAGE2_CHUNK = 1 << 23
GUESS_SPACE = 1 << 26
MAX_TASK_ACTIONS = 900
MAX_TASK_SECONDS = 7200
STAGE1_NAME = re.compile(r"[0-9a-f]{32}\.json")


def _write_private(path: Path, payload: dict[str, Any]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _private_stage1(database: Path, run_id: str, firsts: tuple[int, ...]) -> list[dict[str, Any]]:
    root = database.parent / "private-stay" / run_id
    if root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:
        raise ValueError("run-private Stage 1 directory unavailable")
    eligible = []
    for path in sorted(root.iterdir()):
        if not STAGE1_NAME.fullmatch(path.name):
            continue
        if (path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077
                or path.stat().st_size > 262_144):
            raise ValueError("unsafe Stage 1 shard")
        hits = json.loads(path.read_text(encoding="utf-8"))["hits"]
        for offset, (index, masks) in enumerate(hits):
            if (type(index) is not int or not 0 <= index < 1 << 40
                    or len(masks) != len(firsts)
                    or any(type(mask) is not int or not 1 <= mask <= 15 for mask in masks)):
                raise ValueError("invalid Stage 1 candidate")
            intervals = tuple(zc._stay_first_stage_key1_intervals(index, tuple(masks), firsts))
            if intervals:
                width = sum(upper - lower + 1 for (_high, lower, upper), _pairs in intervals)
                eligible.append({"shard": f"private-stay/{run_id}/{path.name}",
                                 "hit_index": offset, "width": width})
    return eligible


def _sample(eligible: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(eligible, key=lambda item: (item["width"], item["shard"], item["hit_index"]))
    positions = (0, 1, len(ordered) // 2 - 1, len(ordered) // 2,
                 len(ordered) - 4, len(ordered) - 3, len(ordered) - 2, len(ordered) - 1)
    return [ordered[position] for position in positions]


def _artifact_path(database: Path, run_id: str) -> Path:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT manifest,artifact_root FROM codex_sessions WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise ValueError("registered run unavailable")
    manifest = json.loads(row[0])
    if ARTIFACT not in manifest["artifacts"]:
        raise ValueError("official archive is not registered")
    root = database.parent / row[1]
    path = root / ARTIFACT
    if hashlib.sha256(path.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("official archive digest changed")
    return path


def _load_or_create(database: Path, eligible: list[dict[str, Any]]) -> tuple[Path, dict[str, Any]]:
    root = database.parent / "private-stay" / RUN_ID
    path = root / "target-progress.json"
    if path.exists():
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError("unsafe progress file")
        state = json.loads(path.read_text(encoding="utf-8"))
        if (state.get("run_id") != RUN_ID or state.get("archive_sha256") != ARCHIVE_SHA256
                or state.get("eligible") != eligible):
            raise ValueError("progress identity mismatch")
        return path, state
    state = {"run_id": RUN_ID, "archive_sha256": ARCHIVE_SHA256,
             "started_at": time.time(), "actions": 0, "eligible": eligible,
             "phase": "probe", "probe": [], "full_cursor": 0,
             "full_next_index": 0, "stage2_hits": [], "recovery": [], "inflight": None}
    _write_private(path, state)
    return path, state


def _check_budget(state: dict[str, Any], session: CodexSession) -> None:
    if state["inflight"] is not None:
        raise RuntimeError("in-flight action requires audit before resume")
    if time.time() >= state["started_at"] + MAX_TASK_SECONDS:
        raise RuntimeError("two-hour task budget reached")
    if state["actions"] >= MAX_TASK_ACTIONS:
        raise RuntimeError("task action budget reached")
    context = session.context(RUN_ID)
    if context["status"] != "planning" or context["seconds_remaining"] < 10:
        raise RuntimeError("run needs an authorized budget extension")
    if context["actions_remaining"] < 1:
        raise RuntimeError("run action budget exhausted")


def _operation_seconds(state: dict[str, Any], session: CodexSession) -> int:
    context = session.context(RUN_ID)
    phase_limit = 1800 if state["phase"] == "probe" else (
        5400 if state["phase"] == "scanning" else MAX_TASK_SECONDS)
    left = min(context["seconds_remaining"],
               int(state["started_at"] + phase_limit - time.time()), 300)
    if left < 10:
        raise RuntimeError("phase or run wall-time budget reached")
    return left


def _scan(session: CodexSession, path: Path, state: dict[str, Any],
          item: dict[str, Any], headers_hex: str, start: int, stop: int) -> dict[str, Any]:
    _check_budget(state, session)
    seconds = _operation_seconds(state, session)
    state["inflight"] = {"kind": "stage2", "shard": item["shard"],
                         "hit_index": item["hit_index"], "start": start, "stop": stop}
    _write_private(path, state)
    response = session.artifact(RUN_ID, ARTIFACT, "zipcrypto_stay_stage2", {
        "random_header_bytes_hex": headers_hex,
        "stage1_shard": item["shard"], "hit_index": item["hit_index"],
        "start": start, "stop": stop, "max_candidates": min(STAGE2_CHUNK, stop - start),
        "seconds": seconds, "max_hits": 4096})
    state["actions"] += 1
    if not isinstance(response, dict) or not response.get("ok"):
        raise RuntimeError("Stage 2 operation rejected")
    result = response.get("result")
    if not isinstance(result, dict):
        raise TypeError("Stage 2 result malformed")
    if (type(result.get("next_index")) is not int
            or not start < result["next_index"] <= stop):
        raise RuntimeError("Stage 2 did not advance")
    if result.get("reason") is not None:
        raise RuntimeError("Stage 2 worker failed")
    if (type(result.get("hits_count")) is not int or result["hits_count"] < 0
            or type(result.get("seconds")) not in (int, float)
            or result["seconds"] < 0
            or type(result.get("scanned")) is not int
            or result["scanned"] != result["next_index"] - start
            or type(result.get("complete")) is not bool
            or result["complete"] != (result["next_index"] == stop)):
        raise RuntimeError("Stage 2 result malformed")
    if bool(result.get("candidate_shard")) != (result["hits_count"] > 0):
        raise RuntimeError("Stage 2 shard count mismatch")
    if result.get("candidate_shard"):
        if not isinstance(result["candidate_shard"], str):
            raise RuntimeError("Stage 2 shard reference malformed")
        state["stage2_hits"].append({"shard": result["candidate_shard"],
                                     "hits_count": result["hits_count"]})
    return result


def _projection(records: list[dict[str, Any]], eligible_count: int) -> dict[str, float | int]:
    if not records or any(row["scanned"] <= 0 for row in records):
        raise ValueError("no usable probe records")
    slowest = max(row["seconds"] / row["scanned"] for row in records)
    stage2_seconds = 2 * slowest * eligible_count * GUESS_SPACE
    actions = eligible_count * (GUESS_SPACE // STAGE2_CHUNK)
    return {"conservative_stage2_seconds": round(stage2_seconds, 1),
            "stage2_actions": actions, "fits": stage2_seconds <= 5400 and actions <= 900}


def probe(session: CodexSession, path: Path, state: dict[str, Any], headers_hex: str) -> dict[str, Any]:
    if state["phase"] not in {"probe", "ready", "needs_optimization"}:
        raise RuntimeError("probe cannot run after the full scan has started")
    cases = _sample(state["eligible"])
    windows = ((0, PROBE_WINDOW),
               (GUESS_SPACE // 2 - PROBE_WINDOW // 2, GUESS_SPACE // 2 + PROBE_WINDOW // 2),
               (GUESS_SPACE - PROBE_WINDOW, GUESS_SPACE))
    done = {(row["sample"], row["start"]) for row in state["probe"]}
    for sample_id, item in enumerate(cases):
        for start, stop in windows:
            if (sample_id, start) in done:
                continue
            result = _scan(session, path, state, item, headers_hex, start, stop)
            state["probe"].append({"sample": sample_id, "start": start,
                                   "scanned": result["next_index"] - start,
                                   "seconds": result["seconds"],
                                   "hits_count": result["hits_count"]})
            state["inflight"] = None
            _write_private(path, state)
            if result["next_index"] != stop:
                raise RuntimeError("probe window incomplete; inspect private progress")
            if time.time() >= state["started_at"] + 1800:
                raise RuntimeError("30-minute probe cap reached")
    projection = _projection(state["probe"], len(state["eligible"]))
    state["phase"] = "ready" if projection["fits"] else "needs_optimization"
    _write_private(path, state)
    return {"eligible_hits": len(state["eligible"]), "probes": len(state["probe"]),
            "scanned": sum(row["scanned"] for row in state["probe"]),
            "hits": sum(row["hits_count"] for row in state["probe"]), **projection}


def _recover(session: CodexSession, path: Path, state: dict[str, Any],
             headers_hex: str) -> dict[str, Any]:
    state.setdefault("recovery_cursor", 0)
    state.setdefault("recovery_product", 0)
    state.setdefault("recovery_extra", 0)
    while state["recovery_cursor"] < len(state["stage2_hits"]):
        _check_budget(state, session)
        seconds = _operation_seconds(state, session)
        ref = state["stage2_hits"][state["recovery_cursor"]]["shard"]
        if not isinstance(ref, str) or not re.fullmatch(
                rf"private-stay/{RUN_ID}/s2-[0-9a-f]{{32}}\.json", ref):
            raise ValueError("invalid Stage 2 shard reference")
        shard = session.database.parent / ref
        if (shard.is_symlink() or not shard.is_file() or shard.stat().st_mode & 0o077
                or shard.stat().st_size > 262_144):
            raise ValueError("unsafe Stage 2 shard")
        hits = json.loads(shard.read_text(encoding="utf-8"))["hits"]
        state.setdefault("recovery_hit_index", 0)
        if state["recovery_hit_index"] >= len(hits):
            state["recovery_cursor"] += 1
            state["recovery_hit_index"] = 0
            state["recovery_product"] = state["recovery_extra"] = 0
            _write_private(path, state)
            continue
        old = (state["recovery_product"], state["recovery_extra"])
        state["inflight"] = {"kind": "recover", "stage2_ordinal": state["recovery_cursor"],
                             "hit_index": state["recovery_hit_index"],
                             "start_product": old[0], "start_extra": old[1]}
        _write_private(path, state)
        response = session.artifact(RUN_ID, ARTIFACT, "zipcrypto_stay_recover", {
            "random_header_bytes_hex": headers_hex, "stage2_shard": ref,
            "hit_index": state["recovery_hit_index"],
            "start_product": old[0], "start_extra": old[1],
            "max_products": 4, "max_candidates": 1 << 26,
            "seconds": seconds, "max_hits": 1})
        state["actions"] += 1
        if not isinstance(response, dict) or not response.get("ok"):
            raise RuntimeError("recovery operation rejected")
        result = response.get("result")
        if not isinstance(result, dict) or type(result.get("keys_count")) is not int:
            raise RuntimeError("recovery result malformed")
        if result.get("keys_count", 0):
            key_ref = result.get("key_shard")
            if not isinstance(key_ref, str) or not re.fullmatch(
                    rf"private-stay/{RUN_ID}/k-[0-9a-f]{{32}}\.json", key_ref):
                raise RuntimeError("recovery key shard missing")
            key_path = session.database.parent / key_ref
            key_root = key_path.parent
            if (key_root.is_symlink() or not key_root.is_dir()
                    or key_root.stat().st_mode & 0o077
                    or key_path.is_symlink() or not key_path.is_file()
                    or key_path.stat().st_mode & 0o077
                    or key_path.stat().st_size > 262_144):
                raise RuntimeError("recovery key shard unsafe")
            key_data = json.loads(key_path.read_text(encoding="utf-8"))
            keys = key_data.get("keys") if isinstance(key_data, dict) else None
            if (not isinstance(keys, list) or len(keys) != result["keys_count"]
                    or any(not isinstance(row, list) or len(row) != 3
                           or any(type(value) is not int or not 0 <= value < 1 << 32
                                  for value in row) for row in keys)):
                raise RuntimeError("recovery key shard malformed")
            state["key_shard"] = key_ref
            state["phase"] = "key_found"
            state["inflight"] = None
            _write_private(path, state)
            return {"phase": "key_found", "actions": state["actions"], "keys_count": result["keys_count"]}
        if result.get("reason") == "complete":
            state["recovery_hit_index"] += 1
            state["recovery_product"] = state["recovery_extra"] = 0
        elif result.get("reason") in {"candidate_limit", "time_limit"}:
            new = (result.get("next_product"), result.get("next_extra"))
            if (type(new[0]) is not int or type(new[1]) is not int or new <= old):
                raise RuntimeError("recovery cursor did not advance")
            state["recovery_product"], state["recovery_extra"] = new
        else:
            raise RuntimeError("recovery stopped without a complete result")
        state["inflight"] = None
        _write_private(path, state)
    state["phase"] = "no_key"
    _write_private(path, state)
    return {"phase": "no_key", "actions": state["actions"],
            "stage2_shards": len(state["stage2_hits"])}


def full(session: CodexSession, path: Path, state: dict[str, Any],
         headers_hex: str) -> dict[str, Any]:
    if state["phase"] not in {"ready", "scanning", "recovering", "key_found", "no_key"}:
        raise RuntimeError("probe has not established the bounded full-scan gate")
    if state["phase"] in {"key_found", "no_key"}:
        return {"phase": state["phase"], "actions": state["actions"],
                "stage2_shards": len(state["stage2_hits"])}
    if state["phase"] in {"ready", "scanning"}:
        state["phase"] = "scanning"
        _write_private(path, state)
        while state["full_cursor"] < len(state["eligible"]):
            if time.time() >= state["started_at"] + 5400:
                raise RuntimeError("90-minute Stage 2 scan cap reached")
            item = state["eligible"][state["full_cursor"]]
            start = state["full_next_index"]
            stop = min(GUESS_SPACE, start + STAGE2_CHUNK)
            result = _scan(session, path, state, item, headers_hex, start, stop)
            state["full_next_index"] = result["next_index"]
            if state["full_next_index"] == GUESS_SPACE:
                state["full_cursor"] += 1
                state["full_next_index"] = 0
            state["inflight"] = None
            _write_private(path, state)
        state["phase"] = "recovering"
        _write_private(path, state)
    return _recover(session, path, state, headers_hex)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--mode", choices=("probe", "full"), required=True)
    args = parser.parse_args()
    database = args.database.resolve(strict=True)
    archive = _artifact_path(database, RUN_ID)
    seed = zc.infozip_seed(archive.read_bytes(), seconds=120)
    if seed.get("found") is not True or len(seed.get("random_header_bytes", [])) != 7:
        raise RuntimeError("official header observations unavailable")
    headers = tuple(bytes.fromhex(value) for value in seed["random_header_bytes"])
    eligible = _private_stage1(database, RUN_ID, tuple(header[0] for header in headers))
    if len(eligible) != 88:
        raise RuntimeError("Stage 1 eligible hit count changed")
    path, state = _load_or_create(database, eligible)
    session = CodexSession(database)
    if args.mode == "probe":
        print(json.dumps(probe(session, path, state, b"".join(headers).hex()), sort_keys=True))
    else:
        print(json.dumps(full(session, path, state, b"".join(headers).hex()), sort_keys=True))


if __name__ == "__main__":
    main()

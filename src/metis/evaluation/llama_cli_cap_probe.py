"""Answer-free compatibility probe for a local llama.cpp hard token cap.

This does not grant the held-out hard-cap capability. Missing or inconsistent
usage telemetry or a chat wrapper makes pre-call admission unproven.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_COMPLETION_LIMIT = 1
_USAGE_FIELDS = {"prompt_tokens", "completion_tokens"}
type _FileIdentity = tuple[int, int, int, int, int, int]


def _identity(info: os.stat_result) -> _FileIdentity:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _snapshot(path: Path) -> tuple[_FileIdentity, str]:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("probe inputs must be regular files")
        remaining = before.st_size
        while remaining:
            chunk = stream.read(min(remaining, 1024 * 1024))
            if not chunk:
                raise ValueError("probe input changed during hashing")
            digest.update(chunk)
            remaining -= len(chunk)
        identity = _identity(before)
        if _identity(os.fstat(stream.fileno())) != identity:
            raise ValueError("probe input changed during hashing")
    return identity, digest.hexdigest()


def _require_file_identities(snapshots: dict[Path, tuple[_FileIdentity, str]]) -> None:
    try:
        unchanged = all(_identity(path.stat(follow_symlinks=False)) == identity
                        for path, (identity, _) in snapshots.items())
    except OSError:
        unchanged = False
    if not unchanged:
        raise ValueError("probe input changed during execution")


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("duplicate JSON field")
    return fields


def _contains_usage_fields(values: Iterable[object]) -> bool:
    pending = list(values)
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if not _USAGE_FIELDS.isdisjoint(value):
                return True
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return False


def assess_cli_output(stdout: str, stderr: str, *, precount_tokens: int,
                      returncode: int) -> dict[str, Any]:
    """Check reported usage against the precount, request, and process exit."""
    output = stdout + "\n" + stderr
    records = []
    malformed_usage = False
    for line in output.splitlines():
        try:
            item = json.loads(line, object_pairs_hook=_unique_fields)
        except json.JSONDecodeError:
            if '"prompt_tokens"' in line or '"completion_tokens"' in line:
                malformed_usage = True
            continue
        except (ValueError, RecursionError):
            # Ambiguous or excessively nested JSON cannot be cleared of usage keys.
            malformed_usage = True
            continue
        if isinstance(item, dict):
            if not _USAGE_FIELDS.isdisjoint(item):
                records.append(item)
            if _contains_usage_fields(item.values()):
                malformed_usage = True
        elif isinstance(item, list) and _contains_usage_fields(item):
            malformed_usage = True

    prompt_tokens = completion_tokens = None
    if len(records) == 1 and not malformed_usage:
        prompt = records[0].get("prompt_tokens")
        completion = records[0].get("completion_tokens")
        if type(prompt) is int and prompt >= 0 and type(completion) is int and completion >= 0:
            prompt_tokens, completion_tokens = prompt, completion
    chat_wrapper = "available commands:" in output or bool(re.search(r"(?m)^> ", output))
    compatible = (returncode == 0 and not chat_wrapper and prompt_tokens == precount_tokens
                  and completion_tokens is not None and completion_tokens <= _COMPLETION_LIMIT)
    return {"usage_protocol_compatible": compatible,
            "chat_wrapper_observed": chat_wrapper,
            "usage_observed": prompt_tokens is not None,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens}


def probe(model: Path, cli: Path, tokenizer: Path, *, timeout: int = 30) -> dict[str, Any]:
    """Run one harmless one-token probe; store only hashes and aggregate counts."""
    if not 1 <= timeout <= 120:
        raise ValueError("timeout must be 1..120 seconds")
    model, cli, tokenizer = (path.resolve(strict=True) for path in (model, cli, tokenizer))
    snapshots = {path: _snapshot(path) for path in (model, cli, tokenizer)}

    prompt = "Hello"
    # Use a fixed locale for the tokenizer count and no ambient runtime settings.
    environment = {"LC_ALL": "C"}
    _require_file_identities(snapshots)
    try:
        counted = subprocess.run([str(tokenizer), "-m", str(model), "-p", prompt, "--show-count"],
                                 stdin=subprocess.DEVNULL, capture_output=True, env=environment,
                                 timeout=timeout, check=True)
    finally:
        _require_file_identities(snapshots)
    match = re.search(rb"Total number of tokens: ([0-9]+)\s*$", counted.stdout)
    if match is None:
        raise ValueError("tokenizer count missing")
    precount_tokens = int(match.group(1))
    command = [str(cli), "-m", str(model), "-p", prompt, "-n", str(_COMPLETION_LIMIT), "-c", "256",
               "--single-turn", "--no-context-shift", "--no-warmup", "--simple-io",
               "--no-display-prompt", "--verbose-prompt", "--temp", "0", "--log-jsonl"]
    _require_file_identities(snapshots)
    try:
        generated = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                   env=environment, timeout=timeout, check=False)
    finally:
        _require_file_identities(snapshots)
    try:
        stdout = generated.stdout.decode("utf-8")
        stderr = generated.stderr.decode("utf-8")
    except UnicodeDecodeError:
        # A malformed stream cannot support a compatible usage observation.
        stdout = stderr = ""
    observed = assess_cli_output(stdout, stderr, precount_tokens=precount_tokens,
                                 returncode=generated.returncode)
    return {"model_sha256": snapshots[model][1], "cli_sha256": snapshots[cli][1],
            "tokenizer_sha256": snapshots[tokenizer][1], "precount_tokens": precount_tokens,
            "cli_returncode": generated.returncode, **observed,
            # This does not prove immutable model routing, trusted accounting,
            # or a shared pre-call reservation boundary.
            "strict_cap_ready": False}

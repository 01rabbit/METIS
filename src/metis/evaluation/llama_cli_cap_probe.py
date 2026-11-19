"""Answer-free compatibility probe for a local llama.cpp hard token cap.

This does not grant the held-out hard-cap capability. A missing machine-readable
prompt/output count or a chat wrapper makes pre-call admission unproven.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assess_cli_output(stdout: str, stderr: str) -> dict[str, Any]:
    """Accept only explicit integer prompt/output usage from a non-chat response."""
    records: list[dict[str, Any]] = []
    for line in (stdout + "\n" + stderr).splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    usage = [item for item in records if type(item.get("prompt_tokens")) is int
             and type(item.get("completion_tokens")) is int]
    chat_wrapper = "available commands:" in stdout or bool(re.search(r"(?m)^> ", stdout))
    return {"strict_cap_ready": len(usage) == 1 and not chat_wrapper,
            "chat_wrapper_observed": chat_wrapper,
            "usage_observed": len(usage) == 1,
            "prompt_tokens": usage[0]["prompt_tokens"] if len(usage) == 1 else None,
            "completion_tokens": usage[0]["completion_tokens"] if len(usage) == 1 else None}


def probe(model: Path, cli: Path, tokenizer: Path, *, timeout: int = 30) -> dict[str, Any]:
    """Run one harmless one-token probe; store only hashes and aggregate counts."""
    if not 1 <= timeout <= 120:
        raise ValueError("timeout must be 1..120 seconds")
    for path in (model, cli, tokenizer):
        if not path.is_file():
            raise ValueError("model and binaries must be existing files")
    prompt = "Hello"
    counted = subprocess.run([str(tokenizer), "-m", str(model), "--stdin", "--show-count"],
                             input=prompt.encode(), capture_output=True, timeout=timeout, check=True)
    match = re.search(rb"Total number of tokens: ([0-9]+)\s*$", counted.stdout)
    if match is None:
        raise ValueError("tokenizer count missing")
    command = [str(cli), "-m", str(model), "-p", prompt, "-n", "1", "-c", "256",
               "--single-turn", "--no-context-shift", "--no-warmup", "--simple-io",
               "--no-display-prompt", "--verbose-prompt", "--temp", "0", "--log-jsonl"]
    generated = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    observed = assess_cli_output(generated.stdout, generated.stderr)
    return {"model_sha256": sha256(model), "cli_sha256": sha256(cli),
            "tokenizer_sha256": sha256(tokenizer), "precount_tokens": int(match.group(1)),
            "cli_returncode": generated.returncode, **observed,
            "strict_cap_ready": generated.returncode == 0 and observed["strict_cap_ready"]
            and observed["prompt_tokens"] == int(match.group(1))
            and observed["completion_tokens"] <= 1}

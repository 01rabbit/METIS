#!/usr/bin/env python3
"""Refuse private state, secrets and live answers before they reach Git.

``--staged`` checks the index snapshot (the pre-commit hook); without it every tracked and
untracked-but-not-ignored file is checked. Findings name the path and the rule, never the value.
Set ``METIS_DENY_PATTERN`` to a regular expression to also refuse private identifiers
(for example team or host names) in paths and contents.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from metis.core.answer_vault import ANSWER, EXAMPLE

PRIVATE_PATH = re.compile(
    r"(^|/)(?:\.metis-state|\.metis-cache|\.metis-artifacts-[^/]*|\.metis-web-stage-[^/]*|runs|artifacts)(?:/|$)"
    r"|(?:\.jsonl|\.sqlite3?(?:-wal|-shm)?|\.db(?:-wal|-shm)?|\.ovpn|\.key|\.pem|\.p12|\.pfx|\.kdbx)$"
    r"|(^|/)\.env(?:\.(?!example$)[^/]*)?$|(^|/)answers\.json$|(^|/)id_(?:rsa|ecdsa|ed25519)$")
SECRET = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    rb"|\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}|\bxox[baprs]-[A-Za-z0-9-]{20,}"
    rb"|\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{32,}|\bAIza[0-9A-Za-z_-]{35}\b")
# Tests and the synthetic practice generators create local placeholder answers; elsewhere none.
ANSWER_EXEMPT = re.compile(r"^(?:tests/|src/metis/core/(?:answer_vault|ctf_practice|fixtures)\.py$"
                           r"|scripts/(?:check_repo|mock_ctf)\.py$)")


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def _paths(staged: bool) -> list[str]:
    if staged:
        out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    else:
        out = _git("ls-files", "-c", "-o", "--exclude-standard", "-z")
    return sorted({item for item in out.decode().split("\0") if item})


def _content(path: str, staged: bool) -> bytes | None:
    if staged:
        return _git("show", ":" + path)
    target = ROOT / path
    if target.is_symlink():
        return os.readlink(target).encode()
    if not target.is_file():
        return None
    return target.read_bytes()


def check(staged: bool = False) -> list[str]:
    errors: list[str] = []
    deny = os.environ.get("METIS_DENY_PATTERN")
    paths = _paths(staged)
    for path in paths:
        if PRIVATE_PATH.search(path):
            errors.append(f"private or runtime path: {path}")
        data = _content(path, staged)
        if data is None:
            continue
        if staged:
            work = _content(path, False)
            if work is not None and work != data:
                errors.append(f"staged snapshot differs from the worktree (check what is committed): {path}")
        if SECRET.search(data):
            errors.append(f"secret-shaped content: {path}")
        text = data.decode("utf-8", errors="replace")
        if not ANSWER_EXEMPT.search(path):
            live = [match.group(0) for match in ANSWER.finditer(text) if not EXAMPLE.fullmatch(match.group(0))]
            if live:
                errors.append(f"answer-shaped content ({len(live)}); move it with `metis` answer vault: {path}")
        if deny and (re.search(deny, path, re.IGNORECASE) or re.search(deny, text, re.IGNORECASE)):
            errors.append(f"prohibited identifier: {path}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="check the index (pre-commit hook)")
    args = parser.parse_args(argv)
    errors = check(args.staged)
    for error in errors:
        print(error, file=sys.stderr)
    print(json.dumps({"status": "failed" if errors else "passed", "findings": len(errors)}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

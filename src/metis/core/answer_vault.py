"""Answer vault: keep solved flags out of write-ups, Git and MUNIN (Issue #15).

Write-ups stay in the repository as reusable analysis. The exact answers they used to
contain (flags, accepted candidates) move to a vault file outside the repository, by
default ``$XDG_DATA_HOME/metis/answers.json`` (``~/.local/share/metis/answers.json``), mode
0600. In the Markdown each value is replaced by a reference such as
``⟦answer:ksnctf/8-basic-is-secure.md#1⟧``.

* Nothing is lost: values are written to the vault and read back before any file changes,
  and ``restore`` puts them back. Git history is not rewritten.
* Codex specialists cannot read the vault (their turns cannot read the home directory, #16);
  Claude subagents are told not to and the Claude Code integration ships a deny rule.
* MUNIN never reads the vault.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

ANSWER = re.compile(r"FLAG_[A-Za-z0-9_]{6,}(?:\{[^{}\r\n]{1,200}\})?|(?:Alpaca|FLAG|flag|CTF|ctf)\{[^{}\r\n]{1,200}\}")
PLACEHOLDER = re.compile(r"⟦answer:([^⟧]{1,240})⟧")
# Format examples in prose ("FLAG_XXXXXXXX", "Alpaca{...}") are not answers.
EXAMPLE = re.compile(r"(?:FLAG_[Xx_*.]+|[A-Za-z]+\{(?:\.\.\.|…|x+|X+|[*]+)\})")
TEXT_SUFFIXES = {".md", ".txt", ".py", ".json", ".sh", ".c", ".js", ".html", ".sage", ".lean", ".payload", ".rb",
                 ".go", ".rs", ".cpp", ".h", ".yaml", ".yml", ".csv"}


def default_vault() -> Path:
    configured = os.environ.get("METIS_ANSWER_VAULT")
    if configured:
        return Path(configured)
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "metis" / "answers.json"


def is_answer(value: str) -> bool:
    return bool(ANSWER.fullmatch(value)) and not EXAMPLE.fullmatch(value)


class AnswerVault:
    def __init__(self, path: Path | None = None):
        self.path = path or default_vault()

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("answer vault is not a JSON object")
        return data

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(temporary, self.path)

    def put_many(self, entries: dict[str, dict[str, Any]]) -> None:
        """Add entries; an existing key with a different value is kept and the new one is appended."""
        data = self.load()
        for key, entry in entries.items():
            current = data.get(key)
            if current is None or current.get("value") == entry["value"]:
                data[key] = {**(current or {}), **entry}
            else:
                alternates = current.setdefault("alternates", [])
                if entry["value"] not in alternates:
                    alternates.append(entry["value"])
        self._write(data)
        stored = self.load()
        missing = [key for key, entry in entries.items() if entry["value"] not in
                   [stored.get(key, {}).get("value"), *stored.get(key, {}).get("alternates", [])]]
        if missing:
            raise RuntimeError(f"answer vault verification failed for {len(missing)} entries")

    def get(self, key: str) -> str | None:
        entry = self.load().get(key)
        return None if entry is None else entry.get("value")


def redact(text: str, key_prefix: str, *, start: int = 1) -> tuple[str, dict[str, dict[str, Any]]]:
    """Replace answers in ``text`` with vault references; return the new text and the entries."""
    entries: dict[str, dict[str, Any]] = {}
    counter = start
    seen: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        nonlocal counter
        value = match.group(0)
        if EXAMPLE.fullmatch(value):
            return value
        if value not in seen:
            key = f"{key_prefix}#{counter}"
            counter += 1
            seen[value] = key
            line = text.count("\n", 0, match.start()) + 1
            entries[key] = {"value": value, "source": key_prefix, "line": line, "recorded": time.time()}
        return f"⟦answer:{seen[value]}⟧"

    return ANSWER.sub(replace, text), entries


def encoded_forms(value: str) -> list[str]:
    """Substrings that reveal ``value`` inside hex or Base64 text (at any byte alignment).

    A Basic-auth token or a JSON dump can carry the answer without its flag format; the
    stable core of each encoding is enough to find (and reversibly replace) it.
    """
    raw = value.encode()
    forms = [raw.hex()]
    for pad in range(3):
        encoded = base64.b64encode(b"\0" * pad + raw).decode().rstrip("=")
        start = -(-(pad * 4) // 3) + (1 if pad else 0)
        core = encoded[start:len(encoded) - 3]
        if len(core) >= 12:
            forms.append(core)
    return forms


def _redact_encoded(text: str, values: set[str], key_prefix: str, start: int) -> tuple[str, dict[str, dict[str, Any]]]:
    entries: dict[str, dict[str, Any]] = {}
    counter = start
    for value in sorted(values):
        for form in encoded_forms(value):
            if form not in text:
                continue
            key = f"{key_prefix}#enc{counter}"
            counter += 1
            line = text.count("\n", 0, text.index(form)) + 1
            entries[key] = {"value": form, "source": key_prefix, "line": line, "recorded": time.time(),
                            "kind": "encoded"}
            text = text.replace(form, f"⟦answer:{key}⟧")
    return text, entries


def scan(roots: list[Path], base: Path) -> list[tuple[Path, str]]:
    found = []
    for root in roots:
        candidates = [root] if root.is_file() else sorted(path for path in root.rglob("*") if path.is_file())
        for path in candidates:
            if path.suffix.lower() not in TEXT_SUFFIXES and path.suffix:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if any(not EXAMPLE.fullmatch(match.group(0)) for match in ANSWER.finditer(text)):
                found.append((path, path.resolve().relative_to(base.resolve()).as_posix()))
    return found


def migrate(roots: list[Path], base: Path, vault: AnswerVault, *, apply: bool = False) -> dict[str, Any]:
    """Move answers from files under ``roots`` into the vault. Dry run unless ``apply``."""
    plan: list[dict[str, Any]] = []
    pending: dict[str, dict[str, Any]] = {}
    rewritten: dict[Path, str] = {}
    for path, relative in scan(roots, base):
        text = path.read_text(encoding="utf-8")
        existing = len(PLACEHOLDER.findall(text))
        rewritten[path], entries = redact(text, relative, start=existing + 1)
        plan.append({"file": relative, "answers": len(entries)})
        pending.update(entries)
    # Second pass: hex/Base64 forms of every known answer (this run's and the vault's).
    values = {entry["value"] for entry in pending.values()}
    values |= {entry["value"] for entry in vault.load().values() if entry.get("kind") != "encoded"}
    for root in roots:
        for path in ([root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())):
            if path.suffix.lower() not in TEXT_SUFFIXES and path.suffix:
                continue
            try:
                text = rewritten.get(path) or path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            relative = path.resolve().relative_to(base.resolve()).as_posix()
            updated, entries = _redact_encoded(text, values, relative, len(PLACEHOLDER.findall(text)) + 1)
            if entries:
                rewritten[path] = updated
                pending.update(entries)
                plan.append({"file": relative, "encoded": len(entries)})
    rewrites = list(rewritten.items())
    result: dict[str, Any] = {"files": plan, "answers": len(pending), "vault": str(vault.path), "applied": False}
    if apply and pending:
        vault.put_many(pending)  # verified read-back before any file is touched
        for path, updated in rewrites:
            path.write_text(updated, encoding="utf-8")
        result["applied"] = True
    return result


def restore(roots: list[Path], vault: AnswerVault, *, apply: bool = False) -> dict[str, Any]:
    """Put vault values back in place of their references (undo of ``migrate``)."""
    data = vault.load()
    changed, missing = [], []
    for root in roots:
        for path in ([root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if not PLACEHOLDER.search(text):
                continue

            def back(match: re.Match[str]) -> str:
                entry = data.get(match.group(1))
                if entry is None:
                    missing.append(match.group(1))
                    return match.group(0)
                return str(entry["value"])

            updated = PLACEHOLDER.sub(back, text)
            changed.append(str(path))
            if apply:
                path.write_text(updated, encoding="utf-8")
    return {"files": len(changed), "missing": missing, "applied": apply}


# -- evaluation split -------------------------------------------------------------------------
SPLIT_FILE = "EVALUATION_SPLIT.json"
ADAPTER_DIRS = {"ksnctf": "ksnctf"}


def build_split(root: Path) -> dict[str, Any]:
    """Every problem with a write-up is ``practice``: its solution is on record, so a later
    solve is not an independent (heldout) evaluation."""
    practice = []
    for path in sorted(root.glob("*/*.md")):
        if path.name in {"README.md", "KNOWLEDGE.md"}:
            continue
        head = path.stem.split("-", 1)[0]
        practice.append({"ctf": path.parent.name, "problem": head if head.isdigit() else path.stem,
                         "writeup": path.relative_to(root).as_posix()})
    return {"policy": "Problems with a write-up are practice, never heldout. Answers are in the vault, not here.",
            "practice": practice, "heldout": []}


def write_split(root: Path) -> dict[str, Any]:
    split = build_split(root)
    (root / SPLIT_FILE).write_text(json.dumps(split, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"path": str(root / SPLIT_FILE), "practice": len(split["practice"])}


def split_for(root: Path, adapter: str, challenge_id: object) -> dict[str, Any]:
    directory = ADAPTER_DIRS.get(adapter)
    if directory is None or challenge_id is None:
        return {"split": "unlisted", "reason": "no write-up mapping for this platform"}
    file = root / SPLIT_FILE
    split = json.loads(file.read_text(encoding="utf-8")) if file.is_file() else build_split(root)
    for item in split.get("practice", []):
        if item["ctf"] == directory and item["problem"] == str(challenge_id):
            return {"split": "practice", "independent_evaluation": False,
                    "reason": f"a write-up exists ({item['writeup']}); do not read it when solving independently"}
    return {"split": "unlisted", "reason": "no write-up on record"}

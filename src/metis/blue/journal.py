"""Private analyst case journals.

Records observations; it executes no queries.

The JSON record shapes are kept stable for existing case directories. A cooperating
CLI process holds one root lock. Individual replacements are atomic, but a command
that updates several files is not a database transaction. Credential screening is
only a heuristic and does not make case material suitable for publication.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from metis.core.answer_vault import ANSWER, EXAMPLE

CASE_TYPES = ("incident", "hunt", "ctf", "training", "detection", "intel")
CONFIDENCE = ("high", "medium", "low", "unproven")
OUTCOMES = ("confirmed-incident", "true-positive-contained", "false-positive",
            "benign-explained", "inconclusive", "solved", "unsolved", "abandoned")
SUMMARY_START = "<!-- metis:journal:summary:start -->"
SUMMARY_END = "<!-- metis:journal:summary:end -->"


class ContractError(SystemExit):
    def __init__(self, message: str):
        super().__init__("journal: " + message)


class JournalArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's detailed diagnostics can contain user-supplied credentials.
        raise ContractError("invalid command arguments; use --help to inspect the accepted options")


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def screen(text: str, field: str) -> str:
    """Reject recognizable credential material without echoing its value."""
    patterns = (
        r"-----BEGIN[^\r\n]*PRIVATE KEY-----",
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        r"\b(?:aws_secret_access_key|password|passwd|pwd|secret)\s*[:=]\s*[\"']?[^\s\"']{6,}",
        r"\b(?:authorization\s*:\s*|bearer\s+)[A-Za-z0-9_./+~=-]{24,}",
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
        r"\bgh[pousr]_[A-Za-z0-9]{16,}",
        r"\bxox[baprs]-[A-Za-z0-9-]{16,}",
        r"(?:^|\n)\s*(?:set-cookie|cookie)\s*:",
    )
    answers = [match.group(0) for match in ANSWER.finditer(text) if not EXAMPLE.fullmatch(match.group(0))]
    if answers or any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
        raise ContractError(f"{field} contains possible credential or protected answer material; use a private reference")
    return text


def slugify(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.lower())
    result = "-".join(words)[:60]
    if not result:
        raise ContractError("case label needs at least one ASCII letter or digit")
    return result


def _leaf_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ContractError("case ID must be a single local directory name")
    return value


def _directory(path: Path, create: bool = False) -> Path:
    if path.is_symlink():
        raise ContractError("symbolic links are not allowed for journal directories")
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise ContractError("journal directory does not exist or is not a regular directory")
    return path


@contextmanager
def _file(path: Path, flags: int, mode: str):
    descriptor = None
    try:
        descriptor = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ContractError("journal file must be a regular file")
        stream = os.fdopen(descriptor, mode, encoding="utf-8")
        descriptor = None
        with stream:
            yield stream
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _text(path: Path, missing: str | None = None) -> str:
    try:
        with _file(path, os.O_RDONLY, "r") as stream:
            return stream.read()
    except FileNotFoundError:
        if missing is None:
            raise ContractError("required journal file is missing") from None
        return missing


def _replace(path: Path, value: str) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ContractError("journal destination must be a regular file")
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".journal-", dir=path.parent)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def _append(path: Path, value: str) -> None:
    with _file(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, "a") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def append_jsonl(path: Path, record: dict) -> None:
    _append(path, json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _load(path: Path) -> list[dict]:
    records = []
    for number, line in enumerate(_text(path, "").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except (ValueError, UnicodeError):
            raise ContractError(f"invalid journal JSON at line {number}") from None
        if not isinstance(item, dict):
            raise ContractError(f"journal record at line {number} is not an object")
        records.append(item)
    return records


def read_meta(path: Path) -> dict:
    try:
        result = json.loads(_text(path / "meta.json"))
    except ValueError:
        raise ContractError("case metadata is not valid JSON") from None
    if not isinstance(result, dict):
        raise ContractError("case metadata must be an object")
    return result


def write_meta(path: Path, meta: dict) -> None:
    _replace(path / "meta.json", json.dumps(meta, ensure_ascii=False, indent=2) + "\n")


def _constant(text: str) -> Callable[[re.Match[str]], str]:
    return lambda match: text


def _cell(value) -> str:
    return str(value if value is not None else "—").replace("|", "\\|").replace("\n", "<br>").replace("\r", "")


class CaseJournal:
    """Storage and presentation for the existing JSONL case format."""

    def __init__(self, root: Path):
        self.root = _directory(Path(root), create=True)
        self.root.chmod(0o700)

    def locate(self, identifier: str) -> Path:
        return _directory(self.root / _leaf_name(identifier))

    @contextmanager
    def locked(self):
        with _file(self.root / ".lock", os.O_RDWR | os.O_CREAT, "r+") as stream:
            os.fchmod(stream.fileno(), 0o600)
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield self
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def open(self, args) -> None:
        normalized = slugify(args.case)
        identifier = normalized if re.match(r"\d{8}-", normalized) else f"{dt.date.today():%Y%m%d}-{normalized}"
        folder = self.root / identifier
        _directory(folder, create=True)
        if (folder / "meta.json").exists():
            read_meta(folder)
            print(identifier)
            return
        if (folder / "meta.json").is_symlink():
            raise ContractError("case metadata cannot be a symbolic link")
        metadata = {"case_id": identifier, "title": args.title or args.case, "type": args.type,
                        "opened_utc": now(), "closed_utc": None, "outcome": None,
                        "platform": args.platform, "objective": args.objective or "(not stated)", "skills": []}
        for child in ("raw", "work"):
            _directory(folder / child, create=True)
        initial = {
            "case.md": self.cover(metadata),
            "lessons.md": f"# Case lessons: {identifier}\n\nReview generic lessons before promoting them.\n",
            "timeline.jsonl": "", "queries.jsonl": "", "findings.jsonl": "",
        }
        for name, body in initial.items():
            destination = folder / name
            if destination.is_symlink() or (destination.exists() and not destination.is_file()):
                raise ContractError("existing case material is not a regular file")
            if not destination.exists():
                _replace(destination, body)
        write_meta(folder, metadata)
        print(identifier)

    @staticmethod
    def cover(meta: dict) -> str:
        values = (("type", meta["type"]), ("platform", meta["platform"]),
                  ("opened (UTC)", meta["opened_utc"]), ("closed (UTC)", None), ("outcome", None))
        table = "\n".join(f"| {key} | {_cell(value)} |" for key, value in values)
        return (f"# {_cell(meta['title'])}\n\nCase ID: `{meta['case_id']}`\n\n"
                f"| Property | Value |\n| --- | --- |\n{table}\n\n"
                f"## Objective\n\n{meta['objective']}\n\n"
                "## Scope and constraints\n\nRecord authorized assets, time range and collection limits.\n\n"
                "## Hypotheses\n\nTrack competing explanations and the evidence needed to distinguish them.\n\n"
                f"## Outcome\n\n{SUMMARY_START}\nInvestigation is open.\n{SUMMARY_END}\n")

    @staticmethod
    def summarize(cover: str, report: str) -> str:
        block = SUMMARY_START + "\n" + report + "\n" + SUMMARY_END
        if SUMMARY_START in cover or SUMMARY_END in cover:
            if cover.count(SUMMARY_START) != 1 or cover.count(SUMMARY_END) != 1:
                raise ContractError("case summary boundaries are ambiguous; preserve the file and inspect it privately")
            before, rest = cover.split(SUMMARY_START, 1)
            if SUMMARY_END not in rest:
                raise ContractError("case summary boundaries are out of order")
            _, after = rest.split(SUMMARY_END, 1)
            return before + block + after
        # Older layouts have no machine-owned boundaries. Keep their entire text;
        # insert the current summary without guessing which prose is user-authored.
        heading = re.search(r"(?m)^## Outcome[^\S\n]*(?:[^\n]*)$", cover)
        if heading:
            position = heading.end()
            return cover[:position] + "\n\n" + block + "\n" + cover[position:]
        return cover.rstrip() + "\n\n## Outcome\n\n" + block + "\n"

    def record(self, args, kind: str) -> None:
        folder = self.locate(args.case)
        read_meta(folder)
        timestamp = now()
        if kind == "note":
            row = {"ts": timestamp, "kind": kind, "phase": args.phase, "text": args.text, "host": args.host}
            append_jsonl(folder / "timeline.jsonl", row)
            return
        if kind == "query":
            row = {"ts": timestamp, "kind": kind, "platform": args.platform, "purpose": args.purpose or "",
                       "query": args.query, "hits": args.hits, "verdict": args.verdict}
            brief = {key: row[key] for key in ("ts", "kind", "platform", "purpose", "hits")}
            destination = "queries.jsonl"
        else:
            evidence = args.evidence.strip()
            if len(evidence) < 8:
                raise ContractError("evidence needs an identifiable artifact and location (at least 8 characters)")
            row = {"ts": timestamp, "kind": kind, "summary": args.summary, "evidence": evidence,
                       "confidence": args.confidence, "attack": args.attack or [], "host": args.host,
                       "ruled_out": args.ruled_out or ""}
            brief = {key: row[key] for key in ("ts", "kind", "summary", "confidence")}
            destination = "findings.jsonl"
        append_jsonl(folder / destination, row)
        append_jsonl(folder / "timeline.jsonl", brief)

    def lesson(self, args) -> None:
        folder = self.locate(args.case)
        read_meta(folder)
        if any(char in args.tag for char in "\r\n[]"):
            raise ContractError("lesson tag cannot contain line breaks or brackets")
        _append(folder / "lessons.md", f"\n- **[{args.tag}]** {args.text.strip()}\n")

    def close(self, args) -> None:
        folder = self.locate(args.case)
        meta = read_meta(folder)
        findings, queries, timeline = (_load(folder / name) for name in
                                       ("findings.jsonl", "queries.jsonl", "timeline.jsonl"))
        cover = _text(folder / "case.md")
        skills = meta.get("skills", [])
        if not isinstance(skills, list) or any(not isinstance(item, str) for item in skills):
            raise ContractError("metadata skills must be a list of strings")
        meta.update(closed_utc=now(), outcome=args.outcome, skills=sorted(set(skills + (args.skills or []))))
        report = ["### Current recorded outcome", "", f"Outcome: **{args.outcome}**", f"Closed (UTC): {meta['closed_utc']}",
                  f"Records: {len(findings)} findings, {len(queries)} queries, {len(timeline)} timeline entries.",
                  "", args.summary or "No closing narrative was supplied.", "", "### Recorded findings", "",
                  "| Confidence | Summary | Evidence |", "| --- | --- | --- |"]
        for finding in findings:
            if not all(isinstance(finding.get(key), str) for key in ("confidence", "summary", "evidence")):
                print("journal: incomplete finding omitted from summary; original record retained", file=sys.stderr)
                continue
            report.append("| " + " | ".join(_cell(finding[key]) for key in ("confidence", "summary", "evidence")) + " |")
        first_section = re.search(r"(?m)^##\s", cover)
        header = cover[:first_section.start()] if first_section else cover
        table = re.search(r"(?m)^(?:\|[^\n]*\|\n?)+", header)
        if table and all(re.search(r"(?m)^\|\s*" + re.escape(label) + r"\s*\|", table[0])
                         for label in ("type", "opened (UTC)", "closed (UTC)", "outcome")):
            updated = table[0]
            for label, value in (("closed (UTC)", meta["closed_utc"]), ("outcome", args.outcome)):
                replacement = f"| {label} | {_cell(value)} |"
                updated = re.sub(r"(?m)^\|\s*" + re.escape(label) + r"\s*\|[^\n]*$",
                                 _constant(replacement), updated, count=1)
            cover = cover[:table.start()] + updated + cover[table.end():]
        _replace(folder / "case.md", self.summarize(cover, "\n".join(report)))
        write_meta(folder, meta)
        self.index()
        print(f"closed {args.case} -> {args.outcome}")

    def cases(self):
        for folder in sorted(self.root.iterdir(), reverse=True):
            if folder.is_symlink():
                raise ContractError("symbolic link encountered in journal root")
            if folder.is_dir() and (folder / "meta.json").exists():
                yield folder, read_meta(folder)

    def index(self) -> None:
        rows = ["# Private case index", "", "| Case | Type | Opened (UTC) | Outcome | Findings | Title |",
                "| --- | --- | --- | --- | --- | --- |"]
        for folder, meta in self.cases():
            identity = _leaf_name(folder.name)
            row = (f"[{identity}]({identity}/case.md)", meta.get("type"), meta.get("opened_utc"),
                   meta.get("outcome"), len(_load(folder / "findings.jsonl")), meta.get("title"))
            rows.append("| " + " | ".join(map(_cell, row)) + " |")
        if len(rows) == 4:
            rows.append("| No cases recorded | — | — | — | 0 | — |")
        _replace(self.root / "INDEX.md", "\n".join(rows) + "\n")

    def show(self, args) -> None:
        folder = self.locate(args.case)
        print(_text(folder / "case.md"), end="")
        for name in ("findings", "queries"):
            body = _text(folder / f"{name}.jsonl", "")
            if body.strip():
                print(f"\n## {name.title()} records\n\n{body}", end="")

    def lessons(self, args) -> None:
        for folder, _ in reversed(list(self.cases())):
            chosen = [line for line in _text(folder / "lessons.md", "").splitlines()
                      if line.startswith("- **[") and (not args.tag or line.startswith(f"- **[{args.tag}]**"))]
            if chosen:
                print(f"## {folder.name}\n\n" + "\n".join(chosen) + "\n")

    def execute(self, args) -> None:
        for key, value in vars(args).items():
            values = value if isinstance(value, list) else [value]
            for item in values:
                if isinstance(item, str):
                    screen(item, key)
        if args.command in ("note", "query", "finding"):
            self.record(args, args.command)
        elif args.command == "index":
            self.index()
        else:
            getattr(self, args.command)(args)


DEFAULT_ROOT = Path(".metis-state/journal")


def journal_root(value: str | None = None) -> Path:
    return Path(value or os.environ.get("METIS_JOURNAL_ROOT") or DEFAULT_ROOT)


def build_parser() -> argparse.ArgumentParser:
    parser = JournalArgumentParser(description=__doc__)
    add_commands(parser.add_subparsers(dest="command", required=True))
    return parser


def add_commands(commands: Any, parser_class: type[argparse.ArgumentParser] | None = None) -> None:
    """Add the journal subcommands to ``commands`` (also used by ``metis journal``)."""
    specifications: dict[str, list[tuple[str, dict[str, Any]]]] = {
        "open": [("case", {"required": True}), ("type", {"choices": CASE_TYPES, "default": "incident"}),
                 ("title", {}), ("objective", {}), ("platform", {})],
        "note": [("text", {"required": True}), ("phase", {"default": "analysis", "choices":
                 ("intake", "scope", "collect", "analysis", "contain", "report")}), ("host", {})],
        "query": [("platform", {"required": True}), ("query", {"required": True}),
                  ("hits", {"type": int, "default": -1}), ("purpose", {}), ("verdict", {"default": "pending",
                   "choices": ("pending", "useful", "empty", "noisy", "wrong-index")})],
        "finding": [("summary", {"required": True}), ("evidence", {"required": True}),
                    ("confidence", {"choices": CONFIDENCE, "default": "medium"}),
                    ("attack", {"action": "append"}), ("host", {}), ("ruled-out", {})],
        "lesson": [("text", {"required": True}), ("tag", {"default": "general"})],
        "close": [("outcome", {"required": True, "choices": OUTCOMES}), ("summary", {}), ("skills", {"action": "append"})],
        "index": [], "show": [], "lessons": [("tag", {})],
    }
    if parser_class is not None:
        commands._parser_class = parser_class  # keep argument errors from echoing values
    for name, options in specifications.items():
        command = commands.add_parser(name)
        if name not in ("open", "index", "lessons"):
            command.add_argument("--case", required=True)
        for flag, settings in options:
            command.add_argument("--" + flag, **settings)


def run(args: argparse.Namespace, root: Path) -> int:
    previous_mask = os.umask(0o077)
    try:
        with CaseJournal(root).locked() as journal:
            journal.execute(args)
    except (OSError, UnicodeError):
        raise ContractError("journal I/O failed; inspect private storage permissions and file types") from None
    finally:
        os.umask(previous_mask)
    return 0



def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv), journal_root())

"""Create a structural source inventory without exporting names or source passages."""
import argparse
import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

from . import BLUE_ROOT
from .knowledge_intake import (
    MAX_FILE,
    MAX_TOTAL,
    private_report_path,
    safe_read,
    source_state,
    validate_roots,
    write_report,
)


def units(text, markdown=True):
    result = []
    starts = [0]
    fence = None
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if opening:
            marker = opening.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not line[opening.end():].strip():
                fence = None
            continue
        if markdown and fence is None and re.match(r"^ {0,3}#{1,6}[ \t]+", line) and index:
            starts.append(index)
    for start, end in zip(starts, starts[1:] + [len(lines)]):
        value = "".join(lines[start:end])
        if value.strip():
            result.append({"start_line": start + 1, "line_count": end - start,
                           "content_sha256": hashlib.sha256(value.encode()).hexdigest()})
    return result


def inventory(source):
    source = source.resolve(strict=True)
    files = []
    total = 0
    before = source_state(source)
    for identity, path, _ in before:
        raw = safe_read(path, MAX_FILE); total += len(raw)
        if total > MAX_TOTAL:
            raise ValueError("aggregate budget exceeded")
        suffix = path.suffix.lower()
        parts = path.relative_to(source).parts
        category = ("skill" if path.name == "SKILL.md" else
                    "case" if any(p in parts for p in ("logs", "ctf-log", "notes", "data")) else
                    "test" if "tests" in parts or path.name.startswith("test_") else
                    "python" if suffix == ".py" else
                    "document" if suffix in (".md", ".rst", ".txt") else "other")
        row = {"path_sha256": identity, "content_sha256": hashlib.sha256(raw).hexdigest(),
               "category": category, "bytes": len(raw), "units": []}
        if category in ("skill", "document"):
            try:
                row["units"] = units(raw.decode("utf-8"), suffix == ".md")
            except UnicodeError:
                row["parse_status"] = "unsupported-encoding"
        elif category == "python":
            try:
                tree = ast.parse(raw)
                row["module_doc_present"] = bool(ast.get_docstring(tree))
                row["definition_count"] = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                                              for n in ast.walk(tree))
            except (SyntaxError, UnicodeError, RecursionError):
                row["parse_status"] = "syntax-unavailable"
        files.append(row)
    if source_state(source) != before:
        raise ValueError("source-changed-during-inventory")
    return {"schema_version": 1, "scope": "Structural counts do not prove semantic transfer.",
            "files": files,
            "summary": {key: sum(r["category"] == key for r in files)
                        for key in ("skill", "document", "python", "test", "case", "other")},
            "document_units": sum(len(r["units"]) for r in files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=BLUE_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        root, source = validate_roots(args.root, args.source)
        out = private_report_path(root, args.out)
        result = inventory(source)
        write_report(root, out, result)
        print(json.dumps({"files": len(result["files"]), "summary": result["summary"],
                          "document_units": result["document_units"]}))
        return 0
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, RecursionError):
        print(json.dumps({"status": "blocked", "reason": "invalid-or-changing-source-or-output"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

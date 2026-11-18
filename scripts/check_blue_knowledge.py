#!/usr/bin/env python3
"""Validate the METIS Blue knowledge tree: skills, links, discovery paths and the knowledge index.

Checks (paths under ``blue/`` unless noted):
- every directory under ``skills/`` has a ``SKILL.md`` whose front matter opens at the first byte
  with ``---``, closes with a ``---`` line, and has a non-empty ``name`` equal to the directory
  (``[a-z0-9-]{1,64}``) and a non-empty ``description``;
- the migration manifest's skill count and targets, every manifest skill target is present, and
  the target digests (``audit_knowledge``);
- ``.agents/skills`` (repository root) links each Blue skill to exactly ``blue/skills/<name>``;
  any other symbolic link there, dangling or pointing elsewhere, is an error;
- no broken relative links in skills, docs, detections, playbooks and the README.

``--staged`` runs every check on the staged snapshot (the index is checked out into a temporary
directory), so unstaged edits neither hide nor cause findings.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"\]\(([^)]+)\)")
NAME = re.compile(r"[a-z0-9-]{1,64}")
STAGED_PATHS = ("blue", ".agents", "docs/BLUE_TEAM.md")


def _front_matter(text: str) -> dict[str, str] | None:
    """Parse ``---``-fenced front matter that starts at the first byte; None when malformed."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 3)
    if end < 0 and text.endswith("\n---"):
        end = len(text) - 4
    if end < 0:
        return None
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        key, separator, value = line.partition(":")
        if separator and key and not key.startswith((" ", "\t")):
            fields[key.strip()] = value.strip()
    return fields


def _verify_coverage(blue: Path) -> list[str]:
    sys.path.insert(0, str(ROOT / "blue" / "scripts"))
    try:
        from audit_knowledge import verify_coverage
    finally:
        sys.path.pop(0)
    return list(verify_coverage(blue))


def check(root: Path = ROOT) -> list[str]:
    blue = root / "blue"
    errors = _verify_coverage(blue)

    names: set[str] = set()
    for directory in sorted(path for path in (blue / "skills").iterdir() if path.is_dir()):
        manifest = directory / "SKILL.md"
        relative = manifest.relative_to(root)
        names.add(directory.name)
        if not manifest.is_file():
            errors.append(f"skill directory without SKILL.md: {directory.relative_to(root)}")
            continue
        fields = _front_matter(manifest.read_text())
        if fields is None:
            errors.append(f"malformed skill front matter (must open and close with ---): {relative}")
            continue
        name = fields.get("name", "")
        if name != directory.name or not NAME.fullmatch(name):
            errors.append(f"invalid skill name: {relative}")
        if not fields.get("description"):
            errors.append(f"missing skill description: {relative}")

    migration = json.loads((blue / "docs/migration.json").read_text())
    skill_targets = [entry["target"] for entry in migration["entries"] if entry["kind"] == "skill"]
    if len(skill_targets) != migration["source_manifests"]:
        errors.append("migration manifest skill count mismatch")
    for entry in migration["entries"]:
        if not (blue / entry["target"]).is_file():
            errors.append(f"missing migration target: blue/{entry['target']}")
    for target in skill_targets:
        parts = Path(target).parts
        if len(parts) != 3 or parts[0] != "skills" or parts[2] != "SKILL.md" or parts[1] not in names:
            errors.append(f"migration skill target is not a Blue skill directory: blue/{target}")

    discovery = root / ".agents" / "skills"
    for name in sorted(names):
        link = discovery / name
        if not link.is_symlink() or link.resolve() != (blue / "skills" / name).resolve():
            errors.append(f"skill not discoverable at .agents/skills/{name} -> blue/skills/{name}")
    for link in sorted(discovery.iterdir()):
        if not link.is_symlink():
            continue
        if not link.exists():
            errors.append(f"dangling skill link: .agents/skills/{link.name}")
        elif link.name not in names or link.resolve() != (blue / "skills" / link.name).resolve():
            errors.append(f"unexpected skill link: .agents/skills/{link.name}")

    documents = [*(blue / "skills").rglob("*.md"), *(blue / "docs").glob("*.md"),
                 *(blue / "detections").rglob("*.md"), *(blue / "playbooks").rglob("*.md"), blue / "README.md"]
    for document in documents:
        for target in LINK.findall(document.read_text()):
            target = target.split("#")[0]
            if not target or target.startswith(("http:", "https:", "mailto:")) or "<" in target:
                continue
            if not (document.parent / target).exists():
                errors.append(f"broken link: {document.relative_to(root)}: {target}")
    return errors


def check_staged(repository: Path = ROOT) -> list[str]:
    """Check the staged snapshot of the Blue tree, its discovery links and linked METIS docs."""
    with tempfile.TemporaryDirectory(prefix="metis-blue-staged-") as directory:
        listed = subprocess.run(["git", "ls-files", "-z", "--", *STAGED_PATHS], cwd=repository,
                                capture_output=True, check=True).stdout
        paths = [item for item in listed.decode().split("\0") if item]
        if paths:
            subprocess.run(["git", "checkout-index", "--prefix=" + directory + "/", "-z", "--stdin"],
                           cwd=repository, input=b"\0".join(path.encode() for path in paths) + b"\0",
                           check=True, capture_output=True)
        snapshot = Path(directory)
        if not (snapshot / "blue" / "docs" / "migration.json").is_file():
            return ["staged snapshot has no blue/docs/migration.json"]
        return check(snapshot)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="check the staged snapshot instead of the worktree")
    args = parser.parse_args(argv)
    errors = check_staged() if args.staged else check()
    for error in errors:
        print(error, file=sys.stderr)
    print(json.dumps({"status": "failed" if errors else "passed", "findings": len(errors)}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

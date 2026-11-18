#!/usr/bin/env python3
"""Validate the METIS Blue knowledge tree: skills, links, discovery paths and the knowledge index.

Checks (all paths under ``blue/`` unless noted):
- every ``skills/*/SKILL.md`` has front matter with ``name`` equal to its directory
  (``[a-z0-9-]{1,64}``) and a ``description``;
- the migration manifest's skill count and targets, and the target digests (``audit_knowledge``);
- each Blue skill is discoverable as ``.agents/skills/<name>`` resolving to ``blue/skills/<name>``,
  and nothing in ``.agents/skills`` points to a missing Blue skill;
- no broken relative links in skills, docs, detections, playbooks and the README;
- with ``--staged``: the indexed knowledge snapshot equals the worktree (digest checks read files).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLUE = ROOT / "blue"
sys.path.insert(0, str(BLUE / "scripts"))

from audit_knowledge import verify_coverage

LINK = re.compile(r"\]\(([^)]+)\)")


def check(staged: bool = False) -> list[str]:
    errors = list(verify_coverage(BLUE))
    names = set()
    for manifest in sorted((BLUE / "skills").glob("*/SKILL.md")):
        relative = manifest.relative_to(ROOT)
        parts = manifest.read_text().split("---", 2)
        if len(parts) != 3 or not parts[1].strip().startswith("name:"):
            errors.append(f"missing skill front matter: {relative}")
            continue
        name = re.search(r"^name:\s*(.+)$", parts[1], re.MULTILINE)
        description = re.search(r"^description:\s*(.+)$", parts[1], re.MULTILINE)
        if not name or name[1].strip() != manifest.parent.name or not re.fullmatch(r"[a-z0-9-]{1,64}", name[1].strip()):
            errors.append(f"invalid skill name: {relative}")
        if not description:
            errors.append(f"missing skill description: {relative}")
        names.add(manifest.parent.name)

    migration = json.loads((BLUE / "docs/migration.json").read_text())
    if sum(entry["kind"] == "skill" for entry in migration["entries"]) != migration["source_manifests"]:
        errors.append("migration manifest skill count mismatch")
    for entry in migration["entries"]:
        if not (BLUE / entry["target"]).is_file():
            errors.append(f"missing migration target: blue/{entry['target']}")

    discovery = ROOT / ".agents" / "skills"
    for name in sorted(names):
        link = discovery / name
        if not link.is_symlink() or link.resolve() != (BLUE / "skills" / name).resolve():
            errors.append(f"skill not discoverable at .agents/skills/{name} -> blue/skills/{name}")
    for link in sorted(discovery.iterdir()):
        if link.is_symlink() and not link.exists():
            errors.append(f"dangling skill link: .agents/skills/{link.name}")

    documents = [*(BLUE / "skills").rglob("*.md"), *(BLUE / "docs").glob("*.md"),
                 *(BLUE / "detections").rglob("*.md"), *(BLUE / "playbooks").rglob("*.md"), BLUE / "README.md"]
    for document in documents:
        for target in LINK.findall(document.read_text()):
            target = target.split("#")[0]
            if not target or target.startswith(("http:", "https:", "mailto:")) or "<" in target:
                continue
            if not (document.parent / target).exists():
                errors.append(f"broken link: {document.relative_to(ROOT)}: {target}")

    if staged:
        indexed = set(migration["target_digests"]) | {"docs/migration.json", "docs/knowledge-coverage.json"}
        for path in sorted(indexed):
            shown = subprocess.run(["git", "show", ":blue/" + path], cwd=ROOT, capture_output=True, check=False)
            if shown.returncode or shown.stdout != (BLUE / path).read_bytes():
                errors.append(f"knowledge index/worktree mismatch: blue/{path}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="also compare the indexed knowledge snapshot")
    args = parser.parse_args(argv)
    errors = check(args.staged)
    for error in errors:
        print(error, file=sys.stderr)
    print(json.dumps({"status": "failed" if errors else "passed", "findings": len(errors)}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

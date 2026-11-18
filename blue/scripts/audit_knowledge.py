#!/usr/bin/env python3
"""Check source coverage, target digests and every Git object without publishing source names."""
import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISPOSITIONS = {
    "adapted-knowledge", "replaced-runtime", "excluded-private-case",
    "excluded-historical-case", "excluded-source-metadata", "excluded-legacy-lab",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root)


def file_bytes(path):
    return os.readlink(path).encode() if path.is_symlink() else path.read_bytes()


def source_inventory(source):
    records = {}
    for raw in git(source, "ls-files", "-z").split(b"\0"):
        if not raw:
            continue
        path = raw.decode()
        records[digest(raw)] = digest(file_bytes(source / path))
    return records


def verify_coverage(root=ROOT, source=None):
    errors = []
    manifest = json.loads((root / "docs/migration.json").read_text())
    coverage = json.loads((root / "docs/knowledge-coverage.json").read_text())
    targets = manifest["target_digests"]
    if not targets:
        errors.append("Empty target inventory")
    for name, expected in targets.items():
        path = root / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            errors.append("Missing or unsafe migration target: " + name)
        elif digest(path.read_bytes()) != expected:
            errors.append("Migration target digest changed: " + name)
    knowledge_paths = {str(p.relative_to(root)) for directory in ("skills", "detections", "playbooks")
                       for p in (root / directory).rglob("*") if p.is_file()}
    if knowledge_paths - set(targets):
        errors.append("Knowledge files missing from target inventory")
    ids = {e["source_id"]: e for e in manifest["entries"]}
    if len(ids) != len(manifest["entries"]):
        errors.append("Duplicate migration source ID")
    if sum(e["kind"] == "skill" for e in ids.values()) != manifest["source_manifests"]:
        errors.append("Source skill count mismatch")
    for entry in ids.values():
        if any(name not in targets for name in entry.get("additional_targets", [])):
            errors.append("Additional migration target missing from digest inventory")
        if targets.get(entry["target"]) != entry["target_sha256"]:
            errors.append("Entry target digest mismatch: " + entry["source_id"])
    expected_sources = {}
    referenced = set()
    for entry in coverage["files"]:
        key = entry["path_sha256"]
        if key in expected_sources:
            errors.append("Duplicate source path digest")
        expected_sources[key] = entry["content_sha256"]
        if entry["disposition"] not in DISPOSITIONS:
            errors.append("Unknown source disposition")
        source_id = entry.get("source_id")
        if entry["disposition"] == "adapted-knowledge" and source_id not in ids:
            errors.append("Knowledge source lacks a migration entry")
        if source_id:
            referenced.add(source_id)
            if source_id not in ids or ids[source_id]["source_sha256"] != entry["content_sha256"]:
                errors.append("Source content digest differs from migration entry")
    if set(ids) != referenced:
        errors.append("Migration sources and coverage inventory differ")
    if len(expected_sources) != coverage["source_file_count"]:
        errors.append("Source inventory count mismatch")
    if source is not None:
        observed = source_inventory(source)
        added = set(observed) - set(expected_sources)
        missing = set(expected_sources) - set(observed)
        changed = sum(observed[k] != expected_sources[k] for k in observed.keys() & expected_sources.keys())
        if added or missing or changed:
            errors.append(f"Source coverage drift: added={len(added)}, missing={len(missing)}, changed={changed}")
    return errors


def history_issues(root, deny_pattern):
    """Inspect decompressed reachable AND unreachable objects, plus Git metadata."""
    errors = []
    pattern = re.compile(deny_pattern, re.IGNORECASE) if deny_pattern else None
    secret = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
    count = 0
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch-all-objects", "--batch"],
        cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    while True:
        header = proc.stdout.readline()
        if not header:
            break
        oid, kind, size = header.decode().strip().split()
        data = proc.stdout.read(int(size))
        if len(data) != int(size) or proc.stdout.read(1) != b"\n":
            raise RuntimeError("Truncated Git object stream")
        count += 1
        # Do not print offending content, which could itself contain private material.
        decoded = data.decode("utf-8", errors="replace")
        if pattern and pattern.search(decoded):
            errors.append("Prohibited identity in Git " + kind + " " + oid)
        if secret.search(data):
            errors.append("Private key in Git " + kind + " " + oid)
    proc.stdout.close()
    stderr = proc.stderr.read()
    proc.stderr.close()
    if proc.wait() != 0:
        raise RuntimeError("Git object audit failed: " + stderr.decode(errors="replace"))
    git_dir = Path(git(root, "rev-parse", "--absolute-git-dir").decode().strip())
    for path in git_dir.rglob("*"):
        if not path.is_file() or path.is_symlink() or "objects" in path.relative_to(git_dir).parts:
            continue
        if pattern and (pattern.search(str(path.relative_to(git_dir))) or
                        pattern.search(path.read_bytes().decode(errors="replace"))):
            errors.append("Prohibited identity in Git metadata: " + str(path.relative_to(git_dir)))
    return errors, count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Read-only source checkout to compare by opaque hashes")
    parser.add_argument("--history", action="store_true", help="Include all Git objects and metadata")
    args = parser.parse_args()
    errors = verify_coverage(ROOT, args.source)
    count = None
    if args.history:
        more, count = history_issues(ROOT, os.environ.get("METIS_DENY_PATTERN"))
        errors.extend(more)
    print(json.dumps({"status": "failed" if errors else "passed", "errors": errors,
                      "source_compared": args.source is not None, "git_objects": count,
                      "identity_pattern_supplied": bool(os.environ.get("METIS_DENY_PATTERN"))}))
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())

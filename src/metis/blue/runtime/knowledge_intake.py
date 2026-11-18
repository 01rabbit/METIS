"""Metadata-only source intake and a fail-closed gate for independently authored lessons.

No source file is copied, rendered into a prompt, executed or sent over a network.
This gate detects some copying; a passing check is not a copyright clearance.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from . import BLUE_ROOT

VERSION = "independent-lessons-v1"
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_DRAFT = 128 * 1024
MAX_JSON = 8 * 1024 * 1024
MAX_PATHS = 100000
WIDTH = 64
STEP = 16
INTERNAL_FILES = ("docs/migration.json", "docs/intake-ledger.json")
PRIVATE = ".state/intake"
TRANSACTION = PRIVATE + "/transaction"


def validate_roots(root, source):
    root, source = Path(root).resolve(strict=True), Path(source).resolve(strict=True)
    if not root.is_dir() or not source.is_dir() or root.is_relative_to(source) or source.is_relative_to(root):
        raise ValueError("source-and-destination-must-be-disjoint")
    return root, source


def confined_path(root, relative):
    """Reject ambiguous names and symlinks, including existing ancestor links."""
    if not isinstance(relative, str) or not relative or "\0" in relative:
        raise ValueError("invalid-relative-path")
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts or p.as_posix() != relative:
        raise ValueError("invalid-relative-path")
    current = root
    for index, part in enumerate(p.parts):
        current = current / part
        if current.is_symlink():
            raise ValueError("symlinks-not-accepted")
        if index < len(p.parts) - 1 and current.exists() and not current.is_dir():
            raise ValueError("path-ancestor-is-not-a-directory")
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError("path-outside-root")
    return current


def directory(root, relative):
    path = confined_path(root, relative)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not confined_path(root, relative).is_dir():
        raise ValueError("not-a-directory")
    return path


def optional_bytes(path, limit=MAX_JSON):
    return safe_read(path, limit) if path.exists() or path.is_symlink() else None


def content_hash(data):
    return sha(data) if data is not None else None


def load_json(path):
    return json.loads(safe_read(path, MAX_JSON), object_pairs_hook=strict_object)


def internal_state(root):
    return {name: content_hash(optional_bytes(confined_path(root, name))) for name in INTERNAL_FILES}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def safe_read(path, limit):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError("source-not-bounded-regular-file")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("source-identity-changed")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    final = path.lstat()
    attrs = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if len(data) > limit or any(getattr(before, a) != getattr(after, a) or
                               getattr(before, a) != getattr(final, a) for a in attrs):
        raise ValueError("source-changed-or-exceeded-limit")
    return data


def source_files(source):
    source = source.resolve(strict=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    with subprocess.Popen(
        ["git", "-C", str(source), "-c", "core.fsmonitor=false",
         "ls-files", "--cached", "-z"], env=env, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL) as process:
        output = process.stdout.read(MAX_FILE + 1)
        if len(output) > MAX_FILE:
            process.kill()
            raise ValueError("source-path-byte-budget-exceeded")
        if process.wait(timeout=30):
            raise ValueError("source-index-unavailable")
    names = output.split(b"\0")
    if len(names) > MAX_PATHS + 1:
        raise ValueError("source-file-budget-exceeded")
    for raw in sorted({n for n in names if n}):
        name = raw.decode("utf-8", errors="strict")
        path = confined_path(source, name)
        yield sha(raw), path


def source_state(source):
    state = []
    for identity, path in source_files(source):
        info = path.lstat()
        state.append((identity, path, tuple(getattr(info, k) for k in
                      ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode"))))
    return state


def inventory(source, with_index=False):
    rows = []
    grams = set()
    total = 0
    whole = set()
    before = source_state(source)
    for identity, path, _ in before:
        data = safe_read(path, MAX_FILE)
        total += len(data)
        if total > MAX_TOTAL:
            raise ValueError("source-total-byte-budget-exceeded")
        row = {"path_sha256": identity, "content_sha256": sha(data), "bytes": len(data)}
        rows.append(row)
        whole.add(row["content_sha256"])
        if with_index:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            text = normalize(text)
            for start in range(0, max(0, len(text) - WIDTH + 1), STEP):
                grams.add(sha(text[start:start + WIDTH].encode()))
    if source_state(source) != before:
        raise ValueError("source-changed-during-inventory")
    result = {"schema_version": 1, "policy": VERSION, "files": rows}
    result["snapshot_sha256"] = sha(encoded(result))
    return result, grams, whole


def compare(current, baseline):
    for snapshot in (current, baseline):
        if not isinstance(snapshot, dict) or set(snapshot) != {"schema_version", "policy", "files", "snapshot_sha256"}:
            raise ValueError("invalid-snapshot-schema")
        payload = {k: v for k, v in snapshot.items() if k != "snapshot_sha256"}
        if type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1 or snapshot["policy"] != VERSION or sha(encoded(payload)) != snapshot["snapshot_sha256"]:
            raise ValueError("invalid-snapshot-digest-or-version")
        if not isinstance(snapshot["files"], list) or len(snapshot["files"]) > MAX_PATHS:
            raise ValueError("invalid-snapshot-files")
        seen = set()
        for entry in snapshot["files"]:
            if (not isinstance(entry, dict) or set(entry) != {"path_sha256", "content_sha256", "bytes"} or
                    any(not isinstance(entry[k], str) or not re.fullmatch(r"[0-9a-f]{64}", entry[k])
                        for k in ("path_sha256", "content_sha256")) or
                    type(entry["bytes"]) is not int or not 0 <= entry["bytes"] <= MAX_FILE or
                    entry["path_sha256"] in seen):
                raise ValueError("invalid-snapshot-record")
            seen.add(entry["path_sha256"])
        if sum(e["bytes"] for e in snapshot["files"]) > MAX_TOTAL:
            raise ValueError("snapshot-byte-budget-exceeded")
    old = {e["path_sha256"]: e["content_sha256"] for e in baseline["files"]}
    new = {e["path_sha256"]: e["content_sha256"] for e in current["files"]}
    return {
        "added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()),
        "changed": sorted(k for k in new.keys() & old.keys() if new[k] != old[k]),
        "unchanged": sum(new[k] == old[k] for k in new.keys() & old.keys()),
        "snapshot_sha256": current["snapshot_sha256"],
    }


def library_path(root, relative):
    full = confined_path(root, relative)
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts or len(p.parts) < 2 or p.as_posix() != relative:
        raise ValueError("target-must-be-relative-knowledge")
    if p.parts[0] not in {"skills", "detections", "playbooks"}:
        raise ValueError("target-outside-knowledge-library")
    return full


def target_path(root, relative):
    full = library_path(root, relative)
    if full.suffix != ".md":
        raise ValueError("target-must-be-markdown-knowledge")
    return full


def has_overlap(text, grams):
    plain = normalize(text)
    return any(sha(plain[i:i + WIDTH].encode()) in grams
               for i in range(max(0, len(plain) - WIDTH + 1)))


def overlap_review(text, grams):
    """Identify literal registry-only matches without approving their provenance.

    A native identifier can itself exceed the expression window. Only windows
    wholly inside one complete inline registry key are candidates for explicit
    factual review; a window touching surrounding prose still blocks intake.
    """
    plain = normalize(text)
    spans = []
    pattern = r"(?<![\\`])`((?:HKLM|HKCU|HKU|HKEY_LOCAL_MACHINE|HKEY_CURRENT_USER|HKEY_USERS)(?:\\[A-Za-z0-9_.{}%() -]+){2,})`(?!`)"
    for match in re.finditer(pattern, text):
        value = match[1]
        parts = value.split("\\")
        if len(value) > 512 or any(p != p.strip() or p in (".", "..") for p in parts):
            continue
        start = len(normalize(text[:match.start(1)]))
        end = start + len(normalize(value))
        if plain[start:end] == normalize(value):
            spans.append((start, end, sha(value.encode())))
    found = False
    blocked = False
    candidates = set()
    for i in range(max(0, len(plain) - WIDTH + 1)):
        if sha(plain[i:i + WIDTH].encode()) not in grams:
            continue
        found = True
        covering = [h for start, end, h in spans if start <= i and i + WIDTH <= end]
        if covering:
            candidates.update(covering)
        else:
            blocked = True
    return {"long_overlap": found, "non_registry_overlap": blocked,
            "native_registry_sha256": sorted(candidates)}


def audit_library(root, source):
    """Report expression-review candidates without exporting a source passage."""
    root, source = validate_roots(root, source)
    snapshot, grams, whole = inventory(source, with_index=True)
    rows = []
    for directory in ("skills", "detections", "playbooks"):
        confined_path(root, directory)
        for path in sorted((root / directory).rglob("*")):
            if path.is_symlink():
                raise ValueError("library-symlink-not-accepted")
            if not path.is_file():
                continue
            relative = str(path.relative_to(root))
            data = safe_read(library_path(root, relative), MAX_DRAFT)
            exact = sha(data) in whole
            detail = overlap_review(data.decode("utf-8"), grams)
            overlap = detail["long_overlap"]
            rows.append({"target": relative, "target_sha256": sha(data),
                         "identical": exact, "long_overlap": overlap,
                         "native_registry_only": overlap and not exact and not detail["non_registry_overlap"],
                         "native_registry_sha256": detail["native_registry_sha256"],
                         "disposition": "requires-expression-review" if exact or overlap else "no-long-match"})
    pending = sum(r["disposition"] == "requires-expression-review" for r in rows)
    return {"policy": VERSION, "snapshot_sha256": snapshot["snapshot_sha256"],
            "scope": "Similarity candidates; neither infringement findings nor copyright clearance.",
            "files": rows, "summary": {"files": len(rows), "identical": sum(r["identical"] for r in rows),
                                       "requires_expression_review": pending},
            "errors": ["existing-expression-review-required"] if pending else []}


def check_draft(root, source, draft, identity_pattern):
    root, source = validate_roots(root, source)
    current, grams, whole = inventory(source, with_index=True)
    errors = []
    if not identity_pattern:
        errors.append("identifier-policy-required")
    deny = re.compile(identity_pattern, re.IGNORECASE) if identity_pattern else None
    if not isinstance(draft, dict):
        raise ValueError("draft-must-be-an-object")
    if set(draft) != {"policy", "changes"}:
        errors.append("unexpected-draft-fields")
    if draft.get("policy") != VERSION:
        errors.append("wrong-policy-version")
    changes = draft.get("changes")
    if not isinstance(changes, list) or not 1 <= len(changes) <= 20:
        raise ValueError("draft-must-have-1-to-20-changes")
    valid_sources = {e["path_sha256"]: e["content_sha256"] for e in current["files"]}
    seen = set()
    target_state = {}
    native_registry_review = []
    for number, change in enumerate(changes):
        label = str(number)
        try:
            if not isinstance(change, dict) or set(change) != {"target", "text", "sources"}:
                raise ValueError("unexpected-change-fields")
            path = target_path(root, change["target"])
            if change["target"] in seen:
                raise ValueError("duplicate-target")
            seen.add(change["target"])
            text = change["text"]
            if not isinstance(text, str) or not text.strip() or len(text.encode()) > MAX_DRAFT or "\0" in text:
                raise ValueError("invalid-draft-text")
            # JVM/DEX initializer names are native identifiers, not HTML tags.
            # Only exempt these exact inline literals from the format screen;
            # identity, overlap and reviewer checks still use the original text.
            format_text = re.sub(r"(?<![\\`])`<(?:clinit|init)>`(?!`)", "initializer identifier", text)
            # This intake route accepts prose, not software, payloads or embedded media.
            if re.search(r"(?m)^(?:\s*(?:`{3}|~{3})| {4}|\t)|!\[|<\s*/?\s*[a-z][^>]*>|data:[^\s]+;base64", format_text, re.IGNORECASE):
                errors.append(label + ":code-or-media-not-accepted")
            target_has_identity = bool(deny and deny.search(change["target"]))
            if deny and (deny.search(text) or target_has_identity):
                errors.append(label + ":prohibited-identity")
            overlap = overlap_review(text, grams)
            if sha(text.encode()) in whole or overlap["non_registry_overlap"]:
                errors.append(label + ":source-expression-overlap")
            elif overlap["native_registry_sha256"] and not target_has_identity:
                native_registry_review.append({"target": change["target"],
                    "literal_sha256": overlap["native_registry_sha256"]})
            for blob in re.findall(r"[A-Za-z0-9+/]{100,}={0,2}|[0-9a-fA-F]{128,}", text):
                errors.append(label + ":opaque-encoded-content-not-accepted")
                for decoder in (base64.b64decode, bytes.fromhex):
                    try:
                        value = decoder(blob).decode("utf-8")
                    except (ValueError, UnicodeError):
                        continue
                    if has_overlap(value, grams) or (deny and deny.search(value)):
                        errors.append(label + ":encoded-source-expression")
            sources = change.get("sources", [])
            if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_PATHS or any(not isinstance(x, dict) or set(x) != {"path_sha256", "content_sha256"} or
                                  valid_sources.get(x.get("path_sha256")) != x.get("content_sha256")
                                  for x in sources):
                errors.append(label + ":source-references-invalid-or-stale")
            elif len({x["path_sha256"] for x in sources}) != len(sources):
                errors.append(label + ":duplicate-source-reference")
            if not target_has_identity:
                target_state[change["target"]] = sha(safe_read(path, MAX_DRAFT)) if path.exists() else None
        except (KeyError, TypeError, ValueError, OSError):
            errors.append(label + ":invalid-change")
    return {
        "policy": VERSION, "draft_sha256": sha(encoded(draft)),
        "snapshot_sha256": current["snapshot_sha256"], "target_state": target_state,
        "internal_state": internal_state(root),
        "gate_sha256": sha(safe_read(Path(__file__), MAX_FILE)),
        "identity_policy_sha256": sha((identity_pattern or "").encode()),
        "native_registry_review": native_registry_review,
        "errors": sorted(set(errors)), "eligible_for_review": not errors,
        "review_required": True,
    }


def verify_attestation(review, attestation):
    required = ("independent_expression", "facts_and_methods_only", "no_case_or_secret",
                "no_source_code_or_media", "scope_and_accuracy_checked")
    if review.get("native_registry_review"):
        required += ("native_registry_identifiers_are_factual",)
    return (isinstance(attestation, dict) and
            set(attestation) == {"review_sha256", "reviewer", *required} and
            attestation.get("review_sha256") == sha(encoded(review)) and
            all(attestation.get(k) is True for k in required) and
            isinstance(attestation.get("reviewer"), str) and
            1 <= len(attestation["reviewer"].strip()) <= 200)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_bytes(path, data, mode=0o600, staging=None):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=staging or path.parent, prefix=".intake-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        if Path(name).exists():
            Path(name).unlink()


def atomic_json(path, value):
    atomic_bytes(path, json_bytes(value))


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


@contextmanager
def intake_lock(root):
    directory(root, PRIVATE)
    lock_path = confined_path(root, PRIVATE + "/apply.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "r+") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("unsafe-lock-file")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def transaction_target(root, name):
    return confined_path(root, name) if name in INTERNAL_FILES else target_path(root, name)


def valid_digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def read_journal(root):
    journal = load_json(confined_path(root, TRANSACTION + "/journal.json"))
    if (not isinstance(journal, dict) or set(journal) != {"policy", "phase", "files"} or
            journal["policy"] != VERSION or journal["phase"] not in {"preparing", "prepared", "committed", "rolled-back"} or
            not isinstance(journal["files"], list) or not 3 <= len(journal["files"]) <= 22):
        raise ValueError("invalid-transaction-journal")
    seen = set()
    for number, row in enumerate(journal["files"]):
        if (not isinstance(row, dict) or set(row) != {"target", "before", "after", "mode", "backup"} or
                not isinstance(row["target"], str) or row["target"] in seen or
                row["backup"] != f"{number:02d}.bak" or not valid_digest(row["after"]) or
                (row["before"] is not None and not valid_digest(row["before"])) or
                type(row["mode"]) is not int or not 0 <= row["mode"] <= 0o777):
            raise ValueError("invalid-transaction-record")
        transaction_target(root, row["target"])
        seen.add(row["target"])
    if not set(INTERNAL_FILES).issubset(seen):
        raise ValueError("transaction-internal-files-required")
    return journal


def cleanup_transaction(root, journal):
    location = confined_path(root, TRANSACTION)
    allowed = {"journal.json", *(r["backup"] for r in journal["files"])}
    entries = list(location.iterdir())
    if any((p.name not in allowed and not p.name.startswith(".intake-")) or p.is_symlink() or not p.is_file()
           for p in entries):
        raise ValueError("unexpected-transaction-state")
    for path in entries:
        if path.name != "journal.json":
            path.unlink()
    (location / "journal.json").unlink()
    location.rmdir()
    sync_directory(location.parent)


def _recover(root):
    location = confined_path(root, TRANSACTION)
    if not location.exists():
        return {"status": "no-pending-transaction", "restored": 0}
    if not (location / "journal.json").exists():
        entries = list(location.iterdir())
        if any(not p.name.startswith(".intake-") or p.is_symlink() or not p.is_file() for p in entries):
            raise ValueError("missing-transaction-journal")
        for path in entries:
            path.unlink()
        location.rmdir()
        sync_directory(location.parent)
        return {"status": "preparation-discarded", "restored": 0}
    journal = read_journal(root)
    if journal["phase"] in {"preparing", "committed", "rolled-back"}:
        cleanup_transaction(root, journal)
        return {"status": journal["phase"] + "-cleanup",
                "restored": 0}
    # Validate every target and backup before restoring any file. Never overwrite another editor.
    originals = {}
    for row in journal["files"]:
        path = transaction_target(root, row["target"])
        current = content_hash(optional_bytes(path))
        if current not in {row["before"], row["after"]}:
            raise ValueError("recovery-conflicts-with-another-edit")
        previous = None if row["before"] is None else safe_read(
            confined_path(root, TRANSACTION + "/" + row["backup"]), MAX_JSON)
        if content_hash(previous) != row["before"]:
            raise ValueError("recovery-backup-integrity-failed")
        originals[row["target"]] = previous
    restored = 0
    for row in reversed(journal["files"]):
        path = transaction_target(root, row["target"])
        current = content_hash(optional_bytes(path))
        if current not in {row["before"], row["after"]}:
            raise ValueError("recovery-conflicts-with-another-edit")
        if current != row["before"]:
            previous = originals[row["target"]]
            if previous is None:
                path.unlink()
                sync_directory(path.parent)
            else:
                atomic_bytes(path, previous, row["mode"], staging=location)
            restored += 1
    journal["phase"] = "rolled-back"
    atomic_json(location / "journal.json", journal)
    cleanup_transaction(root, journal)
    return {"status": "rolled-back", "restored": restored}


def recover(root, source):
    root, source = validate_roots(root, source)
    with intake_lock(root):
        return _recover(root)


def validate_manifest(manifest):
    if (not isinstance(manifest, dict) or not isinstance(manifest.get("target_digests"), dict) or
            not isinstance(manifest.get("entries"), list) or
            any(not isinstance(k, str) or not valid_digest(v) for k, v in manifest["target_digests"].items()) or
            any(not isinstance(e, dict) or e.get("target") not in manifest["target_digests"] for e in manifest["entries"])):
        raise ValueError("invalid-migration-manifest")


def validate_ledger(ledger):
    if (not isinstance(ledger, dict) or set(ledger) != {"policy", "entries"} or
            ledger["policy"] != VERSION or not isinstance(ledger["entries"], list)):
        raise ValueError("invalid-intake-ledger")
    seen = set()
    for entry in ledger["entries"]:
        keys = {"draft_sha256", "snapshot_sha256", "review_sha256", "attestation_sha256", "targets", "sources"}
        if (not isinstance(entry, dict) or set(entry) != keys or
                any(not valid_digest(entry[k]) for k in keys - {"targets", "sources"}) or
                not isinstance(entry["targets"], dict) or not entry["targets"] or
                any(not isinstance(k, str) or not valid_digest(v) for k, v in entry["targets"].items()) or
                not isinstance(entry["sources"], list) or not entry["sources"] or
                any(not isinstance(s, dict) or set(s) != {"path_sha256", "content_sha256"} or
                    not all(valid_digest(v) for v in s.values()) for s in entry["sources"]) or
                entry["draft_sha256"] in seen):
            raise ValueError("invalid-intake-receipt")
        seen.add(entry["draft_sha256"])


def _apply_draft(root, source, draft, review, attestation, pattern):
    if confined_path(root, TRANSACTION).exists():
        raise ValueError("pending-transaction-requires-recovery")
    now = check_draft(root, source, draft, pattern)
    if now != review or now["errors"] or not verify_attestation(now, attestation):
        raise ValueError("current-review-and-explicit-attestation-required")
    manifest_path = confined_path(root, INTERNAL_FILES[0])
    manifest = load_json(manifest_path)
    validate_manifest(manifest)
    ledger_path = confined_path(root, INTERNAL_FILES[1])
    ledger = load_json(ledger_path) if ledger_path.exists() else {"policy": VERSION, "entries": []}
    validate_ledger(ledger)
    receipt = {"draft_sha256": now["draft_sha256"], "snapshot_sha256": now["snapshot_sha256"],
               "review_sha256": sha(encoded(now)), "attestation_sha256": sha(encoded(attestation)),
               "targets": {c["target"]: sha(c["text"].encode()) for c in draft["changes"]},
               "sources": [x for c in draft["changes"] for x in c["sources"]]}
    if any(e["draft_sha256"] == receipt["draft_sha256"] for e in ledger["entries"]):
        raise ValueError("draft-already-applied")
    ledger["entries"].append(receipt)
    for target, digest in receipt["targets"].items():
        manifest["target_digests"][target] = digest
    for entry in manifest["entries"]:
        entry["target_sha256"] = manifest["target_digests"][entry["target"]]
    updates = {c["target"]: c["text"].encode() for c in draft["changes"]}
    updates.update({INTERNAL_FILES[0]: json_bytes(manifest), INTERNAL_FILES[1]: json_bytes(ledger)})
    if any(len(data) > MAX_JSON for data in updates.values()):
        raise ValueError("transaction-byte-budget-exceeded")
    originals = {}
    rows = []
    expected = {**now["target_state"], **now["internal_state"]}
    for number, (name, value) in enumerate(updates.items()):
        path = transaction_target(root, name)
        old = optional_bytes(path)
        if content_hash(old) != expected[name]:
            raise ValueError("destination-changed-during-preparation")
        originals[name] = old
        rows.append({"target": name, "before": content_hash(old), "after": sha(value),
                     "mode": stat.S_IMODE(path.stat().st_mode) & 0o777 if old is not None else 0o644,
                     "backup": f"{number:02d}.bak"})
    journal = {"policy": VERSION, "phase": "preparing", "files": rows}
    directory(root, TRANSACTION)
    journal_path = confined_path(root, TRANSACTION + "/journal.json")
    atomic_json(journal_path, journal)
    for row in rows:
        if originals[row["target"]] is not None:
            atomic_bytes(confined_path(root, TRANSACTION + "/" + row["backup"]), originals[row["target"]])
    journal["phase"] = "prepared"
    atomic_json(journal_path, journal)
    try:
        if inventory(source)[0]["snapshot_sha256"] != now["snapshot_sha256"]:
            raise ValueError("source-changed-before-apply")
        for row in rows:
            path = transaction_target(root, row["target"])
            if content_hash(optional_bytes(path)) != row["before"]:
                raise ValueError("destination-changed-during-apply")
            directory(root, str(path.parent.relative_to(root)))
            atomic_bytes(transaction_target(root, row["target"]), updates[row["target"]], row["mode"],
                         staging=root / TRANSACTION)
        if (inventory(source)[0]["snapshot_sha256"] != now["snapshot_sha256"] or
                any(content_hash(optional_bytes(transaction_target(root, r["target"]))) != r["after"] for r in rows)):
            raise ValueError("source-or-destination-changed-during-apply")
        journal["phase"] = "committed"
        atomic_json(journal_path, journal)
    except Exception:
        _recover(root)
        raise
    # An interruption leaves a durable journal. The next apply refuses to proceed until recovery.
    cleanup_transaction(root, journal)
    return receipt


def apply_draft(root, source, draft, review, attestation, pattern):
    root, source = validate_roots(root, source)
    with intake_lock(root):
        return _apply_draft(root, source, draft, review, attestation, pattern)


def private_report_path(root, path, inputs=()):
    absolute = Path(os.path.abspath(path))
    if not absolute.is_relative_to(root / PRIVATE) or absolute == root / PRIVATE:
        raise ValueError("output-must-be-private")
    relative = str(absolute.relative_to(root))
    full = confined_path(root, relative)
    if full.suffix != ".json" or full == root / PRIVATE / "apply.lock" or full.is_relative_to(root / TRANSACTION):
        raise ValueError("output-reserved-or-not-json")
    if full.exists() and not full.is_file():
        raise ValueError("output-must-be-a-regular-file")
    if any(p is not None and full.resolve() == Path(p).resolve() for p in inputs):
        raise ValueError("output-cannot-overwrite-an-input")
    return full


def write_report(root, path, value):
    path = private_report_path(root, path)
    directory(root, str(path.parent.relative_to(root)))
    atomic_json(private_report_path(root, path), value)

def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate-json-key")
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["snapshot", "diff", "audit-library", "check", "apply", "recover"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=BLUE_ROOT)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--draft", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--attestation", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    def load(path):
        if path is None:
            raise ValueError("missing-input-file")
        return load_json(path)
    try:
        root, source = validate_roots(args.root, args.source)
        # Operational reports never replace source files, inputs, locks or recovery state.
        out = private_report_path(root, args.out, (args.baseline, args.draft, args.review, args.attestation))
        if args.action in ("snapshot", "diff"):
            result = inventory(source)[0]
            if args.action == "diff":
                result = compare(result, load(args.baseline))
        elif args.action == "audit-library":
            result = audit_library(root, source)
        elif args.action == "recover":
            result = recover(root, source)
        else:
            draft = load(args.draft)
            pattern = os.environ.get("METIS_DENY_PATTERN")
            if args.action == "check":
                result = check_draft(root, source, draft, pattern)
            else:
                result = apply_draft(root, source, draft, load(args.review), load(args.attestation), pattern)
        write_report(root, out, result)
        print(json.dumps({"status": "blocked" if result.get("errors") else "completed",
                          "action": args.action, "report": str(out),
                          "issues": len(result.get("errors", []))}))
        return 2 if result.get("errors") else 0
    except (OSError, ValueError, KeyError, TypeError, re.error, subprocess.SubprocessError, RecursionError):
        print(json.dumps({"status": "blocked", "reason": "invalid-input-or-incomplete-review"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

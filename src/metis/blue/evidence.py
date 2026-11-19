"""Bounded, offline evidence readers.

Reports are observations, never incident verdicts. Readers: ``email`` (EML/MBOX), ``browser``
(Chromium/Firefox history SQLite with WAL sidecars), ``json`` (exact numbers, duplicate keys refused),
``cloudtrail`` and ``evtx-xml`` (``wevtutil``/EvtxECmd XML exports).
"""
import hashlib
import io
import json
import mailbox
import os
import re
import secrets
import signal
import sqlite3
import stat
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from email import policy
from email.parser import BytesParser
from pathlib import Path

VERSION = "metis-offline-evidence-v1"
KINDS = ("email", "browser", "json", "cloudtrail", "evtx-xml")
MAX_OUTPUT = 32 * 1024 * 1024
EVENT_NS = "http://schemas.microsoft.com/win/2004/08/events/event"


class EvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class Limits:
    bytes: int = 16 * 1024 * 1024
    records: int = 10000
    seconds: float = 15.0
    depth: int = 64
    nodes: int = 100000

    def validate(self):
        if not (1 <= self.bytes <= 128 * 1024 * 1024 and 1 <= self.records <= 50000
                and 0 < self.seconds <= 120 and 1 <= self.depth <= 128 and 1 <= self.nodes <= 500000):
            raise EvidenceError("invalid-limits")


class Budget:
    def __init__(self, limits):
        limits.validate()
        self.limits = limits
        self.end = time.monotonic() + limits.seconds
        self.records = 0
        self.nodes = 0

    def check(self):
        if time.monotonic() >= self.end:
            raise EvidenceError("time-limit-reached")

    def node(self, depth=0):
        self.check()
        self.nodes += 1
        if self.nodes > self.limits.nodes:
            raise EvidenceError("node-limit-reached")
        if depth > self.limits.depth:
            raise EvidenceError("depth-limit-reached")

    def record(self):
        self.check()
        if self.records >= self.limits.records:
            raise EvidenceError("record-limit-reached")
        self.records += 1


@contextmanager
def wall_limit(seconds):
    """A hard Python alarm on POSIX main threads; loops also check a monotonic budget."""
    enabled = hasattr(signal, "setitimer") and threading.current_thread() is threading.main_thread()
    if not enabled:
        yield "cooperative"
        return
    def expired(signum, frame):
        raise EvidenceError("time-limit-reached")
    previous = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    # Never replace a surrounding caller's deadline.
    if old_timer[0] or old_timer[1]:
        yield "cooperative-existing-alarm"
        return
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield "posix-alarm-and-cooperative"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stamp(path):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode):
        raise EvidenceError("input-not-regular-file")
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def read_input(path, budget):
    path = Path(os.path.abspath(path))
    before = stamp(path)
    if before[2] > budget.limits.bytes:
        raise EvidenceError("input-byte-limit-reached")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        s = os.fstat(stream.fileno())
        if (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns) != before:
            raise EvidenceError("input-changed-during-read")
        chunks = []
        remaining = budget.limits.bytes + 1
        while remaining:
            budget.check()
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        s = os.fstat(stream.fileno())
        after = (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if len(raw) > budget.limits.bytes:
        raise EvidenceError("input-byte-limit-reached")
    if before != after or stamp(path) != before or len(raw) != before[2]:
        raise EvidenceError("input-changed-during-read")
    return raw, before


def note(report, code):
    if code not in report["limitations"]:
        report["limitations"].append(code)


def incomplete(report, code):
    report["complete_for_input"] = False
    note(report, code)


@dataclass(frozen=True)
class Number:
    lexeme: str
    kind: str

    def decimal(self):
        return Decimal(self.lexeme)


def exact_json(raw, budget):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise EvidenceError("json-utf8-required")
    # Bound structural depth before the recursive standard-library decoder allocates a tree.
    depth = 0
    quoted = False
    escaped = False
    for index, char in enumerate(text):
        if index % 16384 == 0:
            budget.check()
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > budget.limits.depth:
                raise EvidenceError("depth-limit-reached")
        elif char in "]}":
            depth -= 1
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise EvidenceError("duplicate-json-key")
            value[key] = item
        return value
    def number(value, kind):
        if len(value) > 4096:
            raise EvidenceError("numeric-token-limit-reached")
        try:
            d = Decimal(value)
        except InvalidOperation:
            raise EvidenceError("invalid-numeric-token")
        if not d.is_finite() or abs(d.as_tuple().exponent) > 10000:
            raise EvidenceError("numeric-range-unsupported")
        return Number(value, kind)
    def constant(value):
        raise EvidenceError("non-finite-json-number")
    try:
        value = json.loads(text, object_pairs_hook=pairs,
                           parse_int=lambda x: number(x, "integer"),
                           parse_float=lambda x: number(x, "number"), parse_constant=constant)
    except (json.JSONDecodeError, RecursionError):
        raise EvidenceError("malformed-json")
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        budget.node(depth)
        if isinstance(item, dict):
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
    return value


def encode_numbers(value):
    """An unambiguous typed tree: an input object cannot masquerade as a numeric node."""
    if isinstance(value, Number):
        return {"type": value.kind, "lexeme": value.lexeme}
    if isinstance(value, dict):
        return {"type": "object", "value": {k: encode_numbers(v) for k, v in value.items()}}
    if isinstance(value, list):
        return {"type": "array", "value": [encode_numbers(v) for v in value]}
    if value is None:
        return {"type": "null"}
    return {"type": "boolean" if isinstance(value, bool) else "string", "value": value}


def record_array(value, key=None):
    if key is not None:
        if not isinstance(value, dict) or key not in value:
            raise EvidenceError("records-key-missing")
        value = value[key]
    if not isinstance(value, list):
        raise EvidenceError("record-array-required")
    return value


def analyze_json(raw, report, budget, field=None, records_key=None, **unused):
    value = exact_json(raw, budget)
    rows = record_array(value, records_key) if field is not None or records_key is not None else None
    population = rows if rows is not None else value if isinstance(value, list) else [value]
    if len(population) > budget.limits.records:
        raise EvidenceError("record-limit-reached")
    report["data"].update({"value_encoding": "typed-tree-v1", "value": encode_numbers(value)})
    report["scope"] = "one UTF-8 JSON document; number lexemes preserved"
    if field is None:
        for unused_row in population:
            budget.record()
        return
    selected = []
    invalid = []
    maximum = None
    ties = []
    for index, row in enumerate(rows):
        budget.record()
        if not isinstance(row, dict) or not isinstance(row.get(field), Number):
            invalid.append(index)
            continue
        n = row[field]
        candidate = n.decimal()
        selected.append({"record_index": index, "number_type": n.kind, "lexeme": n.lexeme})
        if maximum is None or candidate > maximum:
            maximum = candidate
            ties = [index]
        elif candidate == maximum:
            ties.append(index)
    report["data"]["numeric_selection"] = {"direct_field": field, "records_key": records_key,
        "selected": selected, "invalid_record_indexes": invalid,
        "maximum_record_indexes": ties, "maximum_lexemes": [rows[i][field].lexeme for i in ties],
        "observed_records": len(rows)}
    if invalid:
        incomplete(report, "selected-field-missing-or-not-numeric")
    if not selected:
        incomplete(report, "empty-numeric-population")


def auth_class(event):
    identity = event.get("userIdentity")
    if not isinstance(identity, dict):
        return "unknown"
    # Only explicit anonymous labels are recognized. Missing identity is not anonymity.
    labels = [identity.get(k) for k in ("type", "accountId", "principalId")]
    if any(isinstance(v, str) and v.lower() in ("anonymous", "anonymous_principal") for v in labels):
        if any(identity.get(k) for k in ("accessKeyId", "arn")):
            return "unknown"
        return "anonymous"
    identity_type = identity.get("type")
    known = {"Root", "IAMUser", "AssumedRole", "FederatedUser", "AWSAccount", "AWSService",
             "IdentityCenterUser", "Role", "Directory"}
    if (isinstance(identity_type, str) and identity_type in known
            and any(isinstance(identity.get(k), str) and identity[k] for k in ("arn", "principalId", "accessKeyId"))):
        return "authenticated"
    return "unknown"


def operation_outcome(event):
    if any(event.get(k) not in (None, "") for k in ("errorCode", "errorMessage")):
        return "failure"
    response = event.get("responseElements")
    if event.get("eventName") == "ConsoleLogin":
        value = response.get("ConsoleLogin") if isinstance(response, dict) else None
        if value == "Success":
            return "recorded-success"
        if value == "Failure":
            return "failure"
        return "unknown"
    if (event.get("eventType") == "AwsApiCall" and
            isinstance(event.get("eventSource"), str) and isinstance(event.get("eventName"), str)):
        return "no-recorded-api-error"
    return "unknown"


def parse_time(value, allow_100ns=False):
    if not isinstance(value, str):
        raise EvidenceError("invalid-time-value")
    shape = re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.(\d+))?(?:Z|[+-]\d\d:\d\d)", value)
    if shape is None:
        raise EvidenceError("rfc3339-time-with-timezone-required")
    digits = shape.group(1)
    if digits and len(digits) > (7 if allow_100ns else 6):
        raise EvidenceError("submicrosecond-time-not-supported")
    if digits and allow_100ns:
        # Calendar validation only; the XML reader retains the original 100 ns text.
        value = value[:shape.start(1)] + digits[:6] + value[shape.end(1):]
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise EvidenceError("invalid-time-value")
    if dt.tzinfo is None:
        raise EvidenceError("timezone-required")
    return dt.astimezone(UTC)


def analyze_cloudtrail(raw, report, budget, since=None, until=None, **unused):
    value = exact_json(raw, budget)
    rows = record_array(value, "Records" if isinstance(value, dict) else None)
    report["scope"] = "unique nonconflicting eventID records in the supplied export and selected interval"
    unique = {}
    duplicates = 0
    collisions = set()
    missing = []
    for index, row in enumerate(rows):
        budget.record()
        if not isinstance(row, dict) or not isinstance(row.get("eventID"), str) or not row["eventID"]:
            missing.append(index)
            continue
        eid = row["eventID"]
        fingerprint = digest(json.dumps(encode_numbers(row), ensure_ascii=True, sort_keys=True,
                                        separators=(",", ":")).encode())
        if eid not in unique:
            unique[eid] = (index, row, fingerprint)
        elif unique[eid][2] == fingerprint:
            duplicates += 1
        else:
            collisions.add(eid)
    result = []
    groups = {}
    outside = 0
    for eid, (index, row, fingerprint) in unique.items():
        budget.check()
        if eid in collisions:
            continue
        try:
            when = parse_time(row.get("eventTime"))
        except EvidenceError:
            incomplete(report, "event-time-missing-or-invalid")
            continue
        if (since and when < since) or (until and when >= until):
            outside += 1
            continue
        auth = auth_class(row)
        outcome = operation_outcome(row)
        category = row.get("eventCategory")
        if category not in ("Management", "Data", "NetworkActivity"):
            category = "unknown"
        source = row.get("eventSource") if isinstance(row.get("eventSource"), str) else "unknown"
        action = row.get("eventName") if isinstance(row.get("eventName"), str) else "unknown"
        if "unknown" in (auth, outcome, category, source, action):
            incomplete(report, "unclassified-event-population")
        key = (source, action, category, auth, outcome)
        groups[key] = groups.get(key, 0) + 1
        result.append({"event_id": eid, "record_index": index, "event_time": row.get("eventTime"),
                       "event_source": source, "action": action, "category": category,
                       "authentication": auth, "outcome": outcome,
                       "principal": encode_numbers(row.get("userIdentity")),
                       "request_parameters": encode_numbers(row.get("requestParameters")),
                       "response_elements": encode_numbers(row.get("responseElements")),
                       # As recorded by the service: an address or a service name, not proof of the actor.
                       "source_ip_address": encode_numbers(row.get("sourceIPAddress")),
                       "user_agent": encode_numbers(row.get("userAgent")),
                       "aws_region": encode_numbers(row.get("awsRegion")),
                       "error_code": encode_numbers(row.get("errorCode"))})
    report["data"].update({"records": result, "input_records": len(rows), "duplicate_records": duplicates,
        "conflicting_event_ids": sorted(collisions), "missing_event_id_record_indexes": missing,
        "outside_interval": outside, "groups": [dict(zip(("event_source", "action", "category",
            "authentication", "outcome", "events"), key + (count,))) for key, count in sorted(groups.items())]})
    if collisions:
        incomplete(report, "conflicting-event-id-records-excluded")
    if missing:
        incomplete(report, "missing-event-id-records-excluded")
    note(report, "no-recorded-api-error-is-not-completed-transfer-or-exfiltration")
    note(report, "export-completeness-and-source-authenticity-not-established")


def analyze_email(raw, report, budget, email_format="auto", **unused):
    report["scope"] = "message headers and decoded MIME leaf metadata; no content execution or authentication verification"
    report["data"]["trust"] = {"header_assertions": "unverified", "cryptographic_verification": False,
        "reason": "receiver names and authserv-id are claims; corroborate provider trace and boundary policy"}
    messages = report["data"]["messages"] = []
    if email_format == "auto":
        email_format = "mbox" if raw.startswith(b"From ") else "eml"
    report["data"]["format"] = email_format
    def inspect_message(data, index):
        budget.record()
        msg = BytesParser(policy=policy.default).parsebytes(data)
        headers = []
        for name, value in msg.raw_items():
            budget.node()
            if len(value) > 65536:
                raise EvidenceError("header-size-limit-reached")
            headers.append({"name": name, "raw_value": value})
        item = {"message_index": index, "message_sha256": digest(data), "bytes": len(data),
                "headers": headers, "parts": [], "defects": []}
        if not headers:
            incomplete(report, "message-without-headers")
        stack = [(msg, "1", 0)]
        while stack:
            part, coordinate, depth = stack.pop()
            budget.node(depth)
            for mime_header in ("Content-Type", "Content-Disposition", "Content-Transfer-Encoding"):
                if len(part.get_all(mime_header, [])) > 1:
                    item["defects"].append({"part": coordinate, "kind": "Duplicate" + mime_header + "Header"})
            payload = part.get_payload()
            if isinstance(payload, list):
                for n, child in reversed(list(enumerate(payload, 1))):
                    stack.append((child, coordinate + "." + str(n), depth + 1))
            else:
                cte = str(part.get("Content-Transfer-Encoding", "")).strip().lower()
                if len(part.get_all("Content-Transfer-Encoding", [])) > 1 or cte not in ("", "7bit", "8bit", "binary", "base64", "quoted-printable"):
                    incomplete(report, "unsupported-content-transfer-encoding")
                    item["parts"].append({"coordinate": coordinate, "content_type": part.get_content_type(),
                        "disposition": part.get_content_disposition(), "filename": part.get_filename(),
                        "transfer_encoding": cte, "decoded_bytes": None, "decoded_sha256": None})
                    continue
                decoded = part.get_payload(decode=True)
                if decoded is None:
                    decoded = b""
                    incomplete(report, "mime-leaf-without-decodable-payload")
                if len(decoded) > budget.limits.bytes:
                    raise EvidenceError("decoded-part-byte-limit-reached")
                item["parts"].append({"coordinate": coordinate, "content_type": part.get_content_type(),
                    "disposition": part.get_content_disposition(), "filename": part.get_filename(),
                    "transfer_encoding": str(part.get("Content-Transfer-Encoding", "")),
                    "decoded_bytes": len(decoded), "decoded_sha256": digest(decoded)})
            for defect in part.defects:
                item["defects"].append({"part": coordinate, "kind": type(defect).__name__})
        for header in ("From", "Sender", "Reply-To", "Date", "Message-ID"):
            if len(msg.get_all(header, [])) > 1:
                item["defects"].append({"part": "1", "kind": "Duplicate" + header + "Header"})
        if item["defects"]:
            incomplete(report, "message-parse-or-header-defects")
        messages.append(item)
    if email_format == "eml":
        inspect_message(raw, 0)
    else:
        if raw and not raw.startswith(b"From "):
            raise EvidenceError("mbox-envelope-required")
        # Python's mailbox parser operates only on a throwaway private copy, never the input.
        with tempfile.TemporaryDirectory(prefix="blue-mail-") as directory:
            private = Path(directory) / "mailbox"
            private.write_bytes(raw)
            os.chmod(private, 0o600)
            box = mailbox.mbox(str(private), create=False)
            try:
                for index, key in enumerate(box.iterkeys()):
                    budget.check()
                    inspect_message(box.get_bytes(key, from_=False), index)
            finally:
                box.close()
        note(report, "mbox-splitting-uses-standard-library-envelope-convention")
        note(report, "mbox-message-digests-cover-parser-delimited-bytes-not-original-offset-slices")
    note(report, "sender-claims-and-authentication-results-have-not-been-validated")
    note(report, "mailbox-provider-coverage-and-user-interaction-not-established")


def tag_name(tag):
    if tag.startswith("{"):
        ns, name = tag[1:].split("}", 1)
        if ns != EVENT_NS:
            raise EvidenceError("unsupported-event-xml-namespace")
        return name
    return tag


def direct(parent, name, required=True):
    values = [e for e in parent if tag_name(e.tag) == name]
    if len(values) > 1 or (required and not values):
        raise EvidenceError("missing-or-duplicate-event-system-field")
    return values[0] if values else None


def analyze_evtx_xml(raw, report, budget, **unused):
    report["scope"] = "UTF-8 Event/Events XML export, direct System fields and named EventData only; not binary EVTX"
    if raw.startswith(b"ElfFile"):
        raise EvidenceError("binary-evtx-not-supported-use-xml-export")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise EvidenceError("event-xml-utf8-required")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
        raise EvidenceError("xml-dtd-or-entity-forbidden")
    declaration = re.match(r"\s*<\?xml\b[^?]*\bencoding\s*=\s*(['\"])(.*?)\1", text, re.IGNORECASE)
    if declaration and declaration.group(2).lower() not in ("utf-8", "utf8"):
        raise EvidenceError("event-xml-utf8-required")
    events = report["data"]["events"] = []
    depth = 0
    root_name = None
    event_index = 0
    for action, element in ET.iterparse(io.BytesIO(raw), events=("start", "end")):
        name = tag_name(element.tag)
        if action == "start":
            depth += 1
            budget.node(depth)
            if root_name is None:
                root_name = name
                if name not in ("Event", "Events"):
                    raise EvidenceError("event-xml-root-required")
            elif root_name == "Events" and depth == 2 and name != "Event":
                raise EvidenceError("unsupported-events-child")
            continue
        if name == "Event":
            budget.record()
            index = event_index
            event_index += 1
            expected_depth = 1 if root_name == "Event" else 2
            if depth != expected_depth:
                raise EvidenceError("nested-event-record-not-supported")
            system = direct(element, "System")
            provider = direct(system, "Provider")
            event_id = direct(system, "EventID")
            record_id = direct(system, "EventRecordID", False)
            created = direct(system, "TimeCreated")
            eid = (event_id.text or "").strip()
            if not re.fullmatch(r"[0-9]{1,5}", eid) or int(eid) > 65535:
                raise EvidenceError("invalid-direct-event-id")
            timestamp = created.attrib.get("SystemTime")
            if not isinstance(timestamp, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,7})?Z", timestamp):
                raise EvidenceError("invalid-event-system-time")
            parse_time(timestamp, allow_100ns=True)
            if not provider.attrib.get("Name") and not provider.attrib.get("Guid"):
                raise EvidenceError("event-provider-missing")
            fields = []
            data = direct(element, "EventData", False)
            seen = set()
            if data is not None:
                for child in data:
                    if tag_name(child.tag) != "Data" or len(child):
                        incomplete(report, "event-data-shape-unsupported")
                        continue
                    key = child.attrib.get("Name")
                    if not key or key in seen:
                        incomplete(report, "event-data-name-missing-or-duplicate")
                    seen.add(key)
                    fields.append({"name": key, "value": child.text or ""})
            row = {"event_index": index, "location": "/Event" if root_name == "Event" else "/Events/Event[" + str(index + 1) + "]",
                "provider": dict(provider.attrib), "event_id": int(eid), "event_id_text": eid,
                "event_record_id_text": record_id.text if record_id is not None else None,
                "system_time": timestamp, "event_data": fields}
            for key in ("Computer", "Channel"):
                item = direct(system, key, False)
                row[key.lower()] = item.text if item is not None else None
            row["user_data_present"] = direct(element, "UserData", False) is not None
            if row["user_data_present"]:
                note(report, "user-data-not-expanded")
            events.append(row)
            element.clear()
        depth -= 1
    note(report, "xml-export-does-not-establish-binary-channel-completeness")


def browser_stamp_group(path):
    result = {}
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = Path(str(path) + suffix)
        if p.exists() or p.is_symlink():
            result[suffix] = stamp(p)
    return result


def browser_timestamp(value, chromium):
    if type(value) is not int or value <= 0:
        return {"raw": value, "utc": None, "valid_event_time": False}
    epoch = datetime(1601 if chromium else 1970, 1, 1, tzinfo=UTC)
    try:
        when = epoch + timedelta(microseconds=value)
    except (OverflowError, ValueError):
        return {"raw": value, "utc": None, "valid_event_time": False}
    return {"raw": value, "utc": when.isoformat().replace("+00:00", "Z"), "valid_event_time": True}


def analyze_browser(path, raw, primary_stamp, report, budget, since=None, until=None, **unused):
    report["scope"] = "supported history tables and Chromium download metadata in a stable acquired DB/sidecar set"
    if not raw.startswith(b"SQLite format 3\0"):
        raise EvidenceError("sqlite-database-required")
    before = browser_stamp_group(path)
    if before.get("") != primary_stamp:
        raise EvidenceError("database-changed-before-snapshot")
    if before.get("-journal", (0, 0, 0))[2]:
        raise EvidenceError("rollback-journal-not-supported")
    payloads = {"": raw}
    total = len(raw)
    for suffix in ("-wal", "-shm"):
        if suffix in before:
            value, captured = read_input(Path(str(path) + suffix), budget)
            if captured != before[suffix]:
                raise EvidenceError("sidecar-changed-during-snapshot")
            total += len(value)
            if total > budget.limits.bytes:
                raise EvidenceError("aggregate-database-byte-limit-reached")
            payloads[suffix] = value
    if browser_stamp_group(path) != before:
        raise EvidenceError("database-set-changed-during-snapshot")
    report["data"]["snapshot"] = {suffix or "database": {"sha256": digest(value), "bytes": len(value)}
                                      for suffix, value in payloads.items()}
    with tempfile.TemporaryDirectory(prefix="metis-browser-") as directory:
        private = Path(directory) / "evidence.sqlite"
        for suffix, value in payloads.items():
            target = Path(str(private) + suffix)
            target.write_bytes(value)
            os.chmod(target, 0o600)
        connection = sqlite3.connect(private.as_uri() + "?mode=ro", uri=True, timeout=0.1)
        try:
            if hasattr(connection, "enable_load_extension"):
                connection.enable_load_extension(False)
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.set_progress_handler(lambda: 1 if time.monotonic() >= budget.end else 0, 500)
            if connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise EvidenceError("database-integrity-check-failed")
            schema = {name: (kind, sql, page) for name, kind, sql, page in connection.execute(
                "SELECT name, type, sql, rootpage FROM sqlite_master")}
            chromium = "urls" in schema and "visits" in schema
            firefox = "moz_places" in schema and "moz_historyvisits" in schema
            if chromium == firefox:
                raise EvidenceError("unsupported-or-ambiguous-browser-schema")
            report["data"]["browser_family"] = "chromium" if chromium else "firefox"
            specs = ([
                ("urls", ("id", "url"), ("id", "url", "title", "visit_count", "typed_count", "last_visit_time"), None),
                ("visits", ("id", "url", "visit_time"), ("id", "url", "visit_time", "from_visit", "transition"), "visit_time"),
                ("downloads", ("id", "state", "start_time", "end_time", "received_bytes", "total_bytes"),
                 ("id", "target_path", "current_path", "start_time", "end_time", "received_bytes", "total_bytes", "state", "tab_url"), "start_time"),
                ("downloads_url_chains", ("id", "chain_index", "url"), ("id", "chain_index", "url"), None)] if chromium else [
                ("moz_places", ("id", "url"), ("id", "url", "title", "visit_count", "last_visit_date"), None),
                ("moz_historyvisits", ("id", "place_id", "visit_date"), ("id", "place_id", "from_visit", "visit_date", "visit_type"), "visit_date")])
            allowed = {}
            for table, required, columns, time_field in specs:
                if table not in schema:
                    if table in ("downloads", "downloads_url_chains"):
                        note(report, table + "-table-unavailable")
                        continue
                    raise EvidenceError("required-history-table-missing")
                kind, sql, page = schema[table]
                if kind != "table" or not page or not sql or re.match(r"\s*CREATE\s+VIRTUAL\b", sql, re.IGNORECASE):
                    raise EvidenceError("browser-table-must-be-ordinary-table")
                info = list(connection.execute('PRAGMA table_xinfo("' + table + '")'))
                actual = {row[1] for row in info}
                if not set(required).issubset(actual):
                    raise EvidenceError("unsupported-browser-table-columns")
                chosen = tuple(c for c in columns if c in actual)
                if any(row[1] in chosen and len(row) > 6 and row[6] for row in info):
                    raise EvidenceError("generated-browser-column-not-supported")
                allowed[table] = (chosen, time_field)
            def authorize(action, first, second, database, trigger):
                if action == sqlite3.SQLITE_SELECT:
                    return sqlite3.SQLITE_OK
                if action == sqlite3.SQLITE_READ and first in allowed and second in allowed[first][0] and not trigger:
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY
            connection.set_authorizer(authorize)
            tables = report["data"]["tables"] = {}
            for table, (columns, time_field) in allowed.items():
                budget.check()
                query = 'SELECT ' + ','.join('"' + c + '"' for c in columns) + ' FROM "' + table + '"'
                values = []
                query += ' ORDER BY "id" LIMIT ?'
                values.append(budget.limits.records - budget.records + 1)
                result = tables[table] = []
                for raw_row in connection.execute(query, values):
                    budget.record()
                    row = dict(zip(columns, raw_row))
                    if any(isinstance(v, bytes) for v in row.values()):
                        raise EvidenceError("binary-browser-field-not-supported")
                    if type(row.get("id")) is not int:
                        incomplete(report, "invalid-browser-row-id")
                    url_field = "url" if table in ("urls", "moz_places", "downloads_url_chains") else None
                    if url_field and not isinstance(row[url_field], str):
                        incomplete(report, "invalid-browser-url")
                    foreign_key = "url" if table == "visits" else "place_id" if table == "moz_historyvisits" else None
                    if foreign_key and type(row[foreign_key]) is not int:
                        incomplete(report, "invalid-browser-visit-link")
                    for c in ("visit_time", "last_visit_time", "start_time", "end_time", "visit_date", "last_visit_date"):
                        if c in row:
                            stamp_result = browser_timestamp(row[c], chromium)
                            row[c + "_decoded"] = stamp_result
                            if c == time_field and not stamp_result["valid_event_time"]:
                                incomplete(report, "invalid-browser-event-time")
                    if time_field and (since or until):
                        decoded_time = row[time_field + "_decoded"]
                        if not decoded_time["valid_event_time"]:
                            row["in_requested_interval"] = None
                        else:
                            when = parse_time(decoded_time["utc"])
                            if (since and when < since) or (until and when >= until):
                                report["data"]["outside_interval_rows"] = report["data"].get("outside_interval_rows", 0) + 1
                                continue
                            row["in_requested_interval"] = True
                    if table == "downloads":
                        state = row["state"]
                        good_counts = all(type(row[c]) is int and row[c] >= 0 for c in ("received_bytes", "total_bytes"))
                        row["recorded_complete"] = bool(type(state) is int and state == 1 and good_counts
                            and row["received_bytes"] == row["total_bytes"] and row["end_time_decoded"]["valid_event_time"])
                        row["downloaded_file_verified"] = False
                        if type(state) is not int or state not in (0, 1, 2, 3):
                            incomplete(report, "unknown-download-state")
                        if not good_counts:
                            incomplete(report, "invalid-download-byte-count")
                        if state == 1 and not row["recorded_complete"]:
                            incomplete(report, "completed-download-metadata-inconsistent")
                    result.append(row)
            if firefox:
                note(report, "firefox-download-history-not-supported")
            note(report, "URL-metadata-rows-are-not-individual-visits")
            note(report, "download-completion-metadata-does-not-verify-file-content")
            note(report, "snapshot-stability-does-not-establish-complete-device-history")
            if since or until:
                note(report, "time-filter-applies-to-visit-and-download-start-events-only")
        finally:
            connection.close()
    if browser_stamp_group(path) != before:
        raise EvidenceError("source-database-set-changed-during-analysis")


def analyze(kind, path, limits=None, **options):
    limits = limits or Limits()
    budget = Budget(limits)
    report = {"schema_version": 1, "reader_version": VERSION, "kind": kind,
              "complete_for_input": True, "limitations": [], "data": {}, "source": {},
              "scope": "bounded supplied input only; no incident verdict", "limits": vars(limits)}
    path = Path(os.path.abspath(path))
    try:
        with wall_limit(limits.seconds) as enforcement:
            report["time_limit_enforcement"] = enforcement
            raw, initial = read_input(path, budget)
            report["source"] = {"sha256": digest(raw), "bytes": len(raw)}
            for bound in ("since", "until"):
                if options.get(bound) is not None:
                    if isinstance(options[bound], datetime):
                        if options[bound].tzinfo is None or options[bound].utcoffset() is None:
                            raise EvidenceError("timezone-required")
                        options[bound] = options[bound].astimezone(UTC)
                    else:
                        options[bound] = parse_time(options[bound])
            if options.get("since") and options.get("until") and options["since"] >= options["until"]:
                raise EvidenceError("invalid-time-interval")
            if kind == "browser":
                analyze_browser(path, raw, initial, report, budget, **options)
            else:
                reader = {"json": analyze_json, "email": analyze_email, "cloudtrail": analyze_cloudtrail,
                          "evtx-xml": analyze_evtx_xml}.get(kind)
                if reader is None:
                    raise EvidenceError("unknown-reader")
                reader(raw, report, budget, **options)
            if stamp(path) != initial:
                raise EvidenceError("input-changed-during-analysis")
            budget.check()
    except EvidenceError as error:
        incomplete(report, str(error))
    except (OSError, sqlite3.Error, ET.ParseError, UnicodeError, ValueError, RecursionError, OverflowError):
        incomplete(report, "parser-or-input-failure")
    report["observed_records"] = budget.records
    return report


def write_private_report(root, output, report, inputs=()):
    """Create one new private JSON report with no-overwrite and no-follow directory traversal."""
    root = Path(root).resolve(strict=True)
    output = Path(os.path.abspath(output if Path(output).is_absolute() else root / output))
    try:
        relative = output.relative_to(root)
    except ValueError:
        raise EvidenceError("output-outside-root")
    if len(relative.parts) < 2 or relative.parts[0] != ".metis-state" or output.suffix != ".json":
        raise EvidenceError("output-must-be-new-private-json")
    if any(output == Path(os.path.abspath(p)) for p in inputs):
        raise EvidenceError("output-is-input")
    raw = (json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(raw) > MAX_OUTPUT:
        raise EvidenceError("output-byte-limit-reached")
    directory = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    temp = None
    try:
        for part in relative.parts[:-1]:
            try:
                os.mkdir(part, 0o700, dir_fd=directory)
            except FileExistsError:
                pass
            following = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory)
            os.close(directory)
            directory = following
        temp = ".artifact-report-" + secrets.token_hex(12)
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=directory)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, relative.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        os.fsync(directory)
    finally:
        if temp is not None:
            try:
                os.unlink(temp, dir_fd=directory)
            except FileNotFoundError:
                pass
        os.close(directory)
    return output


def analyze_bytes(kind, data, limits=None, **options):
    """Run a reader on in-memory bytes (a METIS run artifact) through a private 0600 snapshot."""
    with tempfile.TemporaryDirectory(prefix="metis-evidence-") as directory:
        os.chmod(directory, 0o700)
        path = Path(directory) / "input"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        return analyze(kind, path, limits, **options)


def add_arguments(parser):
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, help="new private JSON under .metis-state/ (default: stdout)")
    parser.add_argument("--max-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--max-records", type=int, default=10000)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--field", help="JSON: direct numeric field for exact maximum, retaining all ties")
    parser.add_argument("--records-key", help="JSON: direct root key containing the record array")
    parser.add_argument("--since", help="CloudTrail/browser: inclusive RFC3339 start, at most 6 fractional digits")
    parser.add_argument("--until", help="CloudTrail/browser: exclusive RFC3339 end, at most 6 fractional digits")
    parser.add_argument("--email-format", choices=("auto", "eml", "mbox"), default="auto")


def run(args, root=None):
    try:
        limits = Limits(args.max_bytes, args.max_records, args.seconds)
        limits.validate()
        if (args.field or args.records_key) and args.kind != "json":
            raise EvidenceError("json-option-on-other-reader")
        if (args.since or args.until) and args.kind not in ("cloudtrail", "browser"):
            raise EvidenceError("time-option-on-other-reader")
        report = analyze(args.kind, args.input, limits, field=args.field, records_key=args.records_key,
                         since=args.since, until=args.until, email_format=args.email_format)
        if args.out is None:
            print(json.dumps(report, ensure_ascii=True, sort_keys=True, allow_nan=False))
            return 0 if report["complete_for_input"] else 2
        base = Path(root or os.getcwd())
        try:
            write_private_report(base, args.out, report,
                                 [Path(str(args.input) + s) for s in ("", "-wal", "-shm", "-journal")])
        except EvidenceError as error:
            if str(error) != "output-byte-limit-reached":
                raise
            report["data"] = {}
            incomplete(report, "output-byte-limit-reached")
            write_private_report(base, args.out, report, [args.input])
        print(json.dumps({"complete_for_input": report["complete_for_input"], "kind": args.kind,
                          "observed_records": report["observed_records"], "limitations": report["limitations"]}))
        return 0 if report["complete_for_input"] else 2
    except (EvidenceError, OSError, ValueError):
        print(json.dumps({"status": "blocked", "reason": "invalid-input-limits-or-private-output"}))
        return 2

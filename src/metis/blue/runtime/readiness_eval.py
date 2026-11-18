"""Bundle synthetic evidence questions without answers, then score a frozen model response.

This is a small readiness regression protocol, not a general analyst-tier certification.
Run as ``python3 -m metis.blue.runtime.readiness_eval bundle|score|run-ollama --help``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from . import BLUE_ROOT
from .knowledge_intake import confined_path, safe_read

ROOT = BLUE_ROOT
PROTOCOL = "blue-readiness-v1"
PROTOCOL_V2 = "blue-readiness-v2"
PROTOCOL_ALIASES = {"v1": PROTOCOL, "v2": PROTOCOL_V2, PROTOCOL: PROTOCOL, PROTOCOL_V2: PROTOCOL_V2}
V2_TERMINAL_CONTRACT = (
    "\nFINAL OUTPUT CONTRACT: Return only the requested JSON object in the final channel, "
    "starting with { and ending with }. No explanations, Markdown, or code fences. "
    "Do not call any tool, including no-op, preflight, or placeholder actions. "
    "Make the requested judgments only.\n"
)
MAX_CASES = 64
MAX_CASE_BYTES = 256 * 1024
MAX_REFERENCE_BYTES = 256 * 1024
MAX_TOTAL_REFERENCE_BYTES = 2 * 1024 * 1024
MAX_ANSWER_BYTES = 1024 * 1024
USAGE_KEYS = ("input_tokens", "output_tokens", "cached_input_tokens", "total_tokens")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate-json-key")
        result[key] = value
    return result


def parse_json(data):
    def invalid_constant(_):
        raise ValueError("non-finite-number")
    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("non-finite-number")
        return parsed
    return json.loads(data, object_pairs_hook=strict_pairs, parse_constant=invalid_constant, parse_float=finite_float)


def private_path(root, path):
    root = root.resolve()
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.relative_to(root)
        except ValueError:
            raise ValueError("output-outside-private-workspace") from None
    if p.parts[:2] != (".state", "benchmarks") or len(p.parts) < 3:
        raise ValueError("private-benchmark-path-required")
    return confined_path(root, p.as_posix())


def write_private(root, path, data, replace=True):
    target = private_path(root, path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = private_path(root, path)
    if target.exists() and not target.is_file():
        raise ValueError("output-not-regular-file")
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".readiness-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # The temporary file is mode 0600; replace does not follow an existing leaf link.
        private_path(root, path)
        if replace:
            os.replace(name, target)
        else:
            os.link(name, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return target


def value_schema(value):
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is str:
        return "string"
    if type(value) is list and 0 < len(value) <= 32:
        if type(value[0]) not in (bool, int, str) or any(type(x) is not type(value[0]) for x in value):
            raise ValueError("expected-array-must-be-homogeneous-scalars")
        return "array[" + value_schema(value[0]) + "]"
    raise ValueError("unsupported-expected-value-type")


def reference_path(root, name):
    if not isinstance(name, str) or not (name == "AGENTS.md" or name.startswith("skills/")) or not name.endswith(".md"):
        raise ValueError("reference-must-be-an-operating-contract-or-skill")
    return confined_path(root, name)


def read_cases(root, relative):
    path = confined_path(root, relative)
    if not relative.startswith("examples/") or path.suffix != ".json":
        raise ValueError("case-file-must-be-under-examples")
    raw = safe_read(path, MAX_CASE_BYTES)
    cases = parse_json(raw)
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise ValueError("invalid-case-count")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "question", "references", "expected"}:
            raise ValueError("invalid-case-schema")
        if not isinstance(case["id"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", case["id"]) or case["id"] in ids:
            raise ValueError("invalid-or-duplicate-case-id")
        ids.add(case["id"])
        if not isinstance(case["question"], str) or not case["question"].strip() or len(case["question"]) > 10000:
            raise ValueError("invalid-question")
        if not isinstance(case["references"], list) or not 1 <= len(case["references"]) <= 16:
            raise ValueError("invalid-references")
        for name in case["references"]:
            reference_path(root, name)
        if not isinstance(case["expected"], dict) or not 1 <= len(case["expected"]) <= 32:
            raise ValueError("invalid-answer-schema")
        for name, value in case["expected"].items():
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", name):
                raise ValueError("invalid-answer-key")
            value_schema(value)
    return cases, digest(raw)


def normalize_protocol(protocol):
    if not isinstance(protocol, str) or protocol not in PROTOCOL_ALIASES:
        raise ValueError("unsupported-readiness-protocol")
    return PROTOCOL_ALIASES[protocol]


def build_payload(root, cases_relative, protocol=PROTOCOL):
    protocol = normalize_protocol(protocol)
    cases, cases_hash = read_cases(root, cases_relative)
    names = list(dict.fromkeys(name for case in cases for name in case["references"]))
    parts = [
        ("Synthetic offline METIS readiness questions. Use only the supplied evidence and guidance. "
        "Do not use tools, browse, create case state, or take external actions. "
        "Return exactly one JSON object keyed by the case IDs. Each value must contain only "
        "the listed answer fields, with the stated JSON types. No explanations or code fences. "
        "Array order matters where the question specifies it. Missing evidence must not be invented.\n")
    ]
    references = []
    total = 0
    for name in names:
        raw = safe_read(reference_path(root, name), MAX_REFERENCE_BYTES)
        total += len(raw)
        if total > MAX_TOTAL_REFERENCE_BYTES:
            raise ValueError("reference-byte-budget-exceeded")
        text = raw.decode("utf-8")
        references.append({"path": name, "sha256": digest(raw)})
        parts.append("\nREFERENCE " + name + "\n" + text + "\nEND REFERENCE\n")
    schemas = []
    for case in cases:
        schema = {key: value_schema(value) for key, value in case["expected"].items()}
        schemas.append({"id": case["id"], "fields": schema})
        parts.append("\nCASE " + case["id"] + "\n" + case["question"] +
                     "\nANSWER FIELD TYPES " + json.dumps(schema, ensure_ascii=False, sort_keys=True) + "\n")
    if protocol == PROTOCOL_V2:
        parts.append(V2_TERMINAL_CONTRACT)
    text = "".join(parts).encode("utf-8")
    return text, {
        "schema_version": 1, "protocol": protocol, "cases_path": cases_relative,
        "cases_sha256": cases_hash, "prompt_sha256": digest(text), "references": references,
        "answer_schemas": schemas, "case_count": len(cases),
        "field_count": sum(len(case["expected"]) for case in cases),
    }


def bundle(root=ROOT, out=None, cases_relative="examples/readiness-cases.json", protocol=PROTOCOL):
    root = Path(root).resolve()
    output = private_path(root, out)
    if not output.name.endswith(".prompt.txt"):
        raise ValueError("bundle-output-must-end-with-prompt-txt")
    metadata_path = output.with_name(output.name[:-len(".prompt.txt")] + ".meta.json")
    text, metadata = build_payload(root, cases_relative, protocol)
    metadata.update(prompt_path=str(output.relative_to(root)), created_at_utc=datetime.now(UTC).isoformat())
    write_private(root, output, text)
    write_private(root, metadata_path, (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode())
    return {"prompt": str(output), "metadata": str(metadata_path), "cases": metadata["case_count"], "fields": metadata["field_count"]}


def types_match(actual, expected):
    if type(actual) is not type(expected):
        return False
    if type(expected) is list:
        return all(type(item) is type(expected[0]) for item in actual)
    return True


def same_typed_value(actual, expected):
    if type(actual) is not type(expected):
        return False
    if type(expected) is list:
        return len(actual) == len(expected) and all(same_typed_value(a, b) for a, b in zip(actual, expected))
    return actual == expected


def usage_record(value):
    result = {key: None for key in USAGE_KEYS}
    if value is None:
        return {"source": "unavailable", **result}
    if not isinstance(value, dict) or set(value) - set(USAGE_KEYS):
        raise ValueError("invalid-usage-schema")
    for key, count in value.items():
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError("invalid-usage-count")
        result[key] = count
    return {"source": "operator-supplied", **result}


def frozen_bundle(root, bundle_meta):
    raw_metadata = safe_read(private_path(root, bundle_meta), MAX_CASE_BYTES)
    metadata = parse_json(raw_metadata)
    if not isinstance(metadata, dict) or metadata.get("protocol") not in {PROTOCOL, PROTOCOL_V2}:
        raise ValueError("invalid-bundle-metadata")
    text, current = build_payload(root, metadata.get("cases_path", ""), metadata["protocol"])
    required_keys = set(current) | {"prompt_path", "created_at_utc"}
    if set(metadata) != required_keys:
        raise ValueError("invalid-bundle-metadata-schema")
    stale = [key for key in current if metadata[key] != current[key]]
    stored = safe_read(private_path(root, metadata["prompt_path"]), MAX_TOTAL_REFERENCE_BYTES + MAX_CASE_BYTES * 4)
    if digest(stored) != metadata["prompt_sha256"] or stored != text:
        stale.append("prompt-file")
    if stale:
        raise ValueError("stale-or-modified-bundle")
    return text, metadata, digest(raw_metadata)


def score(root=ROOT, answer=None, bundle_meta=None, model=None, provider=None, usage=None):
    root = Path(root).resolve()
    if provider not in {"desktop", "ollama"} or not isinstance(model, str) or not model.strip() or len(model) > 200 or any(ord(c) < 32 for c in model):
        raise ValueError("explicit-provider-and-model-required")
    _, metadata, metadata_hash = frozen_bundle(root, bundle_meta)
    cases, current_case_hash = read_cases(root, metadata["cases_path"])
    if current_case_hash != metadata["cases_sha256"]:
        raise ValueError("stale-or-modified-bundle")
    raw = safe_read(Path(answer), MAX_ANSWER_BYTES)
    errors = []
    try:
        responses = parse_json(raw)
    except (ValueError, UnicodeError, RecursionError):
        responses = None
        errors.append("invalid-answer-json")
    if not isinstance(responses, dict):
        responses = {}
        errors.append("answer-root-must-be-object")
    wanted = {case["id"] for case in cases}
    missing = sorted(wanted - set(responses))
    extra = sorted(set(responses) - wanted)
    if missing:
        errors.append("missing-case-keys")
    if extra:
        errors.append("extra-case-keys")
    rows = []
    for case in cases:
        expected = case["expected"]
        supplied = responses.get(case["id"])
        object_valid = isinstance(supplied, dict)
        supplied = supplied if object_valid else {}
        missing_fields = sorted(set(expected) - set(supplied))
        extra_fields = sorted(set(supplied) - set(expected))
        fields = [{"field": key, "correct": key in supplied and same_typed_value(supplied[key], value),
                   "type_matches": key in supplied and types_match(supplied[key], value)}
                  for key, value in expected.items()]
        passed = object_valid and not missing_fields and not extra_fields and all(row["correct"] for row in fields)
        rows.append({"id": case["id"], "passed": passed, "missing_fields": missing_fields,
                     "extra_fields": extra_fields, "fields": fields})
    return {
        "protocol": metadata["protocol"], "status": "passed" if not errors and all(r["passed"] for r in rows) else "failed",
        "provider": provider, "model": model, "model_identity_basis": "operator-supplied; verify against UI or API receipt",
        "bundle_sha256": metadata_hash,
        "prompt_sha256": metadata["prompt_sha256"], "cases_sha256": metadata["cases_sha256"],
        "references": metadata["references"], "answer_sha256": digest(raw),
        "cases_passed": sum(row["passed"] for row in rows), "cases_total": len(cases),
        "fields_correct": sum(field["correct"] for row in rows for field in row["fields"]),
        "fields_total": metadata["field_count"], "missing_cases": missing, "extra_cases": extra,
        "errors": errors, "results": rows, "usage": usage_record(usage),
        "limitations": "Small synthetic regression; not production detection validation or a general analyst-tier certification.",
    }


class ResponseCapture:
    """The chat client emits only public content and provider metrics to this sink."""
    def __init__(self):
        self.answer = None
        self.metrics = {}

    def message(self, run, task, sender, recipient, kind, body):
        if kind == "benchmark-answer":
            self.answer = body
        elif kind == "provider-metrics":
            self.metrics = parse_json(body)

    def usage(self, *args, **kwargs):
        # Read raw provider metrics below so absent cache counts remain unknown.
        pass


def provider_usage(metrics):
    counts = {}
    for source, target in (("prompt_eval_count", "input_tokens"), ("eval_count", "output_tokens"),
                           ("prompt_eval_cached_count", "cached_input_tokens")):
        value = metrics.get(source)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("invalid-provider-token-count")
        counts[target] = value
    if counts["cached_input_tokens"] is not None and (counts["input_tokens"] is None or
            counts["cached_input_tokens"] > counts["input_tokens"]):
        raise ValueError("invalid-provider-cache-count")
    counts["total_tokens"] = (counts["input_tokens"] + counts["output_tokens"]
                              if counts["input_tokens"] is not None and counts["output_tokens"] is not None else None)
    return counts


def run_ollama(root=ROOT, bundle_meta=None, model=None, out=None, url=None,
               num_ctx=65536, num_predict=4096, timeout=600, client_factory=None):
    """One inference, one endpoint lock, no retries, downloads, or model tool calls."""
    from .ollama import OllamaClient
    from .skill_eval import inference_lock
    root = Path(root).resolve()
    if (type(num_ctx) is not int or not 65536 <= num_ctx <= 1048576 or
            type(num_predict) is not int or not 1 <= num_predict < num_ctx or
            type(timeout) is not int or not 1 <= timeout <= 3600 or
            not isinstance(model, str) or not model.strip() or len(model) > 200 or any(ord(c) < 32 for c in model)):
        raise ValueError("invalid-inference-settings")
    text, metadata, metadata_hash = frozen_bundle(root, bundle_meta)
    output = private_path(root, out)
    if output.suffix != ".json":
        raise ValueError("run-output-must-be-json")
    answer_path = output.with_name(output.stem + ".answer.json")
    provider_path = output.with_name(output.stem + ".provider.json")
    paths = [output, answer_path, provider_path]
    # A fresh output name is required so a retry cannot erase an earlier measurement.
    for path in paths:
        private_path(root, path)
        if path.exists():
            raise ValueError("run-output-already-exists")
    engine = (client_factory or OllamaClient)(url, timeout, num_predict=num_predict, think=False, num_ctx=num_ctx)
    # Use the same endpoint-keyed directory as the other METIS benchmark commands.
    directory = root / ".state/benchmarks"
    lock_id = "ollama-" + digest(engine.url.encode())[:16]
    private_path(root, ".state/benchmarks/" + lock_id + ".lock")
    guard = private_path(root, ".state/benchmarks/" + lock_id + ".uncertain.json")
    capture = ResponseCapture()
    result = {"protocol": metadata["protocol"], "status": "blocked", "provider": "ollama", "model": model,
              "bundle_sha256": metadata_hash,
              "prompt_sha256": metadata["prompt_sha256"], "cases_sha256": metadata["cases_sha256"],
              "references": metadata["references"], "usage": usage_record(None), "batch_stopped": True,
              "created_at_utc": datetime.now(UTC).isoformat()}
    receipt = {"endpoint": engine.url, "requested_model": model, "num_ctx": num_ctx,
               "num_predict": num_predict, "temperature": 0, "thinking": False,
               "prompt_sha256": metadata["prompt_sha256"], "metrics": {}, "request_started": False,
               "context_verification": "Requested context is recorded; server tokenization and truncation are not independently audited."}
    started = time.monotonic()
    with inference_lock(directory, engine.url):
        if guard.exists():
            raise ValueError("reconcile-provider-completion-before-new-inference")
        # Concurrent invocations cannot replace a previously completed run while awaiting the lock.
        if any(path.exists() for path in paths):
            raise ValueError("run-output-already-exists")
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        reservation = output.with_name(output.name + ".reservation")
        private_path(root, reservation)
        # mkdir is atomic across endpoints and survives interruption. This output name is spent.
        reservation.mkdir(mode=0o700)
        if any(path.exists() for path in paths):
            raise ValueError("run-output-already-exists")
        try:
            inventory = engine.inventory()
            installed = inventory.get("models")
            if not isinstance(installed, list) or not all(isinstance(item, dict) for item in installed):
                raise ValueError("invalid-model-inventory")
            if model not in {item.get("name") for item in installed}:
                raise ValueError("model-not-installed")
            receipt["installed_model"] = next(item for item in installed if item.get("name") == model)
            receipt["server_version"] = inventory.get("version")
            write_private(root, guard, json.dumps({"status": "reconciliation-required", "run_output": str(output.relative_to(root)),
                "reason": "Inference is active or completion is unknown. Confirm completion before removing this marker."}).encode())
            receipt["request_started"] = True
            response = engine.call(model, text.decode("utf-8"), capture, "readiness", "bundle")
            capture.answer, capture.metrics = response["text"], response["metrics"]
            if capture.metrics.get("done") is not True or capture.metrics.get("done_reason") == "length":
                raise ValueError("incomplete-provider-response")
            if capture.metrics.get("model") != model:
                raise ValueError("provider-model-identity-mismatch")
            if not isinstance(capture.answer, str) or not capture.answer.strip():
                raise ValueError("missing-public-answer")
            counts = provider_usage(capture.metrics)
            if len(capture.answer.encode()) > MAX_ANSWER_BYTES:
                raise ValueError("answer-byte-budget-exceeded")
            write_private(root, answer_path, capture.answer.encode(), replace=False)
            scored = score(root=root, answer=answer_path, bundle_meta=bundle_meta, model=model,
                           provider="ollama", usage=counts)
            if (scored["bundle_sha256"] != metadata_hash or scored["prompt_sha256"] != metadata["prompt_sha256"] or
                    scored["cases_sha256"] != metadata["cases_sha256"] or scored["references"] != metadata["references"]):
                raise ValueError("bundle-changed-during-inference")
            result = scored
            result.update(model_identity_basis="Installed tag matched provider response model.",
                          model_identity_verified=True, batch_stopped=True,
                          created_at_utc=datetime.now(UTC).isoformat())
            result["usage"]["source"] = "provider-reported; total is input plus output when both are known"
        except (RuntimeError, ValueError, OSError, KeyError, TypeError, UnicodeError, RecursionError):
            result.update(status="failed", reason="provider-or-response-failure", model_identity_verified=False)
            if capture.metrics.get("done_reason") == "length":
                result["reason"] = "generation-token-limit"
            if receipt["request_started"] and capture.metrics.get("done") is not True:
                result["server_completion_unknown"] = True
                write_private(root, guard, json.dumps({"status": "reconciliation-required", "run_output": str(output.relative_to(root)),
                    "reason": "Request may still occupy the endpoint. Confirm completion before removing this marker."}).encode())
        finally:
            if receipt["request_started"] and capture.metrics.get("done") is True:
                guard.unlink(missing_ok=True)
            if isinstance(capture.answer, str) and len(capture.answer.encode()) <= MAX_ANSWER_BYTES and not answer_path.exists():
                write_private(root, answer_path, capture.answer.encode(), replace=False)
            try:
                counts = provider_usage(capture.metrics)
                result["usage"] = {"source": "provider-reported" if any(v is not None for v in counts.values()) else "unavailable", **counts}
            except ValueError:
                result["usage"] = usage_record(None)
            receipt["metrics"] = capture.metrics
            receipt["seconds"] = round(time.monotonic() - started, 3)
            receipt["answer_sha256"] = digest(capture.answer.encode()) if isinstance(capture.answer, str) else None
            receipt_data = (json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
            write_private(root, provider_path, receipt_data, replace=False)
            result.update(provider_receipt=str(provider_path.relative_to(root)), provider_receipt_sha256=digest(receipt_data),
                          answer_path=str(answer_path.relative_to(root)) if answer_path.exists() else None)
            write_private(root, output, (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(), replace=False)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("bundle", help="Write a plain-text prompt and private frozen metadata")
    pack.add_argument("--out", type=Path, required=True)
    pack.add_argument("--cases", default="examples/readiness-cases.json")
    pack.add_argument("--protocol", choices=tuple(PROTOCOL_ALIASES), default=PROTOCOL,
                      help="v1 preserves the original prompt; v2 appends the final output/tool contract (default: v1)")
    grade = commands.add_parser("score", help="Score exact typed answers against the frozen bundle")
    grade.add_argument("--answer", type=Path, required=True)
    grade.add_argument("--bundle-meta", type=Path, required=True)
    grade.add_argument("--model", required=True)
    grade.add_argument("--provider", choices=["desktop", "ollama"], required=True)
    grade.add_argument("--usage", type=Path, help="Optional measured token counts; unspecified values stay null")
    grade.add_argument("--out", type=Path, required=True)
    run = commands.add_parser("run-ollama", help="Run one frozen bundle under the shared inference lock, then score")
    run.add_argument("--bundle-meta", type=Path, required=True)
    run.add_argument("--model", required=True, help="Exact installed tag; no model downloads")
    run.add_argument("--url")
    run.add_argument("--num-ctx", type=int, required=True, help="Explicit context budget, at least 65536")
    run.add_argument("--num-predict", type=int, default=4096)
    run.add_argument("--timeout", type=int, default=600)
    run.add_argument("--out", type=Path, required=True, help="Fresh private JSON name; unknown completion blocks subsequent runs until reconciled")
    args = parser.parse_args(argv)
    try:
        if args.command == "bundle":
            result = bundle(out=args.out, cases_relative=args.cases, protocol=args.protocol)
            print(json.dumps(result))
            return 0
        if args.command == "run-ollama":
            result = run_ollama(bundle_meta=args.bundle_meta, model=args.model, out=args.out, url=args.url,
                                num_ctx=args.num_ctx, num_predict=args.num_predict, timeout=args.timeout)
            print(json.dumps({key: result[key] for key in ("status", "model", "usage", "batch_stopped")}))
            return 0 if result["status"] == "passed" else 2
        output = private_path(ROOT, args.out)
        if output.suffix != ".json":
            raise ValueError("score-output-must-be-json")
        inputs = [args.answer, args.bundle_meta, args.usage]
        metadata = parse_json(safe_read(private_path(ROOT, args.bundle_meta), MAX_CASE_BYTES))
        if isinstance(metadata, dict) and isinstance(metadata.get("prompt_path"), str):
            inputs.append(private_path(ROOT, metadata["prompt_path"]))
        if any(p is not None and output.resolve() == Path(p).resolve() for p in inputs):
            raise ValueError("output-cannot-overwrite-input")
        usage = parse_json(safe_read(args.usage, 4096)) if args.usage else None
        result = score(answer=args.answer, bundle_meta=args.bundle_meta, model=args.model, provider=args.provider, usage=usage)
        write_private(ROOT, output, (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
        print(json.dumps({"status": result["status"], "cases_passed": result["cases_passed"],
                          "cases_total": result["cases_total"], "fields_correct": result["fields_correct"],
                          "fields_total": result["fields_total"], "output": str(output), "usage": result["usage"]}))
        return 0 if result["status"] == "passed" else 2
    except (RuntimeError, ValueError, OSError, TypeError, UnicodeError, RecursionError, KeyError):
        print(json.dumps({"status": "blocked", "reason": "invalid-input-or-stale-bundle"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import metis.evaluation.native_work_trace as work_trace
from metis.evaluation.native_work_trace import (
    SOURCE_COMMIT,
    TRACE_PREFIX,
    NativeWorkTrace,
    parse_trace,
    validate_retry_probe,
    verify_build_manifest,
)
from scripts.run_llama_work_trace import MAX_LOG_BYTES, _popen_with_bounded_file_size

NONCE = "0123456789abcdef0123456789abcdef"


def _counts(**overrides):
    value = {
        "process_calls": 1, "process_encode_calls": 0, "process_decode_calls": 1,
        "process_failures": 0, "input_positions": 2, "encode_calls": 0,
        "decode_calls": 1, "graph_dispatches": 1, "graph_positions": 2,
        "graph_failures": 0, "graph_pre_dispatch_failures": 0,
        "zero_position_graphs": 0, "server_batch_retries": 0,
        "injected_precompute_failures": 0,
    }
    value.update(overrides)
    return value


def _record(*, startup=None, requests=None):
    return {
        "version": 1, "source_commit": SOURCE_COMMIT, "nonce": NONCE,
        "startup": _counts(**(startup or {})), "requests": _counts(**(requests or {})),
    }


def _stderr(record) -> bytes:
    return ("server log line\n" + TRACE_PREFIX + json.dumps(record) + "\n").encode()


def test_parse_trace_discards_logs_and_preserves_aggregate_retry_counts():
    record = _record(requests={
        "process_calls": 2, "process_failures": 1, "decode_calls": 2,
        "process_decode_calls": 2, "input_positions": 22, "graph_dispatches": 2,
        "graph_positions": 22, "server_batch_retries": 1,
        "injected_precompute_failures": 1,
    })

    trace = parse_trace(_stderr(record), expected_nonce=NONCE)

    assert trace.requests.process_failures == 1
    assert trace.requests.server_batch_retries == 1
    assert trace.requests.injected_precompute_failures == 1


@pytest.mark.parametrize("mutation", [
    {"nonce": "f" * 32},
    {"source_commit": "0" * 40},
])
def test_parse_trace_rejects_wrong_nonce_or_source(mutation):
    record = _record()
    record.update(mutation)

    with pytest.raises(ValueError):
        parse_trace(_stderr(record), expected_nonce=NONCE)


def test_parse_trace_rejects_duplicate_or_missing_records():
    record = _stderr(_record())

    with pytest.raises(ValueError, match="exactly one"):
        parse_trace(record + record, expected_nonce=NONCE)
    with pytest.raises(ValueError, match="exactly one"):
        parse_trace(b"ordinary server log only\n", expected_nonce=NONCE)


def test_parse_trace_rejects_duplicate_json_keys():
    record = json.dumps(_record(), separators=(",", ":"))
    duplicate = '{"version":1,' + record[1:]
    with pytest.raises(ValueError, match="invalid"):
        parse_trace((TRACE_PREFIX + duplicate + "\n").encode(), expected_nonce=NONCE)


@pytest.mark.parametrize("changes", [
    {"process_failures": 2},
    {"graph_failures": 2},
    {"server_batch_retries": 2},
    {"injected_precompute_failures": 2},
])
def test_parse_trace_rejects_inconsistent_counts(changes):
    with pytest.raises(ValueError, match="invalid"):
        parse_trace(_stderr(_record(requests=changes)), expected_nonce=NONCE)


def test_trace_build_manifest_binds_repository_patch_and_binary(tmp_path, monkeypatch):
    binary = tmp_path / "llama-server"
    patch = tmp_path / "trace.patch"
    manifest_path = tmp_path / "trace-build.json"
    binary.write_bytes(b"instrumented-binary")
    patch.write_bytes(b"pinned-source-diff")
    monkeypatch.setattr(work_trace, "TRACE_PATCH_SHA256", hashlib.sha256(patch.read_bytes()).hexdigest())
    manifest = {
        "version": 1,
        "source_commit": SOURCE_COMMIT,
        "trace_patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "target_os": "Darwin",
        "target_arch": "arm64",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert verify_build_manifest(manifest_path, binary=binary, patch=patch).source_commit == SOURCE_COMMIT
    patch.write_bytes(b"changed")
    with pytest.raises(ValueError, match="patch"):
        verify_build_manifest(manifest_path, binary=binary, patch=patch)


def test_trace_build_manifest_rejects_unpinned_patch(tmp_path):
    binary = tmp_path / "llama-server"
    patch = tmp_path / "trace.patch"
    manifest_path = tmp_path / "trace-build.json"
    binary.write_bytes(b"instrumented-binary")
    patch.write_bytes(b"different-but-self-consistent-patch")
    manifest = {
        "version": 1, "source_commit": SOURCE_COMMIT,
        "trace_patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "target_os": "Darwin", "target_arch": "arm64",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="repository-pinned"):
        verify_build_manifest(manifest_path, binary=binary, patch=patch)


def test_builder_checks_patch_digest_before_source_application():
    builder = (Path(__file__).parents[1] / "scripts/build_llama_work_trace.sh").read_text()
    digest_check = builder.index("metis_actual_patch_sha256")
    apply_check = builder.index('git -C "$metis_build_root/source" apply --check')

    assert work_trace.TRACE_PATCH_SHA256 in builder
    assert digest_check < apply_check


def test_retry_probe_requires_exact_synthetic_counters():
    trace = NativeWorkTrace.model_validate(_record(requests={
        "process_calls": 2, "process_decode_calls": 2, "decode_calls": 2,
        "process_failures": 1, "server_batch_retries": 1,
        "injected_precompute_failures": 1,
    }))
    validate_retry_probe(trace, injected=True)

    for changes in (
        {"process_failures": 2},
        {"process_failures": 2, "server_batch_retries": 2},
        {"injected_precompute_failures": 0},
        {"graph_pre_dispatch_failures": 1},
        {"graph_dispatches": 2, "graph_failures": 1},
    ):
        record = _record(requests={
            "process_calls": 2, "process_decode_calls": 2, "decode_calls": 2,
            "process_failures": 1, "server_batch_retries": 1,
            "injected_precompute_failures": 1,
            **changes,
        })
        candidate = NativeWorkTrace.model_validate(record)
        with pytest.raises(ValueError):
            validate_retry_probe(candidate, injected=True)


def test_retry_probe_rejects_unexpected_counters_without_injection():
    trace = NativeWorkTrace.model_validate(_record())
    validate_retry_probe(trace, injected=False)
    candidate = NativeWorkTrace.model_validate(_record(requests={
        "process_calls": 2, "process_decode_calls": 2, "decode_calls": 2,
        "process_failures": 1, "server_batch_retries": 1,
    }))
    with pytest.raises(ValueError):
        validate_retry_probe(candidate, injected=False)


@pytest.mark.parametrize("field", [
    "process_failures", "server_batch_retries", "injected_precompute_failures",
    "graph_failures", "graph_pre_dispatch_failures",
])
def test_retry_probe_rejects_unexpected_startup_failures(field):
    startup = _counts()
    startup[field] = 1
    if field == "process_failures":
        startup.update(process_calls=2, process_decode_calls=2, decode_calls=2)
    elif field == "server_batch_retries":
        startup.update(process_calls=2, process_decode_calls=2, decode_calls=2,
                       process_failures=1)
    elif field == "injected_precompute_failures":
        startup.update(process_calls=2, process_decode_calls=2, decode_calls=2,
                       process_failures=1, server_batch_retries=1)
    elif field == "graph_failures":
        startup.update(graph_dispatches=2)
    trace = NativeWorkTrace.model_validate(_record(startup=startup))

    with pytest.raises(ValueError, match="startup failure"):
        validate_retry_probe(trace, injected=False)
    with pytest.raises(ValueError, match="startup failure"):
        validate_retry_probe(trace, injected=True)


def test_server_log_file_is_limited_by_child_file_size_resource(tmp_path):
    log_path = tmp_path / "server.log"
    with log_path.open("w+b") as log:
        process = _popen_with_bounded_file_size(
            [sys.executable, "-c", "import os; os.write(1, b'x' * (5 * 1024 * 1024))"],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            close_fds=True, start_new_session=True,
        )
        process.wait(timeout=10)
    assert log_path.stat().st_size == MAX_LOG_BYTES

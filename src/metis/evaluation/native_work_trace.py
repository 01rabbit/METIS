"""Validate aggregate-only traces from the pinned, test-only llama.cpp build."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SOURCE_COMMIT = "b1b770d90d94cad9e9ea5b993bdbc383a522fb28"
TRACE_PATCH_SHA256 = "c97500f6a98a2c34554953f82eb46ce6b39d1b82581fa1aef65b197090dd1c4c"
PUBLIC_FIXTURE_SHA256 = "270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d"
TRACE_PREFIX = "METIS_LLAMA_TRACE_V1 "
_HEX256 = re.compile(r"[0-9a-f]{64}")
_NONCE = re.compile(r"[0-9a-f]{32}")
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_TRACE_BYTES = 4 * 1024 * 1024
_MAX_TRACE_LINE_BYTES = 4096


class WorkTraceCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    process_calls: int = Field(ge=0, le=10**12)
    process_encode_calls: int = Field(ge=0, le=10**12)
    process_decode_calls: int = Field(ge=0, le=10**12)
    process_failures: int = Field(ge=0, le=10**12)
    input_positions: int = Field(ge=0, le=10**15)
    encode_calls: int = Field(ge=0, le=10**12)
    decode_calls: int = Field(ge=0, le=10**12)
    graph_dispatches: int = Field(ge=0, le=10**12)
    graph_positions: int = Field(ge=0, le=10**15)
    graph_failures: int = Field(ge=0, le=10**12)
    graph_pre_dispatch_failures: int = Field(ge=0, le=10**12)
    zero_position_graphs: int = Field(ge=0, le=10**12)
    server_batch_retries: int = Field(ge=0, le=10**12)
    injected_memory_prepare_failures: int = Field(ge=0, le=1)
    memory_prepare_failures: int = Field(ge=0, le=10**12)
    memory_update_retry_attempts: int = Field(ge=0, le=10**12)
    memory_update_retry_successes: int = Field(ge=0, le=10**12)
    memory_update_retry_false_results: int = Field(ge=0, le=10**12)

    @model_validator(mode="after")
    def check_counts(self) -> WorkTraceCounts:
        if self.process_encode_calls + self.process_decode_calls > self.process_calls:
            raise ValueError("typed llama_process calls exceed total calls")
        if self.process_failures > self.process_calls:
            raise ValueError("llama_process failures exceed total calls")
        if self.graph_failures > self.graph_dispatches:
            raise ValueError("graph failures exceed submitted graph count")
        if self.zero_position_graphs > self.graph_dispatches:
            raise ValueError("zero-position graphs exceed submitted graph count")
        if self.server_batch_retries > self.process_failures:
            raise ValueError("server retries exceed failed llama_process calls")
        if self.injected_memory_prepare_failures > self.memory_prepare_failures:
            raise ValueError("injected memory prepare failures exceed observed memory prepare failures")
        if self.memory_update_retry_attempts != (
                self.memory_update_retry_successes + self.memory_update_retry_false_results):
            raise ValueError("memory retry outcomes do not match retry attempts")
        if self.memory_update_retry_attempts > self.memory_prepare_failures:
            raise ValueError("memory retry attempts exceed memory prepare failures")
        return self


class NativeWorkTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: Literal[1]
    source_commit: Literal["b1b770d90d94cad9e9ea5b993bdbc383a522fb28"]
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    startup: WorkTraceCounts
    requests: WorkTraceCounts

    @model_validator(mode="after")
    def check_nonce(self) -> NativeWorkTrace:
        if _NONCE.fullmatch(self.nonce) is None:
            raise ValueError("trace nonce is malformed")
        return self


class TraceBuildManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: Literal[1]
    source_commit: Literal["b1b770d90d94cad9e9ea5b993bdbc383a522fb28"]
    trace_patch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    binary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_os: Literal["Darwin", "Linux"]
    target_arch: str = Field(min_length=1, max_length=32)


def _read_regular(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError("trace input is outside its regular-file or size boundary")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            data = source.read(limit + 1)
        if len(data) != info.st_size or len(data) > limit:
            raise ValueError("trace input changed size while being read")
        return data
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _sha256(path: Path, limit: int) -> str:
    return hashlib.sha256(_read_regular(path, limit)).hexdigest()


def parse_trace(stderr: bytes, *, expected_nonce: str) -> NativeWorkTrace:
    """Extract exactly one bounded aggregate record; discard every other log line."""
    if _NONCE.fullmatch(expected_nonce) is None:
        raise ValueError("expected nonce is malformed")
    if len(stderr) > _MAX_TRACE_BYTES:
        raise ValueError("trace log exceeds size boundary")
    try:
        text = stderr.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("trace log is not UTF-8") from exc
    records = [line[len(TRACE_PREFIX):] for line in text.splitlines()
               if line.startswith(TRACE_PREFIX)]
    if len(records) != 1 or len(records[0].encode("utf-8")) > _MAX_TRACE_LINE_BYTES:
        raise ValueError("trace log must contain exactly one bounded aggregate record")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("aggregate trace contains a duplicate key")
            value[key] = item
        return value

    try:
        payload = json.loads(records[0], object_pairs_hook=reject_duplicate_keys)
        trace = NativeWorkTrace.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        raise ValueError("aggregate trace record is invalid") from exc
    if trace.nonce != expected_nonce:
        raise ValueError("trace nonce does not match this run")
    return trace


def verify_build_manifest(manifest_path: Path, *, binary: Path, patch: Path) -> TraceBuildManifest:
    """Check source, patch, and binary digests without executing the binary."""
    manifest_data = _read_regular(manifest_path, _MAX_MANIFEST_BYTES)
    try:
        manifest = TraceBuildManifest.model_validate_json(manifest_data)
    except (ValidationError, ValueError) as exc:
        raise ValueError("trace build manifest is invalid") from exc
    patch_digest = _sha256(patch, 1024 * 1024)
    binary_digest = _sha256(binary, 128 * 1024 * 1024)
    if patch_digest != TRACE_PATCH_SHA256:
        raise ValueError("trace patch does not match the repository-pinned patch")
    if not _HEX256.fullmatch(manifest.trace_patch_sha256) or manifest.trace_patch_sha256 != patch_digest:
        raise ValueError("trace patch does not match build manifest")
    if not _HEX256.fullmatch(manifest.binary_sha256) or manifest.binary_sha256 != binary_digest:
        raise ValueError("trace binary does not match build manifest")
    return manifest


def validate_retry_probe(trace: NativeWorkTrace, *, injected: bool) -> None:
    """Require the injected control-flow probe to have its exact expected counters."""
    startup = trace.startup
    startup_failures = (
        startup.process_failures,
        startup.server_batch_retries,
        startup.injected_memory_prepare_failures,
        startup.graph_failures,
        startup.graph_pre_dispatch_failures,
        startup.memory_prepare_failures,
        startup.memory_update_retry_attempts,
        startup.memory_update_retry_successes,
        startup.memory_update_retry_false_results,
    )
    if startup_failures != (0,) * 9:
        raise ValueError("retry probe recorded an unexpected startup failure")
    counts = trace.requests
    if injected:
        retry_outcomes = counts.memory_update_retry_successes + counts.memory_update_retry_false_results
        common = (counts.injected_memory_prepare_failures == 1
                  and counts.memory_prepare_failures == 1
                  and counts.memory_update_retry_attempts == 1 and retry_outcomes == 1)
        internal_retry = (counts.memory_update_retry_successes == 1
                          and counts.process_failures == 0 and counts.server_batch_retries == 0)
        batch_retry = (counts.memory_update_retry_false_results == 1
                       and counts.process_failures == 1 and counts.server_batch_retries == 1)
        if not common or not (internal_retry or batch_retry):
            raise ValueError("synthetic memory retry counters do not match the selected mode")
    elif (counts.injected_memory_prepare_failures != 0 or counts.memory_prepare_failures != 0
          or counts.memory_update_retry_attempts != 0 or counts.memory_update_retry_successes != 0
          or counts.memory_update_retry_false_results != 0 or counts.process_failures != 0
          or counts.server_batch_retries != 0):
        raise ValueError("retry probe recorded unexpected injected retry counters")
    if counts.graph_failures != 0 or counts.graph_pre_dispatch_failures != 0:
        raise ValueError("synthetic retry probe included a non-injected graph failure")
    if counts.process_calls == counts.process_failures:
        raise ValueError("retry probe recorded no successful request process call")
    if counts.graph_dispatches == counts.zero_position_graphs or counts.graph_positions == 0:
        raise ValueError("retry probe recorded no request graph work with positive positions")

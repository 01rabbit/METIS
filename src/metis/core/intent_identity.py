"""Canonical identity of a specialist tool intent (Issue #11 follow-up).

Specialists were able to re-run an analysis by perturbing options that do not change
the result (``length`` 12000 vs 11999 on an 8 KiB file, ``packets`` 200 vs 199 on a short
capture). The identity used for duplicate control is therefore computed from the
*effective* request:

* integer options are coerced like the tools coerce them ("0x10" == "16" == 16);
* tool defaults are filled in, so an omitted option equals its default;
* byte windows are clipped to the artifact size, and a PCAP packet count to the number
  of records the capture actually holds;
* JSON-object data for structured tools is re-serialised with sorted keys; hex input is
  lower-cased without whitespace (``bytes.fromhex`` ignores both).

Identity only decides duplicates; the tool still runs with the specialist's own request.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
from pathlib import Path
from typing import Any

from metis.core.artifacts import artifact_stream
from metis.core.ctf_artifacts import MAX_FILE
from metis.core.ctf_tools import number

# Defaults copied from the tools (ctf_artifacts); a missing option equals its default.
DEFAULTS: dict[str, dict[str, int | str]] = {
    "text": {"offset": 0, "length": 16_384},
    "hex": {"offset": 0, "length": 256},
    "strings": {"offset": 0, "length": 1_048_576, "minimum": 4, "limit": 100},
    "disassemble": {"offset": 0, "length": 256, "count": 64, "address": 0},
    "pcap": {"packets": 128},
    "zip_read": {"max_bytes": 65_536}, "tar_read": {"max_bytes": 65_536}, "gzip": {"max_bytes": 65_536},
    "zlib": {"max_bytes": 65_536}, "bzip2": {"max_bytes": 65_536}, "xz": {"max_bytes": 65_536},
    "image_lsb": {"bit": 0, "max_bytes": 4096}, "wav_lsb": {"channel": 0, "bit": 0, "max_bytes": 4096},
    "pdf_text": {"pages": 5}, "sqlite": {"limit": 20},
    "x509": {"limit": 8}, "tls_certificates": {"packets": 1024, "connections": 16, "limit": 4},
    "tls_decrypt": {"packets": 1024, "connections": 16, "preview": 600},
    "tls_http_body": {"packets": 1024, "connections": 16, "connection": 0, "side": "server", "message": 0,
                      "max_bytes": 1_048_576},
    "infozip_seed": {"generator": "glibc", "pid_bits": 22, "seconds": 60},
    "zipcrypto_attack": {"offset": 0, "seconds": 60}, "zipcrypto_decrypt": {"max_bytes": 1_048_576},
}
WINDOWED = {"text", "hex", "strings", "disassemble"}
STRUCTURED_DATA = {"bytes_decode", "zlib_decompress", "aes_decrypt", "fermat_factor", "rsa_common_modulus",
                   "pack", "unpack", "cyclic", "cyclic_find", "caesar", "xor", "xor_single", "gcd",
                   "mod_inverse", "crt", "integer_root", "rsa_decrypt"}


def _coerce(value: Any) -> Any:
    try:
        return number(value)
    except (TypeError, ValueError):
        return value


def _pcap_records(stream: Any, limit: int) -> int | None:
    """Number of classic-PCAP records (capped at ``limit``); None if not classic PCAP."""
    header = stream.read(24)
    if len(header) < 24 or header[:4] not in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4",
                                              b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d"):
        return None
    endian = "<" if header[:4] in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
    count = 0
    while count < limit:
        record = stream.read(16)
        if len(record) < 16:
            break
        captured = struct.unpack_from(endian + "I", record, 8)[0]
        stream.seek(captured, os.SEEK_CUR)
        count += 1
    return count


def effective_options(root: Path | None, artifact: str | None, tool: str, options: dict[str, Any]) -> dict[str, Any]:
    effective = {**DEFAULTS.get(tool, {}), **{key: _coerce(value) for key, value in options.items()}}
    if root is None or artifact is None:
        return effective
    try:
        with artifact_stream(root, artifact, max_bytes=MAX_FILE) as stream:
            size = os.fstat(stream.fileno()).st_size
            if tool in WINDOWED and isinstance(effective.get("offset"), int) and isinstance(
                    effective.get("length"), int):
                offset = min(max(effective["offset"], 0), size)
                effective["offset"] = offset
                effective["length"] = max(0, min(effective["length"], size - offset))
            elif tool == "pcap" and isinstance(effective.get("packets"), int):
                records = _pcap_records(stream, effective["packets"])
                if records is not None and records < effective["packets"]:
                    effective["packets"] = records  # asking for more than exist reads the same records
    except (OSError, ValueError):
        pass  # unreadable artifacts fall back to the coerced request; the tool will reject them
    return effective


def canonical_data(tool: str, data: str | None) -> str:
    if data is None:
        return ""
    if tool in STRUCTURED_DATA:
        try:
            value = json.loads(data)
        except json.JSONDecodeError:
            return data
        if isinstance(value, dict):
            return json.dumps({key: _coerce(item) if not isinstance(item, list) else
                               [_coerce(element) for element in item] for key, item in value.items()},
                              sort_keys=True, separators=(",", ":"), default=str)
        return data
    if tool == "hex_decode":
        return "".join(data.split()).lower()
    return data


def intent_identity(kind: str, tool: str, artifact: str | None, options: dict[str, Any], data: str | None,
                    root: Path | None) -> tuple[str, str | None]:
    """Return (identity, family). Family groups option variants of one tool on one artifact;
    data intents have no family (a different input is a different question)."""
    effective = effective_options(root, artifact, tool, options) if kind in {"artifact", "derive"} else options
    body = {"kind": kind, "tool": tool, "artifact": artifact, "options": effective,
            "data_sha256": hashlib.sha256(canonical_data(tool, data).encode()).hexdigest()}
    identity = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    if kind not in {"artifact", "derive"}:
        return identity, None
    return identity, hashlib.sha256(f"{kind}\0{tool}\0{artifact}".encode()).hexdigest()

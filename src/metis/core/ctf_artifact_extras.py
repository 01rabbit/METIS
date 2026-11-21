"""Bounded, pure, offline forensics/misc helpers for artifact tools.

Nothing here executes artifact content: every helper only slices, decodes or
pattern-matches bytes that the caller already holds in memory.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import re
import struct
import zlib

from metis.core.ctf_tools import byte_view, score_text

ONE_MIB = 1_048_576
DEFAULT_FLAG_PATTERN = r"[A-Za-z0-9_]{2,16}\{[^}]{3,200}\}"
_B64_RUN = re.compile(rb"[A-Za-z0-9+/]{16,}={0,2}")
_HEX_RUN = re.compile(rb"(?:[0-9A-Fa-f]{2}){8,}")


def _integer(options: dict, name: str, default: int, low: int, high: int) -> int:
    value = options.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"option {name} must be an integer in [{low}, {high}]")
    return value


def _decode_b64_run(run: bytes) -> bytes | None:
    body = run.rstrip(b"=")
    if len(body) % 4 == 1:
        body = body[:-1]
    try:
        return base64.b64decode(body + b"=" * (-len(body) % 4), validate=True)
    except (binascii.Error, ValueError):
        return None


def base64_extract(data: bytes, options: dict) -> dict:
    """Decode the longest base64 runs found inside surrounding text."""
    minimum = _integer(options, "min_length", 16, 8, 4096)
    limit = _integer(options, "max_runs", 8, 1, 16)
    runs: list[dict] = []
    for match in _B64_RUN.finditer(data):
        if len(match.group()) < minimum:
            continue
        decoded = _decode_b64_run(match.group())
        if decoded:
            runs.append({"start": match.start(), "end": match.end(), "encoded_length": len(match.group()),
                         "decoded_size": len(decoded), "_decoded": decoded})
    if not runs:
        raise ValueError("no base64 run found")
    runs.sort(key=lambda item: (-item["encoded_length"], item["start"]))
    selected = runs[:limit]
    best = selected[0]["_decoded"]
    if len(best) > ONE_MIB:
        raise ValueError("decoded artifact exceeds one MiB")
    for item in selected:
        item["preview"] = item.pop("_decoded")[:80].decode("utf-8", errors="replace")
    return {**byte_view(best), "extract": True, "used_ranges": [[i["start"], i["end"]] for i in selected],
            "runs": selected, "primary_run": 0, "more_runs": len(runs) - len(selected)}


def _key(options: dict) -> bytes:
    if "key" not in options:
        raise ValueError("xor requires option key")
    encoding = options.get("key_encoding", "hex")
    text = options["key"]
    if not isinstance(text, str) or encoding not in {"hex", "utf8"}:
        raise ValueError("key must be a string and key_encoding hex or utf8")
    key = bytes.fromhex(text) if encoding == "hex" else text.encode()
    if not key or len(key) > 4096:
        raise ValueError("XOR key must be 1 to 4096 bytes")
    return key


def xor_repeating(data: bytes, options: dict) -> dict:
    key = _key(options)
    if len(data) > ONE_MIB:
        raise ValueError("xor artifact is limited to one MiB; carve a window first")
    return {**byte_view(bytes(value ^ key[index % len(key)] for index, value in enumerate(data))),
            "key_length": len(key)}


def _printable_ratio(chunk: bytes) -> float:
    if not chunk:
        return 0.0
    return sum(32 <= byte < 127 or byte in (9, 10, 13) for byte in chunk) / len(chunk)


def xor_single(data: bytes, options: dict) -> dict:
    """Try all 256 single-byte keys; rank by flag-pattern hits, then English-text score."""
    window = _integer(options, "max_bytes", 4096, 1, 65_536)
    top = _integer(options, "top", 5, 1, 16)
    preview = _integer(options, "preview", 160, 0, 1024)
    sample = data[:window]
    pattern = re.compile(DEFAULT_FLAG_PATTERN)
    ranked = []
    for key in range(256):
        decoded = bytes(value ^ key for value in sample)
        ratio = _printable_ratio(decoded)
        hits = len(pattern.findall(decoded.decode("latin-1"))) if ratio >= 0.9 else 0
        ranked.append((hits, score_text(decoded), -key, key, decoded))
    ranked.sort(reverse=True)
    return {"analyzed_bytes": len(sample), "truncated": len(data) > len(sample),
            "candidates": [{"key_hex": f"{key:02x}", "printable_ratio": round(_printable_ratio(decoded), 4),
                            "flag_pattern_hits": hits, "preview": decoded[:preview].decode("latin-1")}
                           for hits, _score, _neg, key, decoded in ranked[:top]]}


_SIGNATURES = (
    ("png", b"\x89PNG\r\n\x1a\n"), ("jpeg", b"\xff\xd8\xff"), ("gif", b"GIF87a"), ("gif", b"GIF89a"),
    ("zip", b"PK\x03\x04"), ("gzip", b"\x1f\x8b\x08"), ("pdf", b"%PDF-"), ("elf", b"\x7fELF"),
    ("7z", b"7z\xbc\xaf\x27\x1c"), ("rar", b"Rar!\x1a\x07"), ("xz", b"\xfd7zXZ\x00"),
    ("bzip2", b"BZh"), ("sqlite", b"SQLite format 3\x00"),
)
MAX_HITS = 4096


def _png_end(data: bytes, start: int) -> int | None:
    position = start + 8
    while position + 12 <= len(data):
        length, kind = struct.unpack_from(">I4s", data, position)
        position += 12 + length
        if kind == b"IEND":
            return position if position <= len(data) else None
        if position > len(data):
            return None
    return None


def _zip_end(data: bytes, start: int) -> int | None:
    end = data.find(b"PK\x05\x06", start)
    while end != -1:
        if end + 22 <= len(data):
            comment = struct.unpack_from("<H", data, end + 20)[0]
            return min(len(data), end + 22 + comment)
        end = data.find(b"PK\x05\x06", end + 1)
    return None


def _gzip_end(data: bytes, start: int) -> int | None:
    window = data[start:start + 4 * ONE_MIB]
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        decoder.decompress(window, ONE_MIB)
    except zlib.error:
        return None
    if not decoder.eof:
        return None
    return start + len(window) - len(decoder.unused_data)


def _region_end(data: bytes, kind: str, start: int) -> int | None:
    if kind == "png":
        return _png_end(data, start)
    if kind == "jpeg":
        end = data.find(b"\xff\xd9", start + 3)
        return None if end == -1 else end + 2
    if kind == "gif":
        end = data.find(b"\x00;", start + 6)
        return None if end == -1 else end + 2
    if kind == "zip":
        return _zip_end(data, start)
    if kind == "gzip":
        return _gzip_end(data, start)
    if kind == "pdf":
        end = data.rfind(b"%%EOF", start)
        return None if end == -1 else min(len(data), end + 6)
    if kind == "7z" and start + 32 <= len(data):
        offset, size = struct.unpack_from("<QQ", data, start + 12)
        end = start + 32 + offset + size
        return end if end <= len(data) else None
    return None


def _signature_hits(data: bytes) -> list[tuple[int, str]]:
    digits = {bytes([digit]) for digit in range(0x31, 0x3a)}
    hits: list[tuple[int, str]] = []
    for kind, magic in _SIGNATURES:
        position = data.find(magic)
        while position != -1 and len(hits) < MAX_HITS:
            if kind != "bzip2" or (data[position + 3:position + 4] in digits
                                   and data[position + 4:position + 10] == b"1AY&SY"):
                hits.append((position, kind))
            position = data.find(magic, position + 1)
    return sorted(hits)


def carve(data: bytes, options: dict) -> dict:
    """List embedded signatures and trailing data, or return one region as bytes."""
    limit = _integer(options, "limit", 64, 1, 256)
    if "index" in options and ("offset" in options or "length" in options):
        raise ValueError("use either index or offset/length")
    regions: list[dict] = []
    covered = 0
    for position, kind in _signature_hits(data):
        if position < covered:
            continue
        end = _region_end(data, kind, position)
        if end is not None and kind in {"png", "zip", "7z", "gzip"}:
            covered = end
        regions.append({"kind": kind, "offset": position, "length": (end or len(data)) - position,
                        "exact_end": end is not None})
    starts = [region["offset"] for region in regions]
    for region in list(regions):
        end = region["offset"] + region["length"]
        if region["exact_end"] and region["kind"] in {"png", "jpeg", "zip"} and end < len(data):
            later = [start for start in starts if start >= end]
            gap = (min(later) if later else len(data)) - end
            if gap > 0:
                regions.append({"kind": "trailing", "offset": end, "length": gap, "exact_end": True,
                                "after": region["kind"], "head_hex": data[end:end + 16].hex()})
    regions.sort(key=lambda item: (item["offset"], item["kind"]))
    for index, region in enumerate(regions):
        region["index"] = index
    if "index" in options:
        if not regions:
            raise ValueError("no carved regions")
        chosen = _integer(options, "index", 0, 0, len(regions) - 1)
        offset, length = regions[chosen]["offset"], regions[chosen]["length"]
    elif "offset" in options or "length" in options:
        offset = _integer(options, "offset", 0, 0, len(data))
        length = _integer(options, "length", max(1, len(data) - offset), 1, max(1, len(data)))
        if offset + length > len(data):
            raise ValueError("region exceeds artifact")
    else:
        return {"size": len(data), "regions": regions[:limit], "total_regions": len(regions),
                "truncated": len(regions) > limit}
    if length > ONE_MIB:
        raise ValueError("carved region exceeds one MiB")
    return {"offset": offset, "length": length, **byte_view(data[offset:offset + length])}


def _compile(options: dict) -> re.Pattern[str]:
    pattern = options.get("pattern", DEFAULT_FLAG_PATTERN)
    if not isinstance(pattern, str) or not 1 <= len(pattern) <= 200:
        raise ValueError("pattern must be a regex of 1 to 200 characters")
    if re.search(r"\)\s*[*+{]|\\[1-9]|\(\?[<=!P]", pattern):
        raise ValueError("pattern may not use quantified groups, backreferences or lookarounds")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid pattern: {exc}") from None


def flag_scan(data: bytes, options: dict) -> dict:
    """Locate flag-shaped strings; like `flag_candidates`, results are unverified leads."""
    pattern = _compile(options)
    maximum = _integer(options, "max_hits", 50, 1, 200)
    hits: list[dict] = []
    seen: set[tuple[str, int, int, str]] = set()

    def scan(layer: str, text: str, base: int, scale: int = 1, extra: int = 0, nested: bool = False) -> None:
        for match in pattern.finditer(text):
            offset = base if nested else base + extra + match.start() * scale
            key = (layer, offset, match.start() if nested else 0, match.group())
            if key not in seen and len(hits) < maximum:
                seen.add(key)
                hit = {"layer": layer, "offset": offset, "candidate": match.group()[:300]}
                if nested:
                    hit["decoded_offset"] = match.start()
                hits.append(hit)

    scan("raw", data.decode("latin-1"), 0)
    for alignment in (0, 1):
        scan("utf-16le", data[alignment:].decode("utf-16le", errors="replace"), 0, 2, alignment)
    scan("rot13", codecs.decode(data.decode("latin-1"), "rot_13"), 0)
    for _index, match in zip(range(32), _B64_RUN.finditer(data)):
        decoded = _decode_b64_run(match.group())
        if decoded and len(decoded) <= ONE_MIB:
            scan("base64", decoded.decode("latin-1"), match.start(), nested=True)
    for _index, match in zip(range(32), _HEX_RUN.finditer(data)):
        scan("hex", bytes.fromhex(match.group().decode()).decode("latin-1"), match.start(), nested=True)
    for layer, wbits in (("gzip", 16 + zlib.MAX_WBITS), ("zlib", zlib.MAX_WBITS)):
        try:
            decoded = zlib.decompressobj(wbits).decompress(data, ONE_MIB)
        except zlib.error:
            continue
        scan(layer, decoded.decode("latin-1"), 0, nested=True)
    return {"candidates": hits, "verified": False, "truncated": len(hits) >= maximum,
            "pattern": pattern.pattern,
            "note": "unverified leads. raw/utf-16le/rot13 offsets are byte offsets in the artifact; "
                    "base64/hex layers report the encoded run start as offset and the match position in "
                    "decoded_offset; gzip/zlib report offset 0 and decoded_offset in the stream."}

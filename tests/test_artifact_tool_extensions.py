import base64
import gzip
import io
import struct
import zipfile
import zlib

import pytest

from metis.core.codex_session import tool_catalog
from metis.core.ctf_artifacts import ALLOWED_OPTIONS, ARTIFACT_TOOLS, DERIVE_TOOLS, inspect_bytes


def chunk(kind: bytes, body: bytes = b"") -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


PNG = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)) + chunk(b"IEND")


def test_registered_and_catalogued():
    options = tool_catalog()["artifact_tool_options"]
    for tool in ("xor", "xor_single", "carve", "flag_scan"):
        assert tool in ARTIFACT_TOOLS and tool in ALLOWED_OPTIONS
        assert tool in options
    assert {"xor", "carve"} <= DERIVE_TOOLS
    assert "extract" in options["base64_decode"]


def test_base64_default_unchanged_and_extract():
    payload = b"secret payload bytes!"
    encoded = base64.b64encode(payload)
    assert inspect_bytes(encoded, "base64_decode")["utf8"] == payload.decode()
    with pytest.raises(ValueError):
        inspect_bytes(b"note: " + encoded + b" end", "base64_decode")
    data = b"note: " + encoded + b" end, short QUJD"
    result = inspect_bytes(data, "base64_decode", {"extract": True})
    assert result["utf8"] == payload.decode()
    assert result["used_ranges"] == [[6, 6 + len(encoded)]]
    with pytest.raises(ValueError):
        inspect_bytes(b"nothing here", "base64_decode", {"extract": True})


def test_xor_with_key():
    data = bytes(a ^ b for a, b in zip(b"hello world", b"kykykykykyk"))
    assert inspect_bytes(data, "xor", {"key": "ky", "key_encoding": "utf8"})["utf8"] == "hello world"
    assert inspect_bytes(data, "xor", {"key": "6b79"})["utf8"] == "hello world"
    with pytest.raises(ValueError):
        inspect_bytes(data, "xor", {})
    with pytest.raises(ValueError):
        inspect_bytes(data, "xor", {"key": "zz"})


def test_xor_single_ranks_flag_first():
    plain = b"the text has CTF{xxxx_demo_flag} here, tea and cake"
    result = inspect_bytes(bytes(b ^ 0x5A for b in plain), "xor_single")
    top = result["candidates"][0]
    assert top["key_hex"] == "5a" and top["flag_pattern_hits"] == 1
    assert len(result["candidates"]) == 5
    with pytest.raises(ValueError):
        inspect_bytes(plain, "xor_single", {"top": 99})


def test_carve_lists_signatures_and_trailing():
    blob = b"junk" + PNG + b"TRAILING-SECRET" + b"\xff\xd8\xff\xe0abc\xff\xd9" + b"tail"
    regions = inspect_bytes(blob, "carve")["regions"]
    png = next(r for r in regions if r["kind"] == "png")
    assert (png["offset"], png["length"]) == (4, len(PNG))
    trailing = next(r for r in regions if r["kind"] == "trailing" and r["after"] == "png")
    assert trailing["offset"] == 4 + len(PNG) and trailing["length"] == len(b"TRAILING-SECRET")
    assert any(r["kind"] == "jpeg" for r in regions)
    carved = inspect_bytes(blob, "carve", {"index": png["index"]})
    assert bytes.fromhex(carved["hex"]) == PNG
    window = inspect_bytes(blob, "carve", {"offset": 4, "length": 8})
    assert bytes.fromhex(window["hex"]) == PNG[:8]
    with pytest.raises(ValueError):
        inspect_bytes(blob, "carve", {"offset": len(blob), "length": 5})


def test_carve_zip_gzip_and_pdf_sizes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.txt", "a" * 50)
        archive.writestr("b.txt", "b" * 50)
    archive_bytes = buffer.getvalue()
    gz = gzip.compress(b"hello" * 10)
    blob = b"\x00" * 3 + archive_bytes + b"--" + gz + b"%PDF-1.4 x %%EOF\n"
    regions = inspect_bytes(blob, "carve")["regions"]
    zips = [r for r in regions if r["kind"] == "zip"]
    assert len(zips) == 1 and zips[0]["length"] == len(archive_bytes)
    assert next(r for r in regions if r["kind"] == "gzip")["length"] == len(gz)
    assert any(r["kind"] == "pdf" for r in regions)


def test_flag_scan_layers():
    flag = b"CTF{layered_flag}"
    layers = {
        "raw": b"xx " + flag,
        "utf-16le": b"\x00" + flag.decode().encode("utf-16le"),
        "rot13": b"PGS{ynlrerq_synt}",
        "base64": b"hello " + base64.b64encode(b"prefix " + flag + b" suffix"),
        "hex": b"zz " + flag.hex().encode(),
        "gzip": gzip.compress(flag),
        "zlib": zlib.compress(flag),
    }
    for layer, data in layers.items():
        result = inspect_bytes(data, "flag_scan")
        assert result["verified"] is False
        assert layer in {hit["layer"] for hit in result["candidates"]}, (layer, result)
    raw = inspect_bytes(layers["raw"], "flag_scan")["candidates"][0]
    assert raw["offset"] == 3 and raw["candidate"] == "CTF{layered_flag}"
    utf16 = next(h for h in inspect_bytes(layers["utf-16le"], "flag_scan")["candidates"] if h["layer"] == "utf-16le")
    assert utf16["offset"] == 1
    b64 = next(h for h in inspect_bytes(layers["base64"], "flag_scan")["candidates"] if h["layer"] == "base64")
    assert b64["offset"] == 6 and b64["decoded_offset"] == 7


def test_flag_scan_custom_pattern_and_guards():
    result = inspect_bytes(b"abc HTB{x1y} CTF{abc}", "flag_scan", {"pattern": r"HTB\{[^}]+\}"})
    assert [h["candidate"] for h in result["candidates"]] == ["HTB{x1y}"]
    for bad in ("(a+)+$", "(a)\\1", "[", "x" * 201):
        with pytest.raises(ValueError):
            inspect_bytes(b"aaaa", "flag_scan", {"pattern": bad})
    many = b" ".join(b"AB{abcd%d}" % n for n in range(300))
    capped = inspect_bytes(many, "flag_scan", {"max_hits": 10})
    assert len(capped["candidates"]) == 10 and capped["truncated"]


def test_unknown_options_rejected():
    with pytest.raises(ValueError):
        inspect_bytes(b"x", "carve", {"bogus": 1})


def test_disassemble_detects_elf_architecture():
    from metis.core.ctf_artifacts import elf_architecture, inspect_bytes

    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4], header[5] = 2, 1
    header[18:20] = (183).to_bytes(2, "little")
    assert elf_architecture(bytes(header)) == "arm64"
    header[18:20] = (62).to_bytes(2, "little")
    assert elf_architecture(bytes(header)) == "x86_64"
    assert elf_architecture(b"not an elf at all....") is None
    nop = bytes.fromhex("1f2003d5")  # aarch64 nop
    arm_elf = bytes(header[:18]) + (183).to_bytes(2, "little") + bytes(header[20:]) + nop
    result = inspect_bytes(arm_elf, "disassemble", {"offset": 64, "length": 4})
    assert result["architecture"] == "arm64"
    assert result["instructions"][0]["mnemonic"] == "nop"

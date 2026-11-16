"""Read-only, bounded inspection of authorized challenge bytes; no program execution."""
from __future__ import annotations

import base64
import bz2
import collections
import io
import ipaddress
import json
import lzma
import math
import os
import sqlite3
import stat
import struct
import subprocess
import tarfile
import tempfile
import warnings
import wave
import zipfile
import zlib
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from capstone import CsError
from elftools.common.exceptions import ELFError
from PIL import Image

from metis.core.artifacts import artifact_stream
from metis.core.ctf_tools import byte_view, number

ARTIFACT_TOOLS = frozenset({
    "overview", "strings", "text", "hex", "elf", "disassemble", "zip_list", "zip_read",
    "gzip", "image", "image_lsb", "pcap",
    "pe", "java_class", "wav", "wav_lsb", "sqlite",
    "base64_decode", "base32_decode", "hex_decode", "zlib",
    "tar_list", "tar_read", "bzip2", "xz", "pdf_text", "x509", "tls_certificates",
    "tls_decrypt", "tls_http_body", "zipcrypto_info", "infozip_seed", "zipcrypto_attack", "zipcrypto_decrypt",
})
MAX_ARTIFACT = 8 * 1024 * 1024
MAX_FILE = 256 * 1024 * 1024
ARTIFACT_ERRORS = (OSError, ValueError, KeyError, TypeError, EOFError, struct.error,
                   zipfile.BadZipFile, zlib.error, ELFError, CsError,
                   Image.DecompressionBombError, Image.DecompressionBombWarning,
                   NotImplementedError, RuntimeError, wave.Error, sqlite3.Error, tarfile.TarError,
                   lzma.LZMAError, subprocess.TimeoutExpired)


def inspect_file(root: Path, name: str, tool: str, options: dict | None = None) -> dict:
    """Window large files; whole-structure parsers retain an eight MiB input cap."""
    import hashlib

    options = dict(options or {})
    with artifact_stream(root, name, max_bytes=MAX_FILE) as stream:
        size = os.fstat(stream.fileno()).st_size
        if tool in {"text", "hex", "strings", "disassemble"}:
            offset = bounded_integer(options, "offset", 0, 0, size)
            default_length = 1_048_576 if tool == "strings" else 16_384 if tool == "text" else 256
            maximum = MAX_ARTIFACT if tool == "strings" else 4096 if tool == "hex" else 65_536
            length = bounded_integer(options, "length", default_length, 1, maximum)
            stream.seek(offset)
            data = stream.read(length)
            if tool == "strings":
                options.pop("offset", None)
                options.pop("length", None)
            else:
                options["offset"] = 0
            result = inspect_bytes(data, tool, options)
            result.update(artifact_size=size, window_offset=offset, window_bytes=len(data),
                          more_bytes=offset + len(data) < size)
            if tool == "strings":
                for item in result["strings"]:
                    item["offset"] += offset
            elif tool == "disassemble":
                result["file_offset"] = offset
            else:
                result["offset"] = offset
            return result
        if tool == "overview":
            sample = stream.read(MAX_ARTIFACT)
            result = inspect_bytes(sample, tool, options)
            digest = hashlib.sha256()
            stream.seek(0)
            consumed = 0
            while chunk := stream.read(1_048_576):
                consumed += len(chunk)
                if consumed > MAX_FILE:
                    raise ValueError("artifact grew beyond limit")
                digest.update(chunk)
            result.update(size=consumed, sha256=digest.hexdigest(),
                          sampled=consumed > len(sample), analysis_sample_bytes=len(sample))
            return result
        if tool == "pcap" and size > MAX_ARTIFACT:
            header = stream.read(24)
            if file_kind(header) != "PCAP":
                raise ValueError("large PCAPNG requires an external streaming parser")
            endian = "<" if header[:4] in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
            data_buffer = bytearray(header)
            count = bounded_integer(options, "packets", 128, 1, 1024)
            for _ in range(count):
                record = stream.read(16)
                if not record:
                    break
                if len(record) != 16:
                    raise ValueError("truncated PCAP header")
                captured = struct.unpack_from(endian + "I", record, 8)[0]
                if captured > 1_048_576:
                    raise ValueError("PCAP packet exceeds one MiB")
                if len(data_buffer) + 16 + captured > MAX_ARTIFACT:
                    stream.seek(-16, 1)
                    break
                packet = stream.read(captured)
                if len(packet) != captured:
                    raise ValueError("truncated PCAP packet")
                data_buffer.extend(record + packet)
            result = inspect_bytes(bytes(data_buffer), tool, options)
            result.update(artifact_size=size, more_records=stream.tell() < size,
                          next_record_offset=stream.tell())
            return result
        if size > MAX_ARTIFACT:
            raise ValueError("structure parser needs a file no larger than eight MiB; inspect windows instead")
        return inspect_bytes(stream.read(MAX_ARTIFACT + 1), tool, options)


def bounded_integer(options: dict, name: str, default: int, low: int, high: int) -> int:
    value = number(options.get(name, default))
    if not low <= value <= high:
        raise ValueError("option exceeds limits")
    return value


def strings(data: bytes, *, minimum: int = 4, limit: int = 100) -> list[dict]:
    result = []
    start = 0
    for index in range(len(data) + 1):
        if index < len(data) and 32 <= data[index] <= 126:
            continue
        if index - start >= minimum:
            result.append({"offset": start, "text": data[start:min(index, start + 1024)].decode(),
                           "truncated": index - start > 1024})
            if len(result) >= limit:
                break
        start = index + 1
    return result


def file_kind(data: bytes) -> str:
    for signature, name in ((b"\x7fELF", "ELF"), (b"MZ", "PE/DOS"),
                            (b"PK\x03\x04", "ZIP"), (b"\x1f\x8b", "gzip"),
                            (b"\x89PNG\r\n\x1a\n", "PNG"), (b"\xff\xd8\xff", "JPEG"),
                            (b"GIF8", "GIF"), (b"%PDF-", "PDF"),
                            (b"SQLite format 3\x00", "SQLite"), (b"BZh", "bzip2"),
                            (b"\xfd7zXZ\x00", "XZ"), (b"7z\xbc\xaf\x27\x1c", "7z"),
                            (b"Rar!", "RAR"), (b"II\x2a\x00", "TIFF"), (b"MM\x00\x2a", "TIFF")):
        if data.startswith(signature):
            return name
    if data.startswith(b"\xca\xfe\xba\xbe"):
        return "Java class or Mach-O fat"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "WAV"
    if data[257:262] == b"ustar":
        return "TAR"
    if data[:4] in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4",
                    b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d"):
        return "PCAP"
    if data.startswith(b"\x0a\x0d\x0d\x0a"):
        return "PCAPNG"
    try:
        data.decode()
        return "UTF-8 text"
    except UnicodeError:
        return "binary"


def _zip(data: bytes, tool: str, options: dict) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > 1024:
            raise ValueError("archive has more than 1024 entries")
        if tool == "zip_list":
            return {"members": [{"name": member.filename, "size": member.file_size,
                                  "compressed_size": member.compress_size,
                                  "encrypted": bool(member.flag_bits & 1),
                                  "symlink": stat.S_ISLNK(member.external_attr >> 16)}
                                 for member in members], "extracted": False}
        name = options.get("member")
        if not isinstance(name, str):
            raise TypeError("an exact member name is required")
        if (PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                or PureWindowsPath(name).drive or "\\" in name or "\x00" in name):
            raise ValueError("unsafe archive member name")
        matches = [member for member in members if member.filename == name]
        if len(matches) != 1:
            raise ValueError("member is missing or ambiguous")
        member = matches[0]
        maximum = bounded_integer(options, "max_bytes", 65_536, 1, 1_048_576)
        password = options.get("password")
        if password is not None and (not isinstance(password, str) or len(password.encode()) > 1024):
            raise ValueError("invalid archive password")
        if (member.is_dir() or stat.S_ISLNK(member.external_attr >> 16)
                or (member.flag_bits & 1 and not password) or member.file_size > maximum
                or member.file_size / max(1, member.compress_size) > 200):
            raise ValueError("unsupported or oversized archive member")
        with archive.open(member, pwd=password.encode() if password else None) as stream:
            content = stream.read(maximum + 1)
        if len(content) > maximum:
            raise ValueError("archive member exceeds limit")
        return {"member": name, **byte_view(content), "extracted": False}


def _elf(data: bytes) -> dict:
    from elftools.elf.elffile import ELFFile
    from elftools.elf.sections import SymbolTableSection

    elf = ELFFile(io.BytesIO(data))
    if elf.num_sections() > 512 or elf.num_segments() > 512:
        raise ValueError("ELF table limit exceeded")
    names_index = elf.header["e_shstrndx"]
    if isinstance(names_index, int) and names_index:
        name_table = elf.get_section(names_index)
        if name_table is None or name_table["sh_size"] > 65_536:
            raise ValueError("ELF section name table exceeds limit")
    sections = list(elf.iter_sections())
    segments = list(elf.iter_segments())
    stack = next((segment for segment in segments if segment["p_type"] == "PT_GNU_STACK"), None)
    symbols: list[dict[str, Any]] = []
    canary = False
    symbols_remaining = 4096
    symbol_scan_truncated = False
    for section in sections:
        if not isinstance(section, SymbolTableSection):
            continue
        count = min(section.num_symbols(), symbols_remaining)
        symbol_scan_truncated = symbol_scan_truncated or count < section.num_symbols()
        symbols_remaining -= count
        table = elf.get_section(section["sh_link"])
        if table is None or table["sh_offset"] + table["sh_size"] > len(data):
            raise ValueError("ELF symbol name table exceeds limits")
        names = data[table["sh_offset"]:table["sh_offset"] + table["sh_size"]]
        fmt = ("<" if elf.little_endian else ">") + ("IBBHQQ" if elf.elfclass == 64 else "IIIBBH")
        width = struct.calcsize(fmt)
        if section["sh_entsize"] != width or section["sh_offset"] + section["sh_size"] > len(data):
            raise ValueError("invalid symbol table layout")
        for index in range(count):
            fields = struct.unpack_from(fmt, data, section["sh_offset"] + index * width)
            name_offset = fields[0]
            if name_offset >= len(names):
                raise ValueError("ELF symbol name offset exceeds table")
            end = names.find(b"\x00", name_offset, name_offset + 257)
            truncated = end < 0
            end = min(len(names), name_offset + 256) if truncated else end
            name = names[name_offset:end].decode(errors="replace")
            value, size, info = ((fields[4], fields[5], fields[1]) if elf.elfclass == 64
                                 else (fields[1], fields[2], fields[3]))
            canary = canary or name == "__stack_chk_fail"
            if name and len(symbols) < 512:
                symbols.append({"name": name, "value": hex(value),
                                "size": size, "type": info & 15, "name_truncated": truncated})
    return {"bits": elf.elfclass, "little_endian": elf.little_endian,
            "machine": elf.header["e_machine"], "type": elf.header["e_type"],
            "entry": hex(elf.header["e_entry"]),
            "mitigation_indicators": {
                "position_independent_or_shared": elf.header["e_type"] == "ET_DYN",
                "non_executable_stack": None if stack is None else not bool(stack["p_flags"] & 1),
                "gnu_relro_segment": any(segment["p_type"] == "PT_GNU_RELRO" for segment in segments),
                "stack_canary_import": True if canary else None if symbol_scan_truncated else False,
            },
            "sections": [{"name": section.name[:256], "address": hex(section["sh_addr"]),
                          "offset": section["sh_offset"], "size": section["sh_size"]}
                         for section in sections[:256]], "symbols": symbols,
            "symbol_scan_truncated": symbol_scan_truncated, "executed": False}


def _disassemble(data: bytes, options: dict) -> dict:
    import capstone

    architectures = {
        "x86_64": (capstone.CS_ARCH_X86, capstone.CS_MODE_64),
        "x86": (capstone.CS_ARCH_X86, capstone.CS_MODE_32),
        "arm": (capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM),
        "thumb": (capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB),
        "arm64": (capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM),
    }
    architecture = options.get("architecture", "x86_64")
    if architecture not in architectures:
        raise ValueError("unsupported disassembly architecture")
    offset = bounded_integer(options, "offset", 0, 0, len(data))
    length = bounded_integer(options, "length", 256, 1, 65_536)
    count = bounded_integer(options, "count", 64, 1, 1024)
    address = bounded_integer(options, "address", 0, 0, (1 << 64) - 1)
    decoder = capstone.Cs(*architectures[architecture])
    instructions = [{"address": hex(instruction.address), "bytes": instruction.bytes.hex(),
                     "mnemonic": instruction.mnemonic, "operands": instruction.op_str}
                    for instruction in decoder.disasm(data[offset:offset + length], address, count=count)]
    return {"architecture": architecture, "file_offset": offset,
            "instructions": instructions, "executed": False}


def _image(data: bytes, tool: str, options: dict) -> dict:
    from PIL import ExifTags

    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 4_000_000:
                raise ValueError("image exceeds four million pixels")
            if tool == "image":
                return {"format": image.format, "mode": image.mode, "width": image.width,
                        "height": image.height,
                        "info": {key: str(value)[:2048] if not isinstance(value, bytes)
                                 else f"<{len(value)} bytes>"
                                 for key, value in list(image.info.items())[:32]},
                        "exif": {ExifTags.TAGS.get(key, str(key)): str(value)[:512]
                                 for key, value in list(image.getexif().items())[:128]}}
            channels = options.get("channels", "RGB")
            if not isinstance(channels, str) or not channels or len(channels) > 4 or any(c not in "RGBA" for c in channels) or len(set(channels)) != len(channels):
                raise ValueError("invalid image channel order")
            bit = bounded_integer(options, "bit", 0, 0, 7)
            maximum = bounded_integer(options, "max_bytes", 4096, 1, 65_536)
            result = bytearray()
            value, used = 0, 0
            converted = image.convert("RGBA")
            try:
                pixels = converted.load()
                if pixels is None:
                    raise ValueError("image has no pixel data")
                for index in range(converted.width * converted.height):
                    pixel = pixels[index % converted.width, index // converted.width]
                    if not isinstance(pixel, tuple):
                        raise TypeError("expected RGBA pixel data")
                    for channel in channels:
                        value = (value << 1) | ((pixel["RGBA".index(channel)] >> bit) & 1)
                        used += 1
                        if used == 8:
                            result.append(value)
                            value, used = 0, 0
                            if len(result) >= maximum:
                                return {"channels": channels, "bit": bit, **byte_view(bytes(result))}
                return {"channels": channels, "bit": bit, **byte_view(bytes(result))}
            finally:
                converted.close()


def _pcapng_to_classic(data: bytes, maximum: int) -> tuple[bytes, bool]:
    """Normalize bounded Ethernet PCAPNG EPBs, rejecting mixed link types."""
    cursor, blocks, packets = 0, 0, 0
    endian = "<"
    interfaces: list[tuple[int, float]] = []
    records = bytearray()
    linktype: int | None = None
    while cursor < len(data) and packets < maximum:
        blocks += 1
        if blocks > 4096 or cursor + 12 > len(data):
            raise ValueError("PCAPNG block limit or truncated header")
        if data[cursor:cursor + 4] == b"\x0a\x0d\x0d\x0a":
            magic = data[cursor + 8:cursor + 12]
            if magic not in (b"\x4d\x3c\x2b\x1a", b"\x1a\x2b\x3c\x4d"):
                raise ValueError("invalid PCAPNG byte order")
            endian = "<" if magic == b"\x4d\x3c\x2b\x1a" else ">"
            interfaces = []
        block_type, length = struct.unpack_from(endian + "II", data, cursor)
        if length < 12 or length % 4 or length > len(data) - cursor:
            raise ValueError("invalid PCAPNG block length")
        if struct.unpack_from(endian + "I", data, cursor + length - 4)[0] != length:
            raise ValueError("PCAPNG trailing length mismatch")
        block = data[cursor:cursor + length]
        if block_type == 0x0a0d0d0a and length < 28:
            raise ValueError("short PCAPNG section header")
        if block_type == 1:
            if length < 20 or len(interfaces) >= 32:
                raise ValueError("invalid PCAPNG interface")
            kind = struct.unpack_from(endian + "H", block, 8)[0]
            resolution = 1e-6
            offset = 16
            while offset + 4 <= length - 4:
                option, size = struct.unpack_from(endian + "HH", block, offset)
                offset += 4
                if size > length - 4 - offset:
                    raise ValueError("truncated PCAPNG option")
                if option == 9 and size == 1:
                    exponent = block[offset]
                    resolution = 2 ** -(exponent & 127) if exponent & 128 else 10 ** -exponent
                if option == 0:
                    break
                offset += (size + 3) & ~3
            interfaces.append((kind, resolution))
        if block_type == 6:
            if length < 32:
                raise ValueError("short PCAPNG enhanced packet")
            interface, high, low, captured, original = struct.unpack_from(endian + "IIIII", block, 8)
            if interface >= len(interfaces) or captured > length - 32 or captured > original:
                raise ValueError("invalid PCAPNG packet")
            kind, resolution = interfaces[interface]
            if linktype is not None and kind != linktype:
                raise ValueError("mixed link types need separate analysis")
            linktype = kind
            timestamp = ((high << 32) | low) * resolution
            seconds = int(timestamp)
            if not 0 <= seconds < (1 << 32):
                raise ValueError("PCAPNG timestamp exceeds supported range")
            fraction = min(999999, int((timestamp - seconds) * 1_000_000))
            records.extend(struct.pack("<IIII", seconds, fraction, captured, original))
            records.extend(block[28:28 + captured])
            packets += 1
        cursor += length
    header = struct.pack("<IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, MAX_ARTIFACT, linktype or 1)
    return header + records, cursor < len(data)


def _pcap(data: bytes, options: dict) -> dict:
    maximum = bounded_integer(options, "packets", 128, 1, 1024)
    source_format = file_kind(data)
    source_more = False
    if source_format == "PCAPNG":
        data, source_more = _pcapng_to_classic(data, maximum)
    if len(data) < 24 or file_kind(data) != "PCAP":
        raise ValueError("PCAP or supported PCAPNG required")
    little = data[:4] in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1")
    endian = "<" if little else ">"
    linktype = struct.unpack_from(endian + "I", data, 20)[0]
    packets: list[dict[str, Any]] = []
    cursor = 24
    while cursor < len(data) and len(packets) < maximum:
        if cursor + 16 > len(data):
            raise ValueError("truncated PCAP record header")
        seconds, fraction, captured, original = struct.unpack_from(endian + "IIII", data, cursor)
        cursor += 16
        if captured > len(data) - cursor:
            raise ValueError("truncated PCAP packet")
        packet = data[cursor:cursor + captured]
        cursor += captured
        record: dict[str, Any] = {"seconds": seconds, "fraction": fraction,
                                  "captured": captured, "original": original}
        if linktype == 1 and len(packet) >= 14:
            protocol = int.from_bytes(packet[12:14])
            start = 14
            if protocol == 0x8100 and len(packet) >= 18:
                protocol, start = int.from_bytes(packet[16:18]), 18
            packet = packet[start:] if protocol == 0x0800 else b""
        elif linktype != 101:
            packet = b""
        if len(packet) >= 20 and packet[0] >> 4 == 4:
            ihl = (packet[0] & 15) * 4
            total = int.from_bytes(packet[2:4])
            if ihl < 20 or not ihl <= total <= len(packet):
                raise ValueError("invalid IPv4 lengths")
            record.update(source=str(ipaddress.IPv4Address(packet[12:16])),
                          destination=str(ipaddress.IPv4Address(packet[16:20])),
                          protocol=packet[9])
            payload = packet[ihl:total]
            fragment_offset = int.from_bytes(packet[6:8]) & 0x1fff
            record["fragment_offset"] = fragment_offset
            if not fragment_offset and packet[9] in (6, 17) and len(payload) >= (20 if packet[9] == 6 else 8):
                record.update(source_port=int.from_bytes(payload[:2]),
                              destination_port=int.from_bytes(payload[2:4]))
                header = (payload[12] >> 4) * 4 if packet[9] == 6 else 8
                if not (20 if packet[9] == 6 else 8) <= header <= len(payload):
                    raise ValueError("invalid transport header")
                record["payload_prefix"] = byte_view(payload[header:header + 256])
        packets.append(record)
    return {"format": source_format, "linktype": linktype, "packets": packets,
            "more_records": source_more or cursor < len(data),
            "tcp_reassembly": False}


# Options each artifact tool accepts (also shown to delegated specialists).
ALLOWED_OPTIONS: dict[str, set[str]] = {
    "overview": set(), "strings": {"minimum", "limit"},
    "text": {"offset", "length"},
    "hex": {"offset", "length"}, "elf": set(),
    "disassemble": {"architecture", "offset", "length", "count", "address"},
    "zip_list": set(), "zip_read": {"member", "max_bytes", "password"}, "gzip": {"max_bytes"},
    "image": set(), "image_lsb": {"channels", "bit", "max_bytes"}, "pcap": {"packets"},
    "x509": {"limit"}, "tls_certificates": {"packets", "connections", "limit"},
    "tls_decrypt": {"factor", "packets", "connections", "preview"},
    "tls_http_body": {"factor", "packets", "connections", "connection", "side", "message", "max_bytes"},
    "zipcrypto_info": set(), "infozip_seed": {"generator", "time_from", "time_to", "pid_bits", "seconds"},
    "zipcrypto_attack": {"member", "plaintext_hex", "offset", "seconds"},
    "zipcrypto_decrypt": {"member", "keys", "max_bytes"},
    "pe": set(), "java_class": set(), "wav": set(),
    "wav_lsb": {"channel", "bit", "max_bytes"}, "sqlite": {"table", "limit"},
    "base64_decode": set(), "base32_decode": set(), "hex_decode": set(),
    "zlib": {"max_bytes"},
    "tar_list": set(), "tar_read": {"member", "max_bytes"},
    "bzip2": {"max_bytes"}, "xz": {"max_bytes"}, "pdf_text": {"pages"},
}


def inspect_bytes(data: bytes, tool: str, options: dict | None = None) -> dict:
    options = options or {}
    allowed = ALLOWED_OPTIONS
    if tool not in allowed or not isinstance(options, dict) or set(options) - allowed[tool]:
        raise ValueError("unknown artifact tool or options")
    if len(data) > MAX_ARTIFACT:
        raise ValueError("artifact exceeds eight MiB")
    if tool == "overview":
        import hashlib

        counts = collections.Counter(data)
        entropy = -sum((count / len(data)) * math.log2(count / len(data)) for count in counts.values()) if data else 0.0
        return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "kind": file_kind(data), "entropy_bits_per_byte": entropy,
                "head_hex": data[:64].hex(), "strings": strings(data, limit=20)}
    if tool == "strings":
        minimum = bounded_integer(options, "minimum", 4, 1, 256)
        limit = bounded_integer(options, "limit", 100, 1, 1024)
        return {"strings": strings(data, minimum=minimum, limit=limit)}
    if tool == "hex":
        offset = bounded_integer(options, "offset", 0, 0, len(data))
        length = bounded_integer(options, "length", 256, 1, 4096)
        chunk = data[offset:offset + length]
        return {"offset": offset, **byte_view(chunk)}
    if tool == "text":
        offset = bounded_integer(options, "offset", 0, 0, len(data))
        length = bounded_integer(options, "length", 16_384, 1, 65_536)
        chunk = data[offset:offset + length]
        return {"offset": offset, "text": chunk.decode(errors="replace"),
                "more_bytes": offset + len(chunk) < len(data)}
    if tool in {"zip_list", "zip_read"}:
        return _zip(data, tool, options)
    if tool in {"tar_list", "tar_read"}:
        return _tar(data, tool, options)
    if tool in {"bzip2", "xz"}:
        maximum = bounded_integer(options, "max_bytes", 65_536, 1, 1_048_576)
        decompressor = bz2.BZ2Decompressor() if tool == "bzip2" else lzma.LZMADecompressor(memlimit=64 * 1024 * 1024)
        decoded = decompressor.decompress(data, max_length=maximum + 1)
        if len(decoded) > maximum or not decompressor.eof:
            raise ValueError("truncated or oversized compressed content")
        return {**byte_view(decoded), "trailing_bytes": len(decompressor.unused_data)}
    if tool in {"base64_decode", "base32_decode", "hex_decode"}:
        encoded = b"".join(data.split())
        if len(encoded) > 2_097_152:
            raise ValueError("encoded artifact exceeds limit")
        if tool == "base64_decode":
            decoded = base64.b64decode(encoded, validate=True)
        elif tool == "base32_decode":
            decoded = base64.b32decode(encoded, casefold=True)
        else:
            decoded = bytes.fromhex(encoded.decode("ascii"))
        if len(decoded) > 1_048_576:
            raise ValueError("decoded artifact exceeds one MiB")
        return byte_view(decoded)
    if tool in {"gzip", "zlib"}:
        maximum = bounded_integer(options, "max_bytes", 65_536, 1, 1_048_576)
        decoder = zlib.decompressobj((16 if tool == "gzip" else 0) + zlib.MAX_WBITS)
        decoded = decoder.decompress(data, maximum + 1)
        if len(decoded) > maximum or not decoder.eof:
            raise ValueError("truncated or oversized gzip content")
        return {**byte_view(decoded), "trailing_bytes": len(decoder.unused_data)}
    if tool == "elf":
        return _elf(data)
    if tool == "disassemble":
        return _disassemble(data, options)
    if tool in {"image", "image_lsb"}:
        return _image(data, tool, options)
    if tool == "pcap":
        return _pcap(data, options)
    if tool == "x509":
        from metis.core.ctf_x509 import MAX_CERTIFICATES, x509_file
        return x509_file(data, options, bounded_integer(options, "limit", 8, 1, MAX_CERTIFICATES))
    if tool in {"zipcrypto_info", "infozip_seed", "zipcrypto_attack", "zipcrypto_decrypt"}:
        return _zipcrypto(data, tool, options)
    if tool in {"tls_decrypt", "tls_http_body"}:
        from metis.core.ctf_tls import http_body, tls_decrypt
        packets = bounded_integer(options, "packets", 1024, 1, 4096)
        if file_kind(data) == "PCAPNG":
            data, _more = _pcapng_to_classic(data, packets)
        if len(data) < 24 or file_kind(data) != "PCAP":
            raise ValueError("PCAP or supported PCAPNG required")
        connections = bounded_integer(options, "connections", 16, 1, 32)
        if tool == "tls_http_body":
            return http_body(data, options, packets=packets, connections_limit=connections,
                             max_bytes=bounded_integer(options, "max_bytes", 1_048_576, 1, 1_048_576))
        result = tls_decrypt(data, options, packets=packets, connections_limit=connections,
                             preview=bounded_integer(options, "preview", 600, 0, 4000))
        result.pop("_plaintexts", None)
        return result
    if tool == "tls_certificates":
        from metis.core.ctf_x509 import MAX_CERTIFICATES, MAX_CONNECTIONS, tls_certificates
        packets = bounded_integer(options, "packets", 1024, 1, 4096)
        if file_kind(data) == "PCAPNG":
            data, _more = _pcapng_to_classic(data, packets)
        if len(data) < 24 or file_kind(data) != "PCAP":
            raise ValueError("PCAP or supported PCAPNG required")
        return tls_certificates(data, options, packets=packets,
                                connections=bounded_integer(options, "connections", 16, 1, MAX_CONNECTIONS),
                                limit=bounded_integer(options, "limit", 4, 1, MAX_CERTIFICATES))
    if tool == "pe":
        return _pe(data)
    if tool == "java_class":
        return _java_class(data)
    if tool in {"wav", "wav_lsb"}:
        return _wav(data, tool, options)
    if tool == "sqlite":
        return _sqlite(data, options)
    if tool == "pdf_text":
        return _pdf_text(data, options)
    raise ValueError("unsupported artifact analysis")


def _tar(data: bytes, tool: str, options: dict) -> dict:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        members = []
        for member in archive:
            members.append(member)
            if len(members) > 1024:
                raise ValueError("TAR entry limit exceeded")
        if tool == "tar_list":
            return {"members": [{"name": member.name, "size": member.size,
                                  "regular_file": member.isfile(), "symlink": member.issym(),
                                  "hardlink": member.islnk()} for member in members], "extracted": False}
        name = options.get("member")
        if not isinstance(name, str):
            raise TypeError("an exact member name is required")
        if (PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                or PureWindowsPath(name).drive or "\\" in name or "\x00" in name):
            raise ValueError("unsafe TAR member name")
        found = [member for member in members if member.name == name]
        maximum = bounded_integer(options, "max_bytes", 65_536, 1, 1_048_576)
        if len(found) != 1 or not found[0].isfile() or found[0].size > maximum:
            raise ValueError("TAR member is missing, ambiguous or unsupported")
        stream = archive.extractfile(found[0])
        if stream is None:
            raise ValueError("TAR member unavailable")
        with stream:
            content = stream.read(maximum + 1)
        if len(content) > maximum:
            raise ValueError("TAR member exceeds limit")
        return {"member": name, **byte_view(content), "extracted": False}


def _pdf_text(data: bytes, options: dict) -> dict:
    import resource

    if not data.startswith(b"%PDF-") or not Path("/usr/bin/pdftotext").is_file():
        raise ValueError("PDF and the optional system pdftotext helper are required")
    pages = bounded_integer(options, "pages", 5, 1, 20)

    def limits() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1_048_576, 1_048_576))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

    with tempfile.TemporaryFile() as output:
        result = subprocess.run(["/usr/bin/pdftotext", "-f", "1", "-l", str(pages),
                                 "-layout", "-", "-"], input=data, stdout=output,
                                stderr=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                                preexec_fn=limits, timeout=5, check=False)
        if result.returncode:
            raise ValueError("bounded PDF text extraction failed")
        output.seek(0)
        text = output.read(1_048_577)
        if len(text) > 1_048_576:
            raise ValueError("PDF text exceeds limit")
        return {"text": text.decode(errors="replace"), "pages_requested": pages,
                "helper": "system pdftotext", "challenge_code_executed": False}


def _pe(data: bytes) -> dict:
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError("DOS/PE header required")
    offset = int.from_bytes(data[60:64], "little")
    if offset + 24 > len(data) or data[offset:offset + 4] != b"PE\x00\x00":
        raise ValueError("PE signature missing")
    machine, count, timestamp, _, _, optional_size, characteristics = struct.unpack_from("<HHIIIHH", data, offset + 4)
    if count > 96 or optional_size < 72 or offset + 24 + optional_size + count * 40 > len(data):
        raise ValueError("invalid PE layout")
    base = offset + 24
    magic = struct.unpack_from("<H", data, base)[0]
    if magic not in (0x10b, 0x20b):
        raise ValueError("unsupported PE optional header")
    bits = 64 if magic == 0x20b else 32
    image_base = struct.unpack_from("<Q" if bits == 64 else "<I", data, base + (24 if bits == 64 else 28))[0]
    entry = struct.unpack_from("<I", data, base + 16)[0]
    dll_flags = struct.unpack_from("<H", data, base + 70)[0]
    sections = []
    for index in range(count):
        start = base + optional_size + index * 40
        name = data[start:start + 8].split(b"\x00", 1)[0].decode(errors="replace")
        virtual_size, address, size, pointer = struct.unpack_from("<IIII", data, start + 8)
        if size and pointer + size > len(data):
            raise ValueError("PE raw section exceeds file")
        sections.append({"name": name, "rva": hex(address), "virtual_size": virtual_size,
                         "offset": pointer, "size": size})
    return {"bits": bits, "machine": hex(machine), "timestamp": timestamp,
            "entry_rva": hex(entry), "image_base": hex(image_base), "sections": sections,
            "mitigation_indicators": {"aslr": bool(dll_flags & 0x40), "nx": bool(dll_flags & 0x100),
                                      "cfg": bool(dll_flags & 0x4000),
                                      "relocations_stripped": bool(characteristics & 1)},
            "executed": False}


def _java_class(data: bytes) -> dict:
    if len(data) < 10 or data[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("Java class required")
    minor, major, count = struct.unpack_from(">HHH", data, 4)
    if not 45 <= major <= 100 or not 1 <= count <= 8192:
        raise ValueError("unsupported Java constant pool")
    cursor, index = 10, 1
    texts: list[dict[str, Any]] = []
    while index < count:
        if cursor >= len(data):
            raise ValueError("truncated constant pool")
        tag = data[cursor]
        cursor += 1
        if tag == 1:
            if cursor + 2 > len(data):
                raise ValueError("truncated UTF8 entry")
            size = int.from_bytes(data[cursor:cursor + 2])
            cursor += 2
            if size > len(data) - cursor:
                raise ValueError("truncated constant value")
            if len(texts) < 256:
                texts.append({"index": index, "text": data[cursor:cursor + min(size, 1024)].decode(errors="replace"),
                              "truncated": size > 1024})
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            size = 4
        elif tag in (5, 6):
            size = 8
            index += 1
        elif tag in (7, 8, 16, 19, 20):
            size = 2
        elif tag == 15:
            size = 3
        else:
            raise ValueError("unsupported constant pool tag")
        if size > len(data) - cursor:
            raise ValueError("truncated constant entry")
        cursor += size
        index += 1
    return {"major": major, "minor": minor, "constant_pool_entries": count - 1,
            "utf8_constants": texts, "executed": False}


def _wav(data: bytes, tool: str, options: dict) -> dict:
    with wave.open(io.BytesIO(data), "rb") as sound:
        channels, width, frames = sound.getnchannels(), sound.getsampwidth(), sound.getnframes()
        if not 1 <= channels <= 8 or not 1 <= width <= 4:
            raise ValueError("unsupported PCM layout")
        if tool == "wav":
            return {"channels": channels, "sample_width": width, "frames": frames,
                    "sample_rate": sound.getframerate(), "compression": sound.getcomptype()}
        channel = bounded_integer(options, "channel", 0, 0, channels - 1)
        bit = bounded_integer(options, "bit", 0, 0, 7)
        maximum = bounded_integer(options, "max_bytes", 4096, 1, 65_536)
        raw = sound.readframes(min(frames, maximum * 8))
        result = bytearray()
        value, used = 0, 0
        for index in range(channel * width, len(raw), channels * width):
            value = (value << 1) | ((raw[index] >> bit) & 1)
            used += 1
            if used == 8:
                result.append(value)
                value, used = 0, 0
        return {"channel": channel, "bit": bit, **byte_view(bytes(result))}


def _sqlite(data: bytes, options: dict) -> dict:
    if not data.startswith(b"SQLite format 3\x00"):
        raise ValueError("SQLite file required")
    database = sqlite3.connect(":memory:")
    try:
        database.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_048_576)
        database.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 256)
        database.deserialize(data)
        database.execute("PRAGMA trusted_schema=OFF")
        database.execute("PRAGMA query_only=ON")
        steps = [0]

        def progress() -> int:
            steps[0] += 1
            return int(steps[0] > 5000)

        database.set_progress_handler(progress, 1000)
        schema = database.execute("SELECT name, type, sql FROM sqlite_schema LIMIT 257").fetchall()
        if len(schema) > 256:
            raise ValueError("SQLite schema exceeds 256 entries")
        table = options.get("table")
        if table is None:
            return {"schema": [{"name": name, "type": kind, "sql": (sql or "")[:4096]}
                               for name, kind, sql in schema], "read_only": True}
        allowed = {name for name, kind, sql in schema if kind == "table" and sql
                   and not sql.lstrip().upper().startswith("CREATE VIRTUAL")}
        if not isinstance(table, str) or table not in allowed:
            raise ValueError("only ordinary declared tables may be read")
        limit = bounded_integer(options, "limit", 20, 1, 100)
        quoted = '"' + table.replace('"', '""') + '"'
        cursor = database.execute(f"SELECT * FROM {quoted} LIMIT ?", (limit,))
        output = []
        output_bytes = 0
        truncated = False
        for row in cursor:
            values = [byte_view(value[:1024]) if isinstance(value, bytes)
                      else value[:4096] if isinstance(value, str) else value for value in row]
            output_bytes += len(json.dumps(values).encode())
            if output_bytes > 65_536:
                truncated = True
                break
            output.append(values)
        return {"table": table, "columns": [column[0][:256] for column in cursor.description or ()],
                "rows": output, "truncated": truncated, "read_only": True}
    finally:
        database.close()


def _zipcrypto(data: bytes, tool: str, options: dict) -> dict:
    """ZipCrypto analysis (Issue #28): structure, Info-ZIP seed, known-plaintext attack, decryption."""
    import base64

    from metis.core import ctf_zipcrypto as zc

    if tool == "zipcrypto_info":
        return zc.zipcrypto_info(data)
    seconds = bounded_integer(options, "seconds", 60, 1, 300)
    if tool == "infozip_seed":
        generator = options.get("generator", "glibc")
        if generator not in {"glibc", "msvc"}:
            raise ValueError("generator must be glibc or msvc")
        bounds = {key: bounded_integer(options, key, 0, 0, (1 << 32) - 1) for key in ("time_from", "time_to")
                  if key in options}
        return zc.infozip_seed(data, generator=generator, time_from=bounds.get("time_from"),
                               time_to=bounds.get("time_to"), pid_bits=bounded_integer(options, "pid_bits", 22, 1, 22),
                               seconds=seconds)
    entries = {entry["name"]: entry for entry in zc.members(data) if entry["encrypted"]}
    name = options.get("member")
    if not isinstance(name, str) or name not in entries:
        raise ValueError("member must name an encrypted entry (see zipcrypto_info)")
    entry = entries[name]
    if tool == "zipcrypto_attack":
        hexed = options.get("plaintext_hex")
        if not isinstance(hexed, str) or len(hexed) > 4096:
            raise ValueError("plaintext_hex: known plaintext bytes as hex (at most 2048 bytes)")
        plaintext = bytes.fromhex(hexed)
        offset = bounded_integer(options, "offset", 0, 0, max(0, entry["compressed_size"] - 12))
        ciphertext = zc.member_bytes(data, entry)
        check = zc.check_bytes(entry)
        return zc.known_plaintext_attack(ciphertext, plaintext, 12 + offset, extra={11: check[11]}, seconds=seconds)
    keys = options.get("keys")
    if not isinstance(keys, str):
        raise TypeError("keys: 'x,y,z' hex words from zipcrypto_attack")
    result = zc.decrypt_member(data, name, zc.parse_keys(keys))
    plain = result.pop("plaintext")
    if len(plain) > bounded_integer(options, "max_bytes", 1_048_576, 1, 1_048_576):
        raise ValueError("decrypted member exceeds max_bytes")
    return {**result, "base64": base64.b64encode(plain).decode()}

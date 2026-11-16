"""Generate six transparent local toolchain exercises, not a hidden benchmark."""
from __future__ import annotations

import base64
import codecs
import gzip
import hashlib
import io
import json
import secrets
import struct
import tempfile
import zipfile
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from metis.core.codex_session import CodexSession


def synthetic_elf(encoded: bytes) -> bytes:
    text = b"\xb8\x2a\x00\x00\x00\xc3"
    rodata = encoded + b"\x00"
    names = b"\x00.shstrtab\x00.text\x00.rodata\x00"
    names_offset = 64 + len(text) + len(rodata)
    section_offset = 256
    if names_offset + len(names) > section_offset:
        raise ValueError("practice ELF payload exceeds fixed layout")
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8
    header = ident + struct.pack("<HHIQQQIHHHHHH", 2, 62, 1, 0x401000, 0, section_offset,
                                 0, 64, 56, 0, 64, 4, 1)
    payload = (header + text + rodata + names).ljust(section_offset, b"\x00")
    sections = [b"\x00" * 64,
                struct.pack("<IIQQQQIIQQ", 1, 3, 0, 0, names_offset, len(names), 0, 0, 1, 0),
                struct.pack("<IIQQQQIIQQ", 11, 1, 6, 0x401000, 64, len(text), 0, 0, 1, 0),
                struct.pack("<IIQQQQIIQQ", 17, 1, 2, 0x402000, 64 + len(text), len(rodata), 0, 0, 1, 0)]
    return payload + b"".join(sections)


def practice(session: CodexSession) -> list[dict]:
    root = Path(tempfile.mkdtemp(prefix=".metis-artifacts-practice-", dir=session.database.parent))
    contexts = []

    def start(category: str, title: str, description: str, answer: str,
              filename: str | None = None, content: bytes | None = None) -> None:
        paths = []
        if filename is not None and content is not None:
            path = root / filename
            path.write_bytes(content)
            path.chmod(0o600)
            paths.append(path)
        contexts.append(session.intake(title=title, description=description, paths=paths,
                                       categories=[category],
                                       commitment=hashlib.sha256(answer.encode()).hexdigest(),
                                       evaluation_split="practice"))

    answer = "CTF{" + secrets.token_hex(12) + "}"
    source = ("the competition flag is " + answer).encode()
    key = b"LUNA"
    ciphertext = bytes(value ^ key[index % len(key)] for index, value in enumerate(source))
    start("crypto", "Repeating-key XOR", "Decode this hexadecimal ciphertext. Repeating key is ASCII LUNA. "
          "Submit only the flag substring. Ciphertext: " + ciphertext.hex(), answer)

    answer = "CTF{" + secrets.token_hex(12) + "}"
    parts = [base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
             for value in ({"alg": "HS256", "typ": "JWT"},
                           {"hint": base64.b64encode(answer.encode()).decode()})]
    token = ".".join([*parts, "dGVzdA"])
    http = ("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nSet-Cookie: session=" + token +
            "; HttpOnly\r\n\r\n<p>Offline source exercise: inspect the token hint.</p>")
    start("web", "Offline HTTP and token inspection", "Recover the flag from the supplied captured "
          "HTTP response and the token's encoded hint. This fixture has no live endpoint.",
          answer, "response.http", http.encode())

    answer = "CTF{" + secrets.token_hex(12) + "}"
    bits = [byte >> shift & 1 for byte in answer.encode() for shift in range(7, -1, -1)]
    width, height = 32, (len(bits) + 95) // 96
    bits += [0] * (width * height * 3 - len(bits))
    image = Image.new("RGB", (width, height))
    image.putdata([tuple(128 | bits[index + channel] for channel in range(3))
                   for index in range(0, len(bits), 3)])
    stream = io.BytesIO()
    metadata = PngInfo()
    metadata.add_text("Hint", "RGB channel order, lowest bit, MSB first per byte")
    image.save(stream, format="PNG", pnginfo=metadata)
    image.close()
    start("forensics", "PNG bit-plane data", "Inspect image metadata and recover the embedded text.",
          answer, "image.png", stream.getvalue())

    answer = "CTF{" + secrets.token_hex(12) + "}"
    start("rev", "Synthetic ELF data check", "This is a synthetic static ELF exercise, not a runnable "
          "crackme. Inspect sections and strings. The relevant text is ROT13 encoded.", answer,
          "sample.elf", synthetic_elf(codecs.encode(answer, "rot_13").encode()))

    start("pwn", "Static x86-64 frame offset", "This is a static frame-layout exercise, not a runnable "
          "exploit. Disassemble the supplied x86-64 bytes. The buffer begins at the address computed "
          "by LEA, and the saved return address is at rbp+8. Submit CTF{decimal_offset}.",
          "CTF{56}", "frame.bin", bytes.fromhex("554889e54883ec40488d45d0c9c3"))

    answer = "CTF{" + secrets.token_hex(12) + "}"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("message.gz", gzip.compress(base64.b32encode(answer.encode())))
    start("misc", "Nested archive and encoding", "Inspect the ZIP and the nested compressed file, "
          "then decode the final Base32 text. Preserve originals; do not execute extracted files.",
          answer, "nested.zip", stream.getvalue())
    return contexts

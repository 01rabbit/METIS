"""Bounded offline CTF data transforms. No eval, subprocesses or network access."""
from __future__ import annotations

import base64
import codecs
import hashlib
import html
import json
import math
import re
import urllib.parse
import zlib
from collections import Counter
from itertools import islice
from typing import Any

from metis.core.runtime import ToolRequest, ToolResult

DATA_TOOLS = frozenset({
    "base64_decode", "base64_encode", "base32_decode", "base85_decode", "hex_decode",
    "hex_encode", "sha256", "hashes", "url_decode", "url_encode", "html_decode",
    "rot13", "caesar", "reverse", "xor", "xor_single", "integer", "mod_inverse",
    "gcd", "crt", "integer_root", "rsa_decrypt", "jwt_decode", "http_parse",
    "flag_candidates", "frequency",
    "pack", "unpack", "cyclic", "cyclic_find",
    "aes_decrypt", "fermat_factor", "rsa_common_modulus",
    "base64url_decode", "base64url_encode", "bytes_decode", "zlib_decompress",
})


# Inline tools that take a JSON object string instead of plain text:
# tool -> (accepted keys, required keys). Used by error messages and `codex tools`.
JSON_TOOL_INPUTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "bytes_decode": (("data", "encoding"), ("data",)),
    "zlib_decompress": (("data", "encoding"), ("data",)),
    "aes_decrypt": (("data", "key", "iv", "mode", "padding"), ("data", "key")),
    "fermat_factor": (("n", "steps"), ("n",)),
    "rsa_common_modulus": (("n", "e1", "e2", "c1", "c2"), ("n", "e1", "e2", "c1", "c2")),
    "pack": (("value", "data", "bits", "endian", "signed"), ()),
    "unpack": (("value", "data", "bits", "endian", "signed"), ()),
    "cyclic": (("length", "width", "value", "encoding"), ()),
    "cyclic_find": (("length", "width", "value", "encoding"), ()),
    "caesar": (("text", "shift"), ("text", "shift")),
    "xor": (("data", "key", "encoding", "key_encoding"), ("data",)),
    "xor_single": (("data", "key", "encoding", "key_encoding"), ("data",)),
    "gcd": (("a", "b"), ("a", "b")),
    "mod_inverse": (("a", "b"), ("a", "b")),
    "crt": (("residues", "moduli"), ("residues", "moduli")),
    "integer_root": (("n", "k"), ("n", "k")),
    "rsa_decrypt": (("n", "d", "c", "p", "q", "e"), ("c",)),
}


def input_shape(tool: str) -> str:
    """Compact input shape: JSON keys (required first, optional marked ?) or plain text."""
    spec = JSON_TOOL_INPUTS.get(tool)
    if spec is None:
        return "plain text via --data or stdin"
    accepted, required = spec
    keys = [*required, *(f"{key}?" for key in accepted if key not in required)]
    return "JSON object string {" + ",".join(keys) + "}"


def parameters(data: str, allowed: set[str], required: set[str]) -> dict[str, Any]:
    value = json.loads(data)
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        raise ValueError("invalid parameters")
    return value


def number(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError("boolean is not an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and len(value) <= 2048:
        result = int(value, 16 if value.lower().lstrip("-").startswith("0x") else 10)
    else:
        raise ValueError("invalid bounded integer")
    if result.bit_length() > 4096:
        raise ValueError("integer exceeds 4096 bits")
    return result


def bytes_value(value: str, encoding: str = "utf8") -> bytes:
    if not isinstance(value, str) or len(value.encode()) > 65_536:
        raise ValueError("invalid byte input")
    if encoding == "utf8":
        return value.encode()
    if encoding == "hex":
        return bytes.fromhex(value)
    if encoding == "base64":
        return base64.b64decode(value, validate=True)
    raise ValueError("unknown byte encoding")


def byte_view(value: bytes) -> dict:
    result = {"size": len(value), "hex": value.hex(),
              "base64": base64.b64encode(value).decode()}
    try:
        result["utf8"] = value.decode()
    except UnicodeError:
        pass
    return result


def score_text(value: bytes) -> float:
    common = b" etaoinshrdluETAOINSHRDLU"
    return sum(2 if byte in common else 1 if 32 <= byte < 127 else -3 for byte in value) / max(1, len(value))


def cyclic_pattern(length: int, width: int = 4) -> bytes:
    if not 1 <= length <= 65_536 or width not in (4, 8):
        raise ValueError("invalid bounded cyclic pattern")
    alphabet = b"abcdefghijklmnopqrstuvwxyz"
    state = [0] * (len(alphabet) * width)

    def generate(t: int, period: int):
        if t > width:
            if width % period == 0:
                yield from (alphabet[state[index]] for index in range(1, period + 1))
        else:
            state[t] = state[t - period]
            yield from generate(t + 1, period)
            for value in range(state[t - period] + 1, len(alphabet)):
                state[t] = value
                yield from generate(t + 1, t)

    return bytes(islice(generate(1, 1), length))


def _structured(tool: str, data: str) -> Any:
    if tool in {"bytes_decode", "zlib_decompress"}:
        args = parameters(data, {"data", "encoding"}, {"data"})
        raw = bytes_value(args["data"], args.get("encoding", "hex"))
        if tool == "zlib_decompress":
            decoder = zlib.decompressobj()
            raw = decoder.decompress(raw, 65_537)
            if len(raw) > 65_536 or not decoder.eof:
                raise ValueError("truncated or oversized zlib content")
        return byte_view(raw)
    if tool == "aes_decrypt":
        from cryptography.hazmat.primitives import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        args = parameters(data, {"data", "key", "iv", "mode", "padding"}, {"data", "key"})
        ciphertext = bytes_value(args["data"], "hex")
        key = bytes_value(args["key"], "hex")
        if len(key) not in (16, 24, 32):
            raise ValueError("AES needs a 16, 24 or 32 byte key")
        mode_name = args.get("mode", "cbc")
        iv = bytes_value(args.get("iv", ""), "hex")
        if mode_name == "ecb":
            if iv:
                raise ValueError("ECB does not use an IV")
            mode: modes.ECB | modes.CBC | modes.CTR = modes.ECB()
        elif mode_name == "cbc":
            mode = modes.CBC(iv)
        elif mode_name == "ctr":
            mode = modes.CTR(iv)
        else:
            raise ValueError("unsupported AES mode")
        decryptor = Cipher(algorithms.AES(key), mode).decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        if args.get("padding", "none") == "pkcs7":
            unpadder = padding.PKCS7(128).unpadder()
            plaintext = unpadder.update(plaintext) + unpadder.finalize()
        elif args.get("padding", "none") != "none":
            raise ValueError("unsupported padding")
        return byte_view(plaintext)
    if tool == "fermat_factor":
        args = parameters(data, {"n", "steps"}, {"n"})
        n, steps = number(args["n"]), number(args.get("steps", 1000))
        if n < 2 or not 1 <= steps <= 10_000:
            raise ValueError("invalid bounded Fermat input")
        if n % 2 == 0:
            return {"found": True, "p": "2", "q": str(n // 2), "steps": 0}
        a = math.isqrt(n)
        if a * a < n:
            a += 1
        for attempt in range(steps):
            delta = a * a - n
            b = math.isqrt(delta)
            if b * b == delta and a - b > 1:
                return {"found": True, "p": str(a - b), "q": str(a + b), "steps": attempt + 1}
            a += 1
        return {"found": False, "steps": steps}
    if tool == "rsa_common_modulus":
        args = parameters(data, {"n", "e1", "e2", "c1", "c2"}, {"n", "e1", "e2", "c1", "c2"})
        n, e1, e2, c1, c2 = (number(args[key]) for key in ("n", "e1", "e2", "c1", "c2"))
        if n < 2 or e1 < 1 or e2 < 1 or not 0 <= c1 < n or not 0 <= c2 < n:
            raise ValueError("invalid common-modulus inputs")
        old_r, r, old_s, s, old_t, t = e1, e2, 1, 0, 0, 1
        while r:
            quotient = old_r // r
            old_r, r = r, old_r - quotient * r
            old_s, s = s, old_s - quotient * s
            old_t, t = t, old_t - quotient * t
        if old_r != 1:
            raise ValueError("exponents must be coprime")
        message = pow(c1, old_s, n) * pow(c2, old_t, n) % n
        return {"integer": str(message), **byte_view(message.to_bytes(max(1, (message.bit_length() + 7) // 8)))}
    if tool in {"pack", "unpack"}:
        args = parameters(data, {"value", "data", "bits", "endian", "signed"}, set())
        bits, endian, signed = number(args.get("bits", 64)), args.get("endian", "little"), args.get("signed", False)
        if bits not in (8, 16, 32, 64) or endian not in ("little", "big") or not isinstance(signed, bool):
            raise ValueError("invalid packing format")
        if tool == "pack":
            return byte_view(number(args["value"]).to_bytes(bits // 8, endian, signed=signed))
        raw = bytes_value(args["data"], "hex")
        if len(raw) != bits // 8:
            raise ValueError("packed value length mismatch")
        value = int.from_bytes(raw, endian, signed=signed)
        return {"decimal": str(value), "hex": hex(value)}
    if tool in {"cyclic", "cyclic_find"}:
        args = parameters(data, {"length", "width", "value", "encoding"}, set())
        length, width = number(args.get("length", 4096)), number(args.get("width", 4))
        pattern = cyclic_pattern(length, width)
        if tool == "cyclic":
            return pattern.decode()
        needle = bytes_value(args["value"], args.get("encoding", "hex"))
        if not width <= len(needle) <= 64:
            raise ValueError("cyclic search needs at least width bytes")
        return {"offset": pattern.find(needle), "width": width, "searched_bytes": length}
    if tool == "caesar":
        args = parameters(data, {"text", "shift"}, {"text", "shift"})
        shift = number(args["shift"]) % 26
        text = bytes_value(args["text"]).decode()
        return "".join(chr((ord(char) - ord("A") + shift) % 26 + ord("A"))
                       if "A" <= char <= "Z" else
                       chr((ord(char) - ord("a") + shift) % 26 + ord("a"))
                       if "a" <= char <= "z" else char for char in text)
    if tool in {"xor", "xor_single"}:
        args = parameters(data, {"data", "key", "encoding", "key_encoding"}, {"data"})
        source = bytes_value(args["data"], args.get("encoding", "hex"))
        if tool == "xor":
            key = bytes_value(args["key"], args.get("key_encoding", "hex"))
            if not key:
                raise ValueError("empty XOR key")
            return byte_view(bytes(value ^ key[index % len(key)] for index, value in enumerate(source)))
        if len(source) > 4096:
            raise ValueError("single-byte XOR search is limited to 4096 bytes")
        ranked = []
        for byte_key in range(256):
            decoded = bytes(value ^ byte_key for value in source)
            ranked.append((score_text(decoded), byte_key, decoded))
        return [{"key_hex": f"{candidate_key:02x}", "score": score,
                 "text": decoded[:2048].decode(errors="replace")}
                for score, candidate_key, decoded in sorted(ranked, reverse=True)[:10]]
    if tool == "integer":
        value = number(data.strip())
        if value < 0:
            raise ValueError("integer byte conversion requires nonnegative input")
        return {"decimal": str(value), **byte_view(value.to_bytes(max(1, (value.bit_length() + 7) // 8)))}
    if tool in {"gcd", "mod_inverse"}:
        args = parameters(data, {"a", "b"}, {"a", "b"})
        a, b = number(args["a"]), number(args["b"])
        if tool == "gcd":
            return str(math.gcd(a, b))
        if b < 2:
            raise ValueError("invalid modulus")
        return str(pow(a, -1, b))
    if tool == "crt":
        args = parameters(data, {"residues", "moduli"}, {"residues", "moduli"})
        residues, moduli = args["residues"], args["moduli"]
        if not isinstance(residues, list) or not isinstance(moduli, list) or not 1 <= len(moduli) <= 32 or len(residues) != len(moduli):
            raise ValueError("invalid CRT system")
        x, modulus = 0, 1
        for raw_residue, raw_modulus in zip(residues, moduli, strict=True):
            residue, next_modulus = number(raw_residue), number(raw_modulus)
            if next_modulus < 2 or (modulus * next_modulus).bit_length() > 4096:
                raise ValueError("invalid CRT modulus size")
            common = math.gcd(modulus, next_modulus)
            if (residue - x) % common:
                raise ValueError("inconsistent CRT system")
            reduced = next_modulus // common
            factor = ((residue - x) // common * pow(modulus // common, -1, reduced)) % reduced if reduced > 1 else 0
            x += modulus * factor
            modulus *= reduced
            x %= modulus
        return {"value": str(x), "modulus": str(modulus)}
    if tool == "integer_root":
        args = parameters(data, {"n", "k"}, {"n", "k"})
        n, k = number(args["n"]), number(args["k"])
        if n < 0 or not 1 <= k <= 4096:
            raise ValueError("invalid root parameters")
        low, high = 0, 1 << ((n.bit_length() + k - 1) // k)
        while low < high:
            middle = (low + high + 1) // 2
            if pow(middle, k) <= n:
                low = middle
            else:
                high = middle - 1
        return {"root": str(low), "exact": pow(low, k) == n}
    if tool == "rsa_decrypt":
        args = parameters(data, {"n", "d", "c", "p", "q", "e"}, {"c"})
        if "d" in args:
            n, d = number(args["n"]), number(args["d"])
        else:
            e = number(args["e"])
            if "p" in args and "q" in args:
                p, q = number(args["p"]), number(args["q"])
            else:
                # One factor plus the modulus is enough (e.g. after a shared-prime gcd).
                modulus, known = number(args["n"]), number(args.get("p", args.get("q")))
                if known < 2 or modulus % known:
                    raise ValueError("supplied factor does not divide n")
                p, q = known, modulus // known
            if p < 2 or q < 2 or p == q or (p * q).bit_length() > 4096:
                raise ValueError("invalid supplied RSA factors")
            n, d = p * q, pow(e, -1, (p - 1) * (q - 1))
        c = number(args["c"])
        if n < 2 or d < 1 or not 0 <= c < n:
            raise ValueError("invalid RSA parameters")
        message = pow(c, d, n)
        return {"integer": str(message), **byte_view(message.to_bytes(max(1, (message.bit_length() + 7) // 8)))}
    raise ValueError("unknown structured tool")


def transform(request: ToolRequest) -> ToolResult:
    request = ToolRequest.model_validate(request.model_dump())
    if request.tool not in DATA_TOOLS:
        return ToolResult(ok=False, output="tool denied")
    try:
        data, tool = request.data, request.tool
        if len(data.encode()) > 65_536:
            raise ValueError("input exceeds limit")
        if tool == "base64_decode":
            output: Any = base64.b64decode(data, validate=True).decode()
        elif tool == "base64_encode":
            output = base64.b64encode(data.encode()).decode()
        elif tool == "base64url_decode":
            if not re.fullmatch(r"[A-Za-z0-9_=-]*", data):
                raise ValueError("invalid URL-safe Base64")
            output = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode()
        elif tool == "base64url_encode":
            output = base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")
        elif tool == "base32_decode":
            output = base64.b32decode(data, casefold=True).decode()
        elif tool == "base85_decode":
            output = base64.b85decode(data).decode()
        elif tool == "hex_decode":
            output = bytes.fromhex(data).decode()
        elif tool == "hex_encode":
            output = data.encode().hex()
        elif tool == "sha256":
            output = hashlib.sha256(data.encode()).hexdigest()
        elif tool == "hashes":
            output = {name: hashlib.new(name, data.encode(), usedforsecurity=False).hexdigest()
                      for name in ("md5", "sha1", "sha256", "sha512")}
        elif tool == "url_decode":
            output = urllib.parse.unquote_plus(data, errors="strict")
        elif tool == "url_encode":
            output = urllib.parse.quote(data, safe="")
        elif tool == "html_decode":
            output = html.unescape(data)
        elif tool == "rot13":
            output = codecs.decode(data, "rot_13")
        elif tool == "reverse":
            output = data[::-1]
        elif tool == "flag_candidates":
            braced = re.findall(
                r"[A-Za-z0-9_]{1,32}\{[^{}\r\n]{1,200}\}", data,
            )
            prefixed = re.findall(r"(?:FLAG|flag)_[A-Za-z0-9_!$%+.,:@=/\-]{1,200}", data)
            output = {"candidates": list(dict.fromkeys([*braced, *prefixed]))[:100], "verified": False}
        elif tool == "frequency":
            counts = Counter(data)
            output = {"length": len(data), "counts": dict(counts.most_common(256)),
                      "truncated": len(counts) > 256}
        elif tool == "jwt_decode":
            parts = data.strip().split(".")
            if len(parts) != 3:
                raise ValueError("JWT needs three segments")
            decoded = [json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))) for part in parts[:2]]
            output = {"header": decoded[0], "claims": decoded[1], "signature_verified": False}
        elif tool == "http_parse":
            header, _, body = data.replace("\r\n", "\n").partition("\n\n")
            lines = header.splitlines()
            output = {"start_line": lines[0] if lines else "", "headers": [
                {"name": key.strip(), "value": value.strip()}
                for line in lines[1:] if ":" in line for key, value in [line.split(":", 1)]
            ], "body": body}
        else:
            output = _structured(tool, data)
        return ToolResult(ok=True, output=output if isinstance(output, str) else json.dumps(output))
    except (ValueError, KeyError, TypeError, OverflowError, zlib.error):
        hint = ""
        if request.tool in JSON_TOOL_INPUTS:
            accepted, required = JSON_TOOL_INPUTS[request.tool]
            example = json.dumps({key: "..." for key in (required or accepted[:1])})
            hint = f" (? = optional; integers may be decimal or 0x-hex strings; e.g. --data '{example}')"
        return ToolResult(ok=False, output=("invalid or unsupported bounded tool input; "
                                            f"{request.tool} expects {input_shape(request.tool)}{hint}"))

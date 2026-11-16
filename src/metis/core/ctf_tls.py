"""Decrypt captured TLS 1.0-1.2 sessions that use RSA key exchange (Issue #23).

Given one prime factor of a server certificate's RSA modulus (for example from ``gcd`` over two
moduli that share a prime), the tool rebuilds the private key, decrypts each ClientKeyExchange
to the pre-master secret, derives the master secret (including the extended master secret) and
session keys with the version's PRF, and decrypts the application records. Abbreviated
(resumed) handshakes reuse the master secret of the full handshake with the same session ID.
Every record's MAC (or GCM tag) is verified, so a wrong key cannot pass as plaintext.

Supported cipher suites (RSA key exchange only):
  TLS_RSA_WITH_RC4_128_MD5 (0x0004), TLS_RSA_WITH_RC4_128_SHA (0x0005),
  TLS_RSA_WITH_AES_128_CBC_SHA (0x002f), TLS_RSA_WITH_AES_256_CBC_SHA (0x0035),
  TLS_RSA_WITH_AES_128_CBC_SHA256 (0x003c), TLS_RSA_WITH_AES_256_CBC_SHA256 (0x003d),
  TLS_RSA_WITH_AES_128_GCM_SHA256 (0x009c), TLS_RSA_WITH_AES_256_GCM_SHA384 (0x009d),
with Encrypt-then-MAC and the extended master secret. Out of scope: TLS 1.3, (EC)DHE key
exchange (forward secrecy; an RSA key cannot decrypt it), compression, SSL 3.0, renegotiation.

Nothing here is persisted: keys, secrets and plaintext only exist in the returned observation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.decrepit.ciphers.algorithms import ARC4
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from metis.core.ctf_tools import number
from metis.core.ctf_x509 import _frames, _streams, certificate_facts

# suite -> (name, cipher, key bytes, mac hash or None for AEAD, PRF hash for TLS 1.2)
SUITES: dict[int, tuple[str, str, int, str | None, str]] = {
    0x0004: ("TLS_RSA_WITH_RC4_128_MD5", "rc4", 16, "md5", "sha256"),
    0x0005: ("TLS_RSA_WITH_RC4_128_SHA", "rc4", 16, "sha1", "sha256"),
    0x002F: ("TLS_RSA_WITH_AES_128_CBC_SHA", "aes-cbc", 16, "sha1", "sha256"),
    0x0035: ("TLS_RSA_WITH_AES_256_CBC_SHA", "aes-cbc", 32, "sha1", "sha256"),
    0x003C: ("TLS_RSA_WITH_AES_128_CBC_SHA256", "aes-cbc", 16, "sha256", "sha256"),
    0x003D: ("TLS_RSA_WITH_AES_256_CBC_SHA256", "aes-cbc", 32, "sha256", "sha256"),
    0x009C: ("TLS_RSA_WITH_AES_128_GCM_SHA256", "aes-gcm", 16, None, "sha256"),
    0x009D: ("TLS_RSA_WITH_AES_256_GCM_SHA384", "aes-gcm", 32, None, "sha384"),
}
MAC_SIZE = {"md5": 16, "sha1": 20, "sha256": 32}
VERSIONS = {0x0301: "TLS 1.0", 0x0302: "TLS 1.1", 0x0303: "TLS 1.2"}
MAX_PLAINTEXT = 4 * 1024 * 1024
PREVIEW = 600


# -- PRF ------------------------------------------------------------------------------------
def _p_hash(name: str, secret: bytes, seed: bytes, size: int) -> bytes:
    out, a = b"", seed
    while len(out) < size:
        a = hmac.new(secret, a, name).digest()
        out += hmac.new(secret, a + seed, name).digest()
    return out[:size]


def prf(version: int, prf_hash: str, secret: bytes, label: bytes, seed: bytes, size: int) -> bytes:
    if version >= 0x0303:
        return _p_hash(prf_hash, secret, label + seed, size)
    half = (len(secret) + 1) // 2
    md5 = _p_hash("md5", secret[:half], label + seed, size)
    sha1 = _p_hash("sha1", secret[-half:], label + seed, size)
    return bytes(x ^ y for x, y in zip(md5, sha1, strict=True))


def _session_hash(version: int, prf_hash: str, messages: bytes) -> bytes:
    if version >= 0x0303:
        return hashlib.new(prf_hash, messages).digest()
    return hashlib.md5(messages, usedforsecurity=False).digest() + hashlib.sha1(messages,
                                                                               usedforsecurity=False).digest()


# -- parsing ------------------------------------------------------------------------------------
@dataclass
class Side:
    handshake: list[tuple[int, bytes, bytes]] = field(default_factory=list)  # (type, body, raw message)
    records: list[tuple[int, int, bytes]] = field(default_factory=list)      # encrypted (type, version, fragment)
    ccs_seen: bool = False


def _split(stream: bytes) -> Side:
    side, buffer, offset = Side(), bytearray(), 0
    while offset + 5 <= len(stream):
        kind, version, length = stream[offset], struct.unpack_from(">H", stream, offset + 1)[0], \
            struct.unpack_from(">H", stream, offset + 3)[0]
        fragment = stream[offset + 5: offset + 5 + length]
        offset += 5 + length
        if kind not in (20, 21, 22, 23) or version >> 8 != 3:
            break
        if kind == 20:
            side.ccs_seen = True
            continue
        if side.ccs_seen:
            side.records.append((kind, version, fragment))
        elif kind == 22:
            buffer += fragment
    position = 0
    while position + 4 <= len(buffer):
        kind, size = buffer[position], int.from_bytes(buffer[position + 1:position + 4], "big")
        raw = bytes(buffer[position:position + 4 + size])
        side.handshake.append((kind, raw[4:], raw))
        position += 4 + size
    return side


def _hello(body: bytes) -> dict[str, Any]:
    version = struct.unpack_from(">H", body, 0)[0]
    random, session_length = body[2:34], body[34]
    session = body[35:35 + session_length]
    offset = 35 + session_length
    return {"version": version, "random": random, "session_id": session, "rest": body[offset:]}


def _extensions(data: bytes) -> set[int]:
    if len(data) < 2:
        return set()
    total, offset, found = struct.unpack_from(">H", data, 0)[0], 2, set()
    while offset + 4 <= min(len(data), 2 + total):
        kind, size = struct.unpack_from(">HH", data, offset)
        found.add(kind)
        offset += 4 + size
    return found


def _client_extension(hello_rest: bytes, wanted: int) -> bytes | None:
    """Extension payload from the part of a ClientHello after the session ID."""
    try:
        offset = 2 + struct.unpack_from(">H", hello_rest, 0)[0]
        offset += 1 + hello_rest[offset]
        total = struct.unpack_from(">H", hello_rest, offset)[0]
        offset += 2
        end = offset + total
        while offset + 4 <= end:
            kind, size = struct.unpack_from(">HH", hello_rest, offset)
            if kind == wanted:
                return hello_rest[offset + 4:offset + 4 + size]
            offset += 4 + size
    except (struct.error, IndexError):
        return None
    return None


def _connections(capture: bytes, packets: int) -> list[dict[str, Any]]:
    linktype, frames, _more = _frames(capture, packets)
    streams = _streams(linktype, frames)
    pairs: dict[tuple[str, int, str, int], dict[str, Any]] = {}
    for (source, sport, destination, dport), data in streams.items():
        side = _split(data)
        kinds = {kind for kind, _body, _raw in side.handshake}
        if not kinds & {1, 2}:
            continue
        client_side = 1 in kinds
        key = (source, sport, destination, dport) if client_side else (destination, dport, source, sport)
        pairs.setdefault(key, {})["client" if client_side else "server"] = side
    connections = []
    for (client_ip, client_port, server_ip, server_port), sides in sorted(pairs.items()):
        if "client" not in sides or "server" not in sides:
            continue
        connections.append({"connection": f"{client_ip}:{client_port}->{server_ip}:{server_port}",
                            "client": sides["client"], "server": sides["server"]})
    return connections


# -- record decryption ------------------------------------------------------------------------------
def _decrypt_records(side: Side, *, version: int, suite: tuple[str, str, int, str | None, str], mac_key: bytes,
                     key: bytes, iv: bytes, etm: bool) -> dict[str, Any]:
    _name, cipher, _size, mac_name, _prf = suite
    mac_size = MAC_SIZE[mac_name] if mac_name else 0
    rc4 = Cipher(ARC4(key), mode=None).decryptor() if cipher == "rc4" else None
    chained_iv = iv
    plaintext, mac_ok, mac_bad, records = bytearray(), 0, 0, 0
    for sequence, (kind, record_version, fragment) in enumerate(side.records):
        header = struct.pack(">QBH", sequence, kind, record_version)
        content = b""
        valid = False
        if cipher == "aes-gcm":
            if len(fragment) < 24:
                mac_bad += 1
                continue
            nonce, sealed = iv[:4] + fragment[:8], fragment[8:]
            try:
                content = AESGCM(key).decrypt(nonce, sealed, header + struct.pack(">H", len(sealed) - 16))
                valid = True
            except Exception:  # noqa: BLE001 -- an invalid tag is a failed record, not an error
                valid = False
        elif cipher == "rc4" and rc4 is not None:
            data = rc4.update(fragment)
            content, tag = data[:-mac_size], data[-mac_size:]
            assert mac_name is not None
            valid = hmac.compare_digest(hmac.new(mac_key, header + struct.pack(">H", len(content)) + content,
                                                 mac_name).digest(), tag)
        else:
            assert mac_name is not None
            body = fragment
            if etm:
                body, tag = fragment[:-mac_size], fragment[-mac_size:]
                expected = hmac.new(mac_key, header + struct.pack(">H", len(body)) + body, mac_name).digest()
                valid = hmac.compare_digest(expected, tag)
            if version >= 0x0302:
                record_iv, body = body[:16], body[16:]
            else:
                record_iv = chained_iv
            if len(body) % 16 or not body:
                mac_bad += 1
                continue
            data = Cipher(algorithms.AES(key), modes.CBC(record_iv)).decryptor().update(body)
            chained_iv = body[-16:]
            pad = data[-1]
            if pad + 1 > len(data):
                mac_bad += 1
                continue
            data = data[:-(pad + 1)]
            if etm:
                content = data
            else:
                content, tag = data[:-mac_size], data[-mac_size:]
                valid = hmac.compare_digest(hmac.new(mac_key, header + struct.pack(">H", len(content)) + content,
                                                     mac_name).digest(), tag)
        records += 1
        if not valid:
            mac_bad += 1
            continue
        mac_ok += 1
        if kind == 23 and len(plaintext) < MAX_PLAINTEXT:
            plaintext += content[:MAX_PLAINTEXT - len(plaintext)]
    return {"records": records, "mac_ok": mac_ok, "mac_failed": mac_bad, "plaintext": bytes(plaintext)}


def _http_messages(data: bytes) -> list[dict[str, Any]]:
    """Split an HTTP/1.x byte stream into messages (Content-Length bodies; others to the end)."""
    messages: list[dict[str, Any]] = []
    offset = 0
    while offset < len(data) and len(messages) < 32:
        end = data.find(b"\r\n\r\n", offset)
        if end < 0 or not data[offset:offset + 16].split(b" ")[0][:5] in (b"HTTP/", b"GET", b"POST", b"PUT",
                                                                           b"HEAD", b"DELET", b"OPTIO", b"PATCH"):
            break
        head = data[offset:end].decode("latin-1")
        lines = head.split("\r\n")
        headers = {name.strip().lower(): value.strip() for name, _, value in
                   (line.partition(":") for line in lines[1:]) if name}
        length = headers.get("content-length")
        body_end = end + 4 + int(length) if length and length.isdigit() else len(data)
        body = data[end + 4:body_end]
        messages.append({"start_line": lines[0][:200], "content_type": headers.get("content-type", "")[:100],
                         "content_length": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
                         "body_offset": end + 4})
        offset = body_end
    return messages


# -- the tool ---------------------------------------------------------------------------------------
def _factor(options: dict[str, Any]) -> int:
    if "factor" not in options:
        raise ValueError("tls_decrypt needs options.factor: a prime factor of a server RSA modulus")
    value = number(options["factor"])
    if value < 3:
        raise ValueError("factor must be a prime factor greater than 2")
    return value


def tls_decrypt(capture: bytes, options: dict[str, Any], *, packets: int, connections_limit: int,
                preview: int = PREVIEW) -> dict[str, Any]:
    factor = _factor(options)
    found = _connections(capture, packets)[:connections_limit]
    masters: dict[bytes, tuple[bytes, str]] = {}
    results: list[dict[str, Any]] = []
    plaintexts: dict[tuple[int, str], bytes] = {}
    states: list[dict[str, Any]] = []
    # Pass 1: full handshakes -> master secrets.
    for index, conn in enumerate(found):
        client, server = conn["client"], conn["server"]
        hello_c = next((body for kind, body, _raw in client.handshake if kind == 1), None)
        hello_s = next((body for kind, body, _raw in server.handshake if kind == 2), None)
        entry: dict[str, Any] = {"index": index, "connection": conn["connection"]}
        state: dict[str, Any] = {"entry": entry, "conn": conn}
        states.append(state)
        if hello_c is None or hello_s is None:
            entry["reason"] = "no_handshake"
            continue
        ch, sh = _hello(hello_c), _hello(hello_s)
        suite_id = struct.unpack_from(">H", sh["rest"], 0)[0] if len(sh["rest"]) >= 2 else -1
        extensions = _extensions(sh["rest"][3:])
        entry.update(version=VERSIONS.get(sh["version"], f"0x{sh['version']:04x}"), cipher_suite=f"{suite_id:04x}",
                     session_id=sh["session_id"].hex()[:16], extended_master_secret=0x0017 in extensions,
                     encrypt_then_mac=0x0016 in extensions)
        state.update(ch=ch, sh=sh, suite_id=suite_id, extensions=extensions)
        if sh["version"] not in VERSIONS or 0x002B in extensions:
            entry["reason"] = "unsupported_version"
            continue
        if suite_id not in SUITES:
            entry["reason"] = "unsupported_cipher_suite (only RSA key exchange suites listed in the tool help)"
            continue
        entry["suite"] = SUITES[suite_id][0]
        certificate = next((body for kind, body, _raw in server.handshake if kind == 11), None)
        exchange = next((body for kind, body, _raw in client.handshake if kind == 16), None)
        if certificate is None or exchange is None:
            continue  # abbreviated handshake: resolved in pass 2
        first = int.from_bytes(certificate[3:6], "big")
        public = certificate_facts(certificate[6:6 + first])["public_key"]
        if public.get("type") != "RSA":
            entry["reason"] = "not_rsa_certificate"
            continue
        n, e = int(public["n"]), int(public["e"])
        if n % factor:
            entry["reason"] = "factor_does_not_divide_this_modulus"
            continue
        p, q = factor, n // factor
        d = pow(e, -1, (p - 1) * (q - 1))
        key = rsa.RSAPrivateNumbers(p, q, d, d % (p - 1), d % (q - 1), pow(q, -1, p),
                                    rsa.RSAPublicNumbers(e, n)).private_key()
        size = (n.bit_length() + 7) // 8
        ciphertext = exchange[2:] if len(exchange) == 2 + size else exchange
        try:
            premaster = key.decrypt(ciphertext, padding.PKCS1v15())
        except ValueError:
            entry["reason"] = "premaster_decrypt_failed"
            continue
        if len(premaster) != 48:
            entry["reason"] = "premaster_not_48_bytes"
            continue
        suite = SUITES[suite_id]
        if 0x0017 in extensions:
            messages = b"".join(raw for kind, _body, raw in client.handshake if kind == 1)
            messages += b"".join(raw for kind, _body, raw in server.handshake if kind != 4)  # not NewSessionTicket
            messages += b"".join(raw for kind, _body, raw in client.handshake if kind not in (1, 15, 20))
            seed = _session_hash(sh["version"], suite[4], messages)
            master = prf(sh["version"], suite[4], premaster, b"extended master secret", seed, 48)
        else:
            master = prf(sh["version"], suite[4], premaster, b"master secret", ch["random"] + sh["random"], 48)
        if sh["session_id"]:
            masters[b"sid:" + sh["session_id"]] = (master, conn["connection"])
        ticket = next((body for kind, body, _raw in server.handshake if kind == 4), None)
        if ticket and len(ticket) > 6:
            masters[b"tkt:" + ticket[6:6 + struct.unpack_from(">H", ticket, 4)[0]]] = (master, conn["connection"])
        entry["key_source"] = "factor divides this certificate's modulus"
        state["master"] = master
    # Pass 2: resumed sessions, then record decryption.
    for state in states:
        entry = state["entry"]
        if "reason" in entry or "sh" not in state:
            results.append(entry)
            continue
        if "master" not in state:
            offered = _client_extension(state["ch"]["rest"], 35)
            known = masters.get(b"tkt:" + offered) if offered else None
            if known is None and state["sh"]["session_id"]:
                known = masters.get(b"sid:" + state["sh"]["session_id"])
            if known is None:
                entry["reason"] = "no_master_secret (resumed session without its full handshake, or factor mismatch)"
                results.append(entry)
                continue
            state["master"], entry["resumed_from"] = known
        version, suite = state["sh"]["version"], SUITES[state["suite_id"]]
        _name, cipher, key_size, mac_name, prf_hash = suite
        mac_size = MAC_SIZE[mac_name] if mac_name else 0
        iv_size = 4 if cipher == "aes-gcm" else 16 if cipher == "aes-cbc" else 0
        block = prf(version, prf_hash, state["master"], b"key expansion",
                    state["sh"]["random"] + state["ch"]["random"], 2 * (mac_size + key_size + iv_size))
        sizes = (mac_size, mac_size, key_size, key_size, iv_size, iv_size)
        offsets = [sum(sizes[:index]) for index in range(len(sizes) + 1)]
        client_mac, server_mac, client_key, server_key, client_iv, server_iv = (
            block[offsets[index]:offsets[index + 1]] for index in range(len(sizes)))
        etm = 0x0016 in state["extensions"] and cipher == "aes-cbc"
        entry["decrypted"] = True
        for side_name, side, mac_key, write_key, iv in (
                ("client", state["conn"]["client"], client_mac, client_key, client_iv),
                ("server", state["conn"]["server"], server_mac, server_key, server_iv)):
            result = _decrypt_records(side, version=version, suite=suite, mac_key=mac_key, key=write_key, iv=iv,
                                      etm=etm)
            plain = result.pop("plaintext")
            plaintexts[(entry["index"], side_name)] = plain
            entry[side_name] = {**result, "application_bytes": len(plain),
                                "preview": plain[:preview].decode("utf-8", errors="replace"),
                                "http": _http_messages(plain)}
            if result["records"] and not result["mac_ok"]:
                entry["decrypted"] = False
                entry["reason"] = "record_mac_failed (wrong key or unsupported record format)"
        results.append(entry)
    return {"connections": results, "decrypted": sum(1 for item in results if item.get("decrypted")),
            "supported_suites": [f"{suite:04x} {SUITES[suite][0]}" for suite in SUITES], "_plaintexts": plaintexts}


def http_body(capture: bytes, options: dict[str, Any], *, packets: int, connections_limit: int,
              max_bytes: int) -> dict[str, Any]:
    """One decrypted HTTP body, Base64-encoded, for ``derive`` (registers it as a new artifact)."""
    result = tls_decrypt(capture, options, packets=packets, connections_limit=connections_limit, preview=0)
    index, side = number(options.get("connection", 0)), str(options.get("side", "server"))
    message = number(options.get("message", 0))
    if side not in {"client", "server"}:
        raise ValueError("side must be client or server")
    entry = next((item for item in result["connections"] if item["index"] == index), None)
    if entry is None or not entry.get("decrypted"):
        raise ValueError("that connection was not decrypted")
    plain = result["_plaintexts"][(index, side)]
    messages = entry[side]["http"]
    if not 0 <= message < len(messages):
        raise ValueError("no such HTTP message on that side")
    start = messages[message]["body_offset"]
    body = plain[start:start + messages[message]["content_length"]]
    if len(body) > max_bytes:
        raise ValueError("HTTP body exceeds max_bytes")
    return {"base64": base64.b64encode(body).decode(), "size": len(body), "content_type":
            messages[message]["content_type"], "sha256": hashlib.sha256(body).hexdigest()}

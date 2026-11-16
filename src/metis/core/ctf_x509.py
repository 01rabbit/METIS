"""Bounded X.509 and TLS-certificate analysis (Issue #17).

Two artifact tools, both static and read-only:

* ``x509``             - DER or PEM certificate file(s) -> certificate facts and public key.
* ``tls_certificates`` - classic PCAP / PCAPNG capture -> TCP streams -> cleartext TLS
                         (SSL 3.0 - TLS 1.2) Certificate handshakes -> the same facts per
                         connection, plus the negotiated version, cipher suite and session ID.

RSA keys report the modulus ``n`` (decimal and hex) and exponent ``e`` so they can feed
``gcd`` / ``rsa_decrypt`` intents directly. Failures are returned as structured reason codes
instead of exceptions so a specialist can tell "no certificate here" from "parser limit".
"""
from __future__ import annotations

import base64
import re
import struct
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa

MAX_CERTIFICATES = 16
MAX_CONNECTIONS = 32
MAX_STREAM = 4 * 1024 * 1024
PEM = re.compile(rb"-----BEGIN CERTIFICATE-----\s+([A-Za-z0-9+/=\s]+?)-----END CERTIFICATE-----")


def _key(certificate: x509.Certificate) -> dict[str, Any]:
    try:
        key = certificate.public_key()
    except (ValueError, TypeError) as exc:
        return {"type": "unknown", "error": "unsupported_key", "detail": str(exc)[:120]}
    if isinstance(key, rsa.RSAPublicKey):
        numbers = key.public_numbers()
        return {"type": "RSA", "bits": key.key_size, "n": str(numbers.n), "n_hex": format(numbers.n, "x"),
                "e": numbers.e}
    if isinstance(key, ec.EllipticCurvePublicKey):
        point = key.public_numbers()
        return {"type": "EC", "curve": key.curve.name, "bits": key.curve.key_size, "x": str(point.x),
                "y": str(point.y)}
    if isinstance(key, dsa.DSAPublicKey):
        parameters = key.public_numbers()
        return {"type": "DSA", "bits": key.key_size, "y": str(parameters.y)}
    if isinstance(key, ed25519.Ed25519PublicKey | ed448.Ed448PublicKey):
        return {"type": type(key).__name__.replace("PublicKey", "")}
    return {"type": type(key).__name__}


def _name(value: x509.Name) -> str:
    try:
        return value.rfc4514_string()
    except ValueError:
        return "<unparseable name>"


def certificate_facts(der: bytes) -> dict[str, Any]:
    certificate = x509.load_der_x509_certificate(der)
    try:
        signature = certificate.signature_algorithm_oid._name
    except AttributeError:
        signature = certificate.signature_algorithm_oid.dotted_string
    return {
        "subject": _name(certificate.subject), "issuer": _name(certificate.issuer),
        "serial": str(certificate.serial_number), "version": certificate.version.name,
        "not_before": certificate.not_valid_before_utc.isoformat(),
        "not_after": certificate.not_valid_after_utc.isoformat(),
        "signature_algorithm": signature, "self_issued": certificate.subject == certificate.issuer,
        "sha256": certificate.fingerprint(hashes.SHA256()).hex(), "der_bytes": len(der),
        "public_key": _key(certificate),
    }


def _parse_all(blobs: list[tuple[str, bytes]], limit: int) -> dict[str, Any]:
    certificates: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, (source, der) in enumerate(blobs[:limit]):
        try:
            certificates.append({"index": index, "format": source, **certificate_facts(der)})
        except (ValueError, TypeError) as exc:
            errors.append({"index": index, "reason": "der_parse_error", "detail": str(exc)[:160]})
    if len(blobs) > limit:
        errors.append({"reason": "certificate_limit", "detail": f"{len(blobs) - limit} more not parsed"})
    return {"certificates": certificates, "errors": errors}


def x509_file(data: bytes, options: dict[str, Any], limit: int) -> dict[str, Any]:
    blobs: list[tuple[str, bytes]] = []
    for match in PEM.finditer(data):
        try:
            blobs.append(("PEM", base64.b64decode(b"".join(match.group(1).split()), validate=True)))
        except ValueError:
            blobs.append(("PEM", b""))
    if not blobs and data[:1] == b"\x30":
        blobs.append(("DER", data))
    if not blobs:
        return {"certificates": [], "count": 0,
                "errors": [{"reason": "not_der_or_pem",
                            "detail": "no PEM CERTIFICATE block and no DER SEQUENCE at offset 0"}]}
    result = _parse_all(blobs, limit)
    result["count"] = len(result["certificates"])
    return result


# -- capture -> TCP streams -------------------------------------------------------------------
def _frames(capture: bytes, packets: int) -> tuple[int, list[bytes], bool]:
    endian = "<" if capture[:4] in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
    linktype = struct.unpack_from(endian + "I", capture, 20)[0]
    frames: list[bytes] = []
    offset = 24
    while offset + 16 <= len(capture) and len(frames) < packets:
        captured = struct.unpack_from(endian + "I", capture, offset + 8)[0]
        frames.append(capture[offset + 16: offset + 16 + captured])
        offset += 16 + captured
    return linktype, frames, offset + 16 <= len(capture)


def _ip_payload(linktype: int, frame: bytes) -> bytes | None:
    if linktype == 1:  # Ethernet, with optional 802.1Q tags
        offset, ethertype = 14, frame[12:14]
        while ethertype == b"\x81\x00" and len(frame) >= offset + 4:
            ethertype, offset = frame[offset + 2:offset + 4], offset + 4
        return frame[offset:] if ethertype in (b"\x08\x00", b"\x86\xdd") else None
    if linktype in (0, 108):  # BSD loopback
        return frame[4:]
    if linktype == 101:  # raw IP
        return frame
    if linktype == 113:  # Linux cooked
        return frame[16:] if frame[14:16] in (b"\x08\x00", b"\x86\xdd") else None
    return None


def _tcp(packet: bytes) -> tuple[tuple[str, int, str, int], int, bytes] | None:
    if not packet:
        return None
    version = packet[0] >> 4
    if version == 4 and len(packet) >= 20:
        header, protocol = (packet[0] & 15) * 4, packet[9]
        total = struct.unpack_from(">H", packet, 2)[0] or len(packet)
        source, destination = ".".join(map(str, packet[12:16])), ".".join(map(str, packet[16:20]))
        segment = packet[header:total]
    elif version == 6 and len(packet) >= 40:
        protocol, header = packet[6], 40
        source, destination = packet[8:24].hex(), packet[24:40].hex()
        segment = packet[header:header + struct.unpack_from(">H", packet, 4)[0]]
    else:
        return None
    if protocol != 6 or len(segment) < 20:
        return None
    sport, dport, sequence = struct.unpack_from(">HHI", segment, 0)
    return (source, sport, destination, dport), sequence, segment[(segment[12] >> 4) * 4:]


def _streams(linktype: int, frames: list[bytes]) -> dict[tuple[str, int, str, int], bytes]:
    flows: dict[tuple[str, int, str, int], dict[int, bytes]] = {}
    for frame in frames:
        payload = _ip_payload(linktype, frame)
        parsed = _tcp(payload) if payload else None
        if parsed and parsed[2]:
            flows.setdefault(parsed[0], {}).setdefault(parsed[1], parsed[2])
    streams = {}
    for key, segments in flows.items():
        base = min(segments)
        buffer = bytearray()
        for sequence in sorted(segments):
            position = sequence - base
            chunk = segments[sequence]
            if position > len(buffer):
                break  # a gap: stop at the first missing segment
            buffer[position:position + len(chunk)] = chunk
            if len(buffer) > MAX_STREAM:
                break
        streams[key] = bytes(buffer[:MAX_STREAM])
    return streams


def _handshake_bytes(stream: bytes) -> tuple[bytes, list[str], bool]:
    """Concatenate cleartext handshake fragments until ChangeCipherSpec."""
    handshake, offset = bytearray(), 0
    versions: list[str] = []
    while offset + 5 <= len(stream):
        kind, major, minor, length = stream[offset], stream[offset + 1], stream[offset + 2], \
            struct.unpack_from(">H", stream, offset + 3)[0]
        if kind not in (20, 21, 22, 23) or major != 3:
            return bytes(handshake), versions, False
        versions.append(f"{major}.{minor}")
        if kind == 20:
            break
        if kind == 22:
            handshake += stream[offset + 5: offset + 5 + length]
        offset += 5 + length
    return bytes(handshake), versions, True


def _messages(handshake: bytes) -> list[tuple[int, bytes]]:
    messages, offset = [], 0
    while offset + 4 <= len(handshake):
        kind, length = handshake[offset], int.from_bytes(handshake[offset + 1:offset + 4], "big")
        messages.append((kind, handshake[offset + 4: offset + 4 + length]))
        offset += 4 + length
    return messages


VERSIONS = {"0300": "SSL 3.0", "0301": "TLS 1.0", "0302": "TLS 1.1", "0303": "TLS 1.2", "0304": "TLS 1.3"}


def tls_certificates(capture: bytes, options: dict[str, Any], *, packets: int, connections: int,
                     limit: int) -> dict[str, Any]:
    linktype, frames, more = _frames(capture, packets)
    streams = _streams(linktype, frames)
    found: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    for (source, sport, destination, dport), stream in sorted(streams.items()):
        handshake, versions, is_tls = _handshake_bytes(stream)
        if not versions:
            continue
        name = f"{source}:{sport}->{destination}:{dport}"
        if not is_tls:
            errors.append({"connection": name, "reason": "not_tls_records"})
            continue
        for kind, body in _messages(handshake):
            if kind == 2 and len(body) >= 38:  # ServerHello
                session_length = body[34]
                suite = body[35 + session_length:37 + session_length].hex()
                version = body[0:2].hex()
                if b"\x00\x2b\x00\x02\x03\x04" in body:  # supported_versions = TLS 1.3
                    version = "0304"
                found.setdefault(name, {"connection": name})
                found[name].update(version=VERSIONS.get(version, version), cipher_suite=suite,
                                   session_id=body[35:35 + session_length].hex())
                if version == "0304":
                    found[name]["certificates_encrypted"] = True
                    errors.append({"connection": name, "reason": "tls13_certificates_encrypted"})
            elif kind == 11:  # Certificate (TLS <= 1.2)
                total, offset, blobs = int.from_bytes(body[0:3], "big"), 3, []
                while offset + 3 <= min(len(body), 3 + total):
                    size = int.from_bytes(body[offset:offset + 3], "big")
                    blobs.append(("DER", body[offset + 3:offset + 3 + size]))
                    offset += 3 + size
                parsed = _parse_all(blobs, limit)
                entry = found.setdefault(name, {"connection": name})
                entry["certificates"] = parsed["certificates"]
                errors.extend({"connection": name, **error} for error in parsed["errors"])
        if len(found) >= connections:
            errors.append({"reason": "connection_limit", "detail": f"stopped after {connections} connections"})
            break
    by_session = {entry["session_id"]: entry["connection"] for entry in found.values()
                  if entry.get("certificates") and entry.get("session_id")}
    for entry in found.values():
        if not entry.get("certificates") and entry.get("session_id") in by_session:
            entry["resumed_from"] = by_session[entry["session_id"]]  # abbreviated handshake, same keys
    if not found:
        errors.append({"reason": "no_tls_handshake", "detail": "no cleartext TLS handshake in the parsed packets"})
    elif not any(entry.get("certificates") for entry in found.values()):
        errors.append({"reason": "no_certificate_message",
                       "detail": "TLS seen but no Certificate message (resumed sessions or TLS 1.3)"})
    return {"connections": list(found.values()), "connection_count": len(found),
            "certificate_count": sum(len(entry.get("certificates", [])) for entry in found.values()),
            "packets_parsed": len(frames), "more_records": more, "errors": errors}


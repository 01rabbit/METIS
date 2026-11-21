"""Bounded, offline TCP stream reassembly for PCAP/PCAPNG (``pcap_streams``, ``pcap_stream``, ``http_objects``).

Pure Python and read-only. Segments are placed by sequence number (first-wins on retransmissions
and overlaps), SYN fixes the initial sequence number, and missing ranges are reported as gaps
instead of being invented. Everything is capped: packets, streams, bytes per direction and
decompressed HTTP body size.
"""
from __future__ import annotations

import base64
import bisect
import hashlib
import re
import struct
import zlib
from dataclasses import dataclass, field
from typing import Any

from metis.core.ctf_tools import byte_view, number
from metis.core.ctf_x509 import _frames, _ip_payload

MAX_STREAMS = 256
MAX_DIRECTION_BYTES = 4 * 1024 * 1024
MAX_OBJECTS = 256
FIN, SYN, RST, ACK = 1, 2, 4, 16
HTTP_METHODS = (b"GET ", b"POST ", b"PUT ", b"HEAD ", b"DELETE ", b"OPTIONS ", b"PATCH ", b"CONNECT ")
Endpoint = tuple[str, int]


@dataclass
class Direction:
    segments: list[tuple[int, int, bytes]] = field(default_factory=list)  # (arrival, seq, data)
    packets: int = 0
    syn_seq: int | None = None
    first_seq: int | None = None
    fin: bool = False
    rst: bool = False


@dataclass
class Stream:
    client: Endpoint
    server: Endpoint
    dirs: dict[str, Direction] = field(default_factory=lambda: {"client": Direction(), "server": Direction()})
    client_known: bool = False


@dataclass
class Assembled:
    data: bytes
    gaps: list[dict[str, int]]
    pieces: list[tuple[int, int, int]]  # (output start, output end, arrival)
    truncated: bool


def _tcp_packet(packet: bytes) -> tuple[Endpoint, Endpoint, int, int, bytes] | None:
    if not packet:
        return None
    version = packet[0] >> 4
    if version == 4 and len(packet) >= 20:
        header, protocol = (packet[0] & 15) * 4, packet[9]
        total = struct.unpack_from(">H", packet, 2)[0] or len(packet)
        if header < 20 or total < header or struct.unpack_from(">H", packet, 6)[0] & 0x3fff:
            return None  # invalid or fragmented
        source = ".".join(map(str, packet[12:16]))
        destination = ".".join(map(str, packet[16:20]))
        segment = packet[header:total]
    elif version == 6 and len(packet) >= 40:
        protocol, header = packet[6], 40
        length = struct.unpack_from(">H", packet, 4)[0]
        for _ in range(4):
            if protocol not in (0, 43, 60) or len(packet) < header + 8:
                break
            protocol, header = packet[header], header + (packet[header + 1] + 1) * 8
        source, destination = packet[8:24].hex(), packet[24:40].hex()
        segment = packet[header:40 + length] if length else packet[header:]
    else:
        return None
    if protocol != 6 or len(segment) < 20:
        return None
    sport, dport, sequence = struct.unpack_from(">HHI", segment, 0)
    offset = (segment[12] >> 4) * 4
    if offset < 20 or offset > len(segment):
        return None
    return (source, sport), (destination, dport), sequence, segment[13], segment[offset:]


def collect_streams(capture: bytes, packets: int) -> tuple[list[Stream], bool, bool]:
    """Group TCP packets into bidirectional streams; returns (streams, more packets, stream cap hit)."""
    linktype, frames, more = _frames(capture, packets)
    streams: dict[frozenset[Endpoint], Stream] = {}
    order: list[Stream] = []
    capped = False
    for arrival, frame in enumerate(frames):
        ip = _ip_payload(linktype, frame)
        parsed = _tcp_packet(ip) if ip else None
        if parsed is None:
            continue
        source, destination, sequence, flags, payload = parsed
        key = frozenset((source, destination))
        stream = streams.get(key)
        if stream is None:
            if len(order) >= MAX_STREAMS:
                capped = True
                continue
            stream = Stream(client=source, server=destination)
            streams[key] = stream
            order.append(stream)
        if flags & SYN and not stream.client_known:
            stream.client_known = True
            if flags & ACK:
                stream.client, stream.server = destination, source
            else:
                stream.client, stream.server = source, destination
        direction = stream.dirs["client" if source == stream.client else "server"]
        direction.packets += 1
        if flags & SYN:
            direction.syn_seq = sequence
        if flags & FIN:
            direction.fin = True
        if flags & RST:
            direction.rst = True
        if payload:
            if direction.first_seq is None:
                direction.first_seq = sequence
            direction.segments.append((arrival, sequence, payload))
    return order, more, capped


def _signed(value: int, reference: int) -> int:
    return ((value - reference + 0x80000000) & 0xFFFFFFFF) - 0x80000000


def assemble(direction: Direction, limit: int = MAX_DIRECTION_BYTES) -> Assembled:
    """Order segments by sequence number; first-seen bytes win; holes are recorded as gaps."""
    if not direction.segments:
        return Assembled(b"", [], [], False)
    reference = ((direction.syn_seq + 1) & 0xFFFFFFFF) if direction.syn_seq is not None \
        else (direction.first_seq or 0)
    relative = [(arrival, _signed(seq, reference), data) for arrival, seq, data in direction.segments]
    if direction.syn_seq is None:
        base = min(start for _a, start, _d in relative)
        relative = [(a, start - base, d) for a, start, d in relative]
    covered_starts: list[int] = []
    covered: list[tuple[int, int]] = []
    pieces: list[tuple[int, bytes, int]] = []  # (start, bytes, arrival)
    truncated = False
    for arrival, start, data in relative:
        if start < 0:
            data, start = data[-start:], 0
        end = start + len(data)
        if end > limit:
            truncated = True
            data = data[:max(0, limit - start)]
            end = start + len(data)
        if not data:
            continue
        cursor = start
        index = max(0, bisect.bisect_right(covered_starts, start) - 1)
        new: list[tuple[int, int]] = []
        while index < len(covered) and covered[index][0] < end:
            c_start, c_end = covered[index]
            if c_end > cursor:
                if c_start > cursor:
                    new.append((cursor, c_start))
                cursor = max(cursor, c_end)
            index += 1
        if cursor < end:
            new.append((cursor, end))
        for n_start, n_end in new:
            pieces.append((n_start, data[n_start - start:n_end - start], arrival))
            position = bisect.bisect_left(covered_starts, n_start)
            covered_starts.insert(position, n_start)
            covered.insert(position, (n_start, n_end))
    pieces.sort(key=lambda item: item[0])
    out = bytearray()
    gaps: list[dict[str, int]] = []
    spans: list[tuple[int, int, int]] = []
    position, newest = 0, 0
    for start, data, arrival in pieces:
        if start > position:
            gaps.append({"offset": len(out), "missing": start - position})
        newest = max(newest, arrival)
        spans.append((len(out), len(out) + len(data), newest))
        out.extend(data)
        position = start + len(data)
    return Assembled(bytes(out), gaps, spans, truncated)


def protocol_hint(stream: Stream, client: bytes, server: bytes) -> str:
    ports = {stream.client[1], stream.server[1]}
    if client.startswith(HTTP_METHODS) or server.startswith(b"HTTP/"):
        return "HTTP"
    if server.startswith(b"SSH-") or client.startswith(b"SSH-"):
        return "SSH"
    if client[:2] == b"\x16\x03" or server[:2] == b"\x16\x03":
        return "TLS"
    if server[:4] in (b"220 ", b"220-"):
        lowered = server[:200].lower()
        if b"smtp" in lowered or ports & {25, 587}:
            return "SMTP"
        return "FTP"
    if re.match(rb"(USER|PASS|RETR|STOR|PASV|LIST) ", client[:8]):
        return "FTP"
    if re.match(rb"(EHLO|HELO|MAIL FROM:)", client[:12], re.IGNORECASE):
        return "SMTP"
    if server.startswith(b"+OK"):
        return "POP3"
    if 53 in ports:
        return "DNS-over-TCP"
    if 23 in ports:
        return "Telnet"
    return "unknown"


def _label(endpoint: Endpoint) -> str:
    host, port = endpoint
    return f"[{host}]:{port}" if len(host) == 32 else f"{host}:{port}"


_PRINTABLE = {code: 46 for code in [*range(9), *range(11, 13), *range(14, 32), *range(127, 160)]}


def _preview(data: bytes, size: int) -> dict[str, Any]:
    chunk = data[:size]
    return {"hex": chunk.hex(), "text": chunk.decode("latin-1").translate(_PRINTABLE)}


def list_streams(capture: bytes, *, packets: int, limit: int, preview: int) -> dict[str, Any]:
    streams, more, capped = collect_streams(capture, packets)
    entries = []
    for index, stream in enumerate(streams[:limit]):
        client, server = stream.dirs["client"], stream.dirs["server"]
        a_client, a_server = assemble(client), assemble(server)
        entries.append({
            "index": index, "client": _label(stream.client), "server": _label(stream.server),
            "packets": client.packets + server.packets,
            "packets_client": client.packets, "packets_server": server.packets,
            "bytes_client": len(a_client.data), "bytes_server": len(a_server.data),
            "gaps_client": len(a_client.gaps), "gaps_server": len(a_server.gaps),
            "syn": client.syn_seq is not None or server.syn_seq is not None,
            "fin": client.fin or server.fin, "rst": client.rst or server.rst,
            "truncated": a_client.truncated or a_server.truncated,
            "protocol": protocol_hint(stream, a_client.data, a_server.data),
            "preview_client": _preview(a_client.data, preview),
            "preview_server": _preview(a_server.data, preview),
        })
    return {"streams": entries, "stream_count": len(streams), "more_records": more,
            "streams_capped": capped or len(streams) > limit}


def _stream(streams: list[Stream], index: int) -> Stream:
    if not 0 <= index < len(streams):
        raise ValueError(f"no such stream; capture has {len(streams)}")
    return streams[index]


def stream_payload(capture: bytes, options: dict[str, Any], *, packets: int, max_bytes: int) -> dict[str, Any]:
    """Reassembled payload of one stream; ``base64`` makes it usable with ``derive``."""
    streams, more, _capped = collect_streams(capture, packets)
    index = number(options.get("index", 0))
    stream = _stream(streams, index)
    side = str(options.get("direction", "both"))
    if side not in {"client", "server", "both"}:
        raise ValueError("direction must be client, server or both")
    parts = {name: assemble(stream.dirs[name]) for name in ("client", "server")}
    segments: list[dict[str, Any]] = []
    if side == "both":
        chunks = [(arrival, name != "client", start, name, part.data[start:end])
                  for name, part in parts.items() for start, end, arrival in part.pieces]
        chunks.sort(key=lambda item: item[:3])
        data = bytearray()
        for _arrival, _flag, _start, name, chunk in chunks:
            if segments and segments[-1]["direction"] == name:
                segments[-1]["size"] += len(chunk)
            else:
                segments.append({"direction": name, "offset": len(data), "size": len(chunk)})
            data.extend(chunk)
        content = bytes(data)
        gaps = {name: parts[name].gaps for name in parts}
    else:
        content, gaps = parts[side].data, {side: parts[side].gaps}
    result = byte_view(content[:max_bytes])
    result.update(index=index, direction=side, total_size=len(content),
                  truncated=len(content) > max_bytes or any(part.truncated for part in parts.values()),
                  gaps=gaps, more_records=more, sha256=hashlib.sha256(content).hexdigest(),
                  client=_label(stream.client), server=_label(stream.server))
    if side == "both":
        result["segments"] = segments[:200]
    return result


# -- HTTP -------------------------------------------------------------------------------------

def _headers(block: bytes) -> tuple[str, dict[str, str]]:
    lines = block.decode("latin-1").split("\r\n")
    fields: dict[str, str] = {}
    for line in lines[1:]:
        name, separator, value = line.partition(":")
        if separator:
            fields.setdefault(name.strip().lower(), value.strip())
    return lines[0], fields


def _chunked(data: bytes, start: int) -> tuple[bytes, int, bool]:
    body, cursor = bytearray(), start
    while True:
        end = data.find(b"\r\n", cursor)
        if end < 0 or end - cursor > 20:
            return bytes(body), len(data), False
        try:
            size = int(data[cursor:end].split(b";")[0].strip() or b"x", 16)
        except ValueError:
            return bytes(body), len(data), False
        cursor = end + 2
        if size == 0:
            trailer = data.find(b"\r\n\r\n", cursor - 2)
            return bytes(body), (trailer + 4 if trailer >= 0 else len(data)), True
        if cursor + size > len(data):
            body.extend(data[cursor:])
            return bytes(body), len(data), False
        body.extend(data[cursor:cursor + size])
        cursor += size + 2
        if len(body) > MAX_DIRECTION_BYTES:
            return bytes(body), len(data), False


def _messages(data: bytes, *, response: bool) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(data) and len(messages) < MAX_OBJECTS:
        end = data.find(b"\r\n\r\n", cursor)
        starts_ok = data.startswith(b"HTTP/", cursor) if response else data.startswith(HTTP_METHODS, cursor)
        if end < 0 or not starts_ok:
            break
        start_line, fields = _headers(data[cursor:end])
        body_start = end + 4
        parts = start_line.split()
        status = int(parts[1]) if response and len(parts) > 1 and parts[1].isdigit() else 0
        complete = True
        if "chunked" in fields.get("transfer-encoding", "").lower():
            body, next_cursor, complete = _chunked(data, body_start)
        elif fields.get("content-length", "").isdigit():
            length = int(fields["content-length"])
            body = data[body_start:body_start + length]
            complete = len(body) == length
            next_cursor = body_start + len(body)
        elif response and not (100 <= status < 200 or status in (204, 304)):
            body, next_cursor = data[body_start:], len(data)
        else:
            body, next_cursor = b"", body_start
        messages.append({"start_line": start_line, "headers": fields, "body": body, "complete": complete})
        cursor = next_cursor
    return messages


def _decode_body(body: bytes, encoding: str, max_bytes: int) -> tuple[bytes, str | None]:
    lowered = encoding.lower()
    if lowered not in {"gzip", "x-gzip", "deflate"}:
        return body, None
    try:
        decoder = zlib.decompressobj((16 if "gzip" in lowered else 0) + zlib.MAX_WBITS)
        decoded = decoder.decompress(body, max_bytes + 1)
    except zlib.error as exc:
        return body, f"decompression failed: {exc}"
    if len(decoded) > max_bytes:
        raise ValueError("decompressed HTTP object exceeds max_bytes")
    return decoded, None


def _name(path: str, fields: dict[str, str]) -> str:
    disposition = re.search(r'filename="?([^";]+)', fields.get("content-disposition", ""))
    if disposition:
        return disposition.group(1)
    return path.split("?", 1)[0].rsplit("/", 1)[-1] or "(index)"


def http_objects(capture: bytes, options: dict[str, Any], *, packets: int, max_bytes: int) -> dict[str, Any]:
    """List HTTP response bodies across streams, or return one (``object``) for ``derive``."""
    streams, more, _capped = collect_streams(capture, packets)
    wanted = options.get("object")
    only_stream = options.get("index")
    found: list[dict[str, Any]] = []
    for index, stream in enumerate(streams):
        if only_stream is not None and index != number(only_stream):
            continue
        server, client = assemble(stream.dirs["server"]), assemble(stream.dirs["client"])
        requests = _messages(client.data, response=False)
        for position, response in enumerate(_messages(server.data, response=True)):
            request = requests[position] if position < len(requests) else None
            parts = request["start_line"].split() if request else []
            path = parts[1] if len(parts) > 1 else ""
            fields = response["headers"]
            found.append({"stream": index, "message": position, "status": response["start_line"],
                          "url": f"{request['headers'].get('host', '') if request else ''}{path}",
                          "filename": _name(path, fields), "content_type": fields.get("content-type", ""),
                          "content_encoding": fields.get("content-encoding", ""),
                          "wire_size": len(response["body"]),
                          "complete": response["complete"] and not server.gaps, "gaps": len(server.gaps),
                          "_body": response["body"]})
    for ordinal, item in enumerate(found):
        item["object"] = ordinal
    if wanted is None:
        listing = [{key: value for key, value in item.items() if key != "_body"} for item in found[:MAX_OBJECTS]]
        return {"objects": listing, "object_count": len(found), "more_records": more}
    matches = [entry for entry in found if entry["object"] == number(wanted)]
    if not matches:
        raise ValueError("no such HTTP object; list objects first")
    item = matches[0]
    body, warning = _decode_body(item["_body"], item["content_encoding"], max_bytes)
    if len(body) > max_bytes:
        raise ValueError("HTTP object exceeds max_bytes")
    meta = {key: value for key, value in item.items() if key != "_body"}
    return {**meta, "base64": base64.b64encode(body).decode(), "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(), "decode_warning": warning}

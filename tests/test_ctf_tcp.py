"""TCP reassembly tools over synthetic PCAP/PCAPNG captures."""
from __future__ import annotations

import base64
import gzip
import struct

import pytest

from metis.core.ctf_artifacts import ALLOWED_OPTIONS, ARTIFACT_TOOLS, DERIVE_TOOLS, inspect_bytes

CLIENT, SERVER = "10.0.0.2", "10.0.0.9"
SYN, ACK, PSH, FIN = 2, 16, 8, 1


def _ip(src: str, dst: str, sport: int, dport: int, seq: int, flags: int, payload: bytes = b"") -> bytes:
    tcp = struct.pack(">HHIIBBHHH", sport, dport, seq, 0, 5 << 4, flags, 65535, 0, 0) + payload
    head = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 0, 0, 64, 6, 0,
                       bytes(map(int, src.split("."))), bytes(map(int, dst.split("."))))
    return head + tcp


def _ethernet(packet: bytes) -> bytes:
    return b"\x00" * 12 + b"\x08\x00" + packet


def _pcap(frames: list[bytes], linktype: int = 1) -> bytes:
    out = bytearray(struct.pack("<IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, linktype))
    for number, frame in enumerate(frames):
        out += struct.pack("<IIII", 1_700_000_000 + number, 0, len(frame), len(frame)) + frame
    return bytes(out)


def _pcapng(frames: list[bytes]) -> bytes:
    def block(kind: int, body: bytes) -> bytes:
        body += b"\x00" * (-len(body) % 4)
        return struct.pack("<II", kind, len(body) + 12) + body + struct.pack("<I", len(body) + 12)

    out = block(0x0a0d0d0a, struct.pack("<IHHq", 0x1a2b3c4d, 1, 0, -1))
    out += block(1, struct.pack("<HHI", 1, 0, 65535))
    for number, frame in enumerate(frames):
        out += block(6, struct.pack("<IIIII", 0, 0, number, len(frame), len(frame)) + frame)
    return out


def _conversation(request: bytes, response: bytes, *, mss: int = 40) -> list[bytes]:
    """Handshake, request, response split into ``mss`` segments, FIN; returns IP packets in order."""
    c_seq, s_seq = 1000, 5000
    packets = [_ip(CLIENT, SERVER, 40000, 80, c_seq - 1, SYN),
               _ip(SERVER, CLIENT, 80, 40000, s_seq - 1, SYN | ACK),
               _ip(CLIENT, SERVER, 40000, 80, c_seq, ACK)]
    packets.append(_ip(CLIENT, SERVER, 40000, 80, c_seq, PSH | ACK, request))
    c_seq += len(request)
    for start in range(0, len(response), mss):
        chunk = response[start:start + mss]
        packets.append(_ip(SERVER, CLIENT, 80, 40000, s_seq + start, PSH | ACK, chunk))
    s_seq += len(response)
    packets += [_ip(SERVER, CLIENT, 80, 40000, s_seq, FIN | ACK),
                _ip(CLIENT, SERVER, 40000, 80, c_seq, FIN | ACK)]
    return packets


def _http(body: bytes, headers: str = "") -> bytes:
    return (f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\n{headers}\r\n"
            ).encode() + body


REQUEST = b"GET /files/flag.txt HTTP/1.1\r\nHost: ctf.example\r\n\r\n"
BODY = b"flag{reassembled-" + bytes(range(65, 91)) * 3 + b"}"


def test_tools_registered_and_flag_set():
    assert {"pcap_streams", "pcap_stream", "http_objects"} <= ARTIFACT_TOOLS
    assert {"pcap_stream", "http_objects"} <= DERIVE_TOOLS
    assert ALLOWED_OPTIONS["pcap_stream"] >= {"index", "direction"}
    capture = _pcap([_ethernet(p) for p in _conversation(REQUEST, _http(BODY))])
    assert inspect_bytes(capture, "pcap")["tcp_reassembly"] is True


def test_streams_listing_and_in_order_reassembly():
    frames = [_ethernet(p) for p in _conversation(REQUEST, _http(BODY))]
    result = inspect_bytes(_pcap(frames), "pcap_streams")
    (stream,) = result["streams"]
    assert stream["client"] == f"{CLIENT}:40000" and stream["server"] == f"{SERVER}:80"
    assert stream["protocol"] == "HTTP" and stream["syn"] and stream["fin"]
    assert stream["bytes_client"] == len(REQUEST) and stream["bytes_server"] == len(_http(BODY))
    assert stream["gaps_server"] == 0
    assert stream["preview_client"]["text"].startswith("GET /files/flag.txt")
    server = inspect_bytes(_pcap(frames), "pcap_stream", {"index": 0, "direction": "server"})
    assert base64.b64decode(server["base64"]) == _http(BODY)
    both = inspect_bytes(_pcap(frames), "pcap_stream", {"index": 0})
    assert base64.b64decode(both["base64"]) == REQUEST + _http(BODY)
    assert [s["direction"] for s in both["segments"]] == ["client", "server"]


def test_out_of_order_retransmit_and_overlap_first_wins():
    packets = _conversation(REQUEST, _http(BODY))
    data = packets[4:-2]
    shuffled = [data[3], data[0], data[2], data[1], *data[4:]]
    shuffled.insert(2, data[0])  # exact retransmission
    # overlapping retransmission carrying different bytes: the first-seen bytes must win
    seq = 5000
    poison = _ip(SERVER, CLIENT, 80, 40000, seq + 10, PSH | ACK, b"X" * 50)
    shuffled.append(poison)
    frames = [_ethernet(p) for p in [*packets[:4], *shuffled, *packets[-2:]]]
    out = inspect_bytes(_pcap(frames), "pcap_stream", {"index": 0, "direction": "server"})
    assert base64.b64decode(out["base64"]) == _http(BODY)
    assert out["gaps"] == {"server": []}


def test_missing_segment_is_marked_as_gap():
    packets = _conversation(REQUEST, _http(BODY))
    del packets[6]  # drop the third server segment
    out = inspect_bytes(_pcap([_ethernet(p) for p in packets]), "pcap_stream",
                        {"index": 0, "direction": "server"})
    (gap,) = out["gaps"]["server"]
    assert gap == {"offset": 80, "missing": 40}
    assert out["total_size"] == len(_http(BODY)) - 40
    listing = inspect_bytes(_pcap([_ethernet(p) for p in packets]), "pcap_streams")
    assert listing["streams"][0]["gaps_server"] == 1


def test_sequence_wraparound_without_syn():
    start = 0xFFFFFFF0
    packets = [_ip(CLIENT, SERVER, 1234, 21, (start + 24) & 0xFFFFFFFF, PSH, b"PASS secret\r\n"),
               _ip(CLIENT, SERVER, 1234, 21, start, PSH, b"USER anonymous\r\n"),
               ]
    out = inspect_bytes(_pcap([_ethernet(p) for p in packets]), "pcap_stream", {"direction": "client"})
    assert base64.b64decode(out["base64"]) == b"USER anonymous\r\nPASS secret\r\n"
    assert out["gaps"]["client"] == [{"offset": 16, "missing": 8}]
    listing = inspect_bytes(_pcap([_ethernet(p) for p in packets]), "pcap_streams")
    assert listing["streams"][0]["protocol"] == "FTP"


def test_pcapng_raw_ip_and_sll_inputs():
    packets = _conversation(REQUEST, _http(BODY))
    expected = base64.b64encode(_http(BODY)).decode()
    options = {"index": 0, "direction": "server"}
    assert inspect_bytes(_pcapng([_ethernet(p) for p in packets]), "pcap_stream", options)["base64"] == expected
    assert inspect_bytes(_pcap(packets, linktype=101), "pcap_stream", options)["base64"] == expected
    sll = [b"\x00\x00\x00\x01\x00\x06" + b"\x00" * 8 + b"\x08\x00" + p for p in packets]
    assert inspect_bytes(_pcap(sll, linktype=113), "pcap_stream", options)["base64"] == expected


def test_ipv6_stream():
    def v6(src: bytes, dst: bytes, sport: int, dport: int, seq: int, payload: bytes) -> bytes:
        tcp = struct.pack(">HHIIBBHHH", sport, dport, seq, 0, 5 << 4, PSH | ACK, 65535, 0, 0) + payload
        return struct.pack(">IHBB16s16s", 6 << 28, len(tcp), 6, 64, src, dst) + tcp
    a, b = b"\x20\x01" + b"\x00" * 13 + b"\x01", b"\x20\x01" + b"\x00" * 13 + b"\x02"
    frames = [b"\x00" * 12 + b"\x86\xdd" + v6(a, b, 5000, 25, 1, b"EHLO x\r\n"),
              b"\x00" * 12 + b"\x86\xdd" + v6(b, a, 25, 5000, 9, b"250 ok\r\n")]
    result = inspect_bytes(_pcap(frames), "pcap_streams")["streams"][0]
    assert result["bytes_client"] == 8 and result["bytes_server"] == 8 and result["protocol"] == "SMTP"


def test_http_objects_content_length_and_chunked_and_gzip():
    plain = b"plain-body-" * 10
    packed = gzip.compress(b"compressed secret " * 20)
    chunked_payload = b"chunk-one|chunk-two-is-longer|end"
    chunked = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Type: application/octet-stream\r\n\r\n"
               + b"".join(b"%x\r\n" % len(part) + part + b"\r\n" for part in
                          (chunked_payload[:9], chunked_payload[9:30], chunked_payload[30:]))
               + b"0\r\n\r\n")
    gz = _http(packed, "Content-Encoding: gzip\r\n")
    requests = b"".join(f"GET /f{n} HTTP/1.1\r\nHost: h\r\n\r\n".encode() for n in range(3))
    responses = _http(plain) + chunked + gz
    frames = [_ethernet(p) for p in _conversation(requests, responses, mss=37)]
    capture = _pcap(frames)
    listing = inspect_bytes(capture, "http_objects")
    assert [o["url"] for o in listing["objects"]] == ["h/f0", "h/f1", "h/f2"]
    assert all(o["complete"] for o in listing["objects"])
    assert listing["objects"][2]["content_encoding"] == "gzip"
    bodies = [base64.b64decode(inspect_bytes(capture, "http_objects", {"object": n})["base64"]) for n in range(3)]
    assert bodies == [plain, chunked_payload, b"compressed secret " * 20]


def test_http_object_limits_and_errors():
    big = gzip.compress(b"\x00" * 100_000)
    frames = [_ethernet(p) for p in _conversation(REQUEST, _http(big, "Content-Encoding: gzip\r\n"), mss=1000)]
    capture = _pcap(frames)
    with pytest.raises(ValueError, match="exceeds max_bytes"):
        inspect_bytes(capture, "http_objects", {"object": 0, "max_bytes": 1000})
    with pytest.raises(ValueError, match="no such HTTP object"):
        inspect_bytes(capture, "http_objects", {"object": 9})
    with pytest.raises(ValueError, match="no such stream"):
        inspect_bytes(capture, "pcap_stream", {"index": 5})
    with pytest.raises(ValueError, match="direction"):
        inspect_bytes(capture, "pcap_stream", {"direction": "sideways"})
    with pytest.raises(ValueError, match="unknown option"):
        inspect_bytes(capture, "pcap_streams", {"bogus": 1})


def test_stream_count_and_output_are_bounded():
    from metis.core import ctf_tcp
    frames = [_ethernet(_ip(CLIENT, SERVER, 10000 + n, 80, 1, PSH, b"GET / HTTP/1.1\r\n\r\n"))
              for n in range(ctf_tcp.MAX_STREAMS + 20)]
    result = inspect_bytes(_pcap(frames), "pcap_streams", {"limit": 10})
    assert len(result["streams"]) == 10 and result["streams_capped"] is True
    assert result["stream_count"] == ctf_tcp.MAX_STREAMS
    big = _http(b"A" * 5000)
    out = inspect_bytes(_pcap([_ethernet(p) for p in _conversation(REQUEST, big, mss=1000)]),
                        "pcap_stream", {"direction": "server", "max_bytes": 100})
    assert out["size"] == 100 and out["total_size"] == len(big) and out["truncated"] is True

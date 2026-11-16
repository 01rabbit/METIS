"""TLS RSA key-exchange decryption (Issue #23).

Test vectors are real sessions produced by the local OpenSSL (through Python's ssl module and
memory BIOs, no sockets): an implementation independent of METIS encrypts, METIS decrypts and
verifies every record MAC/tag. RC4 is disabled in modern OpenSSL; the RC4-MD5 path is checked
with the ksnctf #33 capture when METIS_TEST_KSNCTF33_PCAP is set (not stored in Git, see #15).
"""
import datetime
import json
import os
import ssl
import struct
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from metis.core.ctf_artifacts import ALLOWED_OPTIONS, ARTIFACT_TOOLS, inspect_file
from metis.core.ctf_tls import SUITES, prf

pytestmark = pytest.mark.filterwarnings("ignore:ssl.TLSVersion.TLSv1 is deprecated:DeprecationWarning")

BODY = b"synthetic body: the decrypted response\n" * 20
REQUEST = b"GET /secret.txt HTTP/1.1\r\nHost: test\r\n\r\n"
RESPONSE = b"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\nContent-Length: " + str(len(BODY)).encode() + \
    b"\r\n\r\n" + BODY


@pytest.fixture(scope="module")
def server_key(tmp_path_factory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "tls.test")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(7).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256()))
    directory = tmp_path_factory.mktemp("tlskey")
    (directory / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (directory / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                                          serialization.PrivateFormat.TraditionalOpenSSL,
                                                          serialization.NoEncryption()))
    return key, directory


def _contexts(directory: Path, version: ssl.TLSVersion, cipher: str, *, tickets: bool = True):
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    for context in (server, client):
        context.minimum_version = context.maximum_version = version
        context.set_ciphers(cipher + ":@SECLEVEL=0")
    if not tickets:
        server.options |= ssl.OP_NO_TICKET
    server.load_cert_chain(directory / "cert.pem", directory / "key.pem")
    client.check_hostname = False
    client.verify_mode = ssl.CERT_NONE
    return server, client


def _session(server_ctx, client_ctx, *, session=None):
    """Run one TLS connection in memory; return (client->server bytes, server->client bytes, session)."""
    c_in, c_out, s_in, s_out = ssl.MemoryBIO(), ssl.MemoryBIO(), ssl.MemoryBIO(), ssl.MemoryBIO()
    client = client_ctx.wrap_bio(c_in, c_out, server_hostname="tls.test", session=session)
    server = server_ctx.wrap_bio(s_in, s_out, server_side=True)
    to_server, to_client = bytearray(), bytearray()

    def pump():
        data = c_out.read()
        to_server.extend(data)
        s_in.write(data)
        data = s_out.read()
        to_client.extend(data)
        c_in.write(data)

    for _ in range(20):
        for side in (client, server):
            try:
                side.do_handshake()
            except ssl.SSLWantReadError:
                pass
        pump()
        if client.version() and server.version():
            break
    client.write(REQUEST)
    pump()
    assert server.read(4096) == REQUEST
    server.write(RESPONSE)
    pump()
    received = b""
    while len(received) < len(RESPONSE):
        received += client.read(65536)
    pump()
    return bytes(to_server), bytes(to_client), client.session


def _frame(source, destination, sport, dport, sequence, payload):
    tcp = struct.pack(">HHIIBBHHH", sport, dport, sequence, 0, 5 << 4, 0x18, 65535, 0, 0) + payload
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 0, 0, 64, 6, 0,
                     bytes(map(int, source.split("."))), bytes(map(int, destination.split("."))))
    return b"\x00" * 12 + b"\x08\x00" + ip + tcp


def _pcap(connections):
    frames = []
    for port, (up, down) in enumerate(connections, start=40000):
        for offset in range(0, len(up), 700):  # several segments per direction
            frames.append(_frame("198.51.100.7", "192.0.2.1", port, 443, 1000 + offset, up[offset:offset + 700]))
        for offset in range(0, len(down), 900):
            frames.append(_frame("192.0.2.1", "198.51.100.7", 443, port, 9000 + offset, down[offset:offset + 900]))
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    for index, frame in enumerate(frames):
        out += struct.pack("<IIII", index, 0, len(frame), len(frame)) + frame
    return out


CASES = [(ssl.TLSVersion.TLSv1_2, "AES128-SHA", "002f"), (ssl.TLSVersion.TLSv1_2, "AES256-SHA", "0035"),
         (ssl.TLSVersion.TLSv1_2, "AES128-SHA256", "003c"), (ssl.TLSVersion.TLSv1_2, "AES256-SHA256", "003d"),
         (ssl.TLSVersion.TLSv1_2, "AES128-GCM-SHA256", "009c"), (ssl.TLSVersion.TLSv1_2, "AES256-GCM-SHA384", "009d"),
         (ssl.TLSVersion.TLSv1, "AES128-SHA", "002f")]


@pytest.mark.parametrize("version, cipher, suite", CASES, ids=[f"{v.name}-{c}" for v, c, _ in CASES])
def test_openssl_sessions_decrypt_with_verified_macs(tmp_path, server_key, version, cipher, suite):
    key, directory = server_key
    try:
        server_ctx, client_ctx = _contexts(directory, version, cipher)
        up, down, _session_obj = _session(server_ctx, client_ctx)
    except (ssl.SSLError, ValueError) as exc:
        pytest.skip(f"local OpenSSL cannot produce {version.name} {cipher}: {exc}")
    (tmp_path / "s.pcap").write_bytes(_pcap([(up, down)]))
    factor = str(key.private_numbers().p)
    result = inspect_file(tmp_path, "s.pcap", "tls_decrypt", {"factor": factor})
    entry = result["connections"][0]
    assert entry["cipher_suite"] == suite and entry["decrypted"] is True, entry
    assert entry["server"]["mac_failed"] == 0 and entry["client"]["mac_failed"] == 0
    assert entry["client"]["http"][0]["start_line"] == "GET /secret.txt HTTP/1.1"
    assert entry["server"]["http"][0]["content_length"] == len(BODY)
    body = inspect_file(tmp_path, "s.pcap", "tls_http_body", {"factor": factor})
    import base64
    assert base64.b64decode(body["base64"]) == BODY


@pytest.mark.parametrize("tickets", [True, False], ids=["ticket", "session-id"])
def test_resumed_sessions_reuse_the_full_handshake_master_secret(tmp_path, server_key, tickets):
    key, directory = server_key
    server_ctx, client_ctx = _contexts(directory, ssl.TLSVersion.TLSv1_2, "AES128-SHA", tickets=tickets)
    first_up, first_down, session = _session(server_ctx, client_ctx)
    second_up, second_down, _ = _session(server_ctx, client_ctx, session=session)
    (tmp_path / "r.pcap").write_bytes(_pcap([(first_up, first_down), (second_up, second_down)]))
    result = inspect_file(tmp_path, "r.pcap", "tls_decrypt", {"factor": str(key.private_numbers().q)})
    full, resumed = result["connections"]
    assert full["decrypted"] and resumed["decrypted"], result
    assert resumed["resumed_from"] == full["connection"]
    assert resumed["server"]["http"][0]["content_length"] == len(BODY)


def test_wrong_factor_and_unsupported_input_are_reported(tmp_path, server_key):
    _key, directory = server_key
    server_ctx, client_ctx = _contexts(directory, ssl.TLSVersion.TLSv1_2, "AES128-SHA")
    up, down, _ = _session(server_ctx, client_ctx)
    (tmp_path / "s.pcap").write_bytes(_pcap([(up, down)]))
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=1024).private_numbers().p
    entry = inspect_file(tmp_path, "s.pcap", "tls_decrypt", {"factor": str(wrong)})["connections"][0]
    assert entry["reason"] == "factor_does_not_divide_this_modulus" and not entry.get("decrypted")
    with pytest.raises(ValueError, match="factor"):
        inspect_file(tmp_path, "s.pcap", "tls_decrypt", {})
    server13, client13 = _contexts(directory, ssl.TLSVersion.TLSv1_3, "AES128-SHA")
    server13.set_ciphers("ALL")
    up13, down13, _ = _session(server13, client13)
    (tmp_path / "t13.pcap").write_bytes(_pcap([(up13, down13)]))
    entry13 = inspect_file(tmp_path, "t13.pcap", "tls_decrypt", {"factor": "3"})["connections"][0]
    assert entry13["reason"] == "unsupported_version"
    ecdhe_server, ecdhe_client = _contexts(directory, ssl.TLSVersion.TLSv1_2, "ECDHE-RSA-AES128-GCM-SHA256")
    up_e, down_e, _ = _session(ecdhe_server, ecdhe_client)
    (tmp_path / "e.pcap").write_bytes(_pcap([(up_e, down_e)]))
    entry_e = inspect_file(tmp_path, "e.pcap", "tls_decrypt", {"factor": "3"})["connections"][0]
    assert entry_e["reason"].startswith("unsupported_cipher_suite")


def test_observation_and_tool_registry_hold_no_key_material(tmp_path, server_key):
    key, directory = server_key
    server_ctx, client_ctx = _contexts(directory, ssl.TLSVersion.TLSv1_2, "AES128-SHA")
    up, down, _ = _session(server_ctx, client_ctx)
    (tmp_path / "s.pcap").write_bytes(_pcap([(up, down)]))
    result = inspect_file(tmp_path, "s.pcap", "tls_decrypt", {"factor": str(key.private_numbers().p), "preview": 0})
    text = json.dumps(result)
    numbers = key.private_numbers()
    for secret in (numbers.d, numbers.p, numbers.q):
        assert str(secret) not in text
    assert "_plaintexts" not in result
    assert {"tls_decrypt", "tls_http_body"} <= ARTIFACT_TOOLS
    assert ALLOWED_OPTIONS["tls_decrypt"] == {"factor", "packets", "connections", "preview"}
    assert set(SUITES) == {0x0004, 0x0005, 0x002F, 0x0035, 0x003C, 0x003D, 0x009C, 0x009D}


def test_prf_is_deterministic_and_version_specific():
    secret, seed = b"\x01" * 48, b"\x02" * 64
    tls10 = prf(0x0301, "sha256", secret, b"master secret", seed, 48)
    tls12 = prf(0x0303, "sha256", secret, b"master secret", seed, 48)
    assert len(tls10) == len(tls12) == 48 and tls10 != tls12
    assert prf(0x0303, "sha384", secret, b"key expansion", seed, 72)[:48] != tls12


@pytest.mark.skipif(not os.environ.get("METIS_TEST_KSNCTF33_PCAP"),
                    reason="set METIS_TEST_KSNCTF33_PCAP to the ksnctf #33 distribution capture")
def test_ksnctf_33_rc4_md5_sessions_decrypt_end_to_end():
    import base64
    import math

    path = Path(os.environ["METIS_TEST_KSNCTF33_PCAP"])
    certificates = inspect_file(path.parent, path.name, "tls_certificates", {})
    moduli = [int(entry["certificates"][0]["public_key"]["n"]) for entry in certificates["connections"]
              if entry.get("certificates")]
    factor = str(math.gcd(*moduli))
    result = inspect_file(path.parent, path.name, "tls_decrypt", {"factor": factor, "preview": 0})
    assert result["decrypted"] == 4
    assert all(entry["suite"] == "TLS_RSA_WITH_RC4_128_MD5" for entry in result["connections"])
    assert sum(1 for entry in result["connections"] if entry.get("resumed_from")) == 2
    images = [entry for entry in result["connections"] if entry["server"]["http"][0]["content_type"] == "image/jpeg"]
    assert len(images) == 2
    body = inspect_file(path.parent, path.name, "tls_http_body", {"factor": factor, "connection": images[0]["index"]})
    assert base64.b64decode(body["base64"])[:3] == b"\xff\xd8\xff"

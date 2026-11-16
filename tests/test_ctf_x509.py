"""Certificate analysis tools (Issue #17): x509 and tls_certificates.

Synthetic certificates and captures are generated in the test; nothing is executed. The real
ksnctf #33 capture is not stored in Git (it would put a decryptable answer in the repository,
see #15); set METIS_TEST_KSNCTF33_PCAP to its path to run that regression locally.
"""
import datetime
import json
import os
import struct
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from metis.core.agent_host import BridgeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession
from metis.core.codex_specialist import CodexTurn, run_assignment
from metis.core.ctf_artifacts import ALLOWED_OPTIONS, ARTIFACT_TOOLS, inspect_file
from metis.core.ctf_orchestration import AgentLedger


# -- fixtures ------------------------------------------------------------------------------
def _shared_prime_keys():
    first = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    other = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    p, q = first.private_numbers().p, other.private_numbers().q
    e, n = 65537, p * q
    d = pow(e, -1, (p - 1) * (q - 1))
    second = rsa.RSAPrivateNumbers(p, q, d, d % (p - 1), d % (q - 1), pow(q, -1, p),
                                   rsa.RSAPublicNumbers(e, n)).private_key()
    return first, second


def _certificate(key, common_name: str, serial: int) -> x509.Certificate:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(serial).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=30))
            .sign(key, hashes.SHA256()))


def _record(kind: int, body: bytes, version: bytes = b"\x03\x01") -> bytes:
    return bytes([kind]) + version + struct.pack(">H", len(body)) + body


def _handshake(kind: int, body: bytes) -> bytes:
    return bytes([kind]) + len(body).to_bytes(3, "big") + body


def _server_flight(certificates: list[bytes], session: bytes, *, tls13: bool = False) -> bytes:
    hello = b"\x03\x01" + bytes(32) + bytes([len(session)]) + session + b"\x00\x04\x00"
    if tls13:
        hello = b"\x03\x03" + bytes(32) + bytes([len(session)]) + session + b"\x13\x01\x00" + \
            struct.pack(">H", 6) + b"\x00\x2b\x00\x02\x03\x04"
    chain = b"".join(len(der).to_bytes(3, "big") + der for der in certificates)
    messages = _handshake(2, hello) + (b"" if tls13 else _handshake(11, len(chain).to_bytes(3, "big") + chain)) \
        + _handshake(14, b"")
    half = len(messages) // 2  # handshake split across two records
    return _record(22, messages[:half]) + _record(22, messages[half:]) + _record(20, b"\x01")


def _frame(source: str, destination: str, sport: int, dport: int, sequence: int, payload: bytes) -> bytes:
    tcp = struct.pack(">HHIIBBHHH", sport, dport, sequence, 0, 5 << 4, 0x18, 65535, 0, 0) + payload
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 0, 0, 64, 6, 0,
                     bytes(map(int, source.split("."))), bytes(map(int, destination.split("."))))
    return b"\x00" * 12 + b"\x08\x00" + ip + tcp


def _pcap(frames: list[bytes]) -> bytes:
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    for index, frame in enumerate(frames):
        out += struct.pack("<IIII", index, 0, len(frame), len(frame)) + frame
    return out


def _capture(certificates_a: list[bytes], certificates_b: list[bytes]) -> bytes:
    frames = []
    for port, server, chain, session in ((1529, "192.0.2.39", certificates_a, b"\x11" * 32),
                                         (1531, "192.0.2.40", certificates_b, b"\x22" * 32)):
        client_hello = _record(22, _handshake(1, b"\x03\x01" + bytes(32) + b"\x00\x00\x02\x00\x04\x01\x00"))
        frames.append(_frame("198.51.100.7", server, port, 443, 1000, client_hello))
        flight = _server_flight(chain, session)
        cut = len(flight) // 3
        # second segment first: reassembly must order by sequence number
        frames.append(_frame(server, "198.51.100.7", 443, port, 5000 + cut, flight[cut:]))
        frames.append(_frame(server, "198.51.100.7", 443, port, 5000, flight[:cut]))
    # an abbreviated (resumed) handshake on a third connection, no Certificate message
    resumed = _record(22, _handshake(2, b"\x03\x01" + bytes(32) + b"\x20" + b"\x11" * 32 + b"\x00\x04\x00")) + \
        _record(20, b"\x01")
    frames.append(_frame("192.0.2.39", "198.51.100.7", 443, 1530, 9000, resumed))
    return _pcap(frames)


@pytest.fixture(scope="module")
def material():
    first, second = _shared_prime_keys()
    cert_a = _certificate(first, "alpha", 4242)
    cert_b = _certificate(second, "beta", 4243)
    ca = _certificate(ec.generate_private_key(ec.SECP256R1()), "synthetic ca", 1)
    der = [c.public_bytes(serialization.Encoding.DER) for c in (cert_a, cert_b, ca)]
    return {"keys": (first, second), "der": der, "pem": [c.public_bytes(serialization.Encoding.PEM)
                                                         for c in (cert_a, cert_b, ca)]}


# -- x509 ----------------------------------------------------------------------------------
def test_tools_are_registered_with_bounded_options():
    assert {"x509", "tls_certificates"} <= ARTIFACT_TOOLS
    assert ALLOWED_OPTIONS["x509"] == {"limit"}
    assert ALLOWED_OPTIONS["tls_certificates"] == {"packets", "connections", "limit"}


def test_x509_reads_der_and_pem_rsa_and_ec(tmp_path, material):
    (tmp_path / "a.der").write_bytes(material["der"][0])
    (tmp_path / "chain.pem").write_bytes(b"junk\n" + b"".join(material["pem"]))
    der = inspect_file(tmp_path, "a.der", "x509", {})
    key = der["certificates"][0]["public_key"]
    assert der["count"] == 1 and der["certificates"][0]["format"] == "DER"
    assert der["certificates"][0]["subject"] == "CN=alpha" and der["certificates"][0]["serial"] == "4242"
    numbers = material["keys"][0].public_key().public_numbers()
    assert key == {"type": "RSA", "bits": 1024, "n": str(numbers.n), "n_hex": format(numbers.n, "x"), "e": 65537}
    pem = inspect_file(tmp_path, "chain.pem", "x509", {})
    assert [c["format"] for c in pem["certificates"]] == ["PEM"] * 3
    assert pem["certificates"][2]["public_key"]["type"] == "EC"
    assert pem["certificates"][2]["public_key"]["curve"] == "secp256r1"
    assert inspect_file(tmp_path, "chain.pem", "x509", {"limit": 1})["errors"][0]["reason"] == "certificate_limit"


def test_x509_failures_are_structured(tmp_path):
    (tmp_path / "text.txt").write_text("not a certificate")
    (tmp_path / "broken.der").write_bytes(b"\x30\x82\x01\x00" + b"\x00" * 20)
    (tmp_path / "broken.pem").write_text("-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n")
    assert inspect_file(tmp_path, "text.txt", "x509", {})["errors"][0]["reason"] == "not_der_or_pem"
    assert inspect_file(tmp_path, "broken.der", "x509", {})["errors"][0]["reason"] == "der_parse_error"
    assert inspect_file(tmp_path, "broken.pem", "x509", {})["errors"][0]["reason"] == "der_parse_error"
    with pytest.raises(ValueError):
        inspect_file(tmp_path, "text.txt", "x509", {"limit": 0})


# -- tls_certificates ------------------------------------------------------------------------
def test_tls_certificates_from_a_capture(tmp_path, material):
    (tmp_path / "q.pcap").write_bytes(_capture([material["der"][0], material["der"][2]], [material["der"][1]]))
    result = inspect_file(tmp_path, "q.pcap", "tls_certificates", {})
    by_port = {entry["connection"].rsplit(":", 1)[1]: entry for entry in result["connections"]}
    assert by_port["1529"]["version"] == "TLS 1.0" and by_port["1529"]["cipher_suite"] == "0004"
    assert [c["subject"] for c in by_port["1529"]["certificates"]] == ["CN=alpha", "CN=synthetic ca"]
    assert by_port["1531"]["certificates"][0]["public_key"]["n"] == \
        str(material["keys"][1].public_key().public_numbers().n)
    assert by_port["1530"]["resumed_from"] == by_port["1529"]["connection"]
    assert result["certificate_count"] == 3 and result["errors"] == []


def test_tls_certificate_failures_are_structured(tmp_path, material):
    plain = _pcap([_frame("192.0.2.1", "192.0.2.2", 80, 1234, 1, b"HTTP/1.0 200 OK\r\n\r\nhello")])
    (tmp_path / "http.pcap").write_bytes(plain)
    assert inspect_file(tmp_path, "http.pcap", "tls_certificates", {})["errors"][-1]["reason"] == "no_tls_handshake"
    tls13 = _pcap([_frame("192.0.2.1", "192.0.2.2", 443, 1234, 1, _server_flight([], b"", tls13=True))])
    (tmp_path / "tls13.pcap").write_bytes(tls13)
    reasons = {error["reason"] for error in inspect_file(tmp_path, "tls13.pcap", "tls_certificates", {})["errors"]}
    assert {"tls13_certificates_encrypted", "no_certificate_message"} <= reasons
    (tmp_path / "note.txt").write_text("plain")
    with pytest.raises(ValueError, match="PCAP"):
        inspect_file(tmp_path, "note.txt", "tls_certificates", {})
    with pytest.raises(ValueError):
        inspect_file(tmp_path, "http.pcap", "tls_certificates", {"packets": 0})


# -- specialist path: METIS tools only ---------------------------------------------------------
def test_specialist_gets_moduli_and_shared_factor_through_intents_only(tmp_path, material):
    capture = tmp_path / "q.pcap"
    capture.write_bytes(_capture([material["der"][0]], [material["der"][1]]))
    database = tmp_path / ".metis-state" / "metis.sqlite"
    run_id = CodexSession(database).intake(title="Synthetic TLS", description="Decrypt it.", paths=[capture],
                                           categories=["crypto", "forensics"], max_actions=40)["run_id"]
    wave = AgentLedger(database).create_wave(run_id, mode="delegated")
    scheduler = AgentScheduler(database, BridgeHost())
    scheduler.enqueue(run_id, wave["wave_id"])
    job = scheduler.dispatch(run_id)["started"][0]
    name = CodexSession(database).context(run_id)["challenge"]["artifacts"][0]
    seen: dict = {}

    def decide(prompts):
        steps = json.loads(prompts[-1].split("STEPS SO FAR (intent -> controller result):\n")[1])
        if not steps:
            return {"action": "intent", "report": None, "reason": None, "intent": {
                "kind": "artifact", "tool": "tls_certificates", "artifact": name, "data": None,
                "options_json": None, "new_evidence": []}}
        if len(steps) == 1:
            observation = steps[0]["result"]["observation"]
            moduli = [c["public_key"]["n"] for entry in observation["result"]["connections"]
                      for c in entry.get("certificates", [])]
            seen["moduli"] = moduli
            return {"action": "intent", "report": None, "reason": None, "intent": {
                "kind": "data", "tool": "gcd", "artifact": None, "options_json": None, "new_evidence": [],
                "data": json.dumps({"a": moduli[0], "b": moduli[1]})}}
        seen["gcd"] = steps[1]["result"]["observation"]
        return {"action": "report", "intent": None, "reason": None, "report": {
            "hypothesis": "The two server certificates share one RSA prime factor.",
            "evidence": "tls_certificates returned both moduli and gcd of them is a nontrivial factor.",
            "falsifier": "A gcd equal to one would reject the shared-prime hypothesis.",
            "next_action": "Daybreak derives both private keys from the recorded gcd and decrypts the key exchange.",
            "event_sequences": [steps[0]["result"]["event_sequence"], steps[1]["result"]["event_sequence"]],
            "status": "supported", "artifact_refs": [name]}}

    class Runner:
        def __init__(self):
            self.prompts: list = []

        def run(self, prompt, *, model, timeout, should_stop=None, images=None):
            self.prompts.append(prompt)
            return CodexTurn(returncode=0, message=json.dumps(decide(self.prompts)), item_types=["agent_message"])

    result = run_assignment(scheduler, run_id, job["assignment_id"], job["attempt_id"], Runner())
    assert result["job_state"] == "completed"
    p = material["keys"][0].private_numbers().p
    assert len(seen["moduli"]) == 2 and str(p) in json.dumps(seen["gcd"])


@pytest.mark.skipif(not os.environ.get("METIS_TEST_KSNCTF33_PCAP"),
                    reason="set METIS_TEST_KSNCTF33_PCAP to the ksnctf #33 distribution capture")
def test_ksnctf_33_capture_yields_two_rsa_leaf_certificates():
    path = Path(os.environ["METIS_TEST_KSNCTF33_PCAP"])
    result = inspect_file(path.parent, path.name, "tls_certificates", {})
    leaves = [entry["certificates"][0] for entry in result["connections"] if entry.get("certificates")]
    assert len(leaves) == 2 and {leaf["public_key"]["bits"] for leaf in leaves} == {2048}
    assert all(leaf["public_key"]["e"] == 65537 for leaf in leaves)
    first, second = (int(leaf["public_key"]["n"]) for leaf in leaves)
    import math
    assert 1 < math.gcd(first, second) < first
    assert sum(1 for entry in result["connections"] if entry.get("resumed_from")) == 2

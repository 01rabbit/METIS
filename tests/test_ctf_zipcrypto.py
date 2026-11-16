"""ZipCrypto analysis (Issue #28).

Vectors:
* bkcrack's own attack test (ciphertext of "Hello World!" -> keys ea9b4e4d/ba789085/5ff8707d);
* outputs of the real glibc rand() for small and large seeds (taken from Debian glibc via ctypes);
* tests/fixtures/infozip-glibc-vector.zip: seven members written by Info-ZIP Zip 3.0 on Debian
  glibc 2.41 with password ``testpass`` at unix time 1794836147 (synthetic random content).
The full Biham-Kocher search takes minutes; it runs when METIS_TEST_SLOW=1.
"""
import json
import os
import struct
import zipfile
import zlib
from pathlib import Path

import numpy as np
import pytest

from metis.core import ctf_zipcrypto as zc
from metis.core.ctf_artifacts import ALLOWED_OPTIONS, ARTIFACT_TOOLS, inspect_file

FIXTURE = Path(__file__).parent / "fixtures" / "infozip-glibc-vector.zip"
GLIBC = {1: [138, 71, 48, 144, 184, 185, 40, 177, 62, 249, 177, 175],
         3518750973: [161, 71, 183, 103, 250, 182, 82, 80, 30, 28, 130, 90],
         4294967295: [182, 109, 84, 125, 247, 99, 17, 91, 44, 98, 205, 125],
         2147483648: [26, 181, 78, 101, 201, 156, 80, 64, 167, 12, 126, 87]}


def _zipcrypto_archive(entries: dict[str, bytes], password: bytes, *, compress: bool = False) -> bytes:
    """Minimal writer for traditional-encryption ZIPs (Python's zipfile can read but not write them)."""
    out, central = bytearray(), bytearray()
    for name, body in entries.items():
        crc = zlib.crc32(body) & 0xFFFFFFFF
        payload = zlib.compress(body)[2:-4] if compress else body
        header = os.urandom(10) + struct.pack("<H", crc >> 16)
        encrypted = zc.Keys.from_password(password).encrypt(header + payload)
        local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 1, 8 if compress else 0, 0, 0, crc, len(encrypted),
                            len(body), len(name), 0) + name.encode()
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 1, 8 if compress else 0, 0, 0, crc,
                               len(encrypted), len(body), len(name), 0, 0, 0, 0, 0, len(out)) + name.encode()
        out += local + encrypted
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(entries), len(entries), len(central), len(out), 0)
    return bytes(out + central + end)


def test_bkcrack_attack_vector():
    plaintext = b"Hello World!"
    ciphertext = bytes([0x3E, 0xB4, 0xC5, 0x92, 0x58, 0x40, 0x9A, 0x6C, 0xED, 0x99, 0x65, 0x81,
                        0x66, 0x1B, 0x1D, 0xDA, 0x5D, 0x8A, 0x8C, 0x30, 0x07, 0x76, 0x50, 0xBB])
    attack = zc._Attack(ciphertext, plaintext, 12, {}, 7)
    for candidate in (0x00000000, 0x10000000, 0x20000000, 0x30000000, 0x40000000, 0x50000000, 0x60000000,
                      0x74930E66 & 0xFFFFFFFC):
        attack.carryout(candidate)
        if attack.solutions:
            break
    assert attack.solutions[0].hex() == {"x": "ea9b4e4d", "y": "ba789085", "z": "5ff8707d"}


def test_cipher_interoperates_with_zipfile(tmp_path):
    archive = _zipcrypto_archive({"a.txt": b"stored text " * 10, "b.txt": b"deflated text " * 30}, b"pw123")
    (tmp_path / "x.zip").write_bytes(archive)
    with zipfile.ZipFile(tmp_path / "x.zip") as handle:
        assert handle.read("a.txt", pwd=b"pw123") == b"stored text " * 10
    keys = zc.Keys.from_password(b"pw123")
    assert zc.decrypt_member(archive, "b.txt", keys)["plaintext"] == b"deflated text " * 30
    with pytest.raises(ValueError, match="wrong keys"):
        zc.decrypt_member(archive, "a.txt", zc.Keys.from_password(b"wrong"))


def test_glibc_rand_matches_the_real_glibc():
    produced = zc.glibc_rand_bytes(np.array(list(GLIBC), dtype=np.uint64), 12)
    assert [list(map(int, row)) for row in produced] == list(GLIBC.values())


def test_infozip_seed_recovers_every_random_header_byte():
    data = FIXTURE.read_bytes()
    result = zc.infozip_seed(data, seconds=120)
    assert result["found"] and result["salt"] == "pid" and result["matched_leaked_bytes"] == 7
    keys = zc.Keys.from_password(b"testpass")
    for entry, predicted in zip([e for e in zc.members(data) if e["encrypted"]], result["random_header_bytes"],
                                strict=True):
        twice = zc.member_bytes(data, entry)[:10]
        assert keys.decrypt(keys.decrypt(twice)).hex() == predicted  # undo both Info-ZIP encryptions
    assert "2^39" in result["next"]


def test_infozip_seed_reports_misses_and_bounds():
    data = FIXTURE.read_bytes()
    miss = zc.infozip_seed(data, time_from=1_000_000_000, time_to=1_000_000_010, salts=("pi",))
    assert not miss["found"] and miss["reason"] == "no_seed_in_range"
    with pytest.raises(ValueError):
        zc.infozip_seed(data, time_from=0, time_to=40 * 86400)
    two = _zipcrypto_archive({"a": b"x" * 20, "b": b"y" * 20}, b"pw")
    assert zc.infozip_seed(two)["reason"] == "too_few_members"


def test_attack_pipeline_with_a_small_candidate_set(monkeypatch):
    """The full pipeline (reduction result -> parallel workers -> keys) on a reduced candidate set that
    contains the true key2 among decoys; the exhaustive search is the slow test below."""
    keys = zc.Keys.from_password(b"secret pass")
    plain = os.urandom(12) + b"The quick brown fox jumps over the lazy dog. " * 2
    cipher = keys.encrypt(plain)
    state, zs = keys.copy(), []
    for byte in plain:
        zs.append(state.z)
        state.update(byte)
    known = plain[12:12 + 40]
    keystream = [p ^ cipher[12 + i] for i, p in enumerate(known)]
    _candidates, index = zc.z_reduction(keystream, float("inf"))
    true = zs[12 + index] & 0xFFFFFFFC
    decoys = [(true ^ (step << 20)) & 0xFFFFFFFC for step in range(1, 8)]
    monkeypatch.setattr(zc, "z_reduction", lambda _ks, _deadline: (np.array([*decoys, true], dtype=np.uint32),
                                                                   index))
    result = zc.known_plaintext_attack(cipher, known, 12, extra={11: plain[11]}, workers=2, seconds=120)
    assert result["found"] and result["keys"] == keys.hex()


def test_attack_refuses_too_little_plaintext():
    assert zc.known_plaintext_attack(b"\0" * 40, b"short", 12)["reason"] == "not_enough_plaintext"
    assert zc.known_plaintext_attack(b"\0" * 20, b"x" * 12, 12)["reason"] == "plaintext_outside_ciphertext"


@pytest.mark.skipif(not os.environ.get("METIS_TEST_SLOW"), reason="exhaustive search takes minutes; METIS_TEST_SLOW=1")
def test_full_known_plaintext_attack():
    keys = zc.Keys.from_password(os.urandom(8))
    plain = os.urandom(12) + b"The quick brown fox jumps over the lazy dog. " * 4
    cipher = keys.encrypt(plain)
    result = zc.known_plaintext_attack(cipher, plain[12:72], 12, extra={11: plain[11]}, seconds=300)
    assert result["found"] and result["keys"] == keys.hex()


# -- METIS tool surface ----------------------------------------------------------------------------------
def test_tools_are_registered_and_bounded(tmp_path):
    assert {"zipcrypto_info", "infozip_seed", "zipcrypto_attack", "zipcrypto_decrypt"} <= ARTIFACT_TOOLS
    assert ALLOWED_OPTIONS["zipcrypto_attack"] == {"member", "plaintext_hex", "offset", "seconds"}
    (tmp_path / "v.zip").write_bytes(FIXTURE.read_bytes())
    info = inspect_file(tmp_path, "v.zip", "zipcrypto_info", {})
    assert info["encrypted_members"] == 7 and info["members"][0]["data_descriptor"] is True
    seed = inspect_file(tmp_path, "v.zip", "infozip_seed", {"seconds": 60})
    assert seed["found"] and len(seed["random_header_bytes"]) == 7
    with pytest.raises(ValueError):
        inspect_file(tmp_path, "v.zip", "zipcrypto_attack", {"member": "f1.txt", "plaintext_hex": "00",
                                                              "seconds": 301})
    with pytest.raises(ValueError, match="member"):
        inspect_file(tmp_path, "v.zip", "zipcrypto_attack", {"member": "nope", "plaintext_hex": "00"})


def test_decrypt_tool_through_derive(tmp_path):
    from metis.core.codex_session import CodexSession

    archive = _zipcrypto_archive({"flag.txt": b"recovered plaintext for the specialist\n"}, b"k3ys")
    source = tmp_path / "a.zip"
    source.write_bytes(archive)
    database = tmp_path / "state" / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.intake(title="Synthetic", description="zip", paths=[source], categories=["crypto"])["run_id"]
    name = session.context(run_id)["challenge"]["artifacts"][0]
    keys = zc.Keys.from_password(b"k3ys")
    derived = session.derive(run_id, name, "zipcrypto_decrypt",
                             {"member": "flag.txt", "keys": f"{keys.x:08x},{keys.y:08x},{keys.z:08x}"})
    assert derived["ok"]
    text = inspect_file(session.artifact_root(run_id), derived["artifact"], "text", {})["text"]
    assert text == "recovered plaintext for the specialist\n"
    wrong = session.artifact(run_id, name, "zipcrypto_decrypt", {"member": "flag.txt", "keys": "1,2,3"})
    assert not wrong["ok"] and "wrong keys" in wrong["detail"]
    assert "recovered" not in json.dumps(derived)  # the plaintext lives only in the derived artifact


@pytest.mark.skipif(not os.environ.get("METIS_TEST_KSNCTF39_ZIP"),
                    reason="set METIS_TEST_KSNCTF39_ZIP to the ksnctf #39 distribution archive")
def test_ksnctf_39_seed_is_recovered():
    data = Path(os.environ["METIS_TEST_KSNCTF39_ZIP"]).read_bytes()
    result = zc.infozip_seed(data, seconds=120)
    assert result["found"] and result["matched_leaked_bytes"] == 7 and result["salt"] == "pid"


def test_specialist_intents_recover_keys_decrypt_and_xor(tmp_path, monkeypatch):
    """Exercise the specialist controller chain with a reduced, deterministic attack candidate set.

    This verifies the real attack worker and intent routing, not exhaustive key-space search.
    """
    from metis.core.agent_host import BridgeHost
    from metis.core.agent_scheduler import AgentScheduler
    from metis.core.codex_session import CodexSession
    from metis.core.ctf_orchestration import AgentLedger

    known = b"A known plaintext for synthetic ZipCrypto testing. " * 2
    secret = b"synthetic xor result"
    encoded = bytes(byte ^ 0x42 for byte in secret).hex().encode()
    archive = _zipcrypto_archive({"known.txt": known, "encoded.txt": encoded}, b"intent-test")
    source = tmp_path / "input.zip"
    source.write_bytes(archive)
    database = tmp_path / "state" / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.intake(title="Synthetic", description="Recover and decode.", paths=[source],
                            categories=["crypto"], max_actions=40)["run_id"]
    wave = AgentLedger(database).create_wave(run_id, mode="delegated")
    scheduler = AgentScheduler(database, BridgeHost())
    scheduler.enqueue(run_id, wave["wave_id"])
    job = scheduler.dispatch(run_id)["started"][0]
    name = session.context(run_id)["challenge"]["artifacts"][0]

    entry = next(e for e in zc.members(archive) if e["name"] == "known.txt")
    ciphertext = zc.member_bytes(archive, entry)
    keys = zc.Keys.from_password(b"intent-test")
    plain = keys.copy().decrypt(ciphertext)
    stream = [a ^ b for a, b in zip(known[:40], ciphertext[12:52], strict=True)]
    _, index = zc.z_reduction(stream, float("inf"))
    state = keys.copy()
    for byte in plain[:12 + index]:
        state.update(byte)
    true_z = state.z & 0xFFFFFFFC
    monkeypatch.setattr(zc, "z_reduction", lambda _stream, _deadline: (
        np.array([true_z ^ 0x100000, true_z], dtype=np.uint32), index))

    def intent(kind, tool, *, artifact=None, options=None, data=None):
        return scheduler.intent(run_id, job["assignment_id"], job["attempt_id"],
                                {"kind": kind, "tool": tool, "artifact": artifact,
                                 "options": options or {}, "data": data})["observation"]

    attack = intent("artifact", "zipcrypto_attack", artifact=name,
                    options={"member": "known.txt", "plaintext_hex": known[:40].hex(), "seconds": 120})
    assert attack["ok"] and attack["result"]["found"]
    recovered = attack["result"]["keys"]
    assert recovered == keys.hex()
    recovered_keys = zc.parse_keys(",".join(recovered[k] for k in ("x", "y", "z")))
    for member in ("known.txt", "encoded.txt"):
        decrypted_member = zc.decrypt_member(archive, member, recovered_keys)
        assert decrypted_member["crc_ok"]
    derived = intent("derive", "zipcrypto_decrypt", artifact=name,
                     options={"member": "encoded.txt", "keys": ",".join(recovered[k] for k in ("x", "y", "z"))})
    assert derived["ok"]
    content = intent("artifact", "text", artifact=derived["artifact"])
    assert content["ok"]
    decoded = intent("data", "xor", data=json.dumps({"data": content["result"]["text"], "key": "42"}))
    assert decoded["ok"] and json.loads(decoded["output"])["utf8"] == secret.decode()

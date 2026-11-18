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
import random
import sqlite3
import struct
import subprocess
import time
import zipfile
import zlib
from pathlib import Path

import numpy as np
import pytest

from metis.core import ctf_zipcrypto as zc
from metis.core.ctf_artifacts import ALLOWED_OPTIONS, ARTIFACT_TOOLS, inspect_bytes, inspect_file

FIXTURE = Path(__file__).parent / "fixtures" / "infozip-glibc-vector.zip"
GLIBC = {1: [138, 71, 48, 144, 184, 185, 40, 177, 62, 249, 177, 175],
         3518750973: [161, 71, 183, 103, 250, 182, 82, 80, 30, 28, 130, 90],
         4294967295: [182, 109, 84, 125, 247, 99, 17, 91, 44, 98, 205, 125],
         2147483648: [26, 181, 78, 101, 201, 156, 80, 64, 167, 12, 126, 87]}


def _zipcrypto_archive(entries: dict[str, bytes], password: bytes, *, compress: bool = False,
                       seed: int | None = None) -> bytes:
    """Minimal writer for traditional-encryption ZIPs (Python's zipfile can read but not write them)."""
    random_bytes = random.Random(seed).randbytes if seed is not None else os.urandom
    out, central = bytearray(), bytearray()
    for name, body in entries.items():
        crc = zlib.crc32(body) & 0xFFFFFFFF
        payload = zlib.compress(body)[2:-4] if compress else body
        header = random_bytes(10) + struct.pack("<H", crc >> 16)
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


def test_stay_member_validation_checks_both_headers_and_all_member_crcs():
    archive = FIXTURE.read_bytes()
    seed_result = zc.infozip_seed(archive, seconds=120)
    assert seed_result["found"] is True
    entries = [entry for entry in zc.members(archive) if entry["encrypted"]]
    random_headers = [bytes.fromhex(value) for value in seed_result["random_header_bytes"]]
    initial_keys = zc.Keys.from_password(b"testpass")

    assert len(entries) == len(random_headers) == 7
    with zipfile.ZipFile(FIXTURE) as handle:
        for entry, random_header in zip(entries, random_headers, strict=True):
            recovered = zc.decrypt_member(
                archive, entry["name"], initial_keys,
                expected_random_header=random_header,
            )
            assert recovered["crc_ok"] is True
            assert recovered["plaintext"] == handle.read(entry["name"], pwd=b"testpass")
            routed = inspect_bytes(
                archive, "zipcrypto_decrypt",
                {"member": entry["name"],
                 "keys": f"{initial_keys.x:08x},{initial_keys.y:08x},{initial_keys.z:08x}",
                 "expected_random_header_hex": random_header.hex()},
            )
            assert routed["crc_ok"] is True and routed["stay_header_ok"] is True
            assert routed["size"] == len(recovered["plaintext"])

    for entry, random_header in zip(entries, random_headers, strict=True):
        for header_offset in (2, 10, 11):
            damaged = bytearray(archive)
            damaged[entry["data_offset"] + header_offset] ^= 1
            with pytest.raises(ValueError):
                zc.decrypt_member(
                    bytes(damaged), entry["name"], initial_keys,
                    expected_random_header=random_header,
                )


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
    assert "Stay section 4 specifically uses" in result["next"]
    assert "stream-byte XOR constraints" in result["next"]


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


def test_attack_time_budget_returns_reason_code():
    result = zc.known_plaintext_attack(b"\0" * 128, b"x" * 40, 12, seconds=1e-9)
    assert result["found"] is False
    assert result["reason"] == "work_exceeds_budget"
    assert result["stage"] == "z-reduction"


def _delayed_attack_shard(_arguments):
    time.sleep(5)
    return 1, None


def test_attack_parent_kills_worker_when_candidate_exceeds_time_budget(monkeypatch):
    monkeypatch.setattr(zc, "z_reduction", lambda _stream, _deadline: (np.array([1, 2], dtype=np.uint32), 7))
    monkeypatch.setattr(zc, "_attack_shard", _delayed_attack_shard)
    started = time.monotonic()
    result = zc.known_plaintext_attack(b"\0" * 128, b"x" * 40, 12, seconds=0.5, workers=2)
    elapsed = time.monotonic() - started
    assert result["found"] is False
    assert result["reason"] == "work_exceeds_budget" and result["stage"] == "key-search"
    assert elapsed < 4.0


@pytest.mark.skipif(not os.environ.get("METIS_TEST_SLOW"), reason="exhaustive search takes minutes; METIS_TEST_SLOW=1")
def test_full_known_plaintext_attack():
    password = b"full-search-test"
    known = b"The quick brown fox jumps over the lazy dog. " * 2
    secret = b"independent member with a known ZipCrypto key"
    encoded = bytes(byte ^ 0x42 for byte in secret).hex().encode("ascii")
    members = {"known.txt": known, "encoded.txt": encoded}
    archive = _zipcrypto_archive(members, password, seed=0x28)
    entry = next(item for item in zc.members(archive) if item["name"] == "known.txt")
    ciphertext = zc.member_bytes(archive, entry)
    result = zc.known_plaintext_attack(ciphertext, known[:60], 12, extra=zc.check_bytes(entry), seconds=300,
                                       workers=8)
    assert result["found"], result
    assert result["keys"] == zc.Keys.from_password(password).hex()
    recovered = zc.parse_keys(",".join(result["keys"][name] for name in ("x", "y", "z")))
    for member, expected in members.items():
        decrypted = zc.decrypt_member(archive, member, recovered)
        assert decrypted["crc_ok"] and decrypted["plaintext"] == expected


# -- METIS tool surface ----------------------------------------------------------------------------------
def test_tools_are_registered_and_bounded(tmp_path):
    assert {"zipcrypto_info", "infozip_seed", "zipcrypto_attack", "zipcrypto_stay_scan",
            "zipcrypto_decrypt"} <= ARTIFACT_TOOLS
    assert ALLOWED_OPTIONS["zipcrypto_attack"] == {"member", "plaintext_hex", "offset", "seconds"}
    (tmp_path / "v.zip").write_bytes(FIXTURE.read_bytes())
    info = inspect_file(tmp_path, "v.zip", "zipcrypto_info", {})
    assert info["encrypted_members"] == 7 and info["members"][0]["data_descriptor"] is True
    assert any("Stay section 4" in note and "stream-byte XOR constraints" in note
               for note in info["notes"])
    seed = inspect_file(tmp_path, "v.zip", "infozip_seed", {"seconds": 60})
    assert seed["found"] and len(seed["random_header_bytes"]) == 7
    with pytest.raises(ValueError):
        inspect_file(tmp_path, "v.zip", "zipcrypto_attack", {"member": "f1.txt", "plaintext_hex": "00",
                                                              "seconds": 301})
    with pytest.raises(ValueError, match="2048 bytes"):
        inspect_file(tmp_path, "v.zip", "zipcrypto_attack", {"member": "f1.txt",
                      "plaintext_hex": "41" * 4097, "seconds": 1},
                     zipcrypto_runner=lambda *_args: pytest.fail("invalid input reached worker"))
    with pytest.raises(ValueError):
        inspect_file(tmp_path, "v.zip", "zipcrypto_attack", {"member": "f1.txt",
                      "plaintext_hex": "not hex", "seconds": 1},
                     zipcrypto_runner=lambda *_args: pytest.fail("invalid input reached worker"))
    with pytest.raises(ValueError, match="isolated worker"):
        inspect_file(tmp_path, "v.zip", "zipcrypto_attack", {"member": "nope", "plaintext_hex": "00"})


def test_stay_scan_options_are_bounded_and_pass_only_to_isolated_runner():
    from metis.core.ctf_artifacts import inspect_bytes

    headers = bytes(range(70)).hex()
    captured = {}

    def runner(data, settings):
        captured["data"] = data
        captured["settings"] = settings
        return {"next_index": 4, "complete": False, "scanned": 4, "hits_count": 0}

    result = inspect_bytes(b"archive snapshot", "zipcrypto_stay_scan", {
        "random_header_bytes_hex": headers, "start": 0, "stop": 20,
        "max_candidates": 4, "seconds": 10, "max_hits": 5,
    }, zipcrypto_runner=runner)
    assert result["next_index"] == 4 and result["scanned"] == 4
    assert captured["data"] == b"archive snapshot"
    assert captured["settings"] == {
        "random_header_bytes_hex": headers, "start": 0, "stop": 20,
        "max_candidates": 4, "seconds": 10, "max_hits": 5,
    }
    with pytest.raises(ValueError, match="5 to 64"):
        inspect_bytes(b"archive", "zipcrypto_stay_scan", {
            "random_header_bytes_hex": "aa" * 40, "start": 0, "stop": 1,
        }, zipcrypto_runner=lambda *_: pytest.fail("invalid observations reached worker"))


def test_stay_scan_runner_persists_hits_privately(tmp_path, monkeypatch):
    from metis.core.ctf_sandbox import Sandbox
    from metis.core.ctf_zipcrypto_worker import run_zipcrypto_stay_scan

    database = tmp_path / "state" / "metis.sqlite"
    database.parent.mkdir()
    run_id = "a" * 32

    def fake_execute(self, *args, **kwargs):
        payload = {"result": {"next_index": 12, "complete": False, "scanned": 12,
                              "seconds": 0.3, "hits": [[9, [1, 2, 3, 4, 5, 6, 7]]]}}
        return {"ok": True, "stdout": {"text": "METIS_PHASE:stay-first-stage-scan\n"
                                                + json.dumps(payload)}}

    monkeypatch.setattr(Sandbox, "__init__", lambda self, _database: None)
    monkeypatch.setattr(Sandbox, "execute", fake_execute)
    options = {"random_header_bytes_hex": "00" * 70, "start": 0, "stop": 100,
                   "max_candidates": 100, "seconds": 10, "max_hits": 5}
    result = run_zipcrypto_stay_scan(database, run_id, "fixture.zip", options)
    assert result == {"hits_count": 1, "next_index": 12, "complete": False, "scanned": 12,
                      "seconds": 0.3, "candidate_shard": result.get("candidate_shard")}, result
    assert result["candidate_shard"]
    shard = database.parent / result["candidate_shard"]
    assert shard.stat().st_mode & 0o777 == 0o600
    assert json.loads(shard.read_text())["hits"] == [[9, [1, 2, 3, 4, 5, 6, 7]]]


def test_stay_native_scan_recovers_planted_candidate_in_sandbox(tmp_path):
    image = os.environ.get("METIS_TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("set METIS_TEST_SANDBOX_IMAGE to a numpy-enabled sandbox image")
    from metis.core.codex_session import CodexSession
    from metis.core.ctf_sandbox import configure
    from metis.core.ctf_zipcrypto_worker import (
        run_zipcrypto_stay_recover,
        run_zipcrypto_stay_scan,
        run_zipcrypto_stay_stage2,
    )

    data = FIXTURE.read_bytes()
    seed = zc.infozip_seed(data, seconds=120)
    assert seed["found"] is True
    headers = [bytes.fromhex(value) for value in seed["random_header_bytes"]]
    encrypted = [entry for entry in zc.members(data) if entry["encrypted"]]
    state = zc.Keys.from_password(b"testpass")
    random_firsts = tuple(header[0] for header in headers)
    observed = tuple(zc.member_bytes(data, entry)[1] ^ header[1]
                     for entry, header in zip(encrypted, headers, strict=True))
    stream = ((state.z & 0xFFFF) | 2)
    first_stream = (stream * (stream ^ 1) >> 8) & 0xFF
    key0_crc_low = zc.crc32(state.x, 0) & 0xFF
    product = state.y * zc.MULT & zc.M32
    key2_crc = zc.crc32(state.z, 0) & 0xFFFC
    first_low = zc.crc32(state.x, random_firsts[0]) & 0xFF
    second_low = zc.crc32(state.x, random_firsts[0] ^ first_stream) & 0xFF
    carry_first = int((product & 0xFFFFFF) + ((first_low * zc.MULT + 1) & 0xFFFFFF) >= 1 << 24)
    carry_second = int((product & 0xFFFFFF) + ((second_low * zc.MULT + 1) & 0xFFFFFF) >= 1 << 24)
    index = (first_stream | key0_crc_low << 8 | (product >> 24) << 16
             | carry_first << 24 | (key2_crc >> 10) << 25
             | (key2_crc >> 2 & 0xFF) << 31 | carry_second << 39)
    expected_masks = zc._stay_first_stage_candidate(index, random_firsts, observed)
    assert expected_masks is not None

    source = tmp_path / "infozip-vector.zip"
    source.write_bytes(data)
    database = tmp_path / "state" / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.intake(title="Stay native filter", description="synthetic seven-member vector",
                            paths=[source])["run_id"]
    artifact = session.context(run_id)["challenge"]["artifacts"][0]
    configure(database, engine="docker", image=image, platform=None)
    result = run_zipcrypto_stay_scan(database, run_id, artifact, {
        "random_header_bytes_hex": b"".join(headers).hex(), "start": index,
        "stop": index + 1, "max_candidates": 1, "seconds": 30, "max_hits": 4,
    })
    assert result["hits_count"] == 1, result
    shard = database.parent / result["candidate_shard"]
    assert json.loads(shard.read_text())["hits"] == [[index, list(expected_masks)]]

    key0_crc = zc.crc32(state.x, 0)
    key2_crc_full = zc.crc32(state.z, 0)
    q8 = ((product * zc.MULT) & zc.M32) >> 24
    key2_stage2 = ((key2_crc_full >> 16) << 2 & 0x3FC) | (key2_crc_full & 0x3)
    guess = ((key0_crc >> 8) & 0xFF) | (key2_stage2 << 8) | (q8 << 18)
    stage2 = run_zipcrypto_stay_stage2(database, run_id, artifact, {
        "random_header_bytes_hex": b"".join(headers).hex(),
        "stage1_shard": result["candidate_shard"], "hit_index": 0,
        "start": guess, "stop": guess + 1, "max_candidates": 1,
        "seconds": 30, "max_hits": 1,
    })
    assert stage2["hits_count"] == 1, stage2
    assert stage2["next_index"] == guess + 1 and stage2["complete"]
    stage2_shard = database.parent / stage2["candidate_shard"]
    assert stage2_shard.stat().st_mode & 0o777 == 0o600
    stage2_hits = json.loads(stage2_shard.read_text())["hits"]
    assert stage2_hits[0][0] == guess
    assert stage2_hits[0][1] >> 24 == product >> 24
    products: list[int] = []
    assert zc._stay_stage2_candidate_matches(
        index, expected_masks, random_firsts, tuple(header[1] for header in headers),
        tuple(zc.member_bytes(data, entry)[2] ^ header[2]
              for entry, header in zip(encrypted, headers, strict=True)),
        guess & 0xFF, (guess >> 8) & 0x3FF, (guess >> 18) & 0xFF,
        product_witness=products, max_product_witnesses=4096)
    recovery_options = {
        "random_header_bytes_hex": b"".join(headers).hex(),
        "stage2_shard": stage2["candidate_shard"], "hit_index": 0,
        "start_product": products.index(product), "start_extra": 0,
        "max_products": 1, "max_candidates": 1 << 24,
        "seconds": 60, "max_hits": 1,
    }
    partial = run_zipcrypto_stay_recover(database, run_id, artifact, {
        **recovery_options, "max_candidates": 1024})
    assert partial["reason"] == "candidate_limit", partial
    assert partial["next_product"] == products.index(product)
    assert partial["next_extra"] == 1024 and partial["keys_count"] == 0
    recovery = run_zipcrypto_stay_recover(database, run_id, artifact, {
        **recovery_options, "start_extra": partial["next_extra"],
        "max_candidates": (1 << 24) - partial["next_extra"]})
    assert recovery["keys_count"] == 1, recovery
    assert "keys" not in recovery
    key_file = database.parent / recovery["key_shard"]
    assert key_file.stat().st_mode & 0o777 == 0o600
    assert json.loads(key_file.read_text())["keys"] == [[state.x, state.y, state.z]]
    assert products.index(product) > 0
    previous = zc._stay_recover_keys_for_guess(
        index, expected_masks, tuple(headers),
        tuple(zc.member_bytes(data, entry)[:12] for entry in encrypted), guess,
        start_product=products.index(product) - 1, start_extra=0,
        max_products=1, max_candidates=1 << 24, max_hits=1, seconds=30)
    assert previous.reason == "candidate_limit", previous
    assert previous.next_product == products.index(product) and previous.next_extra == 0
    resumed = zc._stay_recover_keys_for_guess(
        index, expected_masks, tuple(headers),
        tuple(zc.member_bytes(data, entry)[:12] for entry in encrypted), guess,
        start_product=previous.next_product, start_extra=previous.next_extra,
        max_products=1, max_candidates=1 << 24, max_hits=1, seconds=30)
    assert (state.x, state.y, state.z) in resumed.keys
    repeated = zc._stay_stage2_scan_chunk(
        index, (expected_masks[0],) * 7,
        (headers[0][0],) * 7, (headers[0][1],) * 7,
        (zc.member_bytes(data, encrypted[0])[2] ^ headers[0][2],) * 7,
        start=guess - 32768, stop=guess + 32768,
        max_candidates=65536, max_hits=4096, seconds=30)
    assert repeated.reason == "complete" and len(repeated.hits) == 692
    vector_stage2 = run_zipcrypto_stay_stage2(database, run_id, artifact, {
        "random_header_bytes_hex": b"".join(headers).hex(),
        "stage1_shard": result["candidate_shard"], "hit_index": 0,
        "start": guess - 512, "stop": guess + 1, "max_candidates": 513,
        "seconds": 30, "max_hits": 4,
    })
    assert vector_stage2["hits_count"] >= 1, vector_stage2
    assert any(hit[0] == guess for hit in json.loads(
        (database.parent / vector_stage2["candidate_shard"]).read_text())["hits"])
    probe_mode = os.environ.get("METIS_TEST_STAY_STAGE2_PROBE")
    if probe_mode in {"1", "large"}:
        for count in ((1_000, 10_000, 1 << 23) if probe_mode == "large" else (1_000, 10_000)):
            probe = run_zipcrypto_stay_stage2(database, run_id, artifact, {
                "random_header_bytes_hex": b"".join(headers).hex(),
                "stage1_shard": result["candidate_shard"], "hit_index": 0,
                "start": 0, "stop": count, "max_candidates": count,
                "seconds": 300, "max_hits": 1,
            })
            print("Stage 2 probe:", {key: probe.get(key) for key in (
                "reason", "scanned", "next_index", "complete", "seconds", "hits_count")})
            assert probe.get("next_index") is not None, probe.get("reason")


def test_stay_recover_controller_bounds_options():
    from metis.core.ctf_artifacts import inspect_bytes

    received = []
    def runner(_data, settings):
        received.append(settings)
        return {"keys_count": 0}

    options = {"random_header_bytes_hex": "00" * 50,
               "stage2_shard": f"private-stay/{'a' * 32}/s2-{'b' * 32}.json"}
    assert inspect_bytes(b"archive", "zipcrypto_stay_recover", options,
                         zipcrypto_runner=runner) == {"keys_count": 0}
    assert received[0]["max_products"] == 1
    for update in ({"stage2_shard": "../bad"}, {"max_products": 4097},
                   {"start_extra": 1 << 24}, {"seconds": 301}):
        with pytest.raises(ValueError):
            inspect_bytes(b"archive", "zipcrypto_stay_recover", {**options, **update},
                          zipcrypto_runner=runner)


def test_stay_stage2_runner_keeps_witness_private(tmp_path, monkeypatch):
    from metis.core.ctf_sandbox import Sandbox
    from metis.core.ctf_zipcrypto_worker import run_zipcrypto_stay_stage2

    database = tmp_path / "state" / "metis.sqlite"
    root = database.parent / "private-stay" / ("a" * 32)
    root.mkdir(parents=True, mode=0o700)
    root.parent.chmod(0o700)
    shard_id = "b" * 32 + ".json"
    shard = root / shard_id
    shard.write_text(json.dumps({"hits": [[17, [1] * 7]]}))
    shard.chmod(0o600)

    def fake_execute(self, *args, **kwargs):
        payload = {"result": {"next_index": 4, "reason": "hit_limit", "scanned": 4,
                              "complete": False, "seconds": 0.1, "hits": [[3, 12345]]}}
        return {"ok": True, "stdout": {"text": json.dumps(payload)}}

    monkeypatch.setattr(Sandbox, "__init__", lambda self, _database: None)
    monkeypatch.setattr(Sandbox, "execute", fake_execute)
    result = run_zipcrypto_stay_stage2(database, "a" * 32, "fixture.zip", {
        "random_header_bytes_hex": "00" * 70,
        "stage1_shard": f"private-stay/{'a' * 32}/{shard_id}",
        "hit_index": 0, "start": 0, "stop": 10, "max_candidates": 10,
        "max_hits": 1, "seconds": 10,
    })
    assert result["hits_count"] == 1 and "hits" not in result
    output = database.parent / result["candidate_shard"]
    assert output.name.startswith("s2-")
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text())["hits"] == [[3, 12345]]
    rejected = run_zipcrypto_stay_stage2(database, "a" * 32, "fixture.zip", {
        "stage1_shard": result["candidate_shard"],
    })
    assert rejected == {"reason": "private_state_unavailable", "stage": "candidate-shard"}
    cross_run = run_zipcrypto_stay_stage2(database, "c" * 32, "fixture.zip", {
        "stage1_shard": f"private-stay/{'a' * 32}/{shard_id}",
    })
    assert cross_run == {"reason": "private_state_unavailable", "stage": "candidate-shard"}


def test_stay_stage2_controller_bounds_options():
    from metis.core.ctf_artifacts import inspect_bytes

    seen = []
    def runner(data, settings):
        seen.append(settings)
        return {"next_index": settings["start"], "hits_count": 0}

    options = {"random_header_bytes_hex": "00" * 70,
               "stage1_shard": f"private-stay/{'a' * 32}/{'b' * 32}.json", "hit_index": 0,
               "start": 5, "stop": 8, "max_candidates": 2, "seconds": 10, "max_hits": 1}
    inspect_bytes(b"archive", "zipcrypto_stay_stage2", options, zipcrypto_runner=runner)
    assert seen[0]["start"] == 5 and seen[0]["stop"] == 8
    assert seen[0]["stage1_shard"] == options["stage1_shard"]
    inspect_bytes(b"archive", "zipcrypto_stay_stage2",
                  {**options, "max_candidates": 1 << 23}, zipcrypto_runner=runner)
    with pytest.raises(ValueError):
        inspect_bytes(b"archive", "zipcrypto_stay_stage2",
                      {**options, "max_candidates": (1 << 23) + 1}, zipcrypto_runner=runner)
    with pytest.raises(ValueError):
        inspect_bytes(b"archive", "zipcrypto_stay_stage2", {**options, "stop": 4},
                      zipcrypto_runner=runner)
    with pytest.raises(ValueError):
        inspect_bytes(b"archive", "zipcrypto_stay_stage2", {**options, "stage1_shard": "../bad"},
                      zipcrypto_runner=runner)


def test_zipcrypto_worker_maps_container_memory_kill(tmp_path, monkeypatch):
    from metis.core.codex_session import CodexSession
    from metis.core.ctf_sandbox import Sandbox, configure
    from metis.core.ctf_zipcrypto_worker import run_zipcrypto_attack

    source = tmp_path / "attack.zip"
    source.write_bytes(_zipcrypto_archive({"known.txt": b"known plaintext for memory test"}, b"pass"))
    database = tmp_path / "state" / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.intake(title="Synthetic", description="ZipCrypto worker", paths=[source])["run_id"]
    name = session.context(run_id)["challenge"]["artifacts"][0]
    configure(database, engine="docker", image="sha256:" + "a" * 64, platform=None)
    observed = {}

    def memory_killed(self, seen_run, request, *, _reserved=False, _profile="standard", _operation_id=None):
        observed.update(run_id=seen_run, target=request.target, reserved=_reserved, profile=_profile)
        return {"ok": False, "exit_code": -9, "timed_out": False,
                "memory_limit_exceeded": True, "elapsed": 0.2}

    monkeypatch.setattr(Sandbox, "execute", memory_killed)
    result = run_zipcrypto_attack(database, run_id, name,
                                  {"member": "known.txt", "plaintext_hex": "4142434445464748494a4b4c",
                                   "offset": 0, "seconds": 5})
    assert result["reason"] == "memory_limit_exceeded" and result["stage"] == "sandbox-oom"
    assert observed == {"run_id": run_id, "target": name, "reserved": False, "profile": "zipcrypto"}


def test_zipcrypto_real_low_memory_container_reports_memory_limit(tmp_path):
    image = os.environ.get("METIS_TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("set METIS_TEST_SANDBOX_IMAGE to a built numpy-enabled sandbox image")
    from metis.core.codex_session import CodexSession
    from metis.core.ctf_sandbox import configure
    from metis.core.ctf_zipcrypto_worker import run_zipcrypto_attack

    archive = _zipcrypto_archive({"known.txt": b"known plaintext to exercise bounded key search"}, b"oom-test")
    source = tmp_path / "oom-test.zip"
    source.write_bytes(archive)
    database = tmp_path / "state" / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.intake(title="Synthetic", description="ZipCrypto low-memory integration", paths=[source])["run_id"]
    artifact = session.context(run_id)["challenge"]["artifacts"][0]
    configure(database, engine="docker", image=image, platform=None)
    result = run_zipcrypto_attack(database, run_id, artifact, {
        "member": "known.txt", "plaintext_hex": b"known plaintext to exercise".hex(),
        "offset": 0, "seconds": 10,
    }, _profile="zipcrypto_test_lowmem")
    assert result["reason"] == "memory_limit_exceeded", result
    assert result["stage"] == "sandbox-oom"
    assert result["phase"] in {"worker-imports", "worker-startup", "archive-parsing", "candidate-reduction",
                                "candidate-key-search"}


def test_zipcrypto_production_profile_oom_classification_and_cleanup(tmp_path):
    image = os.environ.get("METIS_TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("set METIS_TEST_SANDBOX_IMAGE to a built numpy-enabled sandbox image")
    from metis.core.codex_session import CodexSession
    from metis.core.ctf_sandbox import Sandbox, SandboxRequest, configure
    from metis.core.ctf_zipcrypto_worker import _sandbox_failure

    source = tmp_path / "oom-profile.zip"
    source.write_bytes(_zipcrypto_archive({"known.txt": b"synthetic profile test"}, b"profile-test"))
    database = tmp_path / "state" / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.intake(title="Synthetic", description="ZipCrypto production profile memory bound",
                            paths=[source])["run_id"]
    artifact = session.context(run_id)["challenge"]["artifacts"][0]
    configure(database, engine="docker", image=image, platform=None)
    pressure = """from pathlib import Path
memory_max = Path("/sys/fs/cgroup/memory.max").read_text().strip()
swap_max = Path("/sys/fs/cgroup/memory.swap.max").read_text().strip()
memory_events = Path("/sys/fs/cgroup/memory.events").read_text()
if (not memory_max.isdigit() or not swap_max.isdigit()
        or not 0 < int(memory_max) <= 2147483648 or int(swap_max) > 2147483648
        or "oom_kill " not in memory_events):
    raise SystemExit("finite ZipCrypto memory/swap cgroup was not confirmed")
chunks = []
while True:
    block = bytearray(64 * 1024 * 1024)
    for offset in range(0, len(block), 4096):
        block[offset] = 1
    chunks.append(block)
"""
    sandbox = Sandbox(database)
    command = sandbox.command("metis-test", profile="zipcrypto")
    assert "--memory=2g" in command and "--memory-swap=2g" in command
    result = sandbox.execute(
        run_id, SandboxRequest(target=artifact, mode="script", script=pressure, timeout=30),
        _profile="zipcrypto")
    assert result["isolation"]["resource_profile"] == "zipcrypto"
    assert result.get("memory_limit_exceeded") is True, result
    failure = _sandbox_failure(result)
    assert failure == {"found": False, "reason": "memory_limit_exceeded", "stage": "sandbox-oom",
                       "seconds": result["elapsed"]}
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT 1 FROM sandbox_workers WHERE run_id=?", (run_id,)).fetchone() is None


def test_zipcrypto_failure_preserves_furthest_worker_phase():
    from metis.core.ctf_zipcrypto_worker import _sandbox_failure

    failure = _sandbox_failure({"memory_limit_exceeded": True, "elapsed": 0.25,
                                "stdout": {"text": "METIS_PHASE:worker-startup\n"
                                                    "METIS_PHASE:candidate-key-search\n"
                                                    "METIS_PHASE:worker-imports\n"}})
    assert failure == {"found": False, "reason": "memory_limit_exceeded", "stage": "sandbox-oom",
                       "seconds": 0.25, "phase": "candidate-key-search"}
    timed_out = _sandbox_failure({"timed_out": True, "elapsed": 120.0,
                                  "stdout": {"text": "METIS_PHASE:candidate-key-search\n"
                                                     "METIS_PHASE:worker-imports\n"}})
    assert timed_out == {"found": False, "reason": "work_exceeds_budget", "stage": "sandbox-timeout",
                         "seconds": 120.0, "phase": "candidate-key-search"}
    unknown = _sandbox_failure({"memory_limit_exceeded": True,
                                "stdout": {"text": "METIS_PHASE:host-secret\n"}})
    assert unknown == {"found": False, "reason": "memory_limit_exceeded", "stage": "sandbox-oom",
                       "seconds": None}


def test_zipcrypto_worker_enforces_container_deadline(tmp_path, monkeypatch):
    image = os.environ.get("METIS_TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("set METIS_TEST_SANDBOX_IMAGE to a built numpy-enabled sandbox image")
    from types import SimpleNamespace

    from metis.core import ctf_sandbox
    from metis.core.codex_session import CodexSession
    from metis.core.ctf_sandbox import configure

    archive = _zipcrypto_archive({"known.txt": b"known plaintext for deadline test"}, b"pass")
    source = tmp_path / "attack.zip"
    source.write_bytes(archive)
    database = tmp_path / "state" / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.intake(title="Synthetic", description="ZipCrypto deadline", paths=[source])["run_id"]
    artifact = session.context(run_id)["challenge"]["artifacts"][0]
    configure(database, engine="docker", image=image, platform=None)
    container_name = "metis-sandbox-" + "zipcrypto-deadline"[:16]
    monkeypatch.setattr(ctf_sandbox, "uuid4", lambda: SimpleNamespace(hex="zipcrypto-deadline"))
    result = session.artifact(run_id, artifact, "zipcrypto_attack", {
        "member": "known.txt", "plaintext_hex": (b"known plaintext" * 2).hex(), "seconds": 1})
    assert result["ok"] is True
    assert result["result"]["found"] is False
    assert result["result"]["reason"] == "work_exceeds_budget"
    assert result["result"]["seconds"] is not None  # timeout came from the in-container supervisor
    inspected = subprocess.run(["docker", "inspect", container_name], capture_output=True, check=False)
    assert inspected.returncode != 0


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


def _specialist_intent_zipcrypto_chain(tmp_path, monkeypatch=None, *, seconds=120, sandbox_image=None):
    from metis.core.agent_host import BridgeHost
    from metis.core.agent_scheduler import AgentScheduler
    from metis.core.codex_session import CodexSession
    from metis.core.ctf_orchestration import AgentLedger

    password = b"full-search-test"
    known = b"The quick brown fox jumps over the lazy dog. " * 2
    secret = b"synthetic xor result"
    encoded = bytes(byte ^ 0x42 for byte in secret).hex().encode()
    archive = _zipcrypto_archive({"known.txt": known, "encoded.txt": encoded}, password, seed=0x28)
    source = tmp_path / "input.zip"
    source.write_bytes(archive)
    database = tmp_path / "state" / "metis.sqlite"
    session = CodexSession(database)
    if sandbox_image:
        from metis.core.ctf_sandbox import configure
        configure(database, engine="docker", image=sandbox_image, platform=None)
    run_id = session.intake(title="Synthetic", description="Recover and decode.", paths=[source],
                            categories=["crypto"], max_actions=40)["run_id"]
    wave = AgentLedger(database).create_wave(run_id, mode="delegated")
    scheduler = AgentScheduler(database, BridgeHost())
    scheduler.enqueue(run_id, wave["wave_id"])
    job = scheduler.dispatch(run_id)["started"][0]
    name = session.context(run_id)["challenge"]["artifacts"][0]

    keys = zc.Keys.from_password(password)
    if monkeypatch is not None:
        entry = next(e for e in zc.members(archive) if e["name"] == "known.txt")
        ciphertext = zc.member_bytes(archive, entry)
        plain = keys.copy().decrypt(ciphertext)
        stream = [a ^ b for a, b in zip(known[:40], ciphertext[12:52], strict=True)]
        _, index = zc.z_reduction(stream, float("inf"))
        state = keys.copy()
        for byte in plain[:12 + index]:
            state.update(byte)
        true_z = state.z & 0xFFFFFFFC
        monkeypatch.setattr(zc, "z_reduction", lambda _stream, _deadline: (
            np.array([true_z ^ 0x100000, true_z], dtype=np.uint32), index))
        from metis.core import ctf_zipcrypto_worker
        monkeypatch.setattr(ctf_zipcrypto_worker, "run_zipcrypto_attack",
                            lambda _db, _run, _artifact, settings, **_kwargs: zc.known_plaintext_attack(
                                ciphertext, known[:60], 12, extra=zc.check_bytes(entry),
                                seconds=settings["seconds"], workers=2))

    def intent(kind, tool, *, artifact=None, options=None, data=None):
        return scheduler.intent(run_id, job["assignment_id"], job["attempt_id"],
                                {"kind": kind, "tool": tool, "artifact": artifact,
                                 "options": options or {}, "data": data})["observation"]

    attack = intent("artifact", "zipcrypto_attack", artifact=name,
                    options={"member": "known.txt", "plaintext_hex": known[:60].hex(), "seconds": seconds})
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


def test_specialist_intents_recover_keys_decrypt_and_xor(tmp_path, monkeypatch):
    """Exercise the intent chain through a reduced, deterministic candidate set."""
    _specialist_intent_zipcrypto_chain(tmp_path, monkeypatch)


@pytest.mark.skipif(not os.environ.get("METIS_TEST_SLOW")
                    or not os.environ.get("METIS_TEST_SANDBOX_IMAGE"),
                    reason="set METIS_TEST_SLOW=1 and METIS_TEST_SANDBOX_IMAGE for isolated full search")
def test_specialist_intents_full_search_decrypt_and_xor(tmp_path):
    """Run the full intent chain in the bounded container, then decrypt and combine members."""
    _specialist_intent_zipcrypto_chain(
        tmp_path, seconds=300, sandbox_image=os.environ["METIS_TEST_SANDBOX_IMAGE"])

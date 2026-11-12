import base64
import json

import pytest

from metis.core.ctf_tools import transform
from metis.core.runtime import ToolRequest


@pytest.mark.parametrize(("tool", "data", "expected"), [
    ("base64_decode", "Zml4dHVyZQ==", "fixture"),
    ("base64_encode", "fixture", "Zml4dHVyZQ=="),
    ("base32_decode", "MZXW6===", "foo"),
    ("base85_decode", base64.b85encode(b"fixture").decode(), "fixture"),
    ("hex_decode", "66697874757265", "fixture"),
    ("hex_encode", "fixture", "66697874757265"),
    ("rot13", "PGS{grfg}", "CTF{test}"),
    ("reverse", "desserts", "stressed"),
    ("url_decode", "CTF%7Bhello+world%7D", "CTF{hello world}"),
    ("url_encode", "a/b ?", "a%2Fb%20%3F"),
    ("html_decode", "&lt;flag&gt;", "<flag>"),
    ("gcd", '{"a":"12345678901234567890","b":6}', "6"),
    ("mod_inverse", '{"a":3,"b":11}', "4"),
    ("caesar", '{"text":"Abc xyz!", "shift":3}', "Def abc!"),
])
def test_known_data_transforms(tool, data, expected):
    result = transform(ToolRequest(tool=tool, data=data))
    assert result.ok, result.output
    assert result.output == expected


@pytest.mark.parametrize(("tool", "data"), [
    ("base64_decode", "not base64!"), ("base32_decode", "!"),
    ("hex_decode", "abc"), ("xor", '{"data":"00", "key":""}'),
    ("mod_inverse", '{"a":2,"b":4}'), ("gcd", '{"a":true,"b":2}'),
    ("rsa_decrypt", '{"n":15,"d":-1,"c":1}'),
    ("integer_root", '{"n":-1,"k":2}'), ("integer_root", '{"n":1,"k":0}'),
    ("crt", '{"residues":[0,1],"moduli":[2,2]}'),
    ("jwt_decode", "not.a.jwt"), ("integer", "-1"),
    ("caesar", '{"text":"abc","shift":1,"shell":"unsafe"}'),
])
def test_bad_transform_inputs_are_failed_results(tool, data):
    assert not transform(ToolRequest(tool=tool, data=data)).ok


def parsed(tool, value):
    result = transform(ToolRequest(tool=tool, data=json.dumps(value)))
    assert result.ok, result.output
    return json.loads(result.output)


def test_xor_known_key_and_single_byte_search():
    plaintext = b"the secret flag is CTF{xor_test}"
    cipher = bytes(value ^ 0x42 for value in plaintext).hex()
    assert parsed("xor", {"data": cipher, "key": "42"})["utf8"] == plaintext.decode()
    candidates = parsed("xor_single", {"data": cipher})
    assert any(candidate["key_hex"] == "42" and candidate["text"] == plaintext.decode()
               for candidate in candidates)


def test_generalized_crt_and_integer_root():
    assert parsed("crt", {"residues": [2, 3, 2], "moduli": [3, 5, 7]}) == {
        "value": "23", "modulus": "105",
    }
    assert parsed("crt", {"residues": [2, 8], "moduli": [6, 9]}) == {
        "value": "8", "modulus": "18",
    }
    assert parsed("integer_root", {"n": 27, "k": 3}) == {"root": "3", "exact": True}
    assert parsed("integer_root", {"n": 28, "k": 3}) == {"root": "3", "exact": False}


def test_rsa_supplied_factors_and_private_exponent():
    ciphertext = pow(65, 17, 3233)
    assert parsed("rsa_decrypt", {"p": 61, "q": 53, "e": 17, "c": ciphertext})["utf8"] == "A"
    assert parsed("rsa_decrypt", {"n": 3233, "d": 2753, "c": ciphertext})["utf8"] == "A"


def test_web_and_candidate_analysis_does_not_claim_verification():
    token = ".".join(base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
                     for value in [{"alg": "none"}, {"role": "admin"}]) + "."
    result = transform(ToolRequest(tool="jwt_decode", data=token))
    assert result.ok
    assert json.loads(result.output)["signature_verified"] is False
    response = "HTTP/1.1 200 OK\r\nSet-Cookie: a=1\r\nSet-Cookie: b=2\r\n\r\nhello"
    result = json.loads(transform(ToolRequest(tool="http_parse", data=response)).output)
    assert len(result["headers"]) == 2 and result["body"] == "hello"
    result = json.loads(transform(ToolRequest(tool="flag_candidates", data="CTF{demo} CTF{demo}")).output)
    assert result == {"candidates": ["CTF{demo}"], "verified": False}


def test_integer_conversion_and_hashes():
    result = json.loads(transform(ToolRequest(tool="integer", data="0x435446")).output)
    assert result["utf8"] == "CTF"
    hashes = json.loads(transform(ToolRequest(tool="hashes", data="abc")).output)
    assert hashes["md5"] == "900150983cd24fb0d6963f7d28e17f72"


def test_packing_and_cyclic_offset_helpers():
    assert parsed("pack", {"value": "0xdeadbeef", "bits": 32})["hex"] == "efbeadde"
    assert parsed("unpack", {"data": "efbeadde", "bits": 32})["hex"] == "0xdeadbeef"
    pattern = transform(ToolRequest(tool="cyclic", data='{"length":512}')).output
    needle = pattern[68:72].encode().hex()
    assert parsed("cyclic_find", {"value": needle, "length": 512})["offset"] == 68


def test_aes_known_nist_vector_and_bad_key():
    result = parsed("aes_decrypt", {
        "data": "3ad77bb40d7a3660a89ecaf32466ef97", "mode": "ecb",
        "key": "2b7e151628aed2a6abf7158809cf4f3c",
    })
    assert result["hex"] == "6bc1bee22e409f96e93d7e117393172a"
    assert not transform(ToolRequest(tool="aes_decrypt", data='{"data":"00","key":"01"}')).ok


def test_bounded_rsa_methods():
    factors = parsed("fermat_factor", {"n": 1009 * 1013, "steps": 10})
    assert factors["found"] and int(factors["p"]) * int(factors["q"]) == 1009 * 1013
    assert not parsed("fermat_factor", {"n": 101, "steps": 1})["found"]
    n, message = 3233, 65
    result = parsed("rsa_common_modulus", {"n": n, "e1": 17, "e2": 7,
                                           "c1": pow(message, 17, n), "c2": pow(message, 7, n)})
    assert result["utf8"] == "A"

"""rsa_decrypt accepts one prime factor plus the modulus (shared-prime gcd workflow)."""
import json

from metis.core.ctf_tools import transform
from metis.core.runtime import ToolRequest

P, Q, E = 1000000007, 998244353, 65537


def _decrypt(**fields):
    return transform(ToolRequest(tool="rsa_decrypt", data=json.dumps(fields)))


def test_modulus_and_one_factor_decrypts():
    n, m = P * Q, 4242
    c = pow(m, E, n)
    for known in ({"p": str(P)}, {"q": str(Q)}):
        result = _decrypt(c=str(c), n=str(n), e=str(E), **known)
        assert result.ok
        assert json.loads(result.output)["integer"] == str(m)


def test_non_dividing_factor_is_rejected_with_tool_specific_hint():
    result = _decrypt(c="5", n=str(P * Q), e=str(E), p="13")
    assert not result.ok
    assert "rsa_decrypt expects" in result.output
    assert '"c": "..."' in result.output


def test_quoted_prompt_is_not_a_credential():
    import pytest

    from metis.core.ctf_knowledge import abstract_text

    assert abstract_text("strings show 'password: ' and 'nope'")
    with pytest.raises(ValueError, match="describe it without the value"):
        abstract_text("password: hunter2xyz")

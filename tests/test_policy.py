import math

import pytest
from pydantic import ValidationError

from metis.core.contracts import AllowedEndpoint, ChallengeManifest, RunBudget, ScopeGrant


@pytest.mark.parametrize("host", [
    "*", "*.example.org", "https://example.org", "example.org/path", "user@host",
    "example.org:80", "host\nname", "host\tname", "bad..host", "-host", "host-",
    "0.0.0.0", "::", "224.0.0.1", "ff02::1", "fe80::1%eth0", "127.1", "2130706433",
])
def test_endpoint_rejects_ambiguous_or_non_host_values(host):
    with pytest.raises(ValidationError):
        AllowedEndpoint(hostname=host, port=443)


@pytest.mark.parametrize(("host", "expected"), [
    ("CTF.example.org", "ctf.example.org"), ("127.0.0.1", "127.0.0.1"),
    ("::1", "::1"), ("2001:db8::1", "2001:db8::1"),
])
def test_exact_endpoints_allow_explicit_local_ctf_scope(host, expected):
    assert AllowedEndpoint(hostname=host, port=443).hostname == expected


@pytest.mark.parametrize("authorization", [1, "true", False, None])
def test_authorization_is_never_coerced(authorization):
    with pytest.raises(ValidationError):
        ScopeGrant(granted_by="test", challenge_id="test", authorized=authorization)


@pytest.mark.parametrize("artifact", [
    "", ".", "../answer", "/answer", "C:/answer", "C:answer",
    "..\\answer", "\\\\server\\share", "data\x00.txt",
])
def test_artifact_paths_are_portable_and_relative(artifact):
    with pytest.raises(ValidationError):
        ChallengeManifest.model_validate({
            "challenge_id": "test", "title": "Test", "description": "Local only",
            "artifacts": [artifact],
            "scope": {"granted_by": "test", "challenge_id": "test", "authorized": True},
        })


@pytest.mark.parametrize("cost", [math.nan, math.inf, -math.inf])
def test_budget_must_be_finite(cost):
    with pytest.raises(ValidationError):
        RunBudget(max_cost_usd=cost)


def test_unknown_policy_fields_are_not_silently_ignored():
    with pytest.raises(ValidationError):
        RunBudget.model_validate({"max_actons": 1})

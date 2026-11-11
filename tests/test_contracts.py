import pytest
from pydantic import ValidationError

from metis.core.contracts import ChallengeManifest, RunBudget


def sample():
    return {
        "challenge_id": "demo-001",
        "title": "Test",
        "description": "Local fixture",
        "categories": ["crypto"],
        "scope": {"authorized": True, "granted_by": "local-test", "challenge_id": "demo-001"},
    }


def test_authorized_manifest():
    assert ChallengeManifest.model_validate(sample()).challenge_id == "demo-001"


def test_requires_explicit_authorization():
    value = sample()
    value["scope"]["authorized"] = False
    with pytest.raises(ValidationError):
        ChallengeManifest.model_validate(value)


def test_grant_must_match_challenge():
    value = sample()
    value["scope"]["challenge_id"] = "different"
    with pytest.raises(ValidationError):
        ChallengeManifest.model_validate(value)


@pytest.mark.parametrize("artifact", ["../secret", "/etc/passwd"])
def test_reject_artifact_traversal(artifact):
    value = sample()
    value["artifacts"] = [artifact]
    with pytest.raises(ValidationError):
        ChallengeManifest.model_validate(value)


def test_budget_is_bounded():
    with pytest.raises(ValidationError):
        RunBudget(max_actions=0)

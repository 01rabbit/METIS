"""The model proposal never expands workflow capability or scope."""
import json

import pytest

from metis.core.workflow_model_trial import run_unseen_trial


@pytest.mark.parametrize("change", [
    {"steps": [{"tool": "shell"}]},
    {"steps": [{"tool": "rot13_decode"}]},
    {"policy": "allow-all"},
    {"verifier": "accept"},
    {"code": "print(1)"},
])
def test_model_proposal_cannot_extend_tools_policy_or_verifier(tmp_path, change):
    proposal = {"schema_version": 1, "input_artifact": "challenge.txt",
                "steps": [{"tool": "base64_decode"}], **change}
    with pytest.raises(ValueError, match="fixed schema|unregistered tool"):
        run_unseen_trial(tmp_path / "state.sqlite", image="sha256:" + "a" * 64,
                         platform=None, seeds=(2, 3),
                         proposer=lambda _: json.dumps(proposal).encode())


def test_trial_requires_two_distinct_families(tmp_path):
    with pytest.raises(ValueError, match="distinct seeds"):
        run_unseen_trial(tmp_path / "state.sqlite", image="sha256:" + "a" * 64,
                         platform=None, seeds=(2, 4), proposer=lambda _: b"{}")
    assert not (tmp_path / "state.sqlite").exists()

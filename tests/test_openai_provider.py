import io
import json

import pytest

from metis.core.contracts import ChallengeManifest
from metis.core.models import SolverContext
from metis.core.openai_provider import NoRedirect, OpenAIProvider


def test_missing_model_binding_is_explicit(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("METIS_OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="binding"):
        OpenAIProvider("test-model", max_call_cost_usd=0.01)


def test_provider_uses_fixed_https_destination_and_validates_response(monkeypatch):
    monkeypatch.setenv("METIS_OPENAI_API_KEY", "synthetic-test-key")
    captured = []

    class Opener:
        def open(self, request, timeout):
            captured.append((request, timeout))
            return io.BytesIO(json.dumps({"choices": [{"message": {"content":
                '{"kind":"halt","tool":null,"candidate":null}'}}]}).encode())

    monkeypatch.setattr("urllib.request.build_opener", lambda handler: Opener())
    manifest = ChallengeManifest.model_validate({
        "challenge_id": "test", "title": "Test", "description": "Untrusted data",
        "scope": {"challenge_id": "test", "granted_by": "test", "authorized": True},
    })
    provider = OpenAIProvider("test-model", max_call_cost_usd=0.01)
    decision = provider.decide(SolverContext(challenge=manifest), timeout_seconds=2)
    assert decision.kind == "halt"
    request, timeout = captured[0]
    assert request.full_url == "https://api.openai.com/v1/chat/completions"
    assert timeout == 2
    body = json.loads(request.data)
    assert body["messages"][1]["role"] == "user"
    assert "synthetic-test-key" not in request.data.decode()
    assert body["max_completion_tokens"] == 1024


def test_redirects_are_rejected():
    with pytest.raises(ValueError, match="redirects"):
        NoRedirect().redirect_request(None, None, 302, "", {}, "https://unrelated.example")

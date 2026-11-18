"""The Codex model adapter is isolated and returns only broker decisions."""

import pytest

from metis.core.codex_provider import DECISION_SCHEMA, CodexProvider
from metis.core.codex_specialist import CodexTurn
from metis.core.contracts import ChallengeManifest
from metis.core.models import Decision, SolverContext


class StubCLI:
    def __init__(self, turn):
        self.turn = turn
        self.calls = []

    def run(self, prompt, *, model, timeout, output_schema):
        self.calls.append((prompt, model, timeout, output_schema))
        return self.turn


def context(description="Decode the local puzzle."):
    challenge = ChallengeManifest.model_validate({
        "challenge_id": "codex-provider-fixture", "title": "Local provider fixture",
        "description": description, "categories": ["misc"],
        "scope": {"authorized": True, "granted_by": "test", "challenge_id": "codex-provider-fixture"},
    })
    return SolverContext(challenge=challenge)


def test_provider_uses_structured_codex_call_and_records_usage():
    cli = StubCLI(CodexTurn(returncode=0, message='{"kind":"candidate","tool":null,"candidate":"answer"}',
                            item_types=["agent_message"], usage={"input_tokens": 40, "output_tokens": 8}))
    provider = CodexProvider("gpt-test", cli=cli)
    result = provider.decide(context(), timeout_seconds=10)
    assert result == Decision(kind="candidate", candidate="answer")
    prompt, model, timeout, schema = cli.calls[0]
    assert "UNTRUSTED FIXTURE CONTEXT JSON" in prompt
    assert model == "gpt-test" and timeout == 10 and schema == DECISION_SCHEMA
    assert provider.usage_observed
    assert provider.usage_totals["input_tokens"] == 40
    assert provider.usage_totals["output_tokens"] == 8
    assert provider.reservation_tokens > 0 and provider.reservation_cost == 0


def test_provider_rejects_cli_tool_items_and_failed_calls():
    cli = StubCLI(CodexTurn(returncode=0, message='{"kind":"halt","tool":null,"candidate":null}',
                            item_types=["command_execution"]))
    with pytest.raises(ValueError, match="unavailable tool"):
        CodexProvider(cli=cli).decide(context(), timeout_seconds=5)
    cli.turn = CodexTurn(returncode=1, message=None)
    with pytest.raises(RuntimeError, match="model call failed"):
        CodexProvider(cli=cli).decide(context(), timeout_seconds=5)


def test_provider_bounds_context_before_call():
    cli = StubCLI(CodexTurn(returncode=0, message='{"kind":"halt","tool":null,"candidate":null}'))
    provider = CodexProvider(cli=cli, max_input_bytes=256)
    with pytest.raises(ValueError, match="context exceeds"):
        provider.decide(context("x" * 1000), timeout_seconds=5)
    assert not cli.calls

from metis.evaluation.llama_cli_cap_probe import assess_cli_output


def test_chat_wrapper_without_usage_fails_closed():
    result = assess_cli_output('available commands:\n> Hello\nHello\n',
                               '{"type":"fit_memory_breakdown"}\n')
    assert result == {"strict_cap_ready": False, "chat_wrapper_observed": True,
                      "usage_observed": False, "prompt_tokens": None, "completion_tokens": None}


def test_explicit_usage_without_chat_wrapper_is_only_provisional():
    result = assess_cli_output('{"prompt_tokens":3,"completion_tokens":1}', '')
    assert result["strict_cap_ready"] is True
    assert result["prompt_tokens"] == 3


def test_duplicate_usage_fails_closed():
    row = '{"prompt_tokens":3,"completion_tokens":1}'
    assert assess_cli_output(row + '\n' + row, '')["strict_cap_ready"] is False

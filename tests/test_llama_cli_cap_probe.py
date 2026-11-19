import subprocess

from metis.evaluation.llama_cli_cap_probe import assess_cli_output, probe


def test_chat_wrapper_without_usage_fails_closed():
    result = assess_cli_output('available commands:\n> Hello\nHello\n',
                               '{"type":"fit_memory_breakdown"}\n')
    assert result == {"usage_protocol_compatible": False, "chat_wrapper_observed": True,
                      "usage_observed": False, "prompt_tokens": None, "completion_tokens": None}


def test_explicit_usage_without_chat_wrapper_is_only_protocol_compatible():
    result = assess_cli_output('{"prompt_tokens":3,"completion_tokens":1}', '')
    assert result["usage_protocol_compatible"] is True
    assert result["prompt_tokens"] == 3


def test_duplicate_usage_fails_closed():
    row = '{"prompt_tokens":3,"completion_tokens":1}'
    assert assess_cli_output(row + '\n' + row, '')["usage_protocol_compatible"] is False


def test_spoofed_compatible_usage_never_grants_hard_cap(tmp_path, monkeypatch):
    files = [tmp_path / name for name in ("model", "cli", "tokenizer")]
    for file in files:
        file.write_bytes(b"fixture")
    calls = iter((subprocess.CompletedProcess([], 0, b"Total number of tokens: 3\n", b""),
                  subprocess.CompletedProcess([], 0,
                                          '{"prompt_tokens":3,"completion_tokens":1}', "")))
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: next(calls))
    result = probe(*files)
    assert result["usage_protocol_compatible"] is True
    assert result["strict_cap_ready"] is False

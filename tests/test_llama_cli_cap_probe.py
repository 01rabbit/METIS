import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from metis.evaluation.llama_cli_cap_probe import assess_cli_output, probe


def test_chat_wrapper_without_usage_fails_closed():
    result = assess_cli_output("available commands:\n> Hello\nHello\n",
                               '{"type":"fit_memory_breakdown"}\n', precount_tokens=3, returncode=0)
    assert result == {"usage_protocol_compatible": False, "chat_wrapper_observed": True,
                      "usage_observed": False, "prompt_tokens": None, "completion_tokens": None}


@pytest.mark.parametrize(("prompt", "completion", "returncode", "compatible"), [
    (3, 1, 0, True),
    (3, 0, 0, True),
    (3, 2, 0, False),
    (3, -1, 0, False),
    (-3, 1, 0, False),
    (4, 1, 0, False),
    (True, 1, 0, False),
    (3, False, 0, False),
    (3, 1, 1, False),
    (3, 1, -9, False),
])
def test_usage_requires_matching_counts_and_successful_exit(prompt, completion, returncode, compatible):
    row = json.dumps({"prompt_tokens": prompt, "completion_tokens": completion})
    result = assess_cli_output(row, "", precount_tokens=3, returncode=returncode)
    assert result["usage_protocol_compatible"] is compatible
    if compatible:
        assert result["usage_observed"] is True
        assert (result["prompt_tokens"], result["completion_tokens"]) == (prompt, completion)


@pytest.mark.parametrize("other", [
    '{"prompt_tokens":3,"completion_tokens":1}',
    '{"prompt_tokens":3}',
    '{"prompt_tokens":3,"prompt_tokens":0,"completion_tokens":1}',
])
def test_duplicate_or_ambiguous_usage_fails_closed(other):
    row = '{"prompt_tokens":3,"completion_tokens":1}'
    result = assess_cli_output(row, other, precount_tokens=3, returncode=0)
    assert result["usage_protocol_compatible"] is False
    assert result["usage_observed"] is False


def _files(tmp_path):
    files = [tmp_path / name for name in ("model", "cli", "tokenizer")]
    for file in files:
        file.write_bytes(file.name.encode())
    return files


def test_probe_executes_hashed_absolute_paths_with_closed_stdin(tmp_path, monkeypatch):
    files = _files(tmp_path)
    model, cli, tokenizer = (path.resolve() for path in files)
    alias = tmp_path / "cli-alias"
    alias.symlink_to(cli)
    monkeypatch.chdir(tmp_path)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert "input" not in kwargs
        assert command[1:5] == ["-m", str(model), "-p", "Hello"]
        if command[0] == str(tokenizer):
            return subprocess.CompletedProcess(command, 0, b"Total number of tokens: 3\n", b"")
        assert command[0] == str(cli)
        assert command[5:7] == ["-n", "1"]
        return subprocess.CompletedProcess(command, 0, '{"prompt_tokens":3,"completion_tokens":1}', "")

    monkeypatch.setattr(subprocess, "run", run)
    result = probe(Path("model"), Path("cli-alias"), Path("tokenizer"))
    assert [command[0] for command in calls] == [str(tokenizer), str(cli)]
    for file in files:
        assert result[f"{file.name}_sha256"] == hashlib.sha256(file.name.encode()).hexdigest()
    assert result["usage_protocol_compatible"] is True
    assert result["precount_tokens"] == 3
    assert result["strict_cap_ready"] is False


@pytest.mark.parametrize(("change_during", "change_file"), [
    (1, "model"),
    (1, "cli"),
    (2, "cli"),
    (2, "tokenizer"),
])
def test_replacing_probe_input_rejects_even_identical_bytes(tmp_path, monkeypatch, change_during, change_file):
    files = _files(tmp_path)
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        if len(calls) == change_during:
            path = tmp_path / change_file
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 0, b"Total number of tokens: 3\n", b"")
        return subprocess.CompletedProcess(command, 0, '{"prompt_tokens":3,"completion_tokens":1}', "")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match="probe input changed during execution"):
        probe(*files)
    assert len(calls) == change_during

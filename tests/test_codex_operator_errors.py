"""Actionable errors for `metis codex` artifact, act, tools and submit."""
import hashlib
import io
import json
import sys
import zipfile

import pytest

from metis import cli
from metis.core.codex_session import CodexSession, _safe_cause, tool_catalog
from metis.core.ctf_artifacts import ALLOWED_OPTIONS, inspect_bytes
from metis.core.ctf_tools import DATA_TOOLS, JSON_TOOL_INPUTS, input_shape, transform
from metis.core.runtime import ToolRequest


def _run(tmp_path, content: bytes, name: str = "source.bin", **kwargs):
    source = tmp_path / name
    source.write_bytes(content)
    session = CodexSession(tmp_path / "sessions.sqlite")
    run_id = session.intake(title="t", description="d", paths=[source], **kwargs)["run_id"]
    return session, run_id, "00-" + name


@pytest.mark.parametrize("operation", ["artifact", "derive"])
def test_base64_decode_failure_reports_cause(tmp_path, operation):
    session, run_id, name = _run(tmp_path, b"not base64 here\nQUJD\n")
    result = getattr(session, operation)(run_id, name, "base64_decode")
    assert result["ok"] is False
    assert "Non-base64" in result["detail"] or "base64" in result["detail"].lower()
    assert "binascii" in result["detail"]
    assert str(tmp_path) not in json.dumps(result)


def test_safe_cause_masks_paths_and_bounds_length():
    assert "/Users" not in _safe_cause(ValueError("cannot read /Users/someone/secret/file.txt now"))
    assert _safe_cause(OSError(2, "No such file", "/host/only/path")) == "FileNotFoundError: No such file"
    assert len(_safe_cause(KeyError("x" * 1000))) <= 220


def test_unknown_option_names_key_and_accepted_keys():
    with pytest.raises(ValueError) as caught:
        inspect_bytes(b"", "zip_read", {"name": "a.txt"})
    message = str(caught.value)
    assert "name" in message and "member" in message and "max_bytes" in message


def test_unknown_option_reaches_operator(tmp_path):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", "hello")
    session, run_id, name = _run(tmp_path, archive.getvalue(), "a.zip")
    result = session.artifact(run_id, name, "zip_read", {"name": "a.txt"})
    assert result["ok"] is False
    assert "name" in result["detail"] and "member" in result["detail"]
    assert session.artifact(run_id, name, "zip_read", {"member": "a.txt"})["ok"] is True


def test_unknown_tool_and_non_object_options_have_distinct_messages():
    with pytest.raises(ValueError, match="unknown artifact tool"):
        inspect_bytes(b"", "nope")
    with pytest.raises(TypeError, match="options must be a JSON object"):
        inspect_bytes(b"", "overview", ["x"])  # type: ignore[arg-type]


def test_xor_single_plain_input_states_expected_shape():
    result = transform(ToolRequest(tool="xor_single", data="41424344"))
    assert result.ok is False
    assert result.output.startswith("invalid or unsupported bounded tool input")
    assert "xor_single expects JSON object string {data,key?,encoding?,key_encoding?}" in result.output
    good = transform(ToolRequest(tool="xor_single", data='{"data":"41424344","encoding":"hex"}'))
    assert good.ok is True


def test_plain_text_tool_failure_names_plain_text():
    result = transform(ToolRequest(tool="base64_decode", data="!!!"))
    assert "base64_decode expects plain text" in result.output


def test_tools_catalog_covers_every_tool():
    catalog = tool_catalog()
    assert set(catalog["inline_tool_inputs"]) == set(DATA_TOOLS)
    assert set(JSON_TOOL_INPUTS) <= set(DATA_TOOLS)
    assert catalog["inline_tool_inputs"]["gcd"] == "JSON object string {a,b}"
    assert catalog["inline_tool_inputs"]["sha256"] == input_shape("sha256")
    options = catalog["artifact_tool_options"]
    assert options["zip_read"] == "{" + ",".join(sorted(ALLOWED_OPTIONS["zip_read"])) + "}"
    assert options["overview"] == "{}"


def test_tools_cli_lists_inputs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["metis", "codex", "--database", str(tmp_path / "s.sqlite"), "tools"])
    assert cli.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert "member" in output["artifact_tool_options"]["zip_read"]
    assert output["inline_tool_inputs"]["xor_single"].startswith("JSON object string")
    assert "inline_tools" in output and "artifact_tools" in output


@pytest.mark.parametrize(("text", "expected"), [
    ("FLAG{x}\n", "FLAG{x}"), ("FLAG{x}\r\n", "FLAG{x}"), ("FLAG{x}\n\n", "FLAG{x}\n"),
    ("FLAG{x}", "FLAG{x}"), ("", ""),
])
def test_strip_one_newline(text, expected):
    assert cli.strip_one_newline(text) == expected


def test_codex_submit_cli_strips_one_newline(tmp_path, monkeypatch, capsys):
    database = tmp_path / "s.sqlite"
    session = CodexSession(database)
    source = tmp_path / "f.txt"
    source.write_bytes(b"x")
    commitment = hashlib.sha256(b"FLAG{x}").hexdigest()
    run_id = session.intake(title="t", description="d", paths=[source], commitment=commitment)["run_id"]
    monkeypatch.setattr(sys, "argv", ["metis", "codex", "--database", str(database), "submit", run_id])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"FLAG{x}\n")))
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["verified"] is True


def test_submit_reports_reasons(tmp_path):
    session, run_id, _ = _run(tmp_path, b"x")
    result = session.submit(run_id, "FLAG{x}")
    assert result["verified"] is False and "unavailable" in result["reason"]
    empty = session.submit(run_id, "")
    assert empty["verified"] is False and "empty" in empty["reason"]
    assert session.context(run_id)["actions_remaining"] == session.context(run_id)["budget"]["max_actions"] - 1

    committed, committed_id, _ = _run(tmp_path, b"y", "other.bin",
                                      commitment=hashlib.sha256(b"right").hexdigest())
    wrong = committed.submit(committed_id, "wrong")
    assert wrong["verified"] is False and "does not match" in wrong["reason"]
    assert "reason" not in committed.submit(committed_id, "right")

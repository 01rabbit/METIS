"""Offline smoke paths through the same bounded adapters used by specialists."""
import json
import re

from metis.core.codex_session import CodexSession
from metis.core.ctf_practice import practice
from metis.core.ctf_tools import transform
from metis.core.runtime import ToolRequest


def test_six_practice_categories_use_authorized_bounded_adapters(tmp_path):
    session = CodexSession(tmp_path / ".metis-state" / "metis.sqlite")
    fixtures = practice(session)
    categories = [session.context(item["run_id"])["challenge"]["categories"][0] for item in fixtures]
    assert categories == ["crypto", "web", "forensics", "rev", "pwn", "misc"]

    paths = {
        "crypto": lambda item: transform(ToolRequest(tool="xor", data=json.dumps({
                "data": re.search(r"Ciphertext: ([0-9a-f]+)", item["challenge"]["description"])[1],
            "key": "LUNA", "key_encoding": "utf8"}))).output,
        "web": lambda item: session.artifact(item["run_id"], item["challenge"]["artifacts"][0], "text"),
        "forensics": lambda item: session.artifact(item["run_id"], item["challenge"]["artifacts"][0], "image_lsb"),
        "rev": lambda item: session.artifact(item["run_id"], item["challenge"]["artifacts"][0], "strings"),
        "pwn": lambda item: session.artifact(item["run_id"], item["challenge"]["artifacts"][0], "disassemble"),
        "misc": lambda item: session.artifact(item["run_id"], item["challenge"]["artifacts"][0], "zip_list"),
    }
    for item in fixtures:
        context = session.context(item["run_id"])
        assert context["challenge"]["scope"]["authorized"] is True
        assert context["challenge"]["scope"]["granted_by"] == "explicit-user-intake"
        category = context["challenge"]["categories"][0]
        result = paths[category](item)
        if category == "crypto":
            assert "the competition flag is CTF{" in json.loads(result)["utf8"]
        else:
            assert result["ok"] is True
            assert result["result"]


def test_practice_unsupported_tools_fail_closed_with_reason(tmp_path):
    session = CodexSession(tmp_path / ".metis-state" / "metis.sqlite")
    item = practice(session)[0]
    denied_data = transform(ToolRequest(tool="shell", data="true"))
    assert denied_data.ok is False and denied_data.output == "tool denied"
    try:
        session.artifact(item["run_id"], "missing.bin", "execute")
    except ValueError as error:
        assert str(error) == "artifact or operation is outside the declared scope"
    else:
        raise AssertionError("unsupported artifact operation was accepted")

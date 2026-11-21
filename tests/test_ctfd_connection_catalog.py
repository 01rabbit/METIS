import json

from test_ctf_web import fake_ctfd  # noqa: F401

from metis.core.ctf_remote import RemoteWorkflow
from metis.core.ctf_web import WebWorkflow


def test_ctfd_connection_info_reaches_description_and_suggest(fake_ctfd, tmp_path):  # noqa: F811
    fake_ctfd.challenge_body = json.dumps({"success": True, "data": {
        "name": "c", "category": "pwn", "description": "d", "files": [],
        "connection_info": "nc chall.example.com 31337"}})
    database = tmp_path / "s.sqlite"
    result = WebWorkflow(database).open(
        fake_ctfd.BASE, adapter="ctfd", challenge_id=1, token_env="TEST_CTF_TOKEN")
    run_id = result["context"]["run_id"]
    suggestion = RemoteWorkflow(database).suggest(run_id)
    assert suggestion["candidates"] == [{"host": "chall.example.com", "port": 31337, "tls": False}]
    assert RemoteWorkflow(database).endpoints(run_id)["endpoints"] == []


def test_ctfd_catalog_truncates_and_reports_type_and_solved(fake_ctfd, tmp_path):  # noqa: F811
    fake_ctfd.challenge_body = json.dumps({"success": True, "data": [
        {"id": i, "name": f"n{i}", "category": "Web", "value": 10, "solves": 1,
         "type": "standard", "solved_by_me": i == 1} for i in range(1, 602)]})
    result = WebWorkflow(tmp_path / "s.sqlite").catalog(
        fake_ctfd.BASE, token_env="TEST_CTF_TOKEN")
    assert result["truncated"] is True and result["count"] == 500
    assert result["challenges"][0]["type"] == "standard" and result["challenges"][0]["solved"] is True
    assert result["challenges"][1]["solved"] is False

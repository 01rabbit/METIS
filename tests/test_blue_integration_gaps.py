"""Blue Team evidence is reachable from planning, CloudTrail keeps source fields, eval paths work from the checkout."""
import json
import os
from pathlib import Path

from metis.core.agent_contracts import PROFILES
from metis.core.contracts import ChallengeManifest
from metis.core.ctf_artifacts import inspect_bytes
from metis.core.ctf_triage import triage

ROOT = Path(__file__).resolve().parent.parent
READERS = {"evtx_xml", "cloudtrail", "email", "browser_history", "json_records"}


def _manifest(description, artifacts=()):
    return ChallengeManifest.model_validate({
        "schema_version": 1, "challenge_id": "ctf-blue-gap", "title": "Synthetic", "description": description,
        "categories": [], "artifacts": list(artifacts),
        "scope": {"granted_by": "test", "challenge_id": "ctf-blue-gap", "allowed_endpoints": [], "authorized": True}})


def test_incident_evidence_statements_suggest_forensics_with_the_readers():
    for description, artifacts in (("Find the IAM user from the CloudTrail export.", ()),
                                   ("Investigate the incident.", ("Security.evtx",)),
                                   ("Which link did the phish deliver?", ("mail.eml",))):
        result = triage(_manifest(description, artifacts))
        assert "forensics" in result["suggested_categories"], description
        assert READERS <= set(result["playbooks"]["forensics"]["tools"])
    assert READERS <= set(PROFILES["forensics-specialist"].recommended_tools)
    assert "evidence readers" in PROFILES["forensics-specialist"].objective


def test_cloudtrail_records_keep_source_address_and_agent():
    raw = json.dumps({"Records": [{
        "eventID": "e1", "eventTime": "2026-01-01T00:00:00Z", "eventName": "CreateAccessKey",
        "eventSource": "iam.amazonaws.com", "sourceIPAddress": "203.0.113.50", "userAgent": "aws-cli/2",
        "awsRegion": "us-east-1", "errorCode": "AccessDenied",
        "userIdentity": {"type": "IAMUser", "arn": "arn:aws:iam::111122223333:user/u"}}]}).encode()
    record = inspect_bytes(raw, "cloudtrail", {})["data"]["records"][0]
    assert record["source_ip_address"] == {"type": "string", "value": "203.0.113.50"}
    assert record["user_agent"]["value"] == "aws-cli/2" and record["aws_region"]["value"] == "us-east-1"
    assert record["error_code"]["value"] == "AccessDenied"


def test_readiness_eval_accepts_paths_typed_from_the_checkout(monkeypatch, capsys):
    from metis.blue.runtime import readiness_eval

    monkeypatch.chdir(ROOT)
    name = f"gap-{os.getpid()}"
    created = [ROOT / "blue/.state/benchmarks" / f"{name}.{suffix}" for suffix in ("prompt.txt", "meta.json")]
    try:
        status = readiness_eval.main(["bundle", "--protocol", "v2", "--cases", "blue/examples/readiness-cases.json",
                                      "--out", f"blue/.state/benchmarks/{name}.prompt.txt"])
        output = json.loads(capsys.readouterr().out)
        assert status == 0 and output["cases"] == 16 and all(path.is_file() for path in created)
        assert readiness_eval.main(["bundle", "--out", "/tmp/outside.prompt.txt"]) == 2  # still confined
    finally:
        for path in created:
            path.unlink(missing_ok=True)

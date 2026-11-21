"""Triage uses artifact magic before keyword hints."""
from metis.core.contracts import ChallengeManifest
from metis.core.ctf_triage import magic_categories, triage


def _manifest(title: str, artifacts: list[str]) -> ChallengeManifest:
    return ChallengeManifest.model_validate({
        "schema_version": 1, "challenge_id": "ctf-test", "title": title, "description": "password check",
        "categories": [], "artifacts": artifacts,
        "scope": {"granted_by": "test", "challenge_id": "ctf-test", "allowed_endpoints": [], "authorized": True},
    })


def test_elf_without_keywords_is_rev():
    result = triage(_manifest("Gatekeeper", ["00-checker"]), {"00-checker": b"\x7fELF\x02\x01\x01\x00"})
    assert result["suggested_categories"][0] == "rev"
    assert "magic" in result["basis"]


def test_magic_leads_and_keywords_follow_without_duplicates():
    result = triage(_manifest("RSA cipher", ["00-a.png"]), {"00-a.png": b"\x89PNG\r\n\x1a\n"})
    assert result["suggested_categories"] == ["forensics", "crypto"]


def test_no_magics_keeps_keyword_behaviour():
    assert triage(_manifest("Gatekeeper", ["00-checker"]))["suggested_categories"] == ["misc"]
    assert magic_categories({"x": b"plain text"}) == []


def test_elf_with_exploitation_words_is_pwn_first():
    manifest = _manifest("Exploit the buffer overflow", ["00-vuln"])
    result = triage(manifest, {"00-vuln": b"\x7fELF\x02\x01\x01\x00"})
    assert result["suggested_categories"][:2] == ["pwn", "rev"]

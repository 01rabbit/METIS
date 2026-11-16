"""Shared test isolation."""
import pytest


@pytest.fixture(autouse=True)
def _private_answer_vault(tmp_path_factory, monkeypatch):
    """Never let a test write answers into the user's real vault (~/.local/share/metis)."""
    monkeypatch.setenv("METIS_ANSWER_VAULT", str(tmp_path_factory.mktemp("vault") / "answers.json"))

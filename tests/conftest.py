"""Shared test isolation."""
import os
import sys
from pathlib import Path

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Skip only paths the OS refuses to stat (e.g. Claude Code's Bash sandbox hides
    `*credential*` files), so the rest of the suite still runs there. Unsandboxed runs
    and CI stat every path normally and collect everything."""
    try:
        os.stat(collection_path)
    except PermissionError:
        sys.stderr.write(f"warning: not collecting unreadable path {collection_path} (sandboxed?)\n")
        return True
    return None


@pytest.fixture(autouse=True)
def _private_answer_vault(tmp_path_factory, monkeypatch):
    """Never let a test write answers into the user's real vault (~/.local/share/metis)."""
    monkeypatch.setenv("METIS_ANSWER_VAULT", str(tmp_path_factory.mktemp("vault") / "answers.json"))

from pathlib import Path

import pytest

from metis.cli import build_parser

CASES = [
    ["codex", "tools"],
    ["codex", "intake"],
    ["codex", "plan", "RUN"],
    ["plan", "RUN"],
    ["agent", "jobs"],
    ["agent", "dispatch", "RUN", "WAVE"],
    ["remote", "list", "RUN"],
    ["sandbox", "status"],
    ["contest", "list"],
    ["contest", "board", "C1"],
    ["memory", "search", "x"],
    ["writeup", "missing", "C1"],
    ["web", "catalog", "https://example.invalid"],
    ["resource", "status"],
]


def _database(argv: list[str]) -> Path:
    try:
        return build_parser().parse_args(argv).database
    except SystemExit as exc:  # pragma: no cover - failure detail
        pytest.fail(f"parse failed for {argv}: exit {exc.code}")


@pytest.mark.parametrize("command", CASES, ids=lambda c: " ".join(c))
def test_database_before_and_after_subcommand_match(command: list[str]) -> None:
    target = "custom.sqlite"
    before = _database([command[0], "--database", target, *command[1:]])
    after = _database([*command, "--database", target])
    assert before == after == Path(target)


@pytest.mark.parametrize("command", CASES, ids=lambda c: " ".join(c))
def test_default_database_unchanged(command: list[str]) -> None:
    assert _database(command) == Path(".metis-state/metis.sqlite")


def test_leaf_value_overrides_group_value() -> None:
    assert _database(["codex", "--database", "a", "tools", "--database", "b"]) == Path("b")


def test_help_still_works(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["codex", "tools", "--help"])
    assert exc.value.code == 0
    assert "--database" not in capsys.readouterr().out

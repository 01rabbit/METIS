"""The METIS Blue knowledge structure check fails closed on malformed skills, links and discovery paths."""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("check_blue_knowledge", ROOT / "scripts" / "check_blue_knowledge.py")
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)


@pytest.fixture
def tree(tmp_path):
    shutil.copytree(ROOT / "blue", tmp_path / "blue", ignore=shutil.ignore_patterns(".state", "__pycache__"))
    shutil.copytree(ROOT / ".agents", tmp_path / ".agents", symlinks=True)
    (tmp_path / "docs").mkdir()
    shutil.copy2(ROOT / "docs" / "BLUE_TEAM.md", tmp_path / "docs" / "BLUE_TEAM.md")  # linked from blue/README.md
    return tmp_path


def _manifest(tree, name="soc-triage"):
    return tree / "blue" / "skills" / name / "SKILL.md"


def test_current_tree_passes(tree):
    assert checker.check(tree) == []


def test_removed_skill_manifest_is_reported_by_the_structure_check(tree):
    _manifest(tree).unlink()  # directory and references remain
    assert any("skill directory without SKILL.md: blue/skills/soc-triage" in e for e in checker.check(tree))


@pytest.mark.parametrize("mutate, finding", [
    (lambda text: "intro line\n" + text, "malformed skill front matter"),
    (lambda text: text.replace("\n---\n", "\n", 2).replace("---\n", "", 1), "malformed skill front matter"),
    (lambda text: text.replace("name: soc-triage", "name: SOC_Triage", 1), "invalid skill name"),
    (lambda text: text.replace("name: soc-triage", "name:", 1), "invalid skill name"),
])
def test_malformed_front_matter_fails(tree, mutate, finding):
    manifest = _manifest(tree)
    manifest.write_text(mutate(manifest.read_text()))
    assert any(finding in e for e in checker.check(tree))


def test_empty_description_fails(tree):
    manifest = _manifest(tree)
    lines = manifest.read_text().splitlines(keepends=True)
    manifest.write_text("".join("description:\n" if line.startswith("description:") else line for line in lines))
    assert any("missing skill description: blue/skills/soc-triage/SKILL.md" in e for e in checker.check(tree))


def test_broken_link_undiscoverable_dangling_and_unexpected_aliases(tree):
    (tree / "blue" / "playbooks" / "README.md").write_text("see [gone](missing.md)\n")
    skills = tree / ".agents" / "skills"
    (skills / "soc-triage").unlink()
    (skills / "removed-skill").symlink_to("../../blue/skills/removed-skill")
    (tree / "elsewhere").mkdir()
    (skills / "outside").symlink_to("../../elsewhere")
    (skills / "triage-alias").symlink_to("../../blue/skills/soc-host-forensics")
    errors = checker.check(tree)
    assert any("broken link: blue/playbooks/README.md: missing.md" in e for e in errors)
    assert any("not discoverable at .agents/skills/soc-triage" in e for e in errors)
    assert any("dangling skill link: .agents/skills/removed-skill" in e for e in errors)
    assert any("unexpected skill link: .agents/skills/outside" in e for e in errors)
    assert any("unexpected skill link: .agents/skills/triage-alias" in e for e in errors)


def _git(tree, *args):
    subprocess.run(["git", *args], cwd=tree, check=True, capture_output=True)


@pytest.fixture
def repository(tree):
    _git(tree, "init", "-q")
    _git(tree, "add", "-A")
    return tree


def test_staged_mode_checks_the_staged_snapshot_not_the_worktree(repository):
    readme = repository / "blue" / "playbooks" / "README.md"
    original = readme.read_text()
    # Staged-only invalid link: the worktree is valid again, the index is not.
    readme.write_text(original + "\nsee [gone](missing.md)\n")
    _git(repository, "add", "blue/playbooks/README.md")
    readme.write_text(original)
    assert checker.check(repository) == []
    assert any("broken link: blue/playbooks/README.md: missing.md" in e for e in checker.check_staged(repository))
    # Unstaged-only invalid front matter: the index is valid, the worktree is not.
    readme.write_text(original)
    _git(repository, "add", "blue/playbooks/README.md")
    manifest = _manifest(repository)
    manifest.write_text("intro\n" + manifest.read_text())
    assert checker.check_staged(repository) == []
    assert any("malformed skill front matter" in e for e in checker.check(repository))


def test_staged_mode_sees_staged_discovery_links(repository):
    (repository / ".agents" / "skills" / "soc-triage").unlink()
    _git(repository, "add", "-A")
    (repository / ".agents" / "skills" / "soc-triage").symlink_to("../../blue/skills/soc-triage")
    assert any("not discoverable at .agents/skills/soc-triage" in e for e in checker.check_staged(repository))

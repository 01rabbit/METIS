"""The METIS Blue knowledge structure check catches broken skills, links and discovery paths."""
import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(root):
    spec = importlib.util.spec_from_file_location("check_blue_knowledge", ROOT / "scripts" / "check_blue_knowledge.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT, module.BLUE = root, root / "blue"
    return module


@pytest.fixture
def tree(tmp_path):
    shutil.copytree(ROOT / "blue", tmp_path / "blue", ignore=shutil.ignore_patterns(".state", "__pycache__"))
    shutil.copytree(ROOT / ".agents", tmp_path / ".agents", symlinks=True)
    (tmp_path / "docs").mkdir()
    shutil.copy2(ROOT / "docs" / "BLUE_TEAM.md", tmp_path / "docs" / "BLUE_TEAM.md")  # linked from blue/README.md
    return tmp_path


def test_current_tree_passes(tree):
    assert _load(tree).check() == []


def test_invalid_skill_name_and_missing_description(tree):
    manifest = tree / "blue" / "skills" / "soc-triage" / "SKILL.md"
    text = manifest.read_text()
    manifest.write_text(text.replace("name: soc-triage", "name: SOC_Triage", 1).replace("description:", "summary:", 1))
    errors = _load(tree).check()
    assert any("invalid skill name" in e for e in errors) and any("missing skill description" in e for e in errors)


def test_broken_link_and_undiscoverable_skill(tree):
    (tree / "blue" / "playbooks" / "README.md").write_text("see [gone](missing.md)\n")
    (tree / ".agents" / "skills" / "soc-triage").unlink()
    (tree / ".agents" / "skills" / "removed-skill").symlink_to("../../blue/skills/removed-skill")
    errors = _load(tree).check()
    assert any("broken link: blue/playbooks/README.md: missing.md" in e for e in errors)
    assert any("not discoverable at .agents/skills/soc-triage" in e for e in errors)
    assert any("dangling skill link: .agents/skills/removed-skill" in e for e in errors)

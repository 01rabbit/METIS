#!/usr/bin/env python3
"""Install or repair this METIS checkout so it works wherever it is located.

Safe to re-run at any time. After moving or copying the folder (same Mac or a
new one) run:

    python3 scripts/setup.py --all

which (re)creates the project-local Python environment, re-points the Claude
Code integration at the new location, and (re)builds the dynamic-analysis
sandbox image when the container engine does not have it yet.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SANDBOX_PATTERN = "/.venv/bin/metis sandbox *"


def shebang_target(script: Path) -> str | None:
    try:
        with script.open("rb") as stream:
            first = stream.readline(4096).decode(errors="replace").strip()
    except OSError:
        return None
    return first[2:].strip().split()[0] if first.startswith("#!") and len(first) > 2 else None


def environment_is_stale(root: Path) -> bool:
    """True when .venv exists but was created at another path (folder moved or copied)."""
    venv_dir = root / ".venv"
    if not venv_dir.exists():
        return False
    target = shebang_target(venv_dir / "bin" / "metis")
    if target is None:
        return True
    interpreter = Path(target)
    return not str(interpreter).startswith(str(venv_dir) + os.sep) or not interpreter.exists()


def bootstrap_uv(root: Path) -> str:
    executable = shutil.which("uv")
    if executable:
        return executable
    bootstrap = root / ".metis-bootstrap"
    python = bootstrap / "bin" / "python"
    stale = bootstrap.exists() and (
        not python.exists()
        or subprocess.run([str(python), "-c", "pass"], capture_output=True, check=False).returncode != 0)
    if stale:
        print("METIS: rebuilding the uv bootstrap environment (folder was moved).", flush=True)
        shutil.rmtree(bootstrap)
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(bootstrap)
    uv = bootstrap / "bin" / "uv"
    if not uv.exists():
        subprocess.run([str(python), "-m", "pip", "install", "uv==0.13.5"], cwd=root, check=True)
    return str(uv)


def configure_claude_code(root: Path) -> dict:
    """Copy the Claude Code integration and re-point path-dependent local settings."""
    source = root / "integrations" / "claude-code"
    target = root / ".claude"
    target.mkdir(exist_ok=True)
    for name in ("skills", "agents", "commands"):
        shutil.copytree(source / name, target / name, dirs_exist_ok=True)
    # Blue Team skills stay canonical under blue/skills; link them so their relative
    # references to blue/docs, detections and playbooks keep resolving.
    linked = []
    for skill in sorted((root / "blue" / "skills").glob("*/SKILL.md")):
        link = target / "skills" / skill.parent.name
        if link.is_symlink() or not link.exists():
            if link.is_symlink():
                link.unlink()
            link.symlink_to(Path("..") / ".." / "blue" / "skills" / skill.parent.name, target_is_directory=True)
            linked.append(skill.parent.name)
    settings_path = target / "settings.local.json"
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    sandbox = settings.setdefault("sandbox", {})
    excluded = sandbox.setdefault("excludedCommands", [])
    current = str(root / ".venv" / "bin" / "metis") + " sandbox *"
    stale = [item for item in excluded if item.endswith(SANDBOX_PATTERN) and item.startswith("/")
             and item != current]
    excluded[:] = [item for item in excluded if item not in stale]
    for pattern in (".venv/bin/metis sandbox *", "./.venv/bin/metis sandbox *", current):
        if pattern not in excluded:
            excluded.append(pattern)
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    domains = sandbox.get("network", {}).get("allowedDomains", [])
    return {"copied": ["skills", "agents", "commands"], "linked_blue_skills": linked, "removed_stale_paths": stale,
            "sandbox_excluded_commands": excluded, "allowed_domains_kept": domains}


def ensure_sandbox(root: Path, rebuild: bool) -> None:
    metis = str(root / ".venv" / "bin" / "metis")
    status = json.loads(subprocess.run([metis, "sandbox", "status"], cwd=root, capture_output=True,
                                       text=True, check=True).stdout)
    if not status["engine_available"]:
        print("METIS: container engine not reachable (" + str(status.get("engine_error")) + "); start "
              "OrbStack/Docker and re-run with --sandbox. Skipping the sandbox image.", flush=True)
        return
    if status["configured"] and status.get("image_present") and not rebuild:
        print("METIS: sandbox image already present for this engine.", flush=True)
        return
    print("METIS: building the sandbox image for this machine (this can take a while)...", flush=True)
    subprocess.run([metis, "sandbox", "build"], cwd=root, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dev", action="store_true", help="include the test/type/lint tools")
    parser.add_argument("--browser", action="store_true",
                        help="include Playwright for `metis web open --render` and install Chromium")
    parser.add_argument("--claude-code", action="store_true",
                        help="copy integrations/claude-code into .claude and re-point local settings to this path")
    parser.add_argument("--sandbox", action="store_true",
                        help="build the sandbox image if this machine's container engine lacks it")
    parser.add_argument("--rebuild-sandbox", action="store_true", help="always rebuild the sandbox image")
    parser.add_argument("--all", action="store_true", help="--dev --claude-code --sandbox")
    args = parser.parse_args()
    if args.all:
        args.dev = args.claude_code = args.sandbox = True
    if os.name != "posix":
        raise SystemExit("Use Linux/macOS, or run this repository inside WSL on Windows.")
    if sys.version_info < (3, 8):  # noqa: UP036 -- this bootstrap precedes the project Python install.
        raise SystemExit("Python 3.8+ is required to bootstrap uv; uv will provide Python 3.12.")
    root = ROOT
    if environment_is_stale(root):
        print("METIS: .venv was created at another location; recreating it here.", flush=True)
        shutil.rmtree(root / ".venv")
    executable = bootstrap_uv(root)
    environment = os.environ.copy()
    environment.setdefault("UV_CACHE_DIR", str(root / ".metis-cache/uv"))
    environment.setdefault("UV_SYSTEM_CERTS", "true")
    command = [executable, "sync", "--locked", "--python", "3.12"]
    if args.dev:
        command.extend(["--extra", "dev"])
    if args.browser:
        command.extend(["--extra", "browser"])
    subprocess.run(command, cwd=root, env=environment, check=True)
    if args.browser:
        subprocess.run([str(root / ".venv/bin/playwright"), "install", "chromium"], cwd=root, check=True)
    state = root / ".metis-state"
    state.mkdir(exist_ok=True, mode=0o700)
    # Opening the state migrates older absolute artifact paths to relocatable ones.
    subprocess.run([str(root / ".venv/bin/python"), "-c",
                    ("from pathlib import Path; from metis.core.codex_session import CodexSession; "
                    "CodexSession(Path('.metis-state/metis.sqlite'))")], cwd=root, check=True)
    if args.claude_code:
        print("METIS: Claude Code integration: " + json.dumps(configure_claude_code(root), ensure_ascii=False),
              flush=True)
    if args.sandbox or args.rebuild_sandbox:
        ensure_sandbox(root, args.rebuild_sandbox)
    subprocess.run([str(root / ".venv/bin/python"), "-m", "metis.cli", "doctor"], cwd=root, check=True)
    print("METIS is ready in this checkout. Start with ./start (or ./start --agent claude).")


if __name__ == "__main__":
    main()

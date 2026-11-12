#!/usr/bin/env python3
"""Install only project-local tooling and locked dependencies for Codex CLI use."""
import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev", action="store_true", help="include the test/type/lint tools")
    args = parser.parse_args()
    if os.name != "posix":
        raise SystemExit("Use Linux/macOS, or run this repository inside WSL on Windows.")
    if sys.version_info < (3, 8):  # noqa: UP036 -- this bootstrap precedes the project Python install.
        raise SystemExit("Python 3.8+ is required to bootstrap uv; uv will provide Python 3.12.")
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("uv")
    if not executable:
        bootstrap = root / ".metis-bootstrap"
        python = bootstrap / "bin/python"
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(bootstrap)
        subprocess.run([str(python), "-m", "pip", "install", "uv==0.13.5"], cwd=root, check=True)
        executable = str(bootstrap / "bin/uv")
    environment = os.environ.copy()
    environment.setdefault("UV_CACHE_DIR", str(root / ".metis-cache/uv"))
    environment.setdefault("UV_SYSTEM_CERTS", "true")
    command = [executable, "sync", "--locked", "--python", "3.12"]
    if args.dev:
        command.extend(["--extra", "dev"])
    subprocess.run(command, cwd=root, env=environment, check=True)
    state = root / ".metis-state"
    state.mkdir(exist_ok=True, mode=0o700)
    subprocess.run([str(root / ".venv/bin/python"), "-m", "metis.cli", "doctor"], cwd=root, check=True)
    print("METIS is ready in this checkout. Start Codex here and provide the CTF problem URL or files.")


if __name__ == "__main__":
    main()

"""Offline checks for the pinned Issue #6 CodexCLI runtime."""

import argparse
import hashlib
import json
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from metis.core.codex_isolation import (
    AllowlistProxy,
    isolation_backend,
    native_codex,
    self_test,
    wrap,
)
from metis.core.codex_specialist import DISABLED_FEATURES, CodexCLI, CodexTurn

VERSION = "0.169.0"
NATIVE_SHA256 = "739cda86e15d30a6e2b40cf8dcbbfb988aaf48b305b27065573bb8e9fd41d002"


class PilotCodex(CodexCLI):
    """Frozen runtime settings for a later explicitly authorized pilot."""

    def check(self) -> str:
        binary, _package = native_codex(self.executable)
        with open(binary, "rb") as stream:
            binary_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        if binary_hash != NATIVE_SHA256 or isolation_backend() != "seatbelt":
            raise RuntimeError("Issue #6 requires the pinned native Codex and Seatbelt")
        version = super().check()
        if version != VERSION or self.isolation != "required" or self.allow_untested:
            raise RuntimeError("Issue #6 Codex runtime configuration mismatch")
        if self.protected is not None or self.cyber_program is not None:
            raise RuntimeError("Issue #6 requires the default protected roots and standard runtime access")
        return version

    def run(self, prompt: str, *, model: str | None, timeout: float,
            should_stop: Callable[[], bool] | None = None,
            images: list[tuple[str, bytes]] | None = None,
            output_schema: dict[str, Any] | None = None) -> CodexTurn:
        raise RuntimeError("pilot Codex execution is disabled; offline preflight only")

    def argv(self, workdir: Path, schema: Path, output: Path, model: str | None) -> list[str]:
        command = super().argv(workdir, schema, output, model)
        return [*command[:-1], "-c", 'model_reasoning_effort="low"', command[-1]]


def offline_preflight(executable: Path) -> dict[str, Any]:
    cli = PilotCodex(str(executable))
    version = cli.check()
    with tempfile.TemporaryDirectory(prefix="metis-build-preflight-") as temporary, AllowlistProxy() as proxy:
        root = Path(temporary).resolve()
        private = root / "controller"
        private.mkdir(mode=0o700)
        sentinel = private / "private-canary"
        sentinel.write_text("private")
        guards = self_test(sentinel, protected=cli.protected_roots(root))
        if not guards.get("passed"):
            raise RuntimeError("offline Seatbelt controls failed")
        turn = root / "turn"
        turn.mkdir(mode=0o700)
        schema, output = turn / "schema.json", turn / "output.json"
        flags = cli.argv(turn, schema, output, "gpt-6.1-sol")
        disabled = {flags[i + 1] for i, flag in enumerate(flags[:-1]) if flag == "--disable"}
        if "shell_tool" not in disabled or disabled != set(DISABLED_FEATURES).intersection(cli.features):
            raise RuntimeError("Codex tool disables do not match the discovered runtime")
        for flag in ("--ignore-user-config", "--ignore-rules", 'web_search="disabled"',
                     "agents.enabled=false", 'model_reasoning_effort="low"'):
            if flag not in flags:
                raise RuntimeError("Issue #6 Codex argument guard missing")
        binary, package = native_codex(str(executable))
        command, env = wrap(
            "seatbelt", turn_dir=turn, argv=[binary, "--version"], env={"PATH": "/usr/bin:/bin"},
            proxy=proxy, readable=[package], protected=cli.protected_roots(root),
            workdir=turn, executable=Path(binary),
        )
        probe = subprocess.run(command, cwd=turn, env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, timeout=15, check=False)
        if probe.returncode or probe.stdout.decode().strip() != f"codex-cli {version}":
            raise RuntimeError("pinned binary failed under Seatbelt")
    return {"version": version, "native_sha256": NATIVE_SHA256, "backend": "seatbelt",
            "shell_tool_disabled": True, "disabled_features": sorted(disabled),
            "seatbelt_guards": guards, "network_model_calls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(offline_preflight(args.executable), sort_keys=True))


if __name__ == "__main__":
    main()

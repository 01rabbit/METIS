"""Offline checks for the pinned Issue #6 CodexCLI runtime."""

import argparse
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

from ._issue6_canary_process import NATIVE_SHA256, NATIVE_SIZE, stage_native
from ._issue6_canary_process import NATIVE_VERSION as VERSION


class PilotCodex(CodexCLI):
    """Render offline-only flags without probing an executable in the constructor."""

    def __init__(self, executable: Path, features: set[str]):
        super().__init__(str(executable), features=features, isolation="required")

    def check(self) -> str:
        raise RuntimeError("use the sandboxed offline preflight to check the pilot runtime")

    def run(self, prompt: str, *, model: str | None, timeout: float,
            should_stop: Callable[[], bool] | None = None,
            images: list[tuple[str, bytes]] | None = None,
            output_schema: dict[str, Any] | None = None) -> CodexTurn:
        raise RuntimeError("pilot Codex execution is disabled; offline preflight only")

    def argv(self, workdir: Path, schema: Path, output: Path, model: str | None) -> list[str]:
        command = super().argv(workdir, schema, output, model)
        return [*command[:-1], "-c", 'model_reasoning_effort="low"', command[-1]]


def _stage_pinned_native(executable: Path, destination: Path) -> None:
    resolved, _ = native_codex(str(executable))
    stage_native(Path(resolved), destination, size=NATIVE_SIZE, digest=NATIVE_SHA256)


def _probe(binary: Path, turn: Path, proxy: AllowlistProxy, protected: list[Path], *args: str) -> str:
    command, env = wrap(
        "seatbelt", turn_dir=turn, argv=[str(binary), *args],
        env={"PATH": "/usr/bin:/bin", "HOME": str(turn), "CODEX_HOME": str(turn), "LANG": "C"},
        proxy=proxy, readable=[binary], protected=protected, workdir=turn, executable=binary,
    )
    result = subprocess.run(command, cwd=turn, env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=15, check=False)
    if result.returncode:
        raise RuntimeError("pinned native Codex probe failed under Seatbelt")
    return result.stdout.decode()


def offline_preflight(executable: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="metis-build-preflight-") as temporary:
        root = Path(temporary).resolve()
        binary = root / "pinned-codex"
        _stage_pinned_native(executable, binary)
        if isolation_backend() != "seatbelt":
            raise RuntimeError("Issue #6 requires Seatbelt")
        turn = root / "turn"
        turn.mkdir(mode=0o700)
        protected = [path for path in (Path.home(), Path("/private/tmp"), Path("/private/var/tmp"),
                                      Path("/Volumes"), root.parent, root) if path.exists()]
        with AllowlistProxy(hosts=()) as proxy:
            version = _probe(binary, turn, proxy, protected, "--version").strip()
            if version != f"codex-cli {VERSION}":
                raise RuntimeError("Issue #6 native Codex version mismatch")
            feature_text = _probe(binary, turn, proxy, protected, "features", "list")
        features = {line.split()[0] for line in feature_text.splitlines() if line.strip()}
        cli = PilotCodex(binary, features)
        private = root / "controller"
        private.mkdir(mode=0o700)
        sentinel = private / "private-canary"
        sentinel.write_text("private")
        guards = self_test(sentinel, protected=protected)
        if not guards.get("passed"):
            raise RuntimeError("offline Seatbelt controls failed")
        schema, output = turn / "schema.json", turn / "output.json"
        flags = cli.argv(turn, schema, output, "gpt-6.1-sol")
        disabled = {flags[i + 1] for i, flag in enumerate(flags[:-1]) if flag == "--disable"}
        if "shell_tool" not in disabled or disabled != set(DISABLED_FEATURES).intersection(cli.features):
            raise RuntimeError("Codex tool disables do not match the discovered runtime")
        for flag in ("--ignore-user-config", "--ignore-rules", 'web_search="disabled"',
                     "agents.enabled=false", 'model_reasoning_effort="low"'):
            if flag not in flags:
                raise RuntimeError("Issue #6 Codex argument guard missing")
    return {"version": VERSION, "native_sha256": NATIVE_SHA256, "backend": "seatbelt",
            "shell_tool_disabled": True, "disabled_features": sorted(disabled),
            "seatbelt_guards": guards, "network_model_calls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(offline_preflight(args.executable), sort_keys=True))


if __name__ == "__main__":
    main()

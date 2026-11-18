#!/usr/bin/env python3
"""Build and run a disposable isolated protocol lab; retain only private artifacts."""

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED_SECRET_FILES = (
    "client_key",
    "ssh_host_key",
    "ca.key",
    "desktop.key",
    "vpn.key",
    "client.key",
    "tls.key",
    "desktop.password",
    "vnc.pass",
)


def cleanup_generated_secrets(state, shutdown_returncode):
    """Remove only known disposable credentials after confirmed Compose shutdown."""
    receipt = {"status": "retained-shutdown-unconfirmed", "removed": [], "errors": []}
    if type(shutdown_returncode) is not int or shutdown_returncode != 0:
        return receipt
    try:
        directory = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        receipt.update(status="failed", errors=[{"file": None, "reason": type(exc).__name__}])
        return receipt
    try:
        for name in GENERATED_SECRET_FILES:
            try:
                # dir_fd pins the artifact directory; unlink never follows a leaf symlink.
                os.unlink(name, dir_fd=directory)
                receipt["removed"].append(name)
            except FileNotFoundError:
                pass
            except OSError as exc:
                receipt["errors"].append({"file": name, "reason": type(exc).__name__})
        try:
            os.fsync(directory)
        except OSError as exc:
            receipt["errors"].append({"file": None, "reason": type(exc).__name__})
    finally:
        os.close(directory)
    receipt["status"] = "failed" if receipt["errors"] else "complete"
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    state = ROOT / ".metis-state/connection-lab" / uuid.uuid4().hex[:12]
    state.mkdir(parents=True)
    env = dict(os.environ, METIS_LAB_STATE=str(state))
    compose = [
        "docker",
        "compose",
        "-p",
        "metis-lab-" + state.name,
        "-f",
        str(ROOT / "tests/blue_lab/compose.yaml"),
    ]
    client_name = "metis-lab-" + state.name + "-results"

    def run(cmd, **kwargs):
        return subprocess.run(
            cmd, cwd=str(ROOT), env=env, check=True, timeout=kwargs.pop("timeout", 120), **kwargs
        )

    print("Private test artifacts: " + str(state), flush=True)
    status = 0
    try:
        if not args.skip_build:
            with (state / "build.log").open("w") as log:
                run(
                    [
                        "docker",
                        "build",
                        "-t",
                        "metis-connection-lab:local",
                        "-f",
                        "tests/blue_lab/Dockerfile",
                        ".",
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=600,
                )
        run(compose + ["run", "--rm", "-e", "METIS_LAB_ROLE=init", "desktop"])
        run(compose + ["up", "-d", "desktop", "vpn"])
        run(compose + ["run", "--name", client_name, "--no-deps", "client"], timeout=240)
    except (subprocess.SubprocessError, RuntimeError, KeyboardInterrupt) as exc:
        print(str(exc), file=sys.stderr)
        status = 1
    finally:
        cleanup = {"at": datetime.now(UTC).isoformat()}
        try:
            subprocess.run(
                ["docker", "cp", client_name + ":/lab/.", str(state)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            subprocess.run(
                ["docker", "rm", "-f", client_name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            with (state / "compose.log").open("w") as log:
                subprocess.run(
                    compose + ["logs", "--no-color"],
                    check=False,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=30,
                )
        except subprocess.TimeoutExpired as exc:
            cleanup["artifact_error"] = str(exc)
            status = 1
        try:
            cleanup["returncode"] = subprocess.run(
                compose + ["down", "--volumes", "--remove-orphans"], check=False, env=env, timeout=60
            ).returncode
        except subprocess.TimeoutExpired:
            cleanup["returncode"] = 124
        except OSError:
            cleanup["returncode"] = None
            cleanup["error"] = "shutdown-command-unavailable"
        cleanup["generated_secrets"] = cleanup_generated_secrets(state, cleanup["returncode"])
        (state / "cleanup.json").write_text(json.dumps(cleanup) + "\n")
        if cleanup["returncode"] != 0:
            print("Cleanup failed; run docker compose down for the printed project.", file=sys.stderr)
            status = 1
        if cleanup["generated_secrets"]["status"] == "failed":
            print("Generated secret-file cleanup failed; inspect private cleanup.json.", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())

"""Check the process-wide cap with an upstream GGUF text fixture."""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.client import RemoteDisconnected
from pathlib import Path
from typing import BinaryIO
from urllib.error import URLError
from urllib.request import Request, urlopen

FIXTURE_SHA256 = "270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d"
STARTUP_PROBE_TOKENS = 2
PROMPT = {"prompt": "One day, a rabbit ran down the road.", "n_predict": 1, "cache_prompt": False}


def request(base_url: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    http_request = Request(base_url + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(http_request, timeout=10) as response:
        return json.load(response)


@contextmanager
def running_server(
    binary: Path, model: Path, tokens: int
) -> Iterator[tuple[str, subprocess.Popen[bytes], BinaryIO]]:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    command = [str(binary), "--metis-work-budget", str(tokens), "--model", str(model), "--port", str(port)]
    with (
        tempfile.TemporaryFile() as log,
        subprocess.Popen(command, env={"PATH": os.defpath}, stdout=log, stderr=log) as server,
    ):
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and server.poll() is None:
                try:
                    if request(base_url, "/health")["status"] == "ok":
                        break
                except URLError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("server did not become ready")
            yield base_url, server, log
        except Exception:
            log.seek(0)
            print(log.read().decode(errors="replace"))
            raise
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()


def expect_denial(base_url: str, server: subprocess.Popen[bytes], log: BinaryIO) -> None:
    try:
        request(base_url, "/completion", PROMPT)
    except (RemoteDisconnected, ConnectionResetError):
        pass
    else:
        raise AssertionError("the completion survived budget denial")
    assert server.wait(timeout=5) == 75
    log.seek(0)
    assert b"METIS token work budget denied" in log.read()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("model", type=Path)
    args = parser.parse_args()
    binary, model = args.binary.resolve(), args.model.resolve()
    with model.open("rb") as weights:
        assert hashlib.file_digest(weights, "sha256").hexdigest() == FIXTURE_SHA256

    with running_server(binary, model, 4096) as (base_url, _, _log):
        prompt_tokens = request(base_url, "/completion", PROMPT)["tokens_evaluated"]
        assert prompt_tokens > 1

    # common_context_can_seq_rm evaluates two positions before readiness.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    startup = subprocess.run(
        [str(binary), "--metis-work-budget", "1", "--model", str(model), "--port", str(port)],
        env={"PATH": os.defpath},
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert startup.returncode == 75
    assert b"METIS token work budget denied, requested=2" in startup.stderr
    assert b"model loaded" not in startup.stderr

    exact_cap = STARTUP_PROBE_TOKENS + prompt_tokens
    with running_server(binary, model, exact_cap) as (base_url, server, log):
        assert request(base_url, "/tokenize", {"content": PROMPT["prompt"]})["tokens"]
        completion = request(base_url, "/completion", PROMPT)
        assert completion["tokens_evaluated"] == prompt_tokens
        expect_denial(base_url, server, log)

    with running_server(binary, model, exact_cap - 1) as (base_url, server, log):
        expect_denial(base_url, server, log)

    print(f"Exact cap completed at {exact_cap} tokens ({STARTUP_PROBE_TOKENS} startup + {prompt_tokens} prompt).")
    print("Startup, repeated work, and a batch above the remaining cap exited with 75.")


if __name__ == "__main__":
    main()

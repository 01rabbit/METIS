"""Check the native cap and terminal receipt with an upstream GGUF fixture."""

import argparse
import hashlib
import http.client
import json
import os
import secrets
import signal
import socket
import subprocess
import tempfile
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from typing import BinaryIO, Literal

FIXTURE_SHA256 = "270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d"
STARTUP_PROBE_TOKENS = 2
PROMPT = {"prompt": "One day, a rabbit ran down the road.", "n_predict": 1, "cache_prompt": False}


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: Path, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self.path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(self.path))


@dataclass
class Server:
    process: subprocess.Popen[bytes]
    log: BinaryIO
    receipt: BinaryIO
    socket_path: Path
    nonce: str
    cap: int

    def logs(self) -> bytes:
        self.log.seek(0)
        return self.log.read()

    def request(self, path: str, payload: dict | None = None, *, timeout: float = 5) -> dict:
        data = None if payload is None else json.dumps(payload).encode()
        with closing(UnixConnection(self.socket_path, timeout)) as connection:
            connection.request(
                "GET" if payload is None else "POST", path, body=data,
                headers={"Content-Type": "application/json"},
            )
            with connection.getresponse() as response:
                return json.loads(response.read())

    def expect_outcome(self, status: int, charged: int, reason: str) -> None:
        assert self.process.wait(timeout=5) == status
        raw = self.receipt.read(257)
        assert len(raw) <= 256 and raw.count(b"\n") == 1 and raw.endswith(b"\n")
        record = json.loads(raw)
        assert record == {
            "version": 1, "nonce": self.nonce, "cap": self.cap, "charged": charged, "reason": reason,
        }

    def expect_no_receipt(self, status: int) -> None:
        assert self.process.wait(timeout=5) == status
        assert self.receipt.read(257) == b""


@contextmanager
def running_server(
    binary: Path,
    model: Path,
    tokens: int,
    *,
    ready: bool = True,
    private: bool = True,
    stale: Literal["socket", "symlink"] | None = None,
    abandoned_pipe: bool = False,
    socket_name: str = "model.sock",
) -> Iterator[Server]:
    with tempfile.TemporaryDirectory(prefix="m8-", dir="/tmp") as root, tempfile.TemporaryFile() as log:
        private_dir = Path(root).resolve()
        socket_path = private_dir / socket_name
        if not private:
            private_dir.chmod(0o755)
        if stale == "socket":
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale_listener:
                stale_listener.bind(str(socket_path))
        elif stale == "symlink":
            socket_path.symlink_to(private_dir / "missing.sock")

        # A key configured this way makes /completion reject anonymous clients
        # on the stock parser. The dedicated launch profile ignores the file.
        config = private_dir / "llama.cpp" / "config.ini"
        config.parent.mkdir()
        config.write_text("api-key = local-config-test\n")
        environment = {"PATH": os.defpath, "XDG_CONFIG_HOME": str(private_dir)}
        nonce = secrets.token_hex(16)
        read_fd, write_fd = os.pipe()
        with os.fdopen(read_fd, "rb") as receipt:
            if abandoned_pipe:
                receipt.close()
            command = [
                str(binary), "--metis-work-budget", str(tokens), "--model", str(model),
                "--socket", str(socket_path), "--metis-receipt-fd", str(write_fd),
                "--metis-launch-nonce", nonce,
            ]
            try:
                process = subprocess.Popen(
                    command, env=environment, stdout=log, stderr=log, pass_fds=(write_fd,),
                )
            finally:
                os.close(write_fd)
            with process:
                server = Server(process, log, receipt, socket_path, nonce, tokens)
                try:
                    if ready:
                        expect_ready(server)
                    yield server
                except Exception:
                    print(server.logs().decode(errors="replace"))
                    raise
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()


def expect_ready(server: Server) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and server.process.poll() is None:
        try:
            if server.request("/health", timeout=0.5).get("status") == "ok":
                return
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(0.1)
    raise RuntimeError("server did not become ready")


def expect_denial(server: Server, prompt: dict, requested: int, charged: int) -> None:
    try:
        server.request("/completion", prompt)
    except (http.client.RemoteDisconnected, ConnectionResetError):
        pass
    else:
        raise AssertionError("the completion survived budget denial")
    server.expect_outcome(75, charged, "cap_denied")
    denial = f"METIS token work budget denied, requested={requested}\n"
    assert denial.encode() in server.logs()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("model", type=Path)
    args = parser.parse_args()
    binary, model = args.binary.resolve(), args.model.resolve()
    with model.open("rb") as weights:
        assert hashlib.file_digest(weights, "sha256").hexdigest() == FIXTURE_SHA256

    with running_server(binary, model, 4096) as server:
        prompt_tokens = server.request("/completion", PROMPT)["tokens_evaluated"]
        assert prompt_tokens > 1
        server.process.terminate()
        server.expect_outcome(0, STARTUP_PROBE_TOKENS + prompt_tokens, "shutdown")

    with running_server(binary, model, 1, ready=False) as server:
        server.expect_outcome(75, 0, "cap_denied")
        assert b"METIS token work budget denied, requested=2" in server.logs()
        assert b"model loaded" not in server.logs()

    exact_cap = STARTUP_PROBE_TOKENS + prompt_tokens
    with running_server(binary, model, exact_cap) as server:
        assert server.request("/tokenize", {"content": PROMPT["prompt"]})["tokens"]
        assert server.request("/completion", PROMPT)["tokens_evaluated"] == prompt_tokens
        expect_denial(server, PROMPT, prompt_tokens, exact_cap)

    with running_server(binary, model, exact_cap - 1) as server:
        expect_denial(server, PROMPT, prompt_tokens, STARTUP_PROBE_TOKENS)

    with running_server(binary, model, exact_cap) as server:
        start = Barrier(3)

        def concurrent_completion() -> dict | Exception:
            start.wait(timeout=5)
            try:
                return server.request("/completion", PROMPT, timeout=15)
            except (OSError, http.client.HTTPException, TimeoutError, ValueError) as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(concurrent_completion)
            second = workers.submit(concurrent_completion)
            start.wait(timeout=5)
            outcomes = [first.result(timeout=20), second.result(timeout=20)]

        successful = [result for result in outcomes if isinstance(result, dict)]
        assert all(
            result.get("tokens_evaluated") == prompt_tokens
            and result.get("tokens_predicted") == 1
            for result in successful
        ), outcomes
        assert len(successful) in (0, 1), outcomes
        server.expect_outcome(75, exact_cap, "cap_denied")
        assert f"METIS token work budget denied, requested={prompt_tokens}\n".encode() in server.logs()

    longer_completion = {**PROMPT, "n_predict": 3, "temperature": 0, "ignore_eos": True}
    with running_server(binary, model, exact_cap + 2) as server:
        assert server.request("/completion", longer_completion)["tokens_predicted"] == 3
        server.process.terminate()
        server.expect_outcome(0, exact_cap + 2, "shutdown")

    with running_server(binary, model, exact_cap + 1) as server:
        expect_denial(server, longer_completion, 1, exact_cap + 1)

    with running_server(binary, model, exact_cap, ready=False, private=False) as server:
        server.expect_no_receipt(2)

    with running_server(binary, model, exact_cap, ready=False, stale="socket") as server:
        server.expect_no_receipt(2)

    with running_server(binary, model, exact_cap, ready=False, stale="symlink") as server:
        server.expect_no_receipt(2)

    with running_server(binary, model, exact_cap, socket_name='model.sock,127.0.0.1,"tail".sock') as server:
        assert server.request("/completion", PROMPT)["tokens_evaluated"] == prompt_tokens
        server.process.terminate()
        server.expect_outcome(0, exact_cap, "shutdown")
        addresses = [
            line.partition(b"listening on ")[2]
            for line in server.logs().splitlines()
            if b"listening on " in line
        ]
        assert addresses == [f"unix://{server.socket_path}".encode()]

    with running_server(binary, model, 1, ready=False, abandoned_pipe=True) as server:
        assert server.process.wait(timeout=5) == 74

    with running_server(binary, model, exact_cap) as server:
        server.process.send_signal(signal.SIGSTOP)
        _, stopped = os.waitpid(server.process.pid, os.WUNTRACED)
        assert os.WIFSTOPPED(stopped)
        try:
            server.request("/completion", PROMPT, timeout=0.1)
        except TimeoutError:
            server.process.kill()
        else:
            raise AssertionError("the stopped server did not time out")
        server.expect_no_receipt(-signal.SIGKILL)

    print(f"Verified work receipts on Unix socket shutdown and denial at prompt/decode cap {exact_cap}.")
    print("Verified simultaneous client arrivals at cap; denial receipt charged the full cap.")
    print("Verified literal comma path, single Unix listener, and stale/symlink/public paths refused.")
    print("Verified broken receipt pipe refusal and missing receipt after a deadline and SIGKILL.")


if __name__ == "__main__":
    main()

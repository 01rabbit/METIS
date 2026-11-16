import json
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from metis.cli import main
from metis.core.codex_session import CodexSession
from metis.core.ctf_remote import Exchange, RemoteWorkflow, Step


@pytest.fixture
def quiz_server():
    """A tiny CTF-style service: answer three additions, receive a token."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    stop = threading.Event()

    def serve(connection):
        with connection:
            file = connection.makefile("rwb", buffering=0)
            file.write(b"Welcome to the quiz\n")
            for left, right in ((2, 3), (10, 20), (7, 8)):
                file.write(f"{left} + {right} = ?\n".encode())
                answer = file.readline().strip()
                if answer != str(left + right).encode():
                    file.write(b"wrong\n")
                    return
            file.write(b"QUIZ_TOKEN_mock\n")

    def loop():
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            threading.Thread(target=serve, args=(connection,), daemon=True).start()

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    yield listener.getsockname()[1]
    stop.set()
    thread.join()
    listener.close()


def _run(tmp_path: Path, description: str = "Connect with nc 127.0.0.1 1337") -> tuple[Path, str]:
    database = tmp_path / "state" / "metis.sqlite"
    note = tmp_path / "note.txt"
    note.write_text("statement copy")
    context = CodexSession(database).intake(title="Quiz", description=description, paths=[note],
                                            categories=["misc"])
    return database, context["run_id"]


def test_suggestions_are_not_grants(tmp_path):
    database, run_id = _run(tmp_path, "Try nc chall.example.org 31337 or nc --ssl tls.example.org 443")
    remote = RemoteWorkflow(database)
    suggestions = remote.suggest(run_id)["candidates"]
    assert {"host": "chall.example.org", "port": 31337, "tls": False} in suggestions
    assert {"host": "tls.example.org", "port": 443, "tls": True} in suggestions
    with pytest.raises(ValueError, match="not granted"):
        remote.exchange(run_id, 0, Exchange(steps=[Step(recv_line=True)]))
    assert CodexSession(database).context(run_id)["network_tools"] == []


def test_scripted_exchange_solves_quiz_and_records_artifact(tmp_path, quiz_server):
    database, run_id = _run(tmp_path)
    remote = RemoteWorkflow(database)
    grant = remote.grant(run_id, "127.0.0.1", quiz_server)
    assert grant["index"] == 0
    assert remote.grant(run_id, "127.0.0.1", quiz_server)["index"] == 0
    steps = [Step(recv_line=True), Step(recv_line=True), Step(send_line="5", recv_line=True),
             Step(send_line="30", recv_line=True), Step(send_line="15", recv_all=True, timeout=2)]
    result = remote.exchange(run_id, 0, Exchange(steps=steps))
    assert result["ok"] is True
    assert "QUIZ_TOKEN_mock" in result["steps"][-1]["received"]["text"]
    session = CodexSession(database)
    context = session.context(run_id)
    assert context["network_tools"][0]["port"] == quiz_server
    assert result["received_artifact"] in context["challenge"]["artifacts"]
    analysed = session.artifact(run_id, result["received_artifact"], "strings")
    assert analysed["ok"]
    # Evidence stores digests only, never the received token.
    events = json.dumps([event.model_dump(mode="json") for event in session.store.read(run_id)])
    assert "QUIZ_TOKEN_mock" not in events


def test_exchange_reports_unmet_receive_condition(tmp_path, quiz_server):
    database, run_id = _run(tmp_path)
    remote = RemoteWorkflow(database)
    remote.grant(run_id, "127.0.0.1", quiz_server)
    result = remote.exchange(run_id, 0, Exchange(steps=[Step(recv_until="never-sent", timeout=0.5)]))
    assert result["ok"] is False
    assert "receive condition" in result["error"]
    assert CodexSession(database).context(run_id)["status"] == "planning"


def test_solver_pipe_bridges_agent_code(tmp_path, quiz_server):
    database, run_id = _run(tmp_path)
    remote = RemoteWorkflow(database)
    remote.grant(run_id, "127.0.0.1", quiz_server)
    solver = tmp_path / "solver.py"
    solver.write_text(
        "import re, sys\n"
        "for line in sys.stdin:\n"
        "    m = re.match(r'(\\d+) \\+ (\\d+)', line)\n"
        "    if m:\n"
        "        print(int(m[1]) + int(m[2]), flush=True)\n"
        "    if 'TOKEN' in line:\n"
        "        break\n")
    result = remote.pipe(run_id, 0, [sys.executable, str(solver)], timeout=20)
    assert result["ok"] is True, result
    assert "QUIZ_TOKEN_mock" in result["received_tail"]["text"]


def test_pipe_refuses_challenge_artifacts_on_host(tmp_path, quiz_server):
    database, run_id = _run(tmp_path)
    remote = RemoteWorkflow(database)
    remote.grant(run_id, "127.0.0.1", quiz_server)
    root = CodexSession(database).artifact_root(run_id)
    assert root is not None
    target = next(root.iterdir())
    with pytest.raises(ValueError, match="sandbox"):
        remote.pipe(run_id, 0, [str(target)])


PROXY_VARIABLES = ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
                   "NO_PROXY", "no_proxy")


def _no_proxy(monkeypatch):
    for name in PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_hostname_resolving_private_is_rejected(tmp_path, monkeypatch):
    _no_proxy(monkeypatch)
    database, run_id = _run(tmp_path)
    remote = RemoteWorkflow(database)
    remote.grant(run_id, "internal.example.org", 4000)
    monkeypatch.setattr("socket.getaddrinfo",
                        lambda *args, **kwargs: [(0, 0, 0, "", ("10.0.0.5", 4000))])
    result = remote.exchange(run_id, 0, Exchange(steps=[Step(recv_line=True)]))
    assert result["ok"] is False and "private" in result["detail"]


def test_step_validation():
    with pytest.raises(ValueError):
        Step(send="a", send_line="b")
    with pytest.raises(ValueError):
        Step()
    with pytest.raises(ValueError):
        Step(send_hex="zz")


def test_cli_remote_flow(tmp_path, quiz_server, monkeypatch, capsys):
    database, run_id = _run(tmp_path)
    monkeypatch.setattr(sys, "argv", ["metis", "remote", "--database", str(database), "grant", run_id,
                                      "127.0.0.1", str(quiz_server)])
    assert main() == 0
    capsys.readouterr()
    script = tmp_path / "steps.json"
    script.write_text(json.dumps({"steps": [{"recv_line": True}, {"recv_line": True},
                                            {"send_line": "4", "recv_line": True}]}))
    monkeypatch.setattr(sys, "argv", ["metis", "remote", "--database", str(database), "exchange", run_id,
                                      "0", "--script", str(script)])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["steps"][-1]["received"]["text"] == "wrong\n"


def _relay(client, upstream):
    def pump(source, sink):
        try:
            while data := source.recv(65536):
                sink.sendall(data)
        except OSError:
            pass
        finally:
            try:
                sink.shutdown(socket.SHUT_WR)
            except OSError:
                pass
    threading.Thread(target=pump, args=(client, upstream), daemon=True).start()
    threading.Thread(target=pump, args=(upstream, client), daemon=True).start()


@pytest.fixture
def proxies(quiz_server):
    """Local SOCKS5 and HTTP CONNECT proxies that resolve 'quiz.metis.test' themselves."""
    seen = {"socks": [], "http": []}

    def resolve(host):
        if host != "quiz.metis.test":
            return None
        return ("127.0.0.1", quiz_server)

    def socks_serve(connection):
        def take(size):
            data = b""
            while len(data) < size:
                chunk = connection.recv(size - len(data))
                if not chunk:
                    raise OSError
                data += chunk
            return data
        try:
            _, count = take(2)
            take(count)
            connection.sendall(b"\x05\x00")
            _, command, _, kind = take(4)
            assert command == 1 and kind == 3
            host = take(take(1)[0]).decode()
            port = int.from_bytes(take(2), "big")
            seen["socks"].append((host, port))
            target = resolve(host)
            if target is None:
                connection.sendall(b"\x05\x02\x00\x01" + bytes(6))
                connection.close()
                return
            upstream = socket.create_connection(target)
            connection.sendall(b"\x05\x00\x00\x01" + bytes(6))
            _relay(connection, upstream)
        except (OSError, AssertionError):
            connection.close()

    def http_serve(connection):
        data = b""
        while b"\r\n\r\n" not in data:
            data += connection.recv(1)
        line = data.split(b"\r\n", 1)[0].decode()
        authority = line.split(" ")[1]
        host, port = authority.rsplit(":", 1)
        seen["http"].append((host, int(port)))
        target = resolve(host)
        if target is None:
            connection.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            connection.close()
            return
        upstream = socket.create_connection(target)
        connection.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        _relay(connection, upstream)

    listeners = {}
    threads = []
    stop = threading.Event()
    for name, handler in (("socks", socks_serve), ("http", http_serve)):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        listener.settimeout(0.2)
        listeners[name] = listener

        def loop(listener=listener, handler=handler):
            while not stop.is_set():
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    break
                threading.Thread(target=handler, args=(connection,), daemon=True).start()
        threads.append(threading.Thread(target=loop, daemon=True))
        threads[-1].start()
    yield {name: listener.getsockname()[1] for name, listener in listeners.items()}, seen
    stop.set()
    for thread in threads:
        thread.join()
    for listener in listeners.values():
        listener.close()


def _quiz_steps():
    return Exchange(steps=[Step(recv_line=True), Step(recv_line=True), Step(send_line="5", recv_line=True)])


@pytest.mark.parametrize("variable,kind", [("ALL_PROXY", "socks"), ("HTTPS_PROXY", "http")])
def test_exchange_tunnels_through_sandbox_proxy(tmp_path, proxies, monkeypatch, variable, kind):
    ports, seen = proxies
    _no_proxy(monkeypatch)
    scheme = "socks5h" if kind == "socks" else "http"
    monkeypatch.setenv(variable, f"{scheme}://127.0.0.1:{ports[kind]}")

    real_getaddrinfo = socket.getaddrinfo

    def no_local_dns(host, *args, **kwargs):
        # Inside the sandbox only the local proxy (a literal address) is reachable.
        if host not in {"127.0.0.1", "localhost"}:
            raise socket.gaierror("local DNS is unavailable inside the sandbox")
        return real_getaddrinfo(host, *args, **kwargs)
    monkeypatch.setattr("socket.getaddrinfo", no_local_dns)
    database, run_id = _run(tmp_path)
    remote = RemoteWorkflow(database)
    remote.grant(run_id, "quiz.metis.test", 31337)
    result = remote.exchange(run_id, 0, _quiz_steps())
    assert result["ok"] is True, result
    assert result["route"] == f"{'socks5' if kind == 'socks' else 'http'}://127.0.0.1:{ports[kind]}"
    assert seen[kind] == [("quiz.metis.test", 31337)]


def test_proxy_refusal_is_reported(tmp_path, proxies, monkeypatch):
    ports, _ = proxies
    _no_proxy(monkeypatch)
    monkeypatch.setenv("ALL_PROXY", f"socks5h://127.0.0.1:{ports['socks']}")
    database, run_id = _run(tmp_path)
    remote = RemoteWorkflow(database)
    remote.grant(run_id, "blocked.metis.test", 4000)
    result = remote.exchange(run_id, 0, _quiz_steps())
    assert result["ok"] is False and "not allowed by ruleset" in result["detail"]


def test_no_proxy_bypass(monkeypatch):
    from metis.core.ctf_proxy import proxy_for
    _no_proxy(monkeypatch)
    monkeypatch.setenv("ALL_PROXY", "socks5h://127.0.0.1:1080")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.0/8,.internal.test")
    assert proxy_for("127.0.0.1") is None
    assert proxy_for("svc.internal.test") is None
    assert proxy_for("ctfq.example.org").describe() == "socks5://127.0.0.1:1080"


def test_stdio_bridge_for_ssh_proxycommand(tmp_path, quiz_server):
    database, run_id = _run(tmp_path)
    RemoteWorkflow(database).grant(run_id, "127.0.0.1", quiz_server)
    completed = subprocess.run(
        [sys.executable, "-m", "metis.cli", "remote", "--database", str(database), "connect", run_id, "0"],
        input=b"5\n30\n15\n", capture_output=True, timeout=30, check=False)
    assert b"QUIZ_TOKEN_mock" in completed.stdout, completed.stderr


def test_endpoint_selectors_replace_and_revoke(tmp_path, quiz_server, monkeypatch, capsys):
    database, run_id = _run(tmp_path)
    remote = RemoteWorkflow(database)
    old = remote.grant(run_id, "127.0.0.1", 1)
    new = remote.grant(run_id, "127.0.0.1", quiz_server, replace=True)
    assert new["index"] == 1 and new["revoked"] == [old["index"]]
    assert remote.resolve(run_id, "latest") == 1
    assert remote.resolve(run_id, f"127.0.0.1:{quiz_server}") == 1
    with pytest.raises(ValueError, match="revoked"):
        remote._endpoint(run_id, remote.resolve(run_id, "0"))
    listed = remote.endpoints(run_id)["endpoints"]
    assert [(item["active"], item["latest"]) for item in listed] == [(False, False), (True, True)]
    script = tmp_path / "quiz.json"
    script.write_text(json.dumps({"steps": [{"recv_line": True}, {"recv_line": True},
                                            {"send_line": "5", "recv_line": True},
                                            {"send_line": "30", "recv_line": True},
                                            {"send_line": "15", "recv_all": True, "timeout": 2}]}))
    monkeypatch.setattr(sys, "argv", ["metis", "remote", "--database", str(database), "exchange", run_id, "latest",
                                      "--script", str(script)])
    assert main() == 0
    assert "QUIZ_TOKEN_mock" in capsys.readouterr().out
    assert remote.revoke(run_id, "latest")["revoked"] is True
    with pytest.raises(ValueError):
        remote.resolve(run_id, "latest")
    with pytest.raises(ValueError, match="host:port"):
        remote.resolve(run_id, "nonsense")
    # Re-granting a revoked endpoint reactivates it under the same index.
    assert remote.grant(run_id, "127.0.0.1", 1)["index"] == 0
    assert remote.resolve(run_id, "latest") == 0

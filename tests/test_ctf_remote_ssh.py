import json
import socket
import sys
import threading

import paramiko
import pytest

from metis.cli import main
from metis.core.codex_session import CodexSession
from metis.core.ctf_remote import RemoteWorkflow

FILES = {"/home/q4/flag.txt": b"SSH_FILE_TOKEN_mock\n"}


class StubSFTPHandle(paramiko.SFTPHandle):
    def __init__(self, data: bytes):
        super().__init__()
        self.data = data

    def read(self, offset, length):
        return self.data[offset:offset + length]


class StubSFTP(paramiko.SFTPServerInterface):
    def stat(self, path):
        if path not in FILES:
            return paramiko.SFTPServer.convert_errno(2)
        attributes = paramiko.SFTPAttributes()
        attributes.st_size = len(FILES[path])
        attributes.st_mode = 0o100644
        return attributes

    lstat = stat

    def open(self, path, flags, attr):
        if path not in FILES:
            return paramiko.SFTPServer.convert_errno(2)
        return StubSFTPHandle(FILES[path])


class Server(paramiko.ServerInterface):
    def __init__(self):
        self.command = None
        self.ready = threading.Event()

    def check_auth_password(self, username, password):
        return (paramiko.AUTH_SUCCESSFUL if (username, password) == ("q4", "public-statement-pass")
                else paramiko.AUTH_FAILED)

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel, command):
        self.command = command.decode()
        self.ready.set()
        return True


@pytest.fixture
def ssh_server():
    host_key = paramiko.Ed25519Key.generate() if hasattr(paramiko.Ed25519Key, "generate") else None
    if host_key is None:
        host_key = paramiko.RSAKey.generate(2048)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    listener.settimeout(0.2)
    stop = threading.Event()

    def handle(connection):
        transport = paramiko.Transport(connection)
        transport.add_server_key(host_key)
        transport.set_subsystem_handler("sftp", paramiko.SFTPServer, StubSFTP)
        server = Server()
        try:
            transport.start_server(server=server)
            channel = transport.accept(10)
            if channel is None:
                return
            if server.ready.wait(5):
                received = b""
                while not channel.eof_received:
                    chunk = channel.recv(1024)
                    if not chunk:
                        break
                    received += chunk
                if server.command == "id":
                    channel.sendall(b"uid=1004(q4) gid=1004(q4)\n")
                    channel.send_exit_status(0)
                elif server.command == "./q4":
                    channel.sendall(b"echo:" + received)
                    channel.sendall_stderr(b"warn\n")
                    channel.send_exit_status(3)
                channel.close()
            else:
                while transport.is_active():  # SFTP-only session
                    if stop.wait(0.05):
                        break
        except (paramiko.SSHException, EOFError, OSError):
            pass
        finally:
            transport.close()

    def loop():
        while not stop.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=handle, args=(connection,), daemon=True).start()

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    yield listener.getsockname()[1]
    stop.set()
    thread.join()
    listener.close()


def _run(tmp_path, port):
    database = tmp_path / "state" / "metis.sqlite"
    note = tmp_path / "note.txt"
    note.write_text("ssh -p PORT q4@host")
    run_id = CodexSession(database).intake(title="Villager", description="ssh", paths=[note])["run_id"]
    RemoteWorkflow(database).grant(run_id, "127.0.0.1", port)
    return database, run_id


def test_ssh_command_stdin_download_and_host_key_pinning(tmp_path, ssh_server):
    database, run_id = _run(tmp_path, ssh_server)
    remote = RemoteWorkflow(database)
    first = remote.ssh(run_id, 0, username="q4", password="public-statement-pass", command="id")
    assert first["ok"] is True, first
    assert first["stdout"]["text"].startswith("uid=1004(q4)")
    assert first["host_key"]["pinned"] is False
    second = remote.ssh(run_id, 0, username="q4", password="public-statement-pass", command="./q4",
                        stdin=b"%p%p\n")
    assert second["exit_status"] == 3 and second["ok"] is False
    assert second["stdout"]["text"] == "echo:%p%p\n" and second["stderr"]["text"] == "warn\n"
    assert second["host_key"]["pinned"] is True
    fetched = remote.ssh(run_id, 0, username="q4", password="public-statement-pass",
                         downloads=["/home/q4/flag.txt"])
    assert fetched["ok"] is True, fetched
    artifact = fetched["downloads"][0]["artifact"]
    session = CodexSession(database)
    assert artifact in session.context(run_id)["challenge"]["artifacts"]
    assert session.artifact(run_id, artifact, "strings")["ok"]
    events = json.dumps([event.model_dump(mode="json") for event in session.store.read(run_id)])
    assert "public-statement-pass" not in events and "SSH_FILE_TOKEN_mock" not in events


def test_ssh_rejects_bad_password_and_changed_host_key(tmp_path, ssh_server):
    database, run_id = _run(tmp_path, ssh_server)
    remote = RemoteWorkflow(database)
    failed = remote.ssh(run_id, 0, username="q4", password="wrong", command="id")
    assert failed["ok"] is False and failed["error"] == "SSH authentication failed"
    import sqlite3
    with sqlite3.connect(database) as db:
        db.execute("UPDATE remote_host_keys SET fingerprint='SHA256:other' WHERE run_id=?", (run_id,))
    changed = remote.ssh(run_id, 0, username="q4", password="public-statement-pass", command="id")
    assert changed["ok"] is False and "host key changed" in changed["error"]
    with pytest.raises(ValueError):
        remote.ssh(run_id, 0, username="q4; rm", password="x", command="id")


def test_cli_ssh_password_from_stdin(tmp_path, ssh_server, monkeypatch, capsys):
    database, run_id = _run(tmp_path, ssh_server)
    import io
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"public-statement-pass\n")))
    monkeypatch.setattr(sys, "argv", ["metis", "remote", "--database", str(database), "ssh", run_id, "0",
                                      "--user", "q4", "--command", "id", "--password-stdin"])
    assert main() == 0
    assert "uid=1004" in json.loads(capsys.readouterr().out)["stdout"]["text"]

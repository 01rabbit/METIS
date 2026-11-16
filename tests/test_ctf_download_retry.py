import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from metis.cli import main
from metis.core.codex_session import CodexSession
from metis.core.ctf_web import WebWorkflow

PAYLOAD = b"distribution-bytes-" * 100


@pytest.fixture
def flaky(monkeypatch, tmp_path):
    monkeypatch.setattr("urllib.request.getproxies", dict)
    monkeypatch.setattr("metis.core.ctf_web.time.sleep", lambda _s: None)
    state = {"task": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def do_GET(self):
            if self.path == "/problem":
                body = (b'<title>Flaky</title><p>Two files.</p><a href="/files/task.zip" download>a</a>'
                        b'<a href="/files/dead.zip" download>b</a>')
                status, length = 200, len(body)
            elif self.path == "/files/task.zip":
                state["task"] += 1
                # First attempt is truncated (connection closes before Content-Length is met).
                body = PAYLOAD if state["task"] > 1 else PAYLOAD[:50]
                status, length = 200, len(PAYLOAD)
            elif self.path == "/files/dead.zip":
                body, status, length = PAYLOAD[:10], 200, len(PAYLOAD)
            else:
                body, status, length = b"", 404, 0
            self.send_response(status)
            self.send_header("Content-Length", str(length))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", state, tmp_path / ".metis-state" / "metis.sqlite"
    server.shutdown()


def test_truncated_download_is_retried_and_persistent_failure_is_skipped(flaky, tmp_path):
    base, state, database = flaky
    result = WebWorkflow(database).open(base + "/problem")
    assert state["task"] == 2
    assert result["downloaded_files"] == 1
    [skipped] = result["skipped_files"]
    assert "dead.zip" in skipped["url"] and "IncompleteRead" in skipped["reason"]
    assert "add-file" in skipped["next"]
    run_id = result["context"]["run_id"]
    root = CodexSession(database).artifact_root(run_id)
    files = {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}
    assert [name for name in files if "task" in name] and PAYLOAD in files.values()
    assert not [name for name in files if "dead" in name]


def test_add_file_declares_browser_download(flaky, tmp_path, monkeypatch, capsys):
    base, _, database = flaky
    run_id = WebWorkflow(database).open(base + "/problem")["context"]["run_id"]
    manual = tmp_path / "dead.zip"
    manual.write_bytes(PAYLOAD)
    monkeypatch.setattr(sys, "argv", ["metis", "codex", "--database", str(database), "add-file", run_id,
                                      str(manual)])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["artifact"] == ".metis-added/dead.zip" and output["size"] == len(PAYLOAD)
    session = CodexSession(database)
    observed = session.artifact(run_id, ".metis-added/dead.zip", "overview")
    assert observed["ok"] is True
    again = session.add_file(run_id, manual)
    assert again["artifact"] == ".metis-added/dead-2.zip"
    with pytest.raises(ValueError):
        session.add_file(run_id, tmp_path)

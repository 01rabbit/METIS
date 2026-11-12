#!/usr/bin/env python3
"""Local CTFd-shaped rehearsal server. It never prints or exposes answer-store data."""
from __future__ import annotations

import argparse
import base64
import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    answers = {index: "FLAG_" + secrets.token_hex(16) for index in (1, 2)}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            return

        def send(self, payload, status=200, kind="application/json"):
            content = json.dumps(payload).encode() if kind == "application/json" else payload
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            if self.path == "/api/v1/challenges":
                return self.send({"success": True, "data": [
                    {"id": index, "name": f"Encoded Note {index}", "category": "crypto"}
                    for index in answers]})
            for index, answer in answers.items():
                if self.path == f"/api/v1/challenges/{index}":
                    return self.send({"success": True, "data": {
                        "id": index, "name": f"Encoded Note {index}", "category": "crypto",
                        "description": "The attachment is a Base64-encoded note. Submit only the token "
                                       "that begins with the uppercase word FLAG followed by an underscore. "
                                       "The explanatory prefix is not part of the answer.",
                        "files": [f"/files/{index}.txt"],
                    }})
                if self.path == f"/files/{index}.txt":
                    note = ("The recovered token is: " if index == 1 else "Answer token: ") + answer
                    return self.send(base64.b64encode(note.encode()), kind="text/plain")
            return self.send({"success": False, "message": "not found"}, 404)

        def do_POST(self):
            if self.path != "/api/v1/challenges/attempt":
                return self.send({"success": False}, 404)
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 131072:
                return self.send({"success": False}, 400)
            try:
                payload = json.loads(self.rfile.read(length))
                expected = answers[int(payload["challenge_id"])]
                candidate = payload["submission"]
                correct = isinstance(candidate, str) and hmac.compare_digest(candidate.encode(), expected.encode())
            except (ValueError, KeyError, TypeError):
                return self.send({"success": False}, 400)
            return self.send({"success": True, "data": {
                "status": "correct" if correct else "incorrect",
                "message": "Accepted" if correct else "Incorrect; submit only the requested token.",
            }})

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}", "adapter": "ctfd",
                      "challenge_ids": [1, 2], "mode": "local rehearsal, not a benchmark"}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

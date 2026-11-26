"""A stand-in CLIProxyAPI: the endpoints the gateway uses, behind the same keys.

Run as `python subscription_gateway_fake.py --config <path>`; it reads the
port and keys the supervisor wrote, like the real binary does.
"""

import gzip
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

config = yaml.safe_load(Path(sys.argv[2]).read_text())
CLIENT = config["access"]["api-keys"][0]
MANAGEMENT = config["management"]["secret-key"]
PREFIXES: dict[str, str] = {}
assert config["server"]["host"] == "127.0.0.1"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return None

    def _send(self, status: int, body: object) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self, key: str) -> bool:
        if self.headers.get("Authorization") != f"Bearer {key}":
            self._send(401, {"error": "unauthorized"})
            return False
        return True

    def _route(self, method: str) -> None:
        url = urlsplit(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"null") if length else None
        if url.path.startswith("/v1/"):
            if not self._authorized(CLIENT):
                return
            if url.path == "/v1/models":
                self._send(200, {"data": [{"id": "gemini-test", "port": config["server"]["port"]}]})
                return
            if body and body.get("model") == "compressed-test":
                data = gzip.compress('data: {"text":"Cześć"}\n\ndata: [DONE]\n\n'.encode())
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for word in ("Hello", " from", f" {body['model']}"):
                chunk = {"choices": [{"delta": {"content": word}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            return
        if not self._authorized(MANAGEMENT):
            return
        path = url.path.removeprefix("/v8/management")
        if path == "/oauth/auth-url":
            if query.get("provider") == "xai":
                self._send(200, ["not", "an", "object"])
                return
            if query.get("provider") == "broken":
                self._send(500, {"error": "boom"})
                return
            self._send(
                200,
                {
                    "status": "ok",
                    "url": f"https://login.example/{query['provider']}",
                    "state": "state-1",
                    "flow": "device",
                    "user_code": "CODE-1",
                    "internal": "never forwarded",
                },
            )
        elif path == "/oauth/status":
            if query.get("state") == "odd":
                self._send(200, ["odd"])
                return
            self._send(200, {"status": "ok" if query.get("state") == "state-1" else "wait"})
        elif path == "/oauth/callback":
            self._send(200 if body and body.get("state") == "state-1" else 400, {"status": "ok"})
        elif path == "/oauth/session" and method == "DELETE":
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
        elif path == "/credentials/fields" and method == "PATCH":
            PREFIXES[body["name"]] = body["prefix"]
            self._send(200, {"status": "ok"})
        elif path == "/credentials/models":
            self._send(
                200,
                {
                    "models": [
                        {
                            "id": (PREFIXES.get(query.get("name", ""), "") + "/").lstrip("/")
                            + "claude-via-google"
                        }
                    ]
                }
                if query.get("name") == "antigravity-me.json"
                else {"models": "invalid"},
            )
        elif path == "/credentials" and method == "GET":
            self._send(
                200,
                {
                    "files": [
                        {
                            "name": "antigravity-me.json",
                            "provider": "antigravity",
                            "email": "me@example.com",
                            "status": "active",
                            "access_token": "must-not-leave",
                        },
                        "not-a-row",
                    ]
                },
            )
        elif path == "/credentials" and method == "DELETE":
            self._send(200, {"deleted": query.get("name")})
        else:
            self._send(404, {"error": "unknown"})

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def do_PATCH(self) -> None:
        self._route("PATCH")

    def do_DELETE(self) -> None:
        self._route("DELETE")


ThreadingHTTPServer(("127.0.0.1", config["server"]["port"]), Handler).serve_forever()

"""Deterministic local OpenAI Chat Completions fixture; never a production model."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

ANSWER = "AgenticOS smoke check passed."


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 1024 * 1024:
            self.send_error(413)
            return
        self.rfile.read(length)
        body = json.dumps(
            {
                "id": "smoke-completion",
                "object": "chat.completion",
                "created": 0,
                "model": "smoke",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": ANSWER},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # noqa: S104 - container-only fixture, no host port

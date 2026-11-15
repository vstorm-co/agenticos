"""Deterministic OpenAI protocol fixture, never a production model provider."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        request: object = json.loads(self.rfile.read(length))
        if not isinstance(request, dict):
            self.send_error(400, "Expected a JSON object")
            return
        model = request.get("model")
        if not isinstance(model, str):
            self.send_error(400, "Expected a model name")
            return
        if self.path == "/v1/embeddings":
            inputs = request["input"]
            count = len(inputs) if isinstance(inputs, list) else 1
            response = {
                "object": "list",
                "model": model,
                "data": [
                    {
                        "object": "embedding",
                        "index": i,
                        "embedding": [1.0] + [0.0] * 767,
                    }
                    for i in range(count)
                ],
                "usage": {"prompt_tokens": 8, "total_tokens": 8},
            }
        elif self.path == "/v1/chat/completions":
            response = {
                "id": "chatcmpl-kubernetes-smoke",
                "object": "chat.completion",
                "created": 1,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "KUBERNETES-SMOKE-OK",
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 4,
                    "total_tokens": 12,
                },
            }
        else:
            self.send_error(404)
            return
        data = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 4010), Handler).serve_forever()  # noqa: S104 -- ClusterIP fixture accepts pod traffic.

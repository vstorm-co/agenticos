"""Deterministic OpenAI protocol fixture, never a production model provider."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def object_fields(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError("Expected a protocol object")
    return {key: item for key, item in value.items() if isinstance(key, str)}


def sandbox_message(request: dict[str, object]) -> tuple[dict[str, object], str]:
    """Select real workspace tools; return their actual result without inventing file data."""
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("The sandbox fixture requires messages")
    last = object_fields(messages[-1])
    if last.get("role") == "tool":
        content = last.get("content")
        return {
            "role": "assistant",
            "content": content if isinstance(content, str) else json.dumps(content),
        }, "stop"
    prompt = last.get("content")
    if not isinstance(prompt, str):
        raise TypeError("The sandbox fixture requires a text instruction")
    if "OPENSHIFT-SANDBOX-WRITE" in prompt:
        required = "write_file"
        arguments = {"path": "/workspace/validation.txt", "content": "OPENSHIFT-PERSISTED-FILE"}
    elif "OPENSHIFT-SANDBOX-READ" in prompt:
        required = "read_file"
        arguments = {"path": "/workspace/validation.txt"}
    else:
        raise ValueError("Unknown sandbox fixture instruction")
    tools = request.get("tools")
    if not isinstance(tools, list):
        raise TypeError("The sandbox fixture requires workspace tools")
    for tool in tools:
        function = object_fields(object_fields(tool).get("function"))
        name = function.get("name")
        if isinstance(name, str) and name.endswith(required):
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"validation-{required}",
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(arguments),
                        },
                    }
                ],
            }, "tool_calls"
    raise ValueError("The requested workspace tool was not exposed")


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
            message: dict[str, object] = {"role": "assistant", "content": "KUBERNETES-SMOKE-OK"}
            finish_reason = "stop"
            if model == "sandbox-validation":
                try:
                    message, finish_reason = sandbox_message(object_fields(request))
                except (TypeError, ValueError) as error:
                    self.send_error(400, str(error))
                    return
            response = {
                "id": "chatcmpl-kubernetes-smoke",
                "object": "chat.completion",
                "created": 1,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": finish_reason,
                        "message": message,
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

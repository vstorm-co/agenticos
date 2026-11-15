"""Exercise a disposable chart install through the public HTTP contracts.

Run only against scripts/kubernetes fixtures, after the smoke bootstrap command.
No paid provider is contacted. Failures are assertions, never skipped checks.
"""

import json
import time
from http.client import HTTPConnection
from urllib.parse import urlencode
from uuid import uuid4


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError("Expected a JSON object")
    return {key: item for key, item in value.items() if isinstance(key, str)}


def text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Expected a JSON string")
    return value


def rows(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("Expected a JSON array")
    return list(value)


class Client:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}

    def request(
        self,
        method: str,
        path: str,
        body: object = None,
        *,
        raw: bytes | None = None,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
    ) -> object:
        data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        connection = HTTPConnection("127.0.0.1", 18000, timeout=120)
        try:
            connection.request(
                method,
                "/api/v1" + path,
                body=data,
                headers={
                    **self.headers,
                    "Content-Type": content_type,
                    **(headers or {}),
                },
            )
            response = connection.getresponse()
            payload = response.read()
            if response.status >= 400:
                raise RuntimeError(f"{method} {path}: {response.status}: {payload.decode()}")
            return json.loads(payload) if payload else None
        finally:
            connection.close()

    def upload(self, path: str) -> dict[str, object]:
        body = (
            b'--smoke-boundary\r\nContent-Disposition: form-data; name="file"; '
            b'filename="smoke.md"\r\nContent-Type: text/markdown\r\n\r\n'
            b"Kubernetes smoke: the worker indexes this document.\r\n--smoke-boundary--\r\n"
        )
        return mapping(
            self.request(
                "POST",
                path,
                raw=body,
                content_type="multipart/form-data; boundary=smoke-boundary",
            )
        )


def main() -> None:
    stamp = uuid4().hex[:8]
    client = Client()
    login = mapping(
        client.request(
            "POST",
            "/auth/login",
            raw=urlencode(
                {"username": "smoke@example.com", "password": "smoke-password-2872"}
            ).encode(),
            content_type="application/x-www-form-urlencoded",
        )
    )
    client.headers["Authorization"] = "Bearer " + text(login["access_token"])
    orgs = mapping(client.request("GET", "/orgs"))
    org = mapping(rows(orgs["items"])[0])
    client.headers["X-Organization-Id"] = text(org["id"])
    print("PASS sign-in and organization access", flush=True)

    endpoint = "http://model-fixture.agenticos-smoke-deps.svc.cluster.local:4010/v1"
    profile = mapping(
        client.request(
            "POST",
            "/providers/model-profiles",
            {
                "label": f"Kubernetes smoke {stamp}",
                "provider": "ollama",
                "model": "smoke-model",
                "base_url": endpoint,
            },
        )
    )
    agent = mapping(
        client.request(
            "POST",
            "/agents",
            {
                "spec": {
                    "name": f"Kubernetes smoke {stamp}",
                    "instructions": "Reply KUBERNETES-SMOKE-OK.",
                    "model_profile_id": profile["id"],
                }
            },
        )
    )
    agent_id = text(agent["id"])
    client.request("POST", f"/agents/{agent_id}/publish", {})
    run = mapping(client.request("POST", f"/agents/{agent_id}/run", {"prompt": "hello"}))
    assert run["status"] == "completed", run
    assert run["output"] == "KUBERNETES-SMOKE-OK", run
    print("PASS published agent response", flush=True)

    upload = client.upload("/files/upload")
    assert isinstance(upload["id"], str), upload
    print("PASS S3 file upload", flush=True)

    service = mapping(
        client.request(
            "POST",
            "/local-services",
            {
                "name": f"Smoke embeddings {stamp}",
                "kind": "embedding",
                "provider": "ollama",
                "base_url": endpoint,
            },
        )
    )
    kb = mapping(
        client.request(
            "POST",
            "/kb",
            {
                "name": f"Kubernetes smoke {stamp}",
                "embedding_model": "nomic-embed-text",
                "embedding_provider": "ollama",
                "embedding_endpoint_id": service["id"],
            },
        )
    )
    kb_id = text(kb["id"])
    client.upload(f"/kb/{kb_id}/documents")
    deadline = time.monotonic() + 180
    while True:
        state = mapping(client.request("GET", f"/kb/{kb_id}/ingestion"))
        assert state["failed_count"] == 0, state
        if state["indexing_status"] == "complete" and state["indexed_count"] == 1:
            break
        if time.monotonic() > deadline:
            raise TimeoutError(f"Ingestion did not complete: {state}")
        time.sleep(2)
    print("PASS asynchronous upload ingestion through worker and pgvector", flush=True)

    queued = mapping(
        client.request(
            "POST",
            f"/agents/{agent_id}/run",
            {"prompt": "queued"},
            headers={"Prefer": "respond-async"},
        )
    )
    request_id = text(queued["id"])
    deadline = time.monotonic() + 120
    while True:
        state = mapping(client.request("GET", f"/run-requests/{request_id}"))
        assert state["status"] != "failed", state
        if state["status"] == "completed":
            assert mapping(state["result"])["output"] == "KUBERNETES-SMOKE-OK", state
            break
        if time.monotonic() > deadline:
            raise TimeoutError(f"Background run did not complete: {state}")
        time.sleep(2)
    print("PASS durable background agent job", flush=True)


if __name__ == "__main__":
    main()

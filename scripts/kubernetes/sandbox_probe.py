"""Validate a disposable OpenSandbox connection through the platform's public API.

Read the generated provider key from stdin; never echo credentials or HTTP bodies.
Requires the local CRC fixtures, trusted Routes and the sandbox-validation model.
"""

import json
import sys
import time
from uuid import uuid4

import httpx
from oidc_probe import BASE, client
from smoke_probe import mapping, rows, text


def main() -> None:
    credential = mapping(json.load(sys.stdin))
    key = text(credential["api_key"])
    image = text(credential["image"])
    stamp = uuid4().hex[:8]
    with client() as api:

        def request(method: str, path: str, payload: object = None) -> object:
            response = api.request(method, BASE + path, json=payload, timeout=300)
            assert response.is_success, f"{method} {path}: {response.status_code}"
            return response.json() if response.content else None

        login = api.post(
            BASE + "/auth/login",
            data={"username": "smoke@example.com", "password": "smoke-password-2872"},
        )
        assert login.status_code == 200, login.status_code
        api.headers["Authorization"] = "Bearer " + text(mapping(login.json())["access_token"])
        org = mapping(rows(mapping(request("GET", "/orgs"))["items"])[0])
        api.headers["X-Organization-Id"] = text(org["id"])
        secret = mapping(
            request(
                "POST",
                "/secrets",
                {
                    "name": f"OpenSandbox validation {stamp}",
                    "value": {"kind": "api_key", "api_key": key},
                },
            )
        )
        assert key not in json.dumps(secret), "Plaintext credential escaped the vault response"
        connection = {
            "kind": "opensandbox",
            "base_url": "http://opensandbox-server.opensandbox-system.svc.cluster.local",
            "secret_id": secret["id"],
            "default_runtime": image,
            "secure_access": True,
        }
        request("POST", "/sandbox-connections/probe", connection)
        print("PASS authenticated OpenSandbox connection probe with Secure Access", flush=True)
        registered = mapping(
            request(
                "POST",
                "/sandbox-connections",
                {
                    **connection,
                    "name": f"CRC OpenSandbox {stamp}",
                },
            )
        )
        profile = mapping(
            request(
                "POST",
                "/providers/model-profiles",
                {
                    "label": f"Sandbox validation {stamp}",
                    "provider": "ollama",
                    "model": "sandbox-validation",
                    "base_url": "http://model-fixture.agenticos-smoke-deps.svc.cluster.local:4010/v1",
                },
            )
        )
        agent = mapping(
            request(
                "POST",
                "/agents",
                {
                    "spec": {
                        "name": f"Sandbox validation {stamp}",
                        "instructions": "Use the requested workspace tool and report its actual result.",
                        "model_profile_id": profile["id"],
                        "capabilities": [
                            {
                                "id": "sandbox",
                                "config": {
                                    "backend": "service",
                                    "connection_id": registered["id"],
                                    "session_scope": "conversation",
                                    "include_execute": True,
                                },
                            }
                        ],
                    }
                },
            )
        )
        agent_id = text(agent["id"])
        request("POST", f"/agents/{agent_id}/publish", {})
        first = mapping(
            request("POST", f"/agents/{agent_id}/run", {"prompt": "OPENSHIFT-SANDBOX-WRITE"})
        )
        conversation_id = text(first["conversation_id"])
        try:
            assert first["status"] == "completed", first["status"]
            read = mapping(
                request(
                    "POST",
                    f"/agents/{agent_id}/run",
                    {
                        "prompt": "OPENSHIFT-SANDBOX-READ",
                        "conversation_id": conversation_id,
                    },
                )
            )
            assert read["status"] == "completed", read["status"]
            assert "OPENSHIFT-PERSISTED-FILE" in text(read["output"]), (
                "Tool did not read persisted bytes"
            )
            print("PASS real tool write and next-turn reattachment/read", flush=True)
        finally:
            request("DELETE", f"/conversations/{conversation_id}")
        with httpx.Client(timeout=30, headers={"OPEN-SANDBOX-API-KEY": key}) as provider:
            deadline = time.monotonic() + 120
            while True:
                remaining = provider.get(text(connection["base_url"]) + "/sandboxes")
                assert remaining.status_code == 200, remaining.status_code
                if not rows(mapping(remaining.json())["items"]):
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("Conversation deletion left a provider sandbox running")
                time.sleep(2)
        print(
            "PASS conversation deletion removes provider sandboxes; verify pod cleanup on the host",
            flush=True,
        )


if __name__ == "__main__":
    main()

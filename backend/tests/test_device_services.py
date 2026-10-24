"""Local service grants and real HTTP adapters, without a network."""

import base64
import json
from typing import Literal
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from pydantic_ai import Agent
from pydantic_ai.toolsets import PrefixedToolset

from app.agents.mcp import FittedNames
from app.core.exceptions import BadRequestError
from app.services.device_hub import services
from app.services.device_hub.services import LocalService

pytestmark = pytest.mark.anyio


def reply(body: bytes = b"{}", status: int = 200) -> dict[str, object]:
    return {
        "status": status,
        "headers": {"content-type": "application/json"},
        "body": base64.b64encode(body).decode(),
    }


async def test_only_the_named_native_grant_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    call = AsyncMock(
        return_value={"id": "ollama", "name": "My model", "kind": "model", "model": "installed"}
    )
    monkeypatch.setattr(services._hub, "call", call)
    session = uuid4()
    assert (await services.describe(session, "ollama", "model")).model == "installed"
    assert call.call_args.args[:2] == (session, "service.describe")
    choices: list[tuple[str, Literal["model", "mcp"]]] = [("ollama", "mcp"), ("different", "model")]
    for service_id, kind in choices:
        with pytest.raises(BadRequestError):
            await services.describe(session, service_id, kind)
    call.return_value = {"id": "ollama", "name": "M", "kind": "model"}
    with pytest.raises(BadRequestError):
        await services.describe(session, "ollama", "model")
    call.return_value = {"id": "../bad"}
    with pytest.raises(BadRequestError, match="invalid local service"):
        await services.describe(session, "ollama", "model")


async def test_model_requests_are_carried_only_by_the_paired_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = AsyncMock(return_value=reply(b'{"ok":true}'))
    monkeypatch.setattr(services._hub, "call", call)
    session = uuid4()
    async with httpx2.AsyncClient(transport=services._ModelTransport(session, "mine")) as client:
        response = await client.post(
            "http://device.invalid/chat/completions", json={"model": "installed"}
        )
        assert response.json() == {"ok": True}
        assert call.call_args.args[0] == session
        assert call.call_args.args[2]["service"] == "mine"
        assert json.loads(base64.b64decode(call.call_args.args[2]["body"])) == {
            "model": "installed"
        }
        for url in ["http://127.0.0.1/admin", "http://device.invalid/anything"]:
            with pytest.raises(httpx2.RequestError):
                await client.post(url)


async def test_mcp_keeps_its_session_and_native_failure_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = AsyncMock(return_value=reply(b'{"error":"expired"}', 404))
    monkeypatch.setattr(services._hub, "call", call)
    async with httpx2.AsyncClient(transport=services._McpTransport(uuid4(), "files")) as client:
        response = await client.post(
            "http://device.invalid/mcp", headers={"mcp-session-id": "session"}, content=b"{}"
        )
        assert response.status_code == 404
        assert call.call_args.args[2]["headers"]["mcp-session-id"] == "session"
        assert call.call_args.args[2]["path"] == ""
        with pytest.raises(httpx2.RequestError):
            await client.get("http://device.invalid/secrets")


async def test_local_payloads_have_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "MAX_BYTES", 4)
    call = AsyncMock(return_value=reply(b"12345"))
    monkeypatch.setattr(services._hub, "call", call)
    with pytest.raises(BadRequestError, match="request exceeds"):
        await services._request(uuid4(), "x", "POST", "", {}, b"12345")
    call.assert_not_called()
    with pytest.raises(BadRequestError, match="response exceeds"):
        await services._request(uuid4(), "x", "POST", "", {}, b"")


async def test_a_real_agent_uses_the_local_model_without_a_cloud_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = uuid4()
    response = {
        "id": "local",
        "object": "chat.completion",
        "created": 1,
        "model": "installed",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Local answer"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
    }
    call = AsyncMock(return_value=reply(json.dumps(response).encode()))
    monkeypatch.setattr(services._hub, "call", call)
    spec = services.DeviceModelSpec(
        profile_id=uuid4(),
        label="Local",
        provider="ollama",
        model="installed",
        params={},
        credential=services.ResolvedCredential(provider="ollama", secret=services.NoSecret()),
        fallbacks=[],
        session_id=session,
        service_id="mine",
    )
    assert (await Agent(spec.build()).run("Hello")).output == "Local answer"
    assert call.call_args.args[0] == session
    local = services.model_spec(
        spec, session, LocalService(id="other", name="Other", kind="model", model="installed2")
    )
    assert local.model == "installed2"
    assert local.secret_id is None and local.fallbacks == []
    with pytest.raises(BadRequestError):
        services.model_spec(spec, session, LocalService(id="mcp", name="MCP", kind="mcp"))


def test_mcp_tools_are_namespaced_per_grant() -> None:
    toolset = services.mcp_toolset(uuid4(), LocalService(id="files", name="Files", kind="mcp"))
    assert isinstance(toolset, FittedNames)
    assert isinstance(toolset.wrapped, PrefixedToolset)
    assert toolset.wrapped.prefix == "local_files"
    assert toolset.wrapped.wrapped.id == "local:files"

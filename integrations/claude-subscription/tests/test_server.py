import asyncio
from base64 import b64encode
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import Request
from isolation import Owner
from runtime import ClaudeRuntime
from server import create_app

pytestmark = pytest.mark.anyio
KEY = "runtime-test-key-that-is-not-a-secret"


async def test_runtime_authentication_precedes_body_parsing(
    native_runtime: ClaudeRuntime, owner: Owner
) -> None:
    app = create_app(native_runtime, KEY)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://runtime"
    ) as client:
        response = await client.post(
            "/v1/login/code", content=b"private-code-but-not-json"
        )
        assert response.status_code == 403
        assert response.json() == {"error": {"code": "CLAUDE_ACCESS_DENIED"}}
        assert not native_runtime.accounts
        assert (await client.get("/health")).status_code == 200


async def test_validation_does_not_echo_code(
    native_runtime: ClaudeRuntime, owner: Owner
) -> None:
    app = create_app(native_runtime, KEY)
    body = {
        "organization_id": str(owner.organization_id),
        "user_id": str(owner.user_id),
        "login_id": str(uuid4()),
        "code": "private\ncode",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="http://runtime",
        headers={"X-Claude-Runtime-Key": KEY},
    ) as client:
        response = await client.post("/v1/login/code", json=body)
        assert response.status_code == 422
        assert "private" not in response.text


async def test_request_body_is_bounded(native_runtime: ClaudeRuntime) -> None:
    app = create_app(native_runtime, KEY)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="http://runtime",
        headers={"X-Claude-Runtime-Key": KEY},
    ) as client:
        response = await client.post("/v1/infer", content=b"x" * (1024 * 1024 + 1))
        assert response.status_code == 413
        assert response.json() == {"error": {"code": "CLAUDE_INVALID_REQUEST"}}
        assert "x" * 100 not in response.text
        assert not native_runtime.accounts


async def test_disconnected_http_peer_cancels_native_task(
    native_runtime: ClaudeRuntime, owner: Owner, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancelled = asyncio.Event()

    async def waiting(*_arguments):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(native_runtime, "infer", waiting)
    monkeypatch.setattr(Request, "is_disconnected", AsyncMock(return_value=True))
    app = create_app(native_runtime, KEY)
    body = {
        "organization_id": str(owner.organization_id),
        "user_id": str(owner.user_id),
        "model": "sonnet",
        "prompt": "hello",
        "output_schema": {"type": "object"},
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="http://runtime",
        headers={"X-Claude-Runtime-Key": KEY},
    ) as client:
        response = await client.post("/v1/infer", json=body)
        assert response.status_code == 499
        assert cancelled.is_set()


@pytest.mark.parametrize(
    "extra",
    [
        {"thinking": {"budget_tokens": 4096}},
        {"images": [{"media_type": "image/png", "data": "private-invalid-image"}]},
        {"images": [{"media_type": "image/png", "url": "https://example.com/private"}]},
    ],
)
async def test_invalid_inference_options_are_private_and_never_start_native_work(
    native_runtime, owner, extra
):
    app = create_app(native_runtime, KEY)
    body = {
        "organization_id": str(owner.organization_id),
        "user_id": str(owner.user_id),
        "model": "opus",
        "prompt": "private-prompt",
        "output_schema": {"type": "object"},
        **extra,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="http://runtime",
        headers={"X-Claude-Runtime-Key": KEY},
    ) as client:
        response = await client.post("/v1/infer", json=body)
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "CLAUDE_INVALID_REQUEST"}}
    assert not native_runtime.accounts and not native_runtime.processes


async def test_image_and_prompt_share_the_existing_total_body_cap(
    native_runtime, owner
):
    app = create_app(native_runtime, KEY)
    body = {
        "organization_id": str(owner.organization_id),
        "user_id": str(owner.user_id),
        "model": "opus",
        "prompt": "p" * 500_000,
        "output_schema": {"type": "object"},
        "images": [
            {"media_type": "image/jpeg", "data": b64encode(b"x" * 500_000).decode()}
        ],
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="http://runtime",
        headers={"X-Claude-Runtime-Key": KEY},
    ) as client:
        response = await client.post("/v1/infer", json=body)
    assert response.status_code == 413
    assert response.json() == {"error": {"code": "CLAUDE_INVALID_REQUEST"}}
    assert not native_runtime.accounts and not native_runtime.processes

"""Only the direct signed-in owner can reach a native subscription connection."""

import json
from base64 import b64decode
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.claude_subscription import ClaudeSubscriptionImage, ClaudeSubscriptionOwner
from app.core.config import settings
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConfigurationError,
    ConflictError,
    ExternalServiceError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.schemas.claude_subscription import (
    ClaudeSubscriptionLoginCode,
    ClaudeSubscriptionLoginControl,
    ClaudeSubscriptionRead,
)
from app.services.claude_subscription import (
    ClaudeSubscriptionRuntime,
    ClaudeSubscriptionService,
    subscription_owner,
)
from app.services.claude_subscription._client import ClaudeRuntimeError

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _ctx():
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)


def _state(**overrides):
    return {
        "available": True,
        "connected": False,
        "state": "disconnected",
        "login_id": None,
        "authorization_url": None,
        "expires_at": None,
        "error_code": None,
        **overrides,
    }


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "CLAUDE_SUBSCRIPTION_URL", "http://native-runtime:8080")
    monkeypatch.setattr(
        settings, "CLAUDE_SUBSCRIPTION_SERVICE_KEY", SecretStr("fake-runtime-key-" * 3)
    )


async def test_unconfigured_status_has_no_network_and_login_is_explicit(monkeypatch):
    monkeypatch.setattr(settings, "CLAUDE_SUBSCRIPTION_URL", None)
    transport = httpx.MockTransport(lambda request: pytest.fail("No runtime is configured"))
    runtime = ClaudeSubscriptionRuntime(transport=transport)
    owner = subscription_owner(_ctx())
    assert (await runtime.status(owner)).model_dump() == _state(available=False)
    with pytest.raises(ConfigurationError, match="not configured"):
        await runtime.login(owner)


async def test_private_protocol_uses_authenticated_owner_and_never_returns_credentials(configured):
    ctx, login_id, seen = _ctx(), uuid4(), []

    def respond(request):
        seen.append(request)
        assert request.method == "POST"
        assert request.url.host == "native-runtime"
        assert request.headers["X-Claude-Runtime-Key"] == "fake-runtime-key-" * 3
        body = json.loads(request.content)
        assert body["organization_id"] == str(ctx.organization_id)
        assert body["user_id"] == str(ctx.user_id)
        return httpx.Response(
            200,
            json=_state(
                access_token="must-never-leave-runtime", account_email="private@example.com"
            ),
        )

    service = ClaudeSubscriptionService(
        ClaudeSubscriptionRuntime(transport=httpx.MockTransport(respond))
    )
    for state in [
        await service.status(ctx),
        await service.login(ctx),
        await service.code(
            ctx,
            ClaudeSubscriptionLoginCode(login_id=login_id, code=SecretStr("fake-one-time-code")),
        ),
        await service.cancel(ctx, ClaudeSubscriptionLoginControl(login_id=login_id)),
        await service.disconnect(ctx),
    ]:
        assert "access_token" not in state.model_dump_json()
        assert "private@example.com" not in state.model_dump_json()
    assert [request.url.path for request in seen] == [
        "/v1/status",
        "/v1/login",
        "/v1/login/code",
        "/v1/login/cancel",
        "/v1/disconnect",
    ]
    assert json.loads(seen[2].content)["login_id"] == str(login_id)
    assert json.loads(seen[2].content)["code"] == "fake-one-time-code"


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_id": None},
        {"api_key_id": uuid4()},
        {"key_scopes": frozenset()},
        {"key_scopes": frozenset({Perm.AGENTS_RUN})},
        {"subject_is_publisher_fallback": True},
        {"is_impersonated": True},
        {"is_workflow": True},
        {"channel_identity_id": uuid4()},
        {"fired_as_creator": "schedule"},
        {"fired_as_creator": "event"},
        {"routine_id": uuid4()},
        {"routine_source_policy_id": uuid4()},
        {"routine_activation_id": uuid4()},
    ],
)
async def test_every_connection_action_refuses_delegated_origins_before_runtime(overrides):
    runtime = AsyncMock(spec=ClaudeSubscriptionRuntime)
    service = ClaudeSubscriptionService(runtime)
    ctx, login_id = replace(_ctx(), **overrides), uuid4()
    actions = [
        lambda: service.status(ctx),
        lambda: service.login(ctx),
        lambda: service.code(
            ctx, ClaudeSubscriptionLoginCode(login_id=login_id, code=SecretStr("fake-code"))
        ),
        lambda: service.cancel(ctx, ClaudeSubscriptionLoginControl(login_id=login_id)),
        lambda: service.disconnect(ctx),
        lambda: service.require_connected(ctx),
    ]
    for action in actions:
        with pytest.raises(AuthorizationError):
            await action()
    assert runtime.mock_calls == []


async def test_profiles_require_a_connected_own_subscription():
    ctx = _ctx()
    runtime = AsyncMock(spec=ClaudeSubscriptionRuntime)
    service = ClaudeSubscriptionService(runtime)
    for state in [_state(available=False), _state()]:
        runtime.status.return_value = ClaudeSubscriptionRead.model_validate(state)
        with pytest.raises(ConflictError, match="Connect your Claude"):
            await service.require_connected(ctx)
    runtime.status.return_value = ClaudeSubscriptionRead.model_validate(
        _state(connected=True, state="connected")
    )
    assert await service.require_connected(ctx) == ClaudeSubscriptionOwner(
        ctx.organization_id, ctx.user_id
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://claude.ai/oauth/authorize",
        "https://claude.ai.evil.example/oauth/authorize",
        "https://console.anthropic.com/oauth/authorize",
        "https://claude.ai@evil.example/oauth/authorize",
        "https://someone@claude.ai/oauth/authorize",
        "https://claude.ai:444/oauth/authorize",
        "https://claude.ai/other",
        "https://claude.ai/oauth/authorize#fragment",
        "https://claude.ai:invalid/oauth/authorize",
        "https://claude.com/oauth/authorize",
        "https://claude.ai/cai/oauth/authorize",
        "https://claude.com.evil.example/cai/oauth/authorize",
        "https://someone@claude.com/cai/oauth/authorize",
        "https://claude.com:444/cai/oauth/authorize",
        "https://claude.com/cai/oauth/authorize#fragment",
    ],
)
async def test_only_the_provider_authorization_page_can_be_returned(url, configured):
    runtime = ClaudeSubscriptionRuntime(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_state(authorization_url=url))
        )
    )
    with pytest.raises(ExternalServiceError, match="invalid connection state"):
        await runtime.login(subscription_owner(_ctx()))


def test_native_authorization_url_and_secret_code_schema():
    state = ClaudeSubscriptionRead.model_validate(
        _state(
            state="awaiting_code",
            login_id=str(uuid4()),
            authorization_url="https://claude.ai:443/oauth/authorize/?code_challenge=fake",
            expires_at="2026-11-07T12:00:00Z",
        )
    )
    assert state.authorization_url.startswith("https://claude.ai")
    code = ClaudeSubscriptionLoginCode(login_id=uuid4(), code=SecretStr("one-time-code"))
    assert "one-time-code" not in repr(code)
    assert "one-time-code" not in code.model_dump_json()
    assert "code_challenge" not in repr(state)
    for value in ["", "two words", "line\nbreak", "code\t", "\x1b[31m", "non-ascii-é", "x" * 2049]:
        with pytest.raises(ValidationError):
            ClaudeSubscriptionLoginCode(login_id=uuid4(), code=SecretStr(value))


@pytest.mark.parametrize(
    ("status", "body", "expected_code"),
    [
        (
            409,
            {"error": {"code": "CLAUDE_SIGN_IN_REQUIRED", "details": "private-cli-output"}},
            "CLAUDE_SIGN_IN_REQUIRED",
        ),
        (429, {"error": {"code": "CLAUDE_CAPACITY"}}, "CLAUDE_CAPACITY"),
        (500, {"error": {"code": "private-cli-output"}}, "CLAUDE_RUNTIME_FAILED"),
        (500, {"error": "private-cli-output"}, "CLAUDE_RUNTIME_FAILED"),
        (500, ["private-cli-output"], "CLAUDE_RUNTIME_FAILED"),
    ],
)
async def test_upstream_failures_are_fixed_codes_without_process_output(
    configured, status, body, expected_code
):
    runtime = ClaudeSubscriptionRuntime(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    )
    with pytest.raises(ExternalServiceError) as error:
        await runtime.status(subscription_owner(_ctx()))
    assert error.value.code == expected_code
    assert "private-cli-output" not in repr(error.value)
    if expected_code != "CLAUDE_RUNTIME_FAILED":
        assert isinstance(error.value, ClaudeRuntimeError)
        assert error.value.status_code == status


async def test_redirect_does_not_send_the_service_key_to_another_host(configured):
    requests = []

    def redirect(request):
        requests.append(request)
        return httpx.Response(
            307,
            headers={"Location": "https://other.example/collect"},
            content=b"private-cli-output",
        )

    runtime = ClaudeSubscriptionRuntime(transport=httpx.MockTransport(redirect))
    with pytest.raises(ExternalServiceError) as error:
        await runtime.login(subscription_owner(_ctx()))
    assert len(requests) == 1
    assert "private-cli-output" not in str(error.value)


async def test_connection_errors_and_invalid_states_are_controlled(configured):
    def fail(request):
        raise httpx.ConnectError("private upstream address", request=request)

    runtime = ClaudeSubscriptionRuntime(transport=httpx.MockTransport(fail))
    with pytest.raises(ExternalServiceError, match="unavailable") as error:
        await runtime.status(subscription_owner(_ctx()))
    assert "private upstream" not in repr(error.value)
    for body in [b"not JSON", json.dumps(_state(error_code="CLAUDE_UNKNOWN_RAW_MESSAGE")).encode()]:
        runtime = ClaudeSubscriptionRuntime(
            transport=httpx.MockTransport(
                lambda request, body=body: httpx.Response(200, content=body)
            )
        )
        with pytest.raises(ExternalServiceError, match="invalid connection state"):
            await runtime.status(subscription_owner(_ctx()))


async def test_inference_is_bounded_and_carries_no_provider_credentials(configured):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "structured_output": {"text": "Hello", "tool_calls": []},
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 2,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
                "model": "claude-sonnet-4-6",
            },
        )

    runtime = ClaudeSubscriptionRuntime(transport=httpx.MockTransport(respond))
    owner = subscription_owner(_ctx())
    result = await runtime.infer(
        owner,
        model="sonnet",
        prompt="Hello",
        output_schema={"type": "object"},
        max_output_tokens=256,
    )
    body = json.loads(requests[0].content)
    assert set(body) == {
        "organization_id",
        "user_id",
        "model",
        "prompt",
        "output_schema",
        "max_output_tokens",
    }
    assert requests[0].extensions["timeout"]["read"] == 610
    assert result.structured_output["text"] == "Hello"
    with pytest.raises(BadRequestError, match="conversation is too large"):
        await runtime.infer(owner, model="sonnet", prompt="é" * 400001, output_schema={})
    with pytest.raises(BadRequestError, match="request is too large"):
        await runtime.infer(
            owner, model="sonnet", prompt="Hello", output_schema={"large": "a" * (1024 * 1024)}
        )
    assert len(requests) == 1


@pytest.mark.parametrize(
    "body",
    [b"not JSON", b"{}", b"x" * (4 * 1024 * 1024 + 1)],
    ids=["invalid-json", "invalid-shape", "oversized"],
)
async def test_inference_rejects_malformed_and_oversized_replies(configured, body):
    runtime = ClaudeSubscriptionRuntime(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    )
    with pytest.raises(ExternalServiceError):
        await runtime.infer(
            subscription_owner(_ctx()), model="haiku", prompt="Hi", output_schema={}
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://claude.ai/oauth/authorize?state=fake",
        "https://claude.com/cai/oauth/authorize?state=fake",
        "https://claude.com:443/cai/oauth/authorize/",
    ],
)
def test_native_current_and_legacy_authorization_pages(url):
    from app.schemas.claude_subscription import ClaudeSubscriptionRead

    assert ClaudeSubscriptionRead(available=True, authorization_url=url).authorization_url == url


async def test_inference_preserves_inline_image_bytes_and_false_thinking(configured):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "structured_output": {"text": "Ready", "tool_calls": []},
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
                "model": "claude-test",
            },
        )

    runtime = ClaudeSubscriptionRuntime(transport=httpx.MockTransport(respond))
    image = ClaudeSubscriptionImage(media_type="image/png", data=b"\x89PNG\r\n\x1a\n")
    owner = subscription_owner(_ctx())
    await runtime.infer(
        owner, model="opus", prompt="[image:1]", output_schema={}, images=[image], thinking=False
    )
    body = json.loads(requests[0].content)
    assert body["thinking"] is False
    assert body["user_id"] == str(owner.user_id)
    assert body["images"][0]["media_type"] == image.media_type
    assert b64decode(body["images"][0]["data"], validate=True) == image.data


@pytest.mark.parametrize("raw_size,prompt_size", [(800_000, 1), (500_000, 500_000)])
async def test_total_image_request_limit_accounts_for_base64_expansion(
    configured, raw_size, prompt_size
):
    runtime = ClaudeSubscriptionRuntime(
        transport=httpx.MockTransport(
            lambda request: pytest.fail("An oversized image request must never reach the runtime")
        )
    )
    image = ClaudeSubscriptionImage(media_type="image/jpeg", data=b"x" * raw_size)
    with pytest.raises(BadRequestError, match="request is too large"):
        await runtime.infer(
            subscription_owner(_ctx()),
            model="opus",
            prompt="p" * prompt_size,
            output_schema={},
            images=[image],
        )

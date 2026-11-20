"""The signed-in user's routes expose state and fixed errors, never the login code."""

import json
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starlette.requests import HTTPConnection

from app.api.deps import get_auth_context, get_claude_subscription_service
from app.core.logfire_setup import redact_secret_arguments
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.claude_subscription import ClaudeSubscriptionRead
from app.services.claude_subscription import ClaudeSubscriptionRuntime, ClaudeSubscriptionService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_PATH = "/api/v1/personal-subscriptions/claude"


def _setup():
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    runtime = AsyncMock(spec=ClaudeSubscriptionRuntime)
    for name in ["status", "login", "code", "cancel", "disconnect"]:
        getattr(runtime, name).return_value = ClaudeSubscriptionRead(available=True)
    app.dependency_overrides[get_auth_context] = lambda: ctx
    app.dependency_overrides[get_claude_subscription_service] = lambda: ClaudeSubscriptionService(
        runtime
    )
    return ctx, runtime


async def test_all_five_routes_use_session_owner_and_disable_caching(client):
    ctx, runtime = _setup()
    login_id = str(uuid4())
    for method, path, body in [
        ("GET", "", None),
        ("POST", "/login", None),
        (
            "POST",
            "/login/code",
            {"login_id": login_id, "code": "fake-native-code", "user_id": str(uuid4())},
        ),
        ("POST", "/login/cancel", {"login_id": login_id}),
        ("POST", "/disconnect", None),
    ]:
        result = await client.request(method, _PATH + path, json=body)
        assert result.status_code == 200
        assert result.headers["Cache-Control"] == "no-store"
        assert "fake-native-code" not in result.text
    for name in ["status", "login", "code", "cancel", "disconnect"]:
        owner = getattr(runtime, name).await_args.args[0]
        assert owner.user_id == ctx.user_id and owner.organization_id == ctx.organization_id


async def test_every_route_requires_connections_manage(client):
    ctx, runtime = _setup()
    app.dependency_overrides[get_auth_context] = lambda: replace(ctx, role=OrgRoleName.VIEWER)
    login_id = str(uuid4())
    for method, path, body in [
        ("GET", "", None),
        ("POST", "/login", None),
        ("POST", "/login/code", {"login_id": login_id, "code": "fake"}),
        ("POST", "/login/cancel", {"login_id": login_id}),
        ("POST", "/disconnect", None),
    ]:
        result = await client.request(method, _PATH + path, json=body)
        assert result.status_code == 403
    assert runtime.mock_calls == []


@pytest.mark.parametrize(
    "code", ["private-code with spaces", "private-code\nnewline", "private-code" * 190]
)
async def test_invalid_code_is_not_reflected_in_error_response_or_logs(client, caplog, code):
    _, runtime = _setup()
    result = await client.post(_PATH + "/login/code", json={"login_id": str(uuid4()), "code": code})
    assert result.status_code == 422
    assert "private-code" not in result.text
    assert "private-code" not in caplog.text
    runtime.code.assert_not_awaited()


@pytest.mark.parametrize(
    "errors",
    [
        [],
        [
            {
                "loc": ["body", "code"],
                "input": "private-native-code",
                "msg": "bad private-native-code",
                "type": "value_error",
                "ctx": {"code": "private-native-code"},
            }
        ],
        [{"loc": ["body"], "input": {"code": "private-native-code"}, "type": "json_invalid"}],
        ["private-native-code"],
    ],
)
def test_native_login_trace_attributes_never_contain_submitted_code(errors):
    request = HTTPConnection(
        {"type": "http", "path": _PATH + "/login/code", "query_string": b"", "headers": []}
    )
    attributes = {
        "values": {"data": {"code": "private-native-code", "login_id": str(uuid4())}},
        "errors": errors,
    }
    clean = redact_secret_arguments(request, attributes)
    assert "private-native-code" not in json.dumps(clean)
    assert attributes["values"]["data"]["code"] == "private-native-code"

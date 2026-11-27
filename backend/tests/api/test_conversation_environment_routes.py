"""The internal console API exposes lifecycle, never provider handles or fake runs."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.conversation_environment import (
    ConversationEnvironmentList,
    ConversationEnvironmentRead,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def caller():
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    service = AsyncMock()
    result = ConversationEnvironmentRead(
        id=uuid4(),
        kind="browser",
        execution_target="project",
        agent_id=uuid4(),
        state="starting",
        session_lifetime="conversation",
        idle_seconds=900,
        control="none",
        can_control=False,
        expires_at=None,
        refusal=None,
    )
    service.read.return_value = result
    service.ensure.return_value = result
    service.list.return_value = ConversationEnvironmentList(items=[result])
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_conversation_environment_service] = lambda: service
    try:
        yield ctx, service, result
    finally:
        app.dependency_overrides.pop(deps.get_auth_context, None)
        app.dependency_overrides.pop(deps.get_conversation_environment_service, None)


async def test_reads_are_effect_free_and_keep_selected_execution_target(
    client: AsyncClient, caller
):
    ctx, service, result = caller
    conversation = uuid4()
    query = f"?agent_id={result.agent_id}&project_execution_target=project"
    one = await client.get(f"/api/v1/conversations/{conversation}/environments/browser{query}")
    all_views = await client.get(f"/api/v1/conversations/{conversation}/environments{query}")
    assert one.status_code == 200 and all_views.status_code == 200
    assert one.json()["execution_target"] == "project"
    assert "provider" not in one.text and "cdp_url" not in one.text
    service.read.assert_awaited_once_with(ctx, conversation, result.agent_id, "browser", "project")
    service.ensure.assert_not_awaited()


async def test_explicit_post_returns_201_and_never_accepts_runtime_provider_identity(
    client: AsyncClient, caller
):
    _, service, result = caller
    base = f"/api/v1/conversations/{uuid4()}/environments/browser"
    accepted = await client.post(
        base, json={"agent_id": str(result.agent_id), "project_execution_target": "project"}
    )
    assert accepted.status_code == 201 and accepted.json()["state"] == "starting"
    rejected = await client.post(
        base,
        json={"agent_id": str(result.agent_id), "provider_ref": "injected", "run_id": str(uuid4())},
    )
    assert rejected.status_code == 422
    assert service.ensure.await_count == 1


async def test_end_has_no_body_and_default_target_is_agent(client: AsyncClient, caller):
    ctx, service, result = caller
    conversation = uuid4()
    response = await client.delete(
        f"/api/v1/conversations/{conversation}/environments/desktop?agent_id={result.agent_id}"
    )
    assert response.status_code == 204 and response.content == b""
    service.end.assert_awaited_once_with(ctx, conversation, result.agent_id, "desktop", "agent")


@pytest.mark.parametrize(
    "tail",
    [
        "other",
        "browser?agent_id=not-a-uuid",
        "desktop?agent_id=00000000-0000-0000-0000-000000000001&project_execution_target=local",
    ],
)
async def test_unknown_kinds_and_selectors_are_refused_before_service(
    client: AsyncClient, caller, tail
):
    _, service, _ = caller
    response = await client.get(f"/api/v1/conversations/{uuid4()}/environments/{tail}")
    assert response.status_code == 422
    service.read.assert_not_awaited()


async def test_socket_uses_authenticated_subprotocol_and_requested_target(monkeypatch):
    from types import SimpleNamespace

    from app.api.routes.v1 import conversation_environments as routes

    socket = AsyncMock()
    socket.state = SimpleNamespace(
        accept_subprotocol="environment", auth_token="test-only-private-token"
    )
    stream = AsyncMock()
    monkeypatch.setattr(routes, "stream_environment", stream)
    conversation, environment = uuid4(), uuid4()
    await routes.environment_live(socket, conversation, environment, object(), "project")
    socket.accept.assert_awaited_once_with(subprotocol="environment")
    stream.assert_awaited_once_with(
        socket,
        auth_token="test-only-private-token",
        conversation_id=conversation,
        environment_id=environment,
        execution_target="project",
    )

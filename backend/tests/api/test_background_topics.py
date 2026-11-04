"""Personal task routes pass the authenticated member to domain authorization."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.conversation_task import ConversationTaskRead

pytestmark = pytest.mark.anyio
PREFIX = f"{settings.API_V1_STR}/conversations/background-tasks"
CTX = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")


@pytest.fixture
async def service() -> AsyncGenerator[AsyncMock]:
    tasks = AsyncMock()
    app.dependency_overrides[deps.get_current_user] = lambda: MagicMock(
        id=CTX.user_id, is_app_admin=False
    )
    app.dependency_overrides[deps.get_active_organization] = lambda: MagicMock(
        id=CTX.organization_id
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: CTX
    app.dependency_overrides[deps.get_conversation_task_service] = lambda: tasks
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    try:
        yield tasks
    finally:
        app.dependency_overrides.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize("scoped", [False, True])
async def test_lists_only_through_current_member_authority(
    service: AsyncMock, scoped: bool
) -> None:
    conversation = uuid4() if scoped else None
    service.list_for_member.return_value = []
    async with _client() as client:
        response = await client.get(
            PREFIX, params={} if conversation is None else {"conversation_id": str(conversation)}
        )
    assert response.status_code == 200 and response.json() == []
    service.list_for_member.assert_awaited_once_with(CTX, conversation_id=conversation)


async def test_stops_only_through_current_member_authority(service: AsyncMock) -> None:
    task_id = uuid4()
    task = ConversationTaskRead(
        id=task_id,
        source_conversation_id=uuid4(),
        conversation_id=uuid4(),
        agent_id=uuid4(),
        title="Research",
        status="cancelled",
        delivery="pending",
        run_id=None,
        return_run_id=None,
        outcome="Stopped",
        created_at=datetime.now(UTC),
    )
    service.stop.return_value = task
    async with _client() as client:
        response = await client.post(f"{PREFIX}/{task_id}/stop")
    assert response.status_code == 200
    assert response.json()["id"] == str(task_id)
    assert "local_target" not in response.json()
    service.stop.assert_awaited_once_with(CTX, task_id)


@pytest.mark.parametrize("verb", ["list", "stop"])
async def test_a_task_outside_current_authority_stays_missing(
    service: AsyncMock, verb: str
) -> None:
    refusal = NotFoundError(message="Task not found")
    service.stop.side_effect = refusal
    service.list_for_member.side_effect = refusal
    async with _client() as client:
        response = (
            await client.get(PREFIX)
            if verb == "list"
            else await client.post(f"{PREFIX}/{uuid4()}/stop")
        )
    assert response.status_code == 404


async def test_requires_a_signed_in_member() -> None:
    async with _client() as client:
        response = await client.get(PREFIX)
    assert response.status_code == 401


def test_service_factory_keeps_request_transaction() -> None:
    db = MagicMock()
    assert deps.get_conversation_task_service(db).db is db

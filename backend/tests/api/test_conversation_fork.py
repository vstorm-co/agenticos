"""Forking a conversation, through the app (#2762).

What is pinned here is the wiring: the caller, tenant and answer reach the
service, the new conversation comes back as a 201, the origin is serialized as
the service set it, and the service's refusals keep their status.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    get_active_organization,
    get_auth_context,
    get_conversation_service,
    get_current_user,
    get_db_session,
)
from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.conversation import ConversationForkOrigin

pytestmark = pytest.mark.anyio

SOURCE_ID = uuid4()
ANSWER_ID = uuid4()
ENDPOINT = f"{settings.API_V1_STR}/conversations/{SOURCE_ID}/fork"
CALLER = SimpleNamespace(
    id=uuid4(),
    email="kacper@example.com",
    is_app_admin=False,
    is_active=True,
    created_at=datetime.now(UTC),
)
ORGANIZATION = SimpleNamespace(id=uuid4())


@pytest.fixture(autouse=True)
def fresh_allowance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test forks against an allowance of its own; the floor is per process."""
    from app.services import rate_limit

    monkeypatch.setattr(rate_limit, "_floor", rate_limit.LocalWindows())


@pytest.fixture
async def service() -> AsyncGenerator[AsyncMock]:
    app.dependency_overrides[get_current_user] = lambda: CALLER
    app.dependency_overrides[get_active_organization] = lambda: ORGANIZATION
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=CALLER.id, organization_id=ORGANIZATION.id, role=str(OrgRoleName.MEMBER)
    )
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    conversations = AsyncMock()
    app.dependency_overrides[get_conversation_service] = lambda: conversations
    yield conversations
    app.dependency_overrides.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_a_fork_is_created_for_the_caller_and_names_its_source(service: AsyncMock) -> None:
    fork = SimpleNamespace(
        id=uuid4(),
        title="Pricing",
        user_id=CALLER.id,
        organization_id=ORGANIZATION.id,
        created_at=datetime.now(UTC),
        updated_at=None,
        forked_from=ConversationForkOrigin(
            conversation_id=SOURCE_ID, message_id=ANSWER_ID, title="Pricing"
        ),
    )
    service.fork = AsyncMock(return_value=fork)

    async with _client() as client:
        response = await client.post(ENDPOINT, json={"message_id": str(ANSWER_ID)})

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == str(fork.id)
    assert body["forked_from"] == {
        "conversation_id": str(SOURCE_ID),
        "message_id": str(ANSWER_ID),
        "title": "Pricing",
    }
    assert service.fork.await_args.args == (SOURCE_ID,)
    assert service.fork.await_args.kwargs["message_id"] == ANSWER_ID
    assert service.fork.await_args.kwargs["user_id"] == CALLER.id
    assert service.fork.await_args.kwargs["organization_id"] == ORGANIZATION.id


async def test_a_conversation_the_caller_may_not_fork_is_missing(service: AsyncMock) -> None:
    service.fork = AsyncMock(side_effect=NotFoundError(message="Conversation not found"))

    async with _client() as client:
        response = await client.post(ENDPOINT, json={"message_id": str(ANSWER_ID)})

    assert response.status_code == 404


async def test_an_unfinished_answer_is_refused(service: AsyncMock) -> None:
    service.fork = AsyncMock(side_effect=BadRequestError(message="still running"))

    async with _client() as client:
        response = await client.post(ENDPOINT, json={"message_id": str(ANSWER_ID)})

    assert response.status_code == 400


async def test_a_fork_needs_an_answer(service: AsyncMock) -> None:
    async with _client() as client:
        response = await client.post(ENDPOINT, json={})

    assert response.status_code == 422
    assert service.fork.await_count == 0


@pytest.mark.security
async def test_forking_is_rationed_per_member(
    service: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each fork stores a copy of a whole conversation from a request a few bytes long,
    so one member forking the same long thread in a loop must hit a ceiling."""
    from app.services import rate_limit

    monkeypatch.setattr(rate_limit, "FORKS_PER_MINUTE", 2)
    service.fork = AsyncMock(
        return_value=SimpleNamespace(
            id=uuid4(),
            title="Pricing",
            user_id=CALLER.id,
            organization_id=ORGANIZATION.id,
            created_at=datetime.now(UTC),
            updated_at=None,
        )
    )

    async with _client() as client:
        answers = [
            await client.post(ENDPOINT, json={"message_id": str(ANSWER_ID)}) for _ in range(3)
        ]

    assert [answer.status_code for answer in answers] == [201, 201, 429]
    assert service.fork.await_count == 2

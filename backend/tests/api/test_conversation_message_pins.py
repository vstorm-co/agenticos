"""The private message-pin endpoints keep the caller, tenant and read context."""

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
    get_conversation_message_pin_service,
    get_current_user,
    get_db_session,
)
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.conversation_message_pin import (
    ConversationMessagePinList,
    ConversationMessagePinRead,
)

pytestmark = pytest.mark.anyio

CONVERSATION_ID = uuid4()
MESSAGE_ID = uuid4()
CALLER = SimpleNamespace(
    id=uuid4(),
    email="reader@example.test",
    is_app_admin=False,
    is_active=True,
    created_at=datetime.now(UTC),
)
ORGANIZATION = SimpleNamespace(id=uuid4())
ROOT = f"{settings.API_V1_STR}/conversations/{CONVERSATION_ID}"


@pytest.fixture
async def service() -> AsyncGenerator[AsyncMock]:
    app.dependency_overrides[get_current_user] = lambda: CALLER
    app.dependency_overrides[get_active_organization] = lambda: ORGANIZATION
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=CALLER.id, organization_id=ORGANIZATION.id, role=str(OrgRoleName.MEMBER)
    )
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    pins = AsyncMock()
    app.dependency_overrides[get_conversation_message_pin_service] = lambda: pins
    yield pins
    app.dependency_overrides.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _pin() -> ConversationMessagePinRead:
    return ConversationMessagePinRead(
        message_id=MESSAGE_ID,
        thread_root_message_id=None,
        role="assistant",
        message_created_at=datetime(2026, 11, 17, tzinfo=UTC),
        pinned_at=datetime(2026, 11, 17, tzinfo=UTC),
        preview="The live message excerpt",
    )


async def test_the_paged_list_is_scoped_to_the_active_reader_and_organization(
    service: AsyncMock,
) -> None:
    service.list_message_pins = AsyncMock(
        return_value=ConversationMessagePinList(items=[_pin()], total=51)
    )

    async with _client() as client:
        response = await client.get(f"{ROOT}/message-pins", params={"skip": 50, "limit": 100})

    assert response.status_code == 200
    assert response.json()["items"][0]["message_id"] == str(MESSAGE_ID)
    assert response.json()["total"] == 51
    assert service.list_message_pins.await_args.args == (CONVERSATION_ID,)
    assert service.list_message_pins.await_args.kwargs == {
        "organization_id": ORGANIZATION.id,
        "user_id": CALLER.id,
        "skip": 50,
        "limit": 100,
        "ctx": AuthContext(
            user_id=CALLER.id,
            organization_id=ORGANIZATION.id,
            role=str(OrgRoleName.MEMBER),
        ),
    }


async def test_the_pin_route_returns_the_sanitized_live_projection(service: AsyncMock) -> None:
    service.pin_message = AsyncMock(return_value=_pin())

    async with _client() as client:
        response = await client.post(f"{ROOT}/messages/{MESSAGE_ID}/pin")

    assert response.status_code == 201
    assert response.json()["preview"] == "The live message excerpt"
    assert service.pin_message.await_args.args == (CONVERSATION_ID, MESSAGE_ID)
    assert service.pin_message.await_args.kwargs["user_id"] == CALLER.id
    assert service.pin_message.await_args.kwargs["organization_id"] == ORGANIZATION.id


async def test_unpin_returns_no_body_and_an_inaccessible_conversation_is_missing(
    service: AsyncMock,
) -> None:
    service.unpin_message = AsyncMock()
    async with _client() as client:
        removed = await client.delete(f"{ROOT}/messages/{MESSAGE_ID}/pin")

    assert removed.status_code == 204
    assert removed.content == b""

    service.list_message_pins = AsyncMock(
        side_effect=NotFoundError(message="Conversation not found")
    )
    async with _client() as client:
        missing = await client.get(f"{ROOT}/message-pins")
    assert missing.status_code == 404


async def test_the_list_refuses_pages_above_its_bound(service: AsyncMock) -> None:
    async with _client() as client:
        response = await client.get(f"{ROOT}/message-pins", params={"limit": 101})

    assert response.status_code == 422
    service.list_message_pins.assert_not_awaited()

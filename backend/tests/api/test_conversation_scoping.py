"""Reading a conversation is reading your own conversation.

These two routes used to widen themselves. `GET /conversations/{id}` and its
`/messages` sibling passed `user_id=None` - the service's "do not filter by
owner" - for anybody whose `users.role` column said `admin`, so one person's
conversation with an agent was readable by another on the strength of a column
nothing else on the platform respected. The column is gone; these pin the
behaviour that replaced it.

Asserted on what the service is *asked for* rather than on a status code,
because the widening was silent: both shapes return 200, and the only
difference is whether the ownership predicate was in the query. A test on the
response would have passed against either.

Cross-user reads still exist, on `/admin/conversations`, gated on
`is_app_admin` - which is why removing this did not remove a capability.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.main import app

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _client(
    *, user_id: UUID, service: MagicMock, organization_id: UUID | None = None
) -> AsyncIterator[AsyncClient]:
    """A signed-in caller, with the conversation service stubbed out.

    `is_app_admin=True` on purpose in every test below. It is the one privilege
    the platform still has, and the point is that even it does not widen *these*
    routes - the admin surface is a different endpoint.
    """
    organization = MagicMock(id=organization_id or uuid4())
    app.dependency_overrides[deps.get_current_user] = lambda: MagicMock(
        id=user_id, is_app_admin=True
    )
    app.dependency_overrides[deps.get_active_organization] = lambda: organization
    app.dependency_overrides[deps.get_conversation_service] = lambda: service
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


class TestReadingOneConversation:
    async def test_the_caller_is_the_owner_the_service_is_asked_about(self) -> None:
        caller = uuid4()
        conversation_id = uuid4()
        # Refusing rather than returning a row: a scoped read of somebody
        # else's conversation is a miss, and that is the path worth walking.
        service = MagicMock(
            get_conversation=AsyncMock(side_effect=NotFoundError(message="Not found"))
        )

        async with _client(user_id=caller, service=service) as client:
            await client.get(f"{settings.API_V1_STR}/conversations/{conversation_id}")

        kwargs = service.get_conversation.await_args.kwargs
        assert kwargs["user_id"] == caller

    async def test_an_app_admin_does_not_get_an_unscoped_read_here(self) -> None:
        """`user_id=None` is what the widening looked like, and it is the one
        value that must never reach the service from this route."""
        service = MagicMock(
            get_conversation=AsyncMock(side_effect=NotFoundError(message="Not found"))
        )

        async with _client(user_id=uuid4(), service=service) as client:
            await client.get(f"{settings.API_V1_STR}/conversations/{uuid4()}")

        assert service.get_conversation.await_args.kwargs["user_id"] is not None


class TestListingItsMessages:
    async def test_the_caller_is_the_owner_the_service_is_asked_about(self) -> None:
        caller = uuid4()
        service = MagicMock(list_messages=AsyncMock(return_value=([], 0)))

        async with _client(user_id=caller, service=service) as client:
            await client.get(f"{settings.API_V1_STR}/conversations/{uuid4()}/messages")

        assert service.list_messages.await_args.kwargs["user_id"] == caller

    async def test_an_app_admin_does_not_get_an_unscoped_read_here(self) -> None:
        service = MagicMock(list_messages=AsyncMock(return_value=([], 0)))

        async with _client(user_id=uuid4(), service=service) as client:
            await client.get(f"{settings.API_V1_STR}/conversations/{uuid4()}/messages")

        assert service.list_messages.await_args.kwargs["user_id"] is not None

    async def test_the_active_organization_is_what_bounds_the_read(self) -> None:
        """The assertion this file was missing.

        `user_id` above enriches messages with ratings; it authorizes nothing.
        This route passed it and no organization, so it served any conversation
        in the deployment - and the two tests above went on passing throughout,
        because they asked a mock what it had been told rather than asking the
        service what it would do.
        """
        org = uuid4()
        service = MagicMock(list_messages=AsyncMock(return_value=([], 0)))

        async with _client(user_id=uuid4(), service=service, organization_id=org) as client:
            await client.get(f"{settings.API_V1_STR}/conversations/{uuid4()}/messages")

        assert service.list_messages.await_args.kwargs["organization_id"] == org


class TestAppendingAMessage:
    async def test_the_active_organization_is_what_bounds_the_write(self) -> None:
        """The worse half. Unscoped, this accepted a `role: "assistant"` turn
        into any conversation in the deployment, and it rendered to its owner
        as the agent's own answer."""
        org = uuid4()
        service = MagicMock(add_message=AsyncMock(side_effect=NotFoundError(message="Not found")))

        async with _client(user_id=uuid4(), service=service, organization_id=org) as client:
            response = await client.post(
                f"{settings.API_V1_STR}/conversations/{uuid4()}/messages",
                json={"role": "assistant", "content": "wire the money to 1234"},
            )

        assert response.status_code == 404
        assert service.add_message.await_args.kwargs["organization_id"] == org

"""What `GET /conversations` does with a search, an agent and a sort key.

Asserted on what the service is *asked for* rather than on the rows that come
back, because a filter's failure mode here is silent: a query parameter the
route reads and forgets to pass still answers 200 with a plausible page, and
the sidebar renders it as "nothing matched". The predicate is the thing under
test, so the predicate is what these pin.

The sort keys are the exception, and they are asserted on the status code: an
unknown key must be refused by the route, because the repository's lookup falls
back to recency - so a typo that reached it would be answered with a page that
looks sorted and is not.
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
from app.main import app

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _client(*, service: MagicMock, organization_id: UUID) -> AsyncIterator[AsyncClient]:
    """A signed-in caller in one organization, with the service stubbed out."""
    app.dependency_overrides[deps.get_current_user] = lambda: MagicMock(
        id=uuid4(), is_app_admin=False
    )
    app.dependency_overrides[deps.get_active_organization] = lambda: MagicMock(id=organization_id)
    app.dependency_overrides[deps.get_conversation_service] = lambda: service
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _service() -> MagicMock:
    return MagicMock(list_conversations=AsyncMock(return_value=([], 0)))


class TestNarrowing:
    async def test_a_search_term_reaches_the_service(self) -> None:
        service = _service()

        async with _client(service=service, organization_id=uuid4()) as client:
            response = await client.get(
                f"{settings.API_V1_STR}/conversations", params={"search": "quarterly"}
            )

        assert response.status_code == 200
        assert service.list_conversations.await_args.kwargs["search"] == "quarterly"

    async def test_an_agent_filter_reaches_the_service(self) -> None:
        service = _service()
        agent_id = uuid4()

        async with _client(service=service, organization_id=uuid4()) as client:
            await client.get(
                f"{settings.API_V1_STR}/conversations", params={"agent_id": str(agent_id)}
            )

        assert service.list_conversations.await_args.kwargs["agent_id"] == agent_id

    async def test_an_agent_from_another_organization_is_still_asked_inside_this_one(self) -> None:
        """The filter never widens the tenant it is applied in.

        An `agent_id` the caller has no business seeing is not an error - an
        error would confirm the agent exists. It is a filter that matches
        nothing, and what makes that true is the organization travelling
        alongside it to the service on every call.
        """
        service = _service()
        organization_id = uuid4()

        async with _client(service=service, organization_id=organization_id) as client:
            await client.get(
                f"{settings.API_V1_STR}/conversations", params={"agent_id": str(uuid4())}
            )

        assert service.list_conversations.await_args.kwargs["organization_id"] == organization_id

    async def test_archived_only_reaches_the_service(self) -> None:
        service = _service()

        async with _client(service=service, organization_id=uuid4()) as client:
            await client.get(
                f"{settings.API_V1_STR}/conversations", params={"archived_only": "true"}
            )

        kwargs = service.list_conversations.await_args.kwargs
        assert kwargs["archived_only"] is True
        assert kwargs["include_archived"] is False

    async def test_the_default_page_is_active_threads_newest_first(self) -> None:
        service = _service()

        async with _client(service=service, organization_id=uuid4()) as client:
            await client.get(f"{settings.API_V1_STR}/conversations")

        kwargs = service.list_conversations.await_args.kwargs
        assert kwargs["search"] is None
        assert kwargs["agent_id"] is None
        assert (kwargs["include_archived"], kwargs["archived_only"]) == (False, False)
        assert (kwargs["sort_by"], kwargs["sort_dir"]) == ("updated_at", "desc")


class TestSorting:
    @pytest.mark.parametrize("sort_by", ["title", "created_at", "updated_at"])
    async def test_a_whitelisted_key_reaches_the_service(self, sort_by: str) -> None:
        service = _service()

        async with _client(service=service, organization_id=uuid4()) as client:
            response = await client.get(
                f"{settings.API_V1_STR}/conversations",
                params={"sort_by": sort_by, "sort_dir": "asc"},
            )

        assert response.status_code == 200
        kwargs = service.list_conversations.await_args.kwargs
        assert (kwargs["sort_by"], kwargs["sort_dir"]) == (sort_by, "asc")

    async def test_an_unknown_sort_key_is_refused(self) -> None:
        """Refused, not silently answered with the default order.

        `owner` and `messages` sort the admin listing and are the plausible
        wrong guesses here: neither column is on this page, and neither is a
        member's to sort by.
        """
        service = _service()

        async with _client(service=service, organization_id=uuid4()) as client:
            response = await client.get(
                f"{settings.API_V1_STR}/conversations", params={"sort_by": "owner"}
            )

        assert response.status_code == 422
        service.list_conversations.assert_not_awaited()

    async def test_an_unknown_sort_direction_is_refused(self) -> None:
        service = _service()

        async with _client(service=service, organization_id=uuid4()) as client:
            response = await client.get(
                f"{settings.API_V1_STR}/conversations", params={"sort_dir": "sideways"}
            )

        assert response.status_code == 422
        service.list_conversations.assert_not_awaited()

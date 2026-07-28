"""The skills listing, through the app.

``tests/api/test_platform_routes.py`` proves the route is gated on
``skills:view`` and nothing else; ``tests/test_skills.py`` proves the service
filters and pages where the database is. What is left is the response itself:
the listing is where a card learns how many files a skill has, which shelf it
sits on, and whether it shipped with the deployment - none of which is a column
the ORM row hands over as-is.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]


def _row(name: str, *, category: str | None = None, files: int = 0) -> MagicMock:
    row = MagicMock()
    row.id = uuid.uuid4()
    row.name = name
    row.description = f"What {name} is for."
    row.category = category
    row.enabled = True
    row.resources = [MagicMock() for _ in range(files)]
    return row


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.list_skills = AsyncMock(
        return_value=(
            [
                # A real library name next to one no deployment ships: the
                # `built_in` flag is a name match, and both halves of it matter.
                _row("refund-policy", category="support", files=2),
                _row("quarterly-report", files=0),
            ],
            2,
        )
    )
    stub.list_categories = AsyncMock(return_value=["operations", "support"])
    return stub


@pytest.fixture
def client(service: MagicMock, mock_redis: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_skill_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(query: str = "") -> str:
    return f"{settings.API_V1_STR}/skills{query}"


async def _listed(open_client: OpenClient, query: str = "") -> dict[str, Any]:
    async with open_client() as http:
        response = await http.get(_url(query))
    assert response.status_code == 200
    return response.json()


class TestListing:
    async def test_each_skill_reports_how_many_files_it_carries(self, client: OpenClient):
        """The count is derived from the resources, not stored - so only the
        response can prove a card has a number to show."""
        body = await _listed(client)

        by_name = {item["name"]: item for item in body["items"]}
        assert by_name["refund-policy"]["file_count"] == 2
        assert by_name["quarterly-report"]["file_count"] == 0

    async def test_a_skill_sharing_a_library_name_is_marked_built_in(self, client: OpenClient):
        """Installing copies, so the name is the only trace of where a skill
        came from - and a name the library never shipped must stay unmarked."""
        body = await _listed(client)

        by_name = {item["name"]: item for item in body["items"]}
        assert by_name["refund-policy"]["built_in"] is True
        assert by_name["quarterly-report"]["built_in"] is False

    async def test_each_skill_names_its_category_and_none_is_allowed(self, client: OpenClient):
        body = await _listed(client)

        by_name = {item["name"]: item for item in body["items"]}
        assert by_name["refund-policy"]["category"] == "support"
        assert by_name["quarterly-report"]["category"] is None

    async def test_the_filter_choices_ride_along_with_every_page(
        self, client: OpenClient, service: MagicMock
    ):
        """The chips come from the whole organization, not from the page - a
        category whose skills fell on page two is still a chip on page one."""
        body = await _listed(client)

        assert body["categories"] == ["operations", "support"]
        assert service.list_categories.await_count == 1

    async def test_the_category_filter_and_sort_reach_the_service(
        self, client: OpenClient, service: MagicMock
    ):
        await _listed(client, "?category=support&sort=updated")

        kwargs = service.list_skills.call_args.kwargs
        assert kwargs["category"] == "support"
        assert kwargs["sort"] == "updated"

    async def test_a_sort_the_repository_does_not_know_is_refused(self, client: OpenClient):
        """`sort` is a Literal, so a typo is a 422 at the edge rather than an
        ORDER BY built from request input."""
        async with client() as http:
            response = await http.get(_url("?sort=oldest"))

        assert response.status_code == 422

"""The skills listing, through the app.

`tests/api/test_platform_routes.py` proves the route is gated on
`skills:view` and nothing else; `tests/test_skills.py` proves the service
filters and pages where the database is. What is left is the response itself:
the listing is where a card learns how many files a skill has, which shelf it
sits on, and whether it shipped with the deployment - none of which is a column
the ORM row hands over as-is.

Which is why these run the real service and stub the repository instead: the
assembly lives in `SkillService.list_readable`, and a stubbed service would
prove only that the route returns whatever it was handed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.skills import SkillService

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
def repo() -> MagicMock:
    """The two queries the listing makes, stubbed at the database edge."""
    stub = MagicMock()
    stub.list_visible = AsyncMock(
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
def client(repo: MagicMock, mock_redis: MagicMock) -> Iterator[OpenClient]:
    # An Owner reaches every skill in the organization, so the listing resolves
    # no grants and the repository is the only thing left to stand in for.
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_skill_service] = lambda: SkillService(MagicMock())

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    with (
        patch("app.services.skills.skill_repo.list_visible", repo.list_visible),
        patch("app.services.skills.skill_repo.list_categories", repo.list_categories),
    ):
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
        self, client: OpenClient, repo: MagicMock
    ):
        """The chips come from the whole organization, not from the page - a
        category whose skills fell on page two is still a chip on page one."""
        body = await _listed(client)

        assert body["categories"] == ["operations", "support"]
        assert repo.list_categories.await_count == 1

    async def test_the_category_filter_and_sort_reach_the_query(
        self, client: OpenClient, repo: MagicMock
    ):
        """`category` repeats: two occurrences mean "either shelf", and both
        must reach the query - an encoding that kept the last one would
        silently narrow the filter."""
        await _listed(client, "?category=support&category=devops&sort=updated")

        kwargs = repo.list_visible.call_args.kwargs
        assert kwargs["categories"] == ["support", "devops"]
        assert kwargs["sort"] == "updated"

    async def test_a_sort_the_repository_does_not_know_is_refused(self, client: OpenClient):
        """`sort` is a Literal, so a typo is a 422 at the edge rather than an
        ORDER BY built from request input."""
        async with client() as http:
            response = await http.get(_url("?sort=oldest"))

        assert response.status_code == 422

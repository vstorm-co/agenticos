"""Browsing every workspace the organization's agents keep.

`tests/api/test_platform_routes.py` proves all three routes demand
`connections:manage`. What is left is the shape, and one property behind it: the
listing carries no files. A deployment can hold a workspace per warm conversation,
so reading each one to render a table would be a query or a round trip per row for
a page nobody has asked a question of yet.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()
_WORKSPACE_ID = uuid.uuid4()
_AGENT_ID = uuid.uuid4()


def _row(**overrides: Any) -> MagicMock:
    row = MagicMock(
        id=_WORKSPACE_ID,
        agent_id=_AGENT_ID,
        conversation_id=uuid.uuid4(),
        scope="conversation",
        backend="state",
        bytes_total=2048,
        version=3,
        last_used_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.all_for_organization = AsyncMock(return_value=[(_row(), "Analyst")])
    stub.files_of = AsyncMock(
        return_value=(
            _row(),
            [{"path": "/uploads/report.csv", "size": 128, "is_dir": False}],
        )
    )
    stub.read_file_of = AsyncMock(return_value="month,total")
    return stub


@pytest.fixture
def client(service: MagicMock, mock_redis: MagicMock) -> Iterator[Any]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_sandbox_workspace_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(tail: str) -> str:
    return f"{settings.API_V1_STR}/sandbox-workspaces{tail}"


class TestListing:
    async def test_a_workspace_is_named_by_its_agent_and_who_shares_it(self, client) -> None:
        async with client() as opened:
            response = await opened.get(_url(""))

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["agent_name"] == "Analyst"
        assert body["items"][0]["owner_label"] == "This conversation"
        assert body["items"][0]["bytes_total"] == 2048

    async def test_the_listing_carries_no_files(self, client) -> None:
        """One per warm conversation, and reading each would be a round trip per
        row for a page nobody has asked a question of yet."""
        async with client() as opened:
            response = await opened.get(_url(""))

        assert "items" in response.json()
        assert "files" not in response.json()["items"][0]

    async def test_an_organization_with_none_says_zero_rather_than_failing(
        self, client, service
    ) -> None:
        service.all_for_organization = AsyncMock(return_value=[])

        async with client() as opened:
            response = await opened.get(_url(""))

        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}


class TestOpeningOne:
    async def test_the_files_come_with_whose_workspace_it_is(self, client) -> None:
        async with client() as opened:
            response = await opened.get(_url(f"/{_WORKSPACE_ID}/files"))

        assert response.status_code == 200
        body = response.json()
        assert body["items"][0]["path"] == "/uploads/report.csv"
        assert body["owner_label"] == "This conversation"

    async def test_another_organizations_workspace_is_a_404(self, client, service) -> None:
        """Reported as missing rather than refused, so an id cannot be used to
        find out which workspaces exist elsewhere."""
        service.files_of = AsyncMock(side_effect=NotFoundError(message="Workspace not found"))

        async with client() as opened:
            response = await opened.get(_url(f"/{uuid.uuid4()}/files"))

        assert response.status_code == 404

    async def test_one_file_comes_back_as_text(self, client) -> None:
        async with client() as opened:
            response = await opened.get(
                _url(f"/{_WORKSPACE_ID}/file"), params={"path": "/uploads/report.csv"}
            )

        assert response.status_code == 200
        assert response.json()["content"] == "month,total"

    async def test_a_path_that_is_not_there_is_a_404(self, client, service) -> None:
        service.read_file_of = AsyncMock(return_value=None)

        async with client() as opened:
            response = await opened.get(_url(f"/{_WORKSPACE_ID}/file"), params={"path": "/nope"})

        assert response.status_code == 404

    async def test_the_path_is_a_query_parameter_because_paths_have_slashes(self, client) -> None:
        """A path parameter would need escaping the client has to get right, or a
        catch-all route that swallows the ones beside it."""
        async with client() as opened:
            response = await opened.get(
                _url(f"/{_WORKSPACE_ID}/file"), params={"path": "/a/b/c.txt"}
            )

        assert response.status_code == 200
        assert response.json()["path"] == "/a/b/c.txt"

    async def test_asking_for_a_file_without_naming_one_is_refused(self, client, service) -> None:
        async with client() as opened:
            response = await opened.get(_url(f"/{_WORKSPACE_ID}/file"))

        assert response.status_code == 422
        service.read_file_of.assert_not_called()

"""The context-file routes, through the app.

`tests/api/test_platform_routes.py` proves the collection routes are gated on
`context:view`/`context:edit` and the per-file routes delegate to the service;
`tests/test_context_service.py` proves the service filters and refuses where the
database is. What is left is the five handlers themselves and the response
shapes they return - the list carries modes and sizes, a read carries the body,
a create answers 201 and a delete 204.

These run the real service with the repository stubbed at the database edge, so
the assertions are about what the route returns rather than about a stub echoing
its input.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.context import ContextFile
from app.db.models.resource_grant import Visibility
from app.main import app
from app.services.context import ContextService

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

CONTEXT_PATH = "app.services.context"


def _row(name: str, *, mode: str = "inject") -> ContextFile:
    return ContextFile(
        id=uuid.uuid4(),
        organization_id=_ORGANIZATION_ID,
        owner_user_id=uuid.uuid4(),
        visibility=Visibility.PRIVATE.value,
        name=name,
        description=f"What {name} is.",
        content="# body\n\nsome standing context",
        format="md",
        mode=mode,
        enabled=True,
    )


@pytest.fixture
def client(mock_redis: MagicMock) -> Iterator[OpenClient]:
    # An Owner reaches every file, so resolve_access passes on role scope alone
    # and no grant lookup touches the stubbed session.
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_context_service] = lambda: ContextService(MagicMock())

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/context{suffix}"


class TestListing:
    async def test_the_listing_carries_mode_and_size_without_the_body(self, client: OpenClient):
        rows = [_row("glossary", mode="inject"), _row("runbook", mode="link")]
        with patch(
            f"{CONTEXT_PATH}.context_repo.list_visible", new=AsyncMock(return_value=(rows, 2))
        ):
            async with client() as http:
                response = await http.get(_url())
        assert response.status_code == 200
        body = response.json()
        by_name = {item["name"]: item for item in body["items"]}
        assert by_name["glossary"]["mode"] == "inject"
        assert by_name["runbook"]["mode"] == "link"
        assert by_name["glossary"]["size_bytes"] > 0
        assert "content" not in by_name["glossary"]

    async def test_a_sort_the_repository_does_not_know_is_refused(self, client: OpenClient):
        async with client() as http:
            response = await http.get(_url("?sort=oldest"))
        assert response.status_code == 422


class TestCreate:
    async def test_creating_a_file_answers_201_with_the_body(self, client: OpenClient):
        created = _row("glossary", mode="link")
        with (
            patch(f"{CONTEXT_PATH}.context_repo.get_by_name", new=AsyncMock(return_value=None)),
            patch(f"{CONTEXT_PATH}.context_repo.create", new=AsyncMock(return_value=created)),
            patch(f"{CONTEXT_PATH}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.post(
                    _url(),
                    json={"name": "glossary", "description": "terms", "mode": "link"},
                )
        assert response.status_code == 201
        assert response.json()["mode"] == "link"
        assert response.json()["content"] == created.content

    async def test_an_invalid_mode_is_refused_at_the_edge(self, client: OpenClient):
        async with client() as http:
            response = await http.post(_url(), json={"name": "x", "mode": "sometimes"})
        assert response.status_code == 422


class TestGetPatchDelete:
    async def test_reading_one_file_returns_its_body(self, client: OpenClient):
        row = _row("glossary")
        with patch(f"{CONTEXT_PATH}.context_repo.get", new=AsyncMock(return_value=row)):
            async with client() as http:
                response = await http.get(_url(f"/{row.id}"))
        assert response.status_code == 200
        assert response.json()["content"] == row.content

    async def test_editing_a_file_returns_the_updated_row(self, client: OpenClient):
        row = _row("glossary")
        with (
            patch(f"{CONTEXT_PATH}.context_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{CONTEXT_PATH}.context_repo.update", new=AsyncMock(return_value=row)),
            patch(f"{CONTEXT_PATH}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.patch(_url(f"/{row.id}"), json={"content": "new"})
        assert response.status_code == 200

    async def test_deleting_a_file_answers_204(self, client: OpenClient):
        row = _row("glossary")
        with (
            patch(f"{CONTEXT_PATH}.context_repo.get", new=AsyncMock(return_value=row)),
            patch(f"{CONTEXT_PATH}.resource_grant_repo.delete_for_resource", new=AsyncMock()),
            patch(f"{CONTEXT_PATH}.context_repo.delete", new=AsyncMock()),
            patch(f"{CONTEXT_PATH}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.delete(_url(f"/{row.id}"))
        assert response.status_code == 204

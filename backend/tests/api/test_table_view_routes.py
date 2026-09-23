"""The Table Views routes, through the app: the wire itself.

`tests/integration/test_table_views.py` proves what the service does against a
database; what is left here is status codes and the request/response shape a
client builds on, the same split `test_virtual_table_routes.py` documents for
its own routes.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.table_view import TableViewList, TableViewRead

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_TABLE = uuid.uuid4()
_VIEW = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]


def _view() -> TableViewRead:
    return TableViewRead(
        id=_VIEW,
        table_id=_TABLE,
        owner_user_id=uuid.uuid4(),
        name="Board",
        kind="kanban",
        visibility="private",
        config={},
        can_manage=True,
        created_at=datetime(2026, 9, 23, tzinfo=UTC),
    )


@pytest.fixture
def service() -> MagicMock:
    return MagicMock(
        list_views=AsyncMock(return_value=TableViewList(items=[_view()], total=1)),
        create_view=AsyncMock(return_value=_view()),
        get_view=AsyncMock(return_value=_view()),
        update_view=AsyncMock(return_value=_view()),
        delete_view=AsyncMock(return_value=None),
    )


@pytest.fixture
def client(mock_redis: MagicMock, service: MagicMock) -> AsyncIterator[OpenClient]:
    context = AuthContext(user_id=uuid.uuid4(), organization_id=_ORG, role=OrgRoleName.OWNER)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_table_view_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/tables/{_TABLE}/views{suffix}"


async def test_listing_answers_with_the_callers_views(client, service):
    async with client() as http:
        response = await http.get(_url(), params={"kind": "kanban"})

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert service.list_views.await_args.kwargs == {"kind": "kanban"}


async def test_creating_a_view_is_a_201(client):
    async with client() as http:
        response = await http.post(_url(), json={"name": "Board", "kind": "kanban"})

    assert response.status_code == 201
    assert response.json()["name"] == "Board"


async def test_getting_updating_and_deleting_one_view(client, service):
    async with client() as http:
        got = await http.get(_url(f"/{_VIEW}"))
        updated = await http.patch(_url(f"/{_VIEW}"), json={"name": "Renamed"})
        deleted = await http.delete(_url(f"/{_VIEW}"))

    assert got.status_code == 200
    assert updated.status_code == 200
    assert deleted.status_code == 204
    assert service.update_view.await_args.args[-1].name == "Renamed"


async def test_a_view_nobody_may_manage_is_a_404(client, service):
    service.update_view.side_effect = NotFoundError(
        message="View not found", details={"view_id": _VIEW}
    )

    async with client() as http:
        response = await http.patch(_url(f"/{_VIEW}"), json={"name": "Nope"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_a_taken_name_is_a_409(client, service):
    service.create_view.side_effect = AlreadyExistsError(
        message="A view named 'Board' already exists.", details={"name": "Board"}
    )

    async with client() as http:
        response = await http.post(_url(), json={"name": "Board", "kind": "table"})

    assert response.status_code == 409

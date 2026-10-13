"""The folder routes, through the app (#2124).

`tests/integration/test_folders.py` proves the rules where the database is; these
prove each handler reaches the service with what it was sent and answers in the
shape the console reads - a 201 on create, a 204 on delete and on filing, and a
folder's audience and count beside it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.folder import Folder
from app.db.models.skill import Skill
from app.main import app
from app.services.folder import FolderView

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()
_SALES = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]


def _folder(name: str = "GTM") -> Folder:
    return Folder(
        id=uuid.uuid4(),
        organization_id=_ORGANIZATION_ID,
        kind="skill",
        parent_id=None,
        name=name,
        owner_user_id=uuid.uuid4(),
        visibility="private",
        created_at=datetime.now(UTC),
    )


def _view(folder: Folder) -> FolderView:
    return FolderView(folder=folder, group_ids=[_SALES], user_ids=[], item_count=3, can_edit=True)


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    for method in ("list", "create", "get", "view", "update", "set_audience", "delete", "file"):
        setattr(stub, method, AsyncMock())
    return stub


@pytest.fixture
def session() -> MagicMock:
    stub = MagicMock()
    stub.get = AsyncMock()
    return stub


@pytest.fixture
def client(mock_redis: MagicMock, service: MagicMock, session: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_folder_service] = lambda: service

    async def database() -> AsyncIterator[MagicMock]:
        yield session

    app.dependency_overrides[deps.get_db_session] = database

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(suffix: str = "", kind: str = "skills") -> str:
    return f"{settings.API_V1_STR}/folders/{kind}{suffix}"


async def test_the_listing_carries_each_folders_audience_and_count(
    client: OpenClient, service: MagicMock
) -> None:
    folder = _folder()
    service.list.return_value = [_view(folder)]

    async with client() as http:
        response = await http.get(_url())

    assert response.status_code == 200
    [item] = response.json()["items"]
    assert (item["name"], item["group_ids"], item["item_count"], item["can_edit"]) == (
        "GTM",
        [str(_SALES)],
        3,
        True,
    )
    assert service.list.await_args.kwargs == {"kind": "skill"}


async def test_creating_a_folder_answers_201(client: OpenClient, service: MagicMock) -> None:
    folder = _folder("Sales")
    service.create.return_value = folder
    service.view.return_value = _view(folder)

    async with client() as http:
        response = await http.post(_url(), json={"name": "Sales", "group_ids": [str(_SALES)]})

    assert response.status_code == 201
    assert response.json()["name"] == "Sales"
    data = service.create.await_args.kwargs["data"]
    assert (data.name, data.group_ids, data.visibility.value) == ("Sales", [_SALES], "private")


async def test_a_folder_is_renamed_moved_and_re_audienced(
    client: OpenClient, service: MagicMock
) -> None:
    folder = _folder()
    service.get.return_value = folder
    service.update.return_value = folder
    service.set_audience.return_value = folder
    service.view.return_value = _view(folder)

    async with client() as http:
        renamed = await http.patch(_url(f"/{folder.id}"), json={"name": "GTM EU", "to_top": True})
        audienced = await http.put(_url(f"/{folder.id}/audience"), json={"visibility": "org"})

    assert (renamed.status_code, audienced.status_code) == (200, 200)
    update = service.update.await_args.args[2]
    assert (update.name, update.to_top) == ("GTM EU", True)
    assert service.set_audience.await_args.args[2].visibility.value == "org"


async def test_deleting_a_folder_says_where_its_contents_go(
    client: OpenClient, service: MagicMock
) -> None:
    folder = _folder()
    target = uuid.uuid4()
    service.get.return_value = folder

    async with client() as http:
        response = await http.delete(_url(f"/{folder.id}?move_to={target}"))

    assert response.status_code == 204
    assert service.delete.await_args.kwargs == {"move_to": target}


async def test_filing_a_resource_loads_it_in_the_callers_organization(
    client: OpenClient, service: MagicMock, session: MagicMock
) -> None:
    skill = Skill(id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, name="playbook")
    session.get.return_value = skill
    folder_id = uuid.uuid4()

    async with client() as http:
        response = await http.put(_url(f"/items/{skill.id}"), json={"folder_id": str(folder_id)})

    assert response.status_code == 204
    assert service.file.await_args.kwargs == {
        "kind": "skill",
        "resource": skill,
        "folder_id": folder_id,
    }


async def test_another_organizations_resource_is_not_found(
    client: OpenClient, service: MagicMock, session: MagicMock
) -> None:
    session.get.return_value = Skill(id=uuid.uuid4(), organization_id=uuid.uuid4(), name="x")

    async with client() as http:
        response = await http.put(_url(f"/items/{uuid.uuid4()}"), json={"folder_id": None})

    assert response.status_code == 404
    service.file.assert_not_awaited()


@pytest.mark.parametrize("kind", ["apps", "context", "kb"])
async def test_every_kind_has_its_folders(
    client: OpenClient, service: MagicMock, kind: str
) -> None:
    service.list.return_value = []

    async with client() as http:
        response = await http.get(_url(kind=kind))

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}

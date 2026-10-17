"""The project routes, through the app.

`tests/test_project_service.py` proves who may see, use and change a project.
What is left is the HTTP layer: creating one is gated on `projects:edit` before
the service is reached, each handler answers its status and shape, and a file
listing reads as a project's even before its container exists.
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
from app.main import app
from app.schemas.conversation import ChatPerson, ChatReader, ProjectChatRead
from app.schemas.project import ProjectRead
from app.services.sandbox_workspace import WorkspaceContents

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()
PROJECT_ID = uuid.uuid4()

OpenClient = Callable[[str], AbstractAsyncContextManager[AsyncClient]]


def _read() -> ProjectRead:
    return ProjectRead(
        id=PROJECT_ID,
        name="Launch",
        instructions="Write in British English.",
        visibility="private",
        backend="service",
        can_use=True,
        can_edit=True,
        created_at=datetime(2026, 10, 17, tzinfo=UTC),
    )


@pytest.fixture
def service() -> MagicMock:
    project = MagicMock(backend="service")
    return MagicMock(
        list_projects=AsyncMock(return_value={"items": [_read()], "total": 1}),
        create=AsyncMock(return_value=project),
        get=AsyncMock(return_value=project),
        update=AsyncMock(return_value=project),
        delete=AsyncMock(),
        read=AsyncMock(return_value=_read()),
        files=AsyncMock(return_value=(project, None, WorkspaceContents(entries=[]))),
        file_bytes=AsyncMock(return_value=b"# Notes\n"),
        add_file=AsyncMock(return_value="data/in.csv"),
        add_folder=AsyncMock(return_value="docs"),
        remove=AsyncMock(),
        chats=AsyncMock(return_value=([], 0)),
    )


@pytest.fixture
def client(mock_redis: MagicMock, service: MagicMock) -> Iterator[OpenClient]:
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_project_service] = lambda: service

    @asynccontextmanager
    async def open_client(role: str = OrgRoleName.OWNER) -> AsyncIterator[AsyncClient]:
        context = AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role=role)
        app.dependency_overrides[deps.get_auth_context] = lambda: context
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


async def test_a_viewer_cannot_create_a_project(client: OpenClient, service: MagicMock) -> None:
    async with client(OrgRoleName.VIEWER) as http:
        response = await http.post("/api/v1/projects", json={"name": "Launch"})
    assert response.status_code == 403
    service.create.assert_not_awaited()


async def test_a_project_is_listed_created_read_changed_and_deleted(
    client: OpenClient, service: MagicMock
) -> None:
    async with client() as http:
        listed = await http.get("/api/v1/projects", params={"q": "lau"})
        created = await http.post("/api/v1/projects", json={"name": "Launch"})
        read = await http.get(f"/api/v1/projects/{PROJECT_ID}")
        changed = await http.patch(f"/api/v1/projects/{PROJECT_ID}", json={"instructions": "x"})
        deleted = await http.delete(f"/api/v1/projects/{PROJECT_ID}")

    assert listed.json()["items"][0]["name"] == "Launch"
    assert service.list_projects.await_args.kwargs["search"] == "lau"
    assert created.status_code == 201 and created.json()["can_edit"] is True
    assert read.json()["id"] == str(PROJECT_ID)
    assert service.update.await_args.args[2].instructions == "x"
    assert changed.status_code == 200
    assert deleted.status_code == 204


async def test_an_empty_project_lists_as_the_projects_own_folder(client: OpenClient) -> None:
    async with client() as http:
        response = await http.get(f"/api/v1/projects/{PROJECT_ID}/files")
    body = response.json()
    assert body["scope"] == "project"
    assert body["owner_label"] == "This project"
    assert (body["items"], body["bytes_total"], body["bytes_limit"]) == ([], 0, None)


async def test_a_listing_names_each_file_and_the_container_holding_them(
    client: OpenClient, service: MagicMock
) -> None:
    row = MagicMock(backend="state", scope="project", bytes_total=12)
    contents = WorkspaceContents(
        entries=[{"path": "notes.md", "size": 12, "is_dir": False}],
        previews={"notes.md": "# Notes"},
    )
    service.files = AsyncMock(return_value=(MagicMock(), row, contents))
    async with client() as http:
        body = (await http.get(f"/api/v1/projects/{PROJECT_ID}/files")).json()
    assert body["backend"] == "state"
    assert body["owner_label"] == "This project, shared by every chat in it"
    assert body["items"][0] == {
        "path": "notes.md",
        "size": 12,
        "is_dir": False,
        "modified_at": None,
        "preview": "# Notes",
        "thumbnail": None,
    }
    assert body["bytes_limit"] is not None


async def test_files_are_read_uploaded_foldered_and_removed(
    client: OpenClient, service: MagicMock
) -> None:
    async with client() as http:
        raw = await http.get(
            f"/api/v1/projects/{PROJECT_ID}/files/raw", params={"path": "notes.md"}
        )
        named = await http.post(
            f"/api/v1/projects/{PROJECT_ID}/files",
            files={"file": ("in.csv", b"a,b", "text/csv")},
            data={"path": "data/in.csv"},
        )
        await http.post(
            f"/api/v1/projects/{PROJECT_ID}/files", files={"file": ("top.csv", b"a", "text/csv")}
        )
        folder = await http.post(f"/api/v1/projects/{PROJECT_ID}/folders", json={"path": "docs"})
        removed = await http.delete(f"/api/v1/projects/{PROJECT_ID}/files", params={"path": "docs"})

    assert raw.content == b"# Notes\n"
    assert named.status_code == 201 and named.json() == {"path": "data/in.csv"}
    assert service.add_file.await_args_list[0].kwargs == {"path": "data/in.csv", "data": b"a,b"}
    assert service.add_file.await_args_list[1].kwargs["path"] == "top.csv"
    assert folder.json() == {"path": "docs"}
    assert removed.status_code == 204
    assert service.remove.await_args.kwargs == {"path": "docs"}


async def test_a_projects_chats_are_listed_with_the_people_around_them(
    client: OpenClient, service: MagicMock
) -> None:
    chat = ProjectChatRead(
        id=uuid.uuid4(),
        title="Launch plan",
        project_id=PROJECT_ID,
        created_at=datetime(2026, 10, 17, tzinfo=UTC),
        owner=ChatPerson(user_id=uuid.uuid4(), name="Kacper"),
        seen_by=[
            ChatReader(
                user_id=uuid.uuid4(), name="Anna", read_at=datetime(2026, 10, 17, tzinfo=UTC)
            )
        ],
    )
    service.chats = AsyncMock(return_value=([chat], 1))
    async with client() as http:
        response = await http.get(
            f"/api/v1/projects/{PROJECT_ID}/chats", params={"skip": 50, "limit": 50}
        )
        too_many = await http.get(f"/api/v1/projects/{PROJECT_ID}/chats", params={"limit": 500})

    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["owner"]["name"] == "Kacper"
    assert body["items"][0]["seen_by"][0]["name"] == "Anna"
    assert body["items"][0]["working"] is None
    assert service.chats.await_args.args[1] == PROJECT_ID
    assert service.chats.await_args.kwargs == {"skip": 50, "limit": 50}
    assert too_many.status_code == 422


async def test_an_upload_is_read_no_further_than_one_byte_past_the_ceiling(
    client: OpenClient, service: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The service refuses an over-large file by its length; the route never
    copies more than that length's worth of a body that declared none."""
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    async with client() as http:
        await http.post(
            f"/api/v1/projects/{PROJECT_ID}/files",
            files={"file": ("big.bin", b"x" * (3 * 1024 * 1024))},
        )
    assert len(service.add_file.await_args.kwargs["data"]) == 1024 * 1024 + 1

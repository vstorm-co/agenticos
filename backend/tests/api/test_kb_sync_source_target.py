"""A sync source records the knowledge base it is added to (#2551).

A source used to record an organization and a collection name only, so its sync
wrote into whichever base the name resolved to, and adding one to a base that
was not the organization's oldest of the name was refused with 400. Now the
knowledge-base routes hand the base in the path to the service, which records
it, and the routes naming a collection hand over the base
`CollectionAccessService.source_target` resolved and authorized. The recording
itself is unit-tested in `tests/test_sync_source_audit.py`, and end to end in
`tests/integration/test_sync_source_base.py`.
"""

import uuid
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.sync_source import SyncSourceRead

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_KB_ID = uuid.uuid4()


def _read() -> SyncSourceRead:
    return SyncSourceRead(
        id=str(uuid.uuid4()),
        organization_id=str(uuid.uuid4()),
        name="Docs",
        connector_type="gdrive",
        collection_name="handbook",
        knowledge_base_id=str(_KB_ID),
        config={},
        secret_id=None,
        sync_mode="new_only",
        schedule_minutes=None,
        is_active=True,
        last_sync_at=None,
        last_sync_status=None,
        last_error=None,
        created_at=None,
    )


@pytest.fixture
def wired(mock_db_session: Any, mock_redis: MagicMock) -> Iterator[dict[str, MagicMock]]:
    user = MagicMock()
    user.id = uuid.uuid4()
    context = AuthContext(user_id=user.id, organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)
    kb = MagicMock(id=_KB_ID, collection_name="handbook")
    kb_service = MagicMock(get_for_write=AsyncMock(return_value=kb))
    target = MagicMock(id=uuid.uuid4(), collection_name="handbook")
    access = MagicMock(
        sync_source=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        source_target=AsyncMock(return_value=target),
    )
    sources = MagicMock(
        create_source=AsyncMock(return_value=_read()),
        clone_source=AsyncMock(return_value=_read()),
        update_source=AsyncMock(return_value=_read()),
    )
    app.dependency_overrides[deps.get_db_session] = lambda: mock_db_session
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_knowledge_base_service] = lambda: kb_service
    app.dependency_overrides[deps.get_collection_access_service] = lambda: access
    app.dependency_overrides[deps.get_sync_source_service] = lambda: sources
    yield {"access": access, "sources": sources, "kb": kb, "target": target}
    app.dependency_overrides.clear()


async def _post(path: str, body: dict[str, object]) -> int:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"{settings.API_V1_STR}{path}", json=body)
    return response.status_code


async def test_a_source_added_to_a_base_records_that_base(wired) -> None:
    status = await _post(
        f"/kb/{_KB_ID}/sync-sources",
        {"name": "Docs", "connector_type": "gdrive", "config": {"folder_id": "abc"}},
    )

    assert status == 201
    call = wired["sources"].create_source.await_args
    assert call.kwargs["knowledge_base"] is wired["kb"]
    assert call.args[0].collection_name == "handbook"


async def test_a_source_cloned_into_a_base_records_that_base(wired) -> None:
    status = await _post(
        f"/kb/{_KB_ID}/sync-sources/{uuid.uuid4()}/clone",
        {"collection_name": "handbook", "name": "Docs copy"},
    )

    assert status == 201
    assert wired["sources"].clone_source.await_args.kwargs["knowledge_base"] is wired["kb"]


async def test_a_source_patched_from_a_base_keeps_that_base(wired) -> None:
    wired["access"].kb_sync_source = AsyncMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"{settings.API_V1_STR}/kb/{_KB_ID}/sync-sources/{uuid.uuid4()}",
            json={"collection_name": "handbook"},
        )

    assert response.status_code == 200
    assert wired["sources"].update_source.await_args.kwargs["knowledge_base"] is wired["kb"]


@pytest.mark.parametrize(
    ("path", "body", "method"),
    [
        (
            "/rag/sync/sources",
            {"name": "D", "connector_type": "gdrive", "collection_name": "handbook", "config": {}},
            "create_source",
        ),
        (
            "/org/integrations",
            {"name": "D", "connector_type": "gdrive", "collection_name": "handbook", "config": {}},
            "create_source",
        ),
        (
            f"/rag/sync/sources/{uuid.uuid4()}/clone",
            {"collection_name": "handbook"},
            "clone_source",
        ),
    ],
    # Named, because the clone path holds a random id: xdist workers must collect
    # the same test ids.
    ids=["rag create", "org integration create", "rag clone"],
)
async def test_a_source_pointed_at_a_name_records_the_base_it_was_authorized_for(
    wired, path: str, body: dict[str, object], method: str
) -> None:
    status = await _post(path, body)

    assert status == 201
    wired["access"].source_target.assert_awaited_once()
    assert getattr(wired["sources"], method).await_args.kwargs["knowledge_base"] is wired["target"]


@pytest.mark.parametrize("name", ["handbook", None], ids=["named", "detached"])
async def test_a_patch_by_name_records_the_base_the_repoint_resolved(
    wired, name: str | None
) -> None:
    """`repoint_target` decides whether the source moves and where; the route passes
    on what it answered - the resolved base, or `None` for no move or a detach."""
    wired["access"].repoint_target = AsyncMock(
        return_value=None if name is None else wired["target"]
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"{settings.API_V1_STR}/rag/sync/sources/{uuid.uuid4()}",
            json={"collection_name": name},
        )

    assert response.status_code == 200
    assert wired["access"].repoint_target.await_args.args[2] == name
    expected = None if name is None else wired["target"]
    assert wired["sources"].update_source.await_args.kwargs["knowledge_base"] is expected

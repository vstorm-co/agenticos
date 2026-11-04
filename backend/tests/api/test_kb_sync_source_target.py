"""A sync source is added only to the knowledge base its sync writes into (#2537).

A source records an organization and a collection name, not a base, so its sync
writes into the base the name resolves to. Since bases of one organization no
longer share their chunks, a source added to another same-named base would sync
into the resolved one and not be listed where it was added. These pin that the
knowledge-base routes ask `CollectionAccessService.new_source_feeds` before any
row is written; the rule itself is unit-tested in `tests/test_collection_access.py`.
"""

import uuid
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_KB_ID = uuid.uuid4()


@pytest.fixture
def wired(mock_db_session: Any, mock_redis: MagicMock) -> Iterator[dict[str, MagicMock]]:
    user = MagicMock()
    user.id = uuid.uuid4()
    context = AuthContext(user_id=user.id, organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)
    kb_service = MagicMock(
        get_for_write=AsyncMock(return_value=MagicMock(id=_KB_ID, collection_name="handbook"))
    )
    access = MagicMock(
        new_source_feeds=AsyncMock(
            side_effect=BadRequestError(message="elsewhere", details={"kb_id": str(_KB_ID)})
        ),
        sync_source=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
    )
    sources = MagicMock(create_source=AsyncMock(), clone_source=AsyncMock())
    app.dependency_overrides[deps.get_db_session] = lambda: mock_db_session
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_knowledge_base_service] = lambda: kb_service
    app.dependency_overrides[deps.get_collection_access_service] = lambda: access
    app.dependency_overrides[deps.get_sync_source_service] = lambda: sources
    yield {"access": access, "sources": sources}
    app.dependency_overrides.clear()


async def test_adding_a_source_to_a_base_it_would_not_feed_is_refused(wired) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"{settings.API_V1_STR}/kb/{_KB_ID}/sync-sources",
            json={"name": "Docs", "connector_type": "gdrive", "config": {"folder_id": "abc"}},
        )

    assert response.status_code == 400
    wired["sources"].create_source.assert_not_awaited()


async def test_cloning_a_source_into_a_base_it_would_not_feed_is_refused(wired) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"{settings.API_V1_STR}/kb/{_KB_ID}/sync-sources/{uuid.uuid4()}/clone",
            json={"collection_name": "handbook", "name": "Docs copy"},
        )

    assert response.status_code == 400
    wired["sources"].clone_source.assert_not_awaited()

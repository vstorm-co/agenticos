"""Every manual-trigger HTTP surface reports a paused source without queueing."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.sync_source import SyncSource
from app.main import app
from app.repositories import sync_log_repo, sync_source_repo
from app.services import sync_source as source_module
from app.services.sync_source import PAUSED_SOURCE, SyncSourceService

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("surface", ["rag", "kb", "integration"])
async def test_a_manual_trigger_of_a_paused_source_returns_400_without_work(
    client: AsyncClient,
    mock_db_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)
    kb = KnowledgeBase(id=uuid4(), collection_name="docs")
    source = SyncSource(
        id=uuid4(), organization_id=ctx.organization_id, collection_name="docs", is_active=False
    )
    access = MagicMock(
        writable_sync_source=AsyncMock(return_value=source),
        kb_sync_source=AsyncMock(return_value=source),
        sync_source=AsyncMock(return_value=source),
    )
    kb_service = MagicMock(get_for_write=AsyncMock(return_value=kb))
    service = SyncSourceService(mock_db_session)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_collection_access_service] = lambda: access
    app.dependency_overrides[deps.get_knowledge_base_service] = lambda: kb_service
    app.dependency_overrides[deps.get_sync_source_service] = lambda: service
    monkeypatch.setattr(sync_source_repo, "get_by_id", AsyncMock(return_value=source))
    create_log, enqueue = AsyncMock(), AsyncMock()
    monkeypatch.setattr(sync_log_repo, "create", create_log)
    monkeypatch.setattr(source_module, "enqueue", enqueue)
    paths = {
        "rag": f"/rag/sync/sources/{source.id}/trigger",
        "kb": f"/kb/{kb.id}/sync-sources/{source.id}/trigger",
        "integration": f"/org/integrations/{source.id}/trigger",
    }

    response = await client.post(f"{settings.API_V1_STR}{paths[surface]}")

    assert response.status_code == 400
    assert response.json()["error"]["message"] == PAUSED_SOURCE
    create_log.assert_not_awaited()
    enqueue.assert_not_awaited()

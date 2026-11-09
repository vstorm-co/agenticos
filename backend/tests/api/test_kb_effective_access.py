"""The console receives the same write decision enforced by KB mutations."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.permissions import AuthContext
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.resource_grant import GrantLevel
from app.main import app
from app.services.knowledge_base import KnowledgeBaseService

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("scope", "role", "grant", "expected"),
    [
        ("org", "member", GrantLevel.READ, False),
        ("org", "viewer", GrantLevel.EDIT, True),
        ("app", "owner", None, False),
    ],
)
async def test_detail_serializes_effective_access(
    client: AsyncClient,
    mock_db_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
    role: str,
    grant: GrantLevel | None,
    expected: bool,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=role)
    kb = KnowledgeBase(
        id=uuid4(),
        name="Handbook",
        collection_name="handbook",
        scope=scope,
        organization_id=ctx.organization_id if scope == "org" else uuid4(),
        owner_user_id=uuid4(),
        visibility="private",
        is_default=False,
        ingestion_config={},
        embedding_model="text-embedding-3-small",
        embedding_provider="openrouter",
        embedding_dim=1536,
        created_at=datetime(2026, 11, 9, tzinfo=UTC),
    )
    monkeypatch.setattr(
        "app.repositories.knowledge_base_repo.get_by_id", AsyncMock(return_value=kb)
    )
    monkeypatch.setattr(
        "app.repositories.resource_grant_repo.get_level", AsyncMock(return_value=grant)
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_knowledge_base_service] = lambda: KnowledgeBaseService(
        mock_db_session
    )
    response = await client.get(f"/api/v1/kb/{kb.id}")
    assert response.status_code == 200
    assert response.json()["can_edit"] is expected
    assert response.json()["id"] == str(kb.id)

    monkeypatch.setattr("app.repositories.knowledge_base_repo.update", AsyncMock(return_value=kb))
    mutation = await client.patch(f"/api/v1/kb/{kb.id}", json={"description": "Updated"})
    assert mutation.status_code == (200 if expected else 403)
    if expected:
        assert mutation.json()["can_edit"] is True

"""GET /rag/documents pages rather than serializing every row (#27).

Unbounded, this selected every `rag_documents` row across the caller's readable
collections and held the whole set in memory to answer one request - multi-second
and tens of MB for a tenant with 50k documents. The service now pages and reports
the collection's own count, and the route takes the standard `skip`/`limit`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.rag_document import RAGDocument
from app.main import app
from app.repositories import rag_document as rag_document_repo
from app.schemas.rag import RAGTrackedDocumentList
from app.services.rag_document import RAGDocumentService, _tracked_item

pytestmark = pytest.mark.anyio


def _doc() -> RAGDocument:
    return RAGDocument(
        id=uuid.uuid4(),
        collection_name="docs",
        filename="report.pdf",
        filesize=1024,
        filetype="pdf",
        status="done",
        vector_document_id="vec-1",
        chunk_count=0,
        ingestion_config={},
    )


async def test_the_service_pages_and_reports_the_collection_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The total is the collection's count, not the length of the page returned,
    so a client can page the rest (#27). Without the fix the repo took no
    `skip`/`limit` and the service reported `len(docs)`."""
    page = [_doc(), _doc()]
    captured: dict[str, object] = {}

    async def get_all(
        _db: Any, *, collections: list[str], skip: int, limit: int
    ) -> tuple[list[RAGDocument], int]:
        captured.update(collections=collections, skip=skip, limit=limit)
        return page, 137

    monkeypatch.setattr(rag_document_repo, "get_all", get_all)

    result = await RAGDocumentService(db=cast("Any", None)).list_documents(
        collections=["c1"], skip=50, limit=25
    )

    assert captured == {"collections": ["c1"], "skip": 50, "limit": 25}
    assert len(result.items) == 2
    assert result.total == 137


@pytest.fixture
def client(mock_db_session: Any, mock_redis: MagicMock) -> Iterator[AsyncClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )
    access = MagicMock(readable_names_for=AsyncMock(return_value=["c1"]))
    listing = RAGTrackedDocumentList(
        items=[_tracked_item(_doc()), _tracked_item(_doc())], total=137
    )
    rag_doc_svc = MagicMock(list_documents=AsyncMock(return_value=listing))

    app.dependency_overrides[deps.get_db_session] = lambda: mock_db_session
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_collection_access_service] = lambda: access
    app.dependency_overrides[deps.get_rag_document_service] = lambda: rag_doc_svc

    transport = ASGITransport(app=app)
    opened = AsyncClient(transport=transport, base_url="http://test")
    opened.rag_doc_svc = rag_doc_svc  # type: ignore[attr-defined]
    yield opened
    app.dependency_overrides.clear()


async def test_the_route_respects_limit_and_reports_a_larger_total(client: AsyncClient) -> None:
    async with client as opened:
        response = await opened.get(f"{settings.API_V1_STR}/rag/documents", params={"limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] == 137
    opened.rag_doc_svc.list_documents.assert_awaited_once_with(  # type: ignore[attr-defined]
        collections=["c1"], skip=0, limit=2
    )


async def test_the_route_refuses_a_limit_over_the_ceiling(client: AsyncClient) -> None:
    """`le=100` per api-conventions, so an unbounded response cannot be asked for."""
    async with client as opened:
        response = await opened.get(f"{settings.API_V1_STR}/rag/documents", params={"limit": 5000})

    assert response.status_code == 422

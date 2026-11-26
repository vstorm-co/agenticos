"""Per-document indexing honors resource grants without promoting the caller's role."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.main import app
from app.services.collection_access import CollectionAccessService
from app.services.rag_document import RAGDocumentService

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("allowed", [True, False])
async def test_indexing_delegates_to_the_document_access_decision(
    client: AsyncClient, allowed: bool
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")
    document = RAGDocument(id=uuid4(), status=DocumentStatus.STORED)
    access = MagicMock(spec=CollectionAccessService)
    access.writable_document = AsyncMock(return_value=document)
    if not allowed:
        access.writable_document.side_effect = AuthorizationError(
            message="No edit access to this document"
        )
    service = MagicMock(spec=RAGDocumentService)
    service.retry_ingestion = AsyncMock(return_value=document)
    with patch.dict(
        app.dependency_overrides,
        {
            deps.get_auth_context: lambda: ctx,
            deps.get_collection_access_service: lambda: access,
            deps.get_rag_document_service: lambda: service,
        },
    ):
        response = await client.post(f"{settings.API_V1_STR}/rag/documents/{document.id}/retry")
    assert response.status_code == (200 if allowed else 403)
    access.writable_document.assert_awaited_once_with(ctx, str(document.id))
    if allowed:
        service.retry_ingestion.assert_awaited_once_with(str(document.id))
        assert response.json()["status"] == "processing"
    else:
        service.retry_ingestion.assert_not_awaited()

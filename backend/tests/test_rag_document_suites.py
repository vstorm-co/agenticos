"""A knowledge base's content changing is a change to the agents that search it."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.rag_document import RAGDocument
from app.services.rag_document import RAGDocumentService

pytestmark = pytest.mark.anyio


async def test_a_documents_knowledge_base_is_what_the_suites_hear_changed() -> None:
    doc = RAGDocument(organization_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())
    with patch(
        "app.services.eval_suite.EvalSuiteService.dependency_changed", AsyncMock()
    ) as changed:
        await RAGDocumentService(MagicMock())._content_changed(doc)

    changed.assert_awaited_once_with(
        organization_id=doc.organization_id,
        kind="knowledge_base",
        resource_id=doc.knowledge_base_id,
    )


@pytest.mark.parametrize("missing", ["organization_id", "knowledge_base_id"])
async def test_a_document_of_no_organizations_knowledge_base_changes_no_suite(missing: str) -> None:
    doc = RAGDocument(organization_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())
    setattr(doc, missing, None)
    with patch(
        "app.services.eval_suite.EvalSuiteService.dependency_changed", AsyncMock()
    ) as changed:
        await RAGDocumentService(MagicMock())._content_changed(doc)

    changed.assert_not_awaited()

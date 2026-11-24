"""A run's private draft cannot escape its owner or spoof a retrieved hit."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.capabilities.knowledge._search import search_knowledge_base
from app.core.exceptions import ConfigurationError
from app.services.rag.filters import AppScope, RetrievalQuery, TenantScope, UnscopedScope
from app.services.rag.models import SearchResult
from app.services.rag.overlay import KnowledgeOverlay, OverlayDocument, active_overlay, with_overlay


def _doc():
    return OverlayDocument(
        topic_id=uuid4(),
        organization_id=uuid4(),
        collection_name="handbook",
        title="Draft",
        content="A verified-by-a-person passage",
    )


@pytest.mark.security
def test_only_the_exact_tenant_and_collection_can_search_the_overlay():
    doc = _doc()
    overlay = KnowledgeOverlay((doc,))
    assert overlay.matching(
        "handbook", RetrievalQuery(scope=TenantScope(organization_id=doc.organization_id))
    ) == (doc,)
    assert (
        overlay.matching(
            "other", RetrievalQuery(scope=TenantScope(organization_id=doc.organization_id))
        )
        == ()
    )
    for scope in [TenantScope(organization_id=uuid4()), AppScope(), UnscopedScope()]:
        assert overlay.matching("handbook", RetrievalQuery(scope=scope)) == ()


def test_nested_delegates_share_the_owner_and_cleanup_runs_after_failure():
    overlay = KnowledgeOverlay((_doc(),))
    assert active_overlay() is None
    with pytest.raises(RuntimeError), with_overlay(overlay):
        assert active_overlay() is overlay
        with with_overlay(overlay), with_overlay(None):
            assert overlay.documents
        assert overlay.documents
        nested = KnowledgeOverlay((_doc(),))
        with with_overlay(nested):
            assert active_overlay() is nested
        assert active_overlay() is overlay and nested.documents == ()
        raise RuntimeError("Model failed")
    assert active_overlay() is None and overlay.documents == ()


def test_no_overlay_is_the_ordinary_run():
    with with_overlay(None):
        assert active_overlay() is None


@pytest.mark.anyio
async def test_cancellation_clears_bodies_and_thread_embedding_inherits_the_context():
    overlay = KnowledgeOverlay((_doc(),))
    with pytest.raises(asyncio.CancelledError), with_overlay(overlay):
        assert await asyncio.to_thread(active_overlay) is overlay
        raise asyncio.CancelledError
    assert active_overlay() is None and not overlay.documents


def test_only_server_marked_final_hits_count_and_the_marker_is_not_serialized():
    doc = _doc()
    overlay = KnowledgeOverlay((doc,))
    for result in [
        SearchResult(content=doc.content, score=1, metadata={"overlay_token": str(doc.token)}),
        SearchResult(content=doc.content, score=1, overlay_token=uuid4()),
        SearchResult(content="Different content", score=1, overlay_token=doc.token),
    ]:
        overlay.record([result])
        assert overlay.returned_topic_ids == set()
    hit = SearchResult(content=doc.content, score=1, overlay_token=doc.token)
    overlay.record([hit, hit])
    assert overlay.returned_topic_ids == {doc.topic_id}
    assert "overlay_token" not in hit.model_dump()


@pytest.mark.anyio
async def test_an_unsupported_store_refuses_before_a_normal_search_can_hide_the_overlay():
    from unittest.mock import AsyncMock, MagicMock

    from app.core.exceptions import BadRequestError
    from app.services.rag.config import RAGSettings
    from app.services.rag.retrieval import RetrievalService
    from app.services.rag.vectorstore import BaseVectorStore

    doc = _doc()
    overlay = KnowledgeOverlay((doc,))
    store = MagicMock(spec=BaseVectorStore)
    store.supports_knowledge_overlay = False
    store.search = AsyncMock(return_value=[])
    service = RetrievalService(store, RAGSettings())
    with with_overlay(overlay), pytest.raises(BadRequestError, match="does not support"):
        await service.retrieve(
            "returns", "handbook", scope=TenantScope(organization_id=doc.organization_id)
        )
    assert overlay.failed
    store.search.assert_not_awaited()


@pytest.mark.anyio
async def test_a_refused_search_marks_the_overlay_failed_and_keeps_its_own_refusal():
    doc = _doc()
    overlay = KnowledgeOverlay((doc,))
    service = MagicMock()
    service.resolve_scope = AsyncMock(return_value=TenantScope(organization_id=doc.organization_id))
    service.retrieve = AsyncMock(
        side_effect=ConfigurationError(message="No embedding credential is configured")
    )
    with (
        patch(
            "app.agents.capabilities.knowledge._search.get_retrieval_service",
            return_value=service,
        ),
        with_overlay(overlay),
        pytest.raises(ConfigurationError, match="No embedding credential"),
    ):
        await search_knowledge_base(
            query="returns", kb_collection_names=["handbook"], organization_id=doc.organization_id
        )
    assert overlay.failed and overlay.returned_topic_ids == set()

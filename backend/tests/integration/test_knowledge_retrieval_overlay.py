"""Real pgvector ranking and filters with drafts held only in the current run."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agents.capabilities.knowledge._search import search_knowledge_base
from app.services.rag.config import RAGSettings
from app.services.rag.filters import RetrievalFilters, RetrievalQuery, TenantScope
from app.services.rag.overlay import KnowledgeOverlay, OverlayDocument, with_overlay
from app.services.rag.retrieval import RetrievalService
from tests.integration.test_rag_filter_scope import _insert, _store

pytestmark = pytest.mark.anyio


async def _world(engine):
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    store = _store(engine)
    embedder, _ = await store._for_collection("unused")
    embedder.embed_queries = MagicMock(side_effect=lambda texts: [[0.25] * 3 for _ in texts])
    collection = f"overlay_{uuid4().hex[:8]}"
    org = uuid4()
    doc = OverlayDocument(
        topic_id=uuid4(),
        organization_id=org,
        collection_name=collection,
        title="Proposed shipping policy",
        content="Returns are accepted within 30 days.",
    )
    return store, collection, org, doc


async def test_a_draft_is_query_local_and_never_written_to_the_collection(engine: AsyncEngine):
    store, collection, org, doc = await _world(engine)
    await _insert(store, collection, org=org, content="Stored handbook")
    scope = RetrievalQuery(scope=TenantScope(organization_id=org))
    overlay = KnowledgeOverlay((doc,))
    with with_overlay(overlay):
        hits = await store.search(collection, "returns", scope, limit=5)
        assert {hit.content for hit in hits} == {doc.content, "Stored handbook"}
        assert next(hit for hit in hits if hit.content == doc.content).overlay_token == doc.token
    assert overlay.documents == ()
    assert [hit.content for hit in await store.search(collection, "returns", scope)] == [
        "Stored handbook"
    ]


async def test_an_empty_collection_needs_no_persistent_table_to_check_a_draft(engine):
    store, collection, org, doc = await _world(engine)
    overlay = KnowledgeOverlay((doc,))
    scope = RetrievalQuery(scope=TenantScope(organization_id=org))
    with with_overlay(overlay):
        assert [hit.content for hit in await store.search(collection, "returns", scope)] == [
            doc.content
        ]
    assert not await store._collection_exists(collection)
    assert await store.search(collection, "returns", scope) == []


@pytest.mark.security
async def test_tenant_business_and_document_filters_still_deny_the_overlay(engine):
    store, collection, org, doc = await _world(engine)
    overlay = KnowledgeOverlay((doc,))
    with with_overlay(overlay):
        for query in [
            RetrievalQuery(scope=TenantScope(organization_id=uuid4())),
            RetrievalQuery(
                scope=TenantScope(organization_id=org, authorized_document_ids=frozenset())
            ),
            RetrievalQuery(
                scope=TenantScope(organization_id=org), filters=RetrievalFilters(source=["s3"])
            ),
            RetrievalQuery(
                scope=TenantScope(organization_id=org),
                filters=RetrievalFilters(document_type=["pdf"]),
            ),
            RetrievalQuery(
                scope=TenantScope(organization_id=org),
                filters=RetrievalFilters(parent_doc_id="an-existing-document"),
            ),
        ]:
            assert await store.search(collection, "returns", query) == []


async def test_only_the_final_search_response_credits_a_draft(engine):
    store, collection, org, doc = await _world(engine)
    service = RetrievalService(store, RAGSettings())
    service.resolve_scope = AsyncMock(return_value=TenantScope(organization_id=org))
    overlay = KnowledgeOverlay((doc,))
    with (
        with_overlay(overlay),
        patch(
            "app.agents.capabilities.knowledge._search.get_retrieval_service", return_value=service
        ),
    ):
        response = await search_knowledge_base("returns", [collection], organization_id=org)
        assert doc.content in response
        assert overlay.returned_topic_ids == {doc.topic_id}


async def test_a_draft_ranked_out_of_the_final_response_is_not_credited(engine):
    store, collection, org, doc = await _world(engine)
    await _insert(store, collection, org=org, content="Existing relevant handbook")
    embedder, _ = await store._for_collection(collection)
    embedder.embed_queries = MagicMock(return_value=[[0.25] * 3, [-0.25] * 3])
    service = RetrievalService(store, RAGSettings())
    service.resolve_scope = AsyncMock(return_value=TenantScope(organization_id=org))
    overlay = KnowledgeOverlay((doc,))
    with (
        with_overlay(overlay),
        patch(
            "app.agents.capabilities.knowledge._search.get_retrieval_service", return_value=service
        ),
    ):
        response = await search_knowledge_base(
            "returns", [collection], top_k=1, organization_id=org
        )
        assert "Existing relevant handbook" in response and doc.content not in response
        assert overlay.returned_topic_ids == set()

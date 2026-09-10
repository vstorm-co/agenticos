"""The public `filter` string becomes a typed `parent_doc_id` before the store.

The store used to take the scalar-filter string and regex the `parent_doc_id`
back out of it on every search; the parse now happens once, in the retrieval
service, so the store takes a typed argument and never speaks the DSL.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rag.models import SearchResult
from app.services.rag.retrieval import RetrievalService, _parent_doc_id_from_filter

pytestmark = pytest.mark.anyio


def _retrieval_over(store: MagicMock) -> RetrievalService:
    settings = MagicMock()
    settings.enable_hybrid_search = False
    return RetrievalService(vector_store=store, settings=settings)


class TestParsingTheFilter:
    def test_reads_the_document_out_of_the_scalar_filter(self):
        assert _parent_doc_id_from_filter('parent_doc_id == "doc-42"') == "doc-42"

    def test_tolerates_the_spacing_the_grammar_allows(self):
        assert _parent_doc_id_from_filter('parent_doc_id=="doc-42"') == "doc-42"

    def test_no_document_clause_means_no_restriction(self):
        assert _parent_doc_id_from_filter('filetype == "pdf"') is None

    def test_an_empty_filter_means_no_restriction(self):
        assert _parent_doc_id_from_filter("") is None


class TestThreadingItToTheStore:
    async def test_a_document_filter_reaches_the_store_typed(self):
        store = MagicMock()
        store.search = AsyncMock(return_value=[SearchResult(content="chunk", score=0.5)])

        await _retrieval_over(store).retrieve(
            query="anything", collection_name="handbook", filter='parent_doc_id == "doc-42"'
        )

        assert store.search.await_args.kwargs["parent_doc_id"] == "doc-42"

    async def test_no_filter_leaves_the_search_unrestricted(self):
        store = MagicMock()
        store.search = AsyncMock(return_value=[])

        await _retrieval_over(store).retrieve(query="anything", collection_name="handbook")

        assert store.search.await_args.kwargs["parent_doc_id"] is None

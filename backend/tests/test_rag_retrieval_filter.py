"""The public `filter` string becomes a typed `parent_doc_id` before the store.

The store used to take the scalar-filter string and regex the `parent_doc_id`
back out of it on every search; the parse now happens once, in the retrieval
service, so the store takes a typed argument and never speaks the DSL.
"""

import uuid
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
        store.resolve_tenant = AsyncMock(return_value=None)
        store.search = AsyncMock(return_value=[SearchResult(content="chunk", score=0.5)])

        await _retrieval_over(store).retrieve(
            query="anything", collection_name="handbook", filter='parent_doc_id == "doc-42"'
        )

        assert store.search.await_args.kwargs["parent_doc_id"] == "doc-42"

    async def test_no_filter_leaves_the_search_unrestricted(self):
        store = MagicMock()
        store.resolve_tenant = AsyncMock(return_value=None)
        store.search = AsyncMock(return_value=[])

        await _retrieval_over(store).retrieve(query="anything", collection_name="handbook")

        assert store.search.await_args.kwargs["parent_doc_id"] is None


@pytest.mark.security
class TestThreadingTheAuthorizedTenant:
    """A caller that already authorized a knowledge base passes its `vector_tenant`,
    and the search reads under exactly that tenant rather than one the store would
    re-resolve from the name - which could prefer a same-named base the caller was
    not granted (#1684)."""

    async def test_an_explicit_tenant_is_used_and_not_re_resolved(self):
        org = uuid.uuid4()
        store = MagicMock()
        store.resolve_tenant = AsyncMock(side_effect=AssertionError("must not re-resolve"))
        store.search = AsyncMock(return_value=[])

        await _retrieval_over(store).retrieve(query="q", collection_name="handbook", tenant=org)

        assert store.search.await_args.kwargs["tenant"] == org

    async def test_an_explicit_none_reads_deployment_wide_without_resolving(self):
        """The disclosure case: the authorized base is app-scoped, so its tenant is
        `None`; the search must read the untagged rows, not let the resolver pick an
        org base sharing the name."""
        store = MagicMock()
        store.resolve_tenant = AsyncMock(side_effect=AssertionError("must not re-resolve"))
        store.search = AsyncMock(return_value=[])

        await _retrieval_over(store).retrieve(query="q", collection_name="handbook", tenant=None)

        assert store.search.await_args.kwargs["tenant"] is None

    async def test_an_omitted_tenant_falls_back_to_resolution(self):
        """The agent capability and the CLI hold only a name, so they omit it and the
        store resolves one from the collection for the searching organization."""
        resolved = uuid.uuid4()
        store = MagicMock()
        store.resolve_tenant = AsyncMock(return_value=resolved)
        store.search = AsyncMock(return_value=[])

        await _retrieval_over(store).retrieve(query="q", collection_name="handbook")

        store.resolve_tenant.assert_awaited_once()
        assert store.search.await_args.kwargs["tenant"] == resolved

    async def test_retrieve_multi_reads_each_collection_under_its_authorized_tenant(self):
        one, two = uuid.uuid4(), uuid.uuid4()
        store = MagicMock()
        store.resolve_tenant = AsyncMock(side_effect=AssertionError("must not re-resolve"))
        store.get_documents = AsyncMock(return_value=[])
        store.search = AsyncMock(return_value=[])

        await _retrieval_over(store).retrieve_multi(
            query="q",
            collection_names=["a", "b"],
            tenants={"a": one, "b": two},
        )

        by_collection = {
            call.kwargs["collection_name"]: call.kwargs["tenant"]
            for call in store.search.await_args_list
        }
        assert by_collection == {"a": one, "b": two}

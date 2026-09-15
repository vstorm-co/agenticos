"""The retrieval service composes a server scope + business filters for the store.

The public `filter` string is retired in favour of a typed `RetrievalFilters`
plus a server-trusted `RetrievalScope`; the deprecated string is folded into
`filters.parent_doc_id` by a full-match shim. The service composes the two into
one `RetrievalQuery` and threads it to every candidate-producing store call, so
no path (vector or the BM25 rerank) can skip enforcement.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError
from app.services.rag.filters import (
    AppScope,
    RetrievalFilters,
    TenantScope,
    UnscopedScope,
    resolve_legacy_filter,
)
from app.services.rag.models import SearchResult
from app.services.rag.retrieval import RetrievalService

pytestmark = pytest.mark.anyio


def _retrieval_over(store: MagicMock, *, hybrid: bool = False) -> RetrievalService:
    settings = MagicMock()
    settings.enable_hybrid_search = hybrid
    return RetrievalService(vector_store=store, settings=settings)


class TestTheLegacyFilterShim:
    def test_reads_the_document_out_of_a_full_match_string(self):
        filters = resolve_legacy_filter('parent_doc_id == "doc-42"', None)
        assert filters is not None
        assert filters.parent_doc_id == "doc-42"

    def test_tolerates_the_spacing_the_grammar_allows(self):
        filters = resolve_legacy_filter('parent_doc_id=="doc-42"', None)
        assert filters is not None
        assert filters.parent_doc_id == "doc-42"

    def test_an_absent_string_leaves_filters_untouched(self):
        existing = RetrievalFilters(source=["upload"])
        assert resolve_legacy_filter(None, existing) is existing
        assert resolve_legacy_filter("", None) is None

    def test_any_other_string_is_refused_not_silently_ignored(self):
        with pytest.raises(BadRequestError):
            resolve_legacy_filter('filetype == "pdf"', None)

    def test_supplying_both_sources_is_a_conflict(self):
        with pytest.raises(BadRequestError):
            resolve_legacy_filter(
                'parent_doc_id == "doc-1"',
                RetrievalFilters(parent_doc_id="doc-2"),
            )


class TestThreadingScopeAndFiltersToTheStore:
    async def test_scope_and_filters_reach_the_store_typed(self):
        store = MagicMock()
        store.resolve_tenant = AsyncMock(return_value=None)
        store.search = AsyncMock(return_value=[SearchResult(content="chunk", score=0.5)])
        org = uuid4()

        await _retrieval_over(store).retrieve(
            query="anything",
            collection_name="handbook",
            scope=TenantScope(organization_id=org),
            filters=RetrievalFilters(parent_doc_id="doc-42", source=["upload"]),
        )

        query_filter = store.search.await_args.kwargs["query_filter"]
        assert query_filter.organization_id == org
        assert query_filter.filters.parent_doc_id == "doc-42"
        assert query_filter.filters.source == ["upload"]

    async def test_no_filters_still_carries_the_scope(self):
        store = MagicMock()
        store.resolve_tenant = AsyncMock(return_value=None)
        store.search = AsyncMock(return_value=[])

        await _retrieval_over(store).retrieve(
            query="anything",
            collection_name="handbook",
            scope=UnscopedScope(),
        )

        query_filter = store.search.await_args.kwargs["query_filter"]
        assert query_filter.organization_id is None
        assert query_filter.filters.parent_doc_id is None

    async def test_bm25_rerank_reuses_the_same_query_filter(self):
        # In hybrid mode the BM25 leg reranks the vector store's own candidates,
        # so the same restricted query_filter must reach its store.search call -
        # otherwise fusion could reintroduce an out-of-scope row.
        store = MagicMock()
        store.search = AsyncMock(return_value=[SearchResult(content="chunk", score=0.5)])
        org = uuid4()

        await _retrieval_over(store, hybrid=True).retrieve(
            query="term",
            collection_name="handbook",
            scope=TenantScope(organization_id=org),
        )

        # Every store.search call (vector leg + BM25 rerank) carried the scope.
        assert store.search.await_count >= 2
        for call in store.search.await_args_list:
            assert call.kwargs["query_filter"].organization_id == org
        # The removed probe means get_documents is never consulted.
        assert not store.get_documents.called

    async def test_retrieve_multi_carries_scope_to_every_collection(self):
        store = MagicMock()
        store.search = AsyncMock(return_value=[])
        org = uuid4()

        await _retrieval_over(store).retrieve_multi(
            query="anything",
            collection_names=["a", "b"],
            scope=TenantScope(organization_id=org),
            filters=RetrievalFilters(document_type=["pdf"]),
        )

        assert store.search.await_count == 2
        for call in store.search.await_args_list:
            query_filter = call.kwargs["query_filter"]
            assert query_filter.organization_id == org
            assert query_filter.filters.document_type == ["pdf"]


@pytest.mark.security
class TestResolvingScopePerCollection:
    """A caller that holds only a name - the agent capability, the CLI - resolves
    its scope through the store's own `resolve_tenant` (#1684) and the matching
    scope shape (FA-039): `AppScope` for an app-scoped base every organization
    reads, `TenantScope` for an org one. Built from the *base's* resolved tenant,
    never from the caller's own organization id, which cannot match an app-scoped
    base's untagged rows - the gap a naive FA-039/#1684 merge reopened."""

    async def test_resolve_scope_maps_a_resolved_tenant_to_tenant_scope(self):
        resolved = uuid.uuid4()
        store = MagicMock()
        store.resolve_tenant = AsyncMock(return_value=resolved)

        scope = await _retrieval_over(store).resolve_scope("handbook", uuid.uuid4())

        store.resolve_tenant.assert_awaited_once()
        assert scope == TenantScope(organization_id=resolved)

    async def test_resolve_scope_maps_no_tenant_to_app_scope(self):
        """The disclosure case: the resolved base is app-scoped, so its tenant is
        `None`; the scope must read the untagged rows, not one that matches
        nothing."""
        store = MagicMock()
        store.resolve_tenant = AsyncMock(return_value=None)

        scope = await _retrieval_over(store).resolve_scope("handbook", uuid.uuid4())

        assert scope == AppScope()

    async def test_retrieve_multi_reads_each_collection_under_its_own_scope(self):
        """A caller that already resolved and authorized each base - the
        `/search` route, through `CollectionAccessService` - passes a `scopes`
        map, so a search spanning an org base and an app-scoped one reads each
        under the scope that matches its own rows rather than one shared scope."""
        org_scope, app_scope = TenantScope(organization_id=uuid.uuid4()), AppScope()
        store = MagicMock()
        store.search = AsyncMock(return_value=[])

        await _retrieval_over(store).retrieve_multi(
            query="q",
            collection_names=["a", "b"],
            scope=org_scope,
            scopes={"a": org_scope, "b": app_scope},
        )

        by_collection = {
            call.kwargs["collection_name"]: call.kwargs["query_filter"].scope
            for call in store.search.await_args_list
        }
        assert by_collection == {"a": org_scope, "b": app_scope}

    async def test_retrieve_multi_falls_back_to_scope_for_a_name_absent_from_scopes(self):
        shared = TenantScope(organization_id=uuid.uuid4())
        store = MagicMock()
        store.search = AsyncMock(return_value=[])

        await _retrieval_over(store).retrieve_multi(
            query="q",
            collection_names=["a", "b"],
            scope=shared,
            scopes={"a": AppScope()},
        )

        by_collection = {
            call.kwargs["collection_name"]: call.kwargs["query_filter"].scope
            for call in store.search.await_args_list
        }
        assert by_collection == {"a": AppScope(), "b": shared}

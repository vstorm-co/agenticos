"""Parent-document (small-to-big) retrieval on the return path (#1651).

Matching and ranking always run on the small chunks; `parent_context` only
decides how much surrounding context each matched chunk is *returned* with. The
expansion is assembled after ranking, bounded per result and per turn,
de-duplicated across overlapping windows, and confined to the caller's own
tenant scope. `off` must leave the pre-#1651 behaviour byte-for-byte unchanged.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.rag.filters import AppScope, TenantScope
from app.services.rag.models import DocumentChunk, ParentContextMode, SearchResult
from app.services.rag.retrieval import RetrievalService

pytestmark = pytest.mark.anyio


def _service(
    store: MagicMock,
    *,
    window_size: int = 1,
    per_result: int = 4000,
    per_turn: int = 16000,
) -> RetrievalService:
    settings = MagicMock()
    settings.enable_hybrid_search = False
    settings.parent_context_window_size = window_size
    settings.parent_context_max_chars_per_result = per_result
    settings.parent_context_max_chars_per_turn = per_turn
    return RetrievalService(vector_store=store, settings=settings)


def _match(chunk_num: int, *, doc: str = "doc", page: int = 0, score: float = 0.9) -> SearchResult:
    return SearchResult(
        content=f"c{chunk_num}",
        score=score,
        parent_doc_id=doc,
        metadata={"page_num": page, "chunk_num": chunk_num},
    )


def _document(*chunk_nums: int, page: int = 0) -> list[DocumentChunk]:
    return [DocumentChunk(content=f"c{n}", page_num=page, chunk_num=n) for n in chunk_nums]


class TestOffPreservesBehaviour:
    async def test_off_never_touches_the_document_and_leaves_results_unchanged(self):
        store = MagicMock()
        store.search = AsyncMock(return_value=[_match(2)])
        store.get_document_chunks = AsyncMock()

        results = await _service(store).retrieve(
            query="q", collection_name="col", scope=TenantScope(organization_id=uuid4())
        )

        # The matched chunk is returned exactly as indexed, with no expansion,
        # and the document is never read - byte-for-byte the pre-#1651 path.
        assert [r.content for r in results] == ["c2"]
        assert results[0].expanded_content is None
        store.get_document_chunks.assert_not_awaited()

    async def test_off_is_the_default(self):
        store = MagicMock()
        store.search = AsyncMock(return_value=[_match(2)])
        store.get_document_chunks = AsyncMock()

        await _service(store).retrieve(
            query="q",
            collection_name="col",
            scope=TenantScope(organization_id=uuid4()),
            parent_context=ParentContextMode.OFF,
        )

        store.get_document_chunks.assert_not_awaited()


class TestWindowAssembly:
    async def test_window_returns_the_match_and_its_neighbours_in_order(self):
        store = MagicMock()
        store.search = AsyncMock(return_value=[_match(2)])
        store.get_document_chunks = AsyncMock(return_value=_document(0, 1, 2, 3, 4))

        results = await _service(store, window_size=1).retrieve(
            query="q",
            collection_name="col",
            scope=TenantScope(organization_id=uuid4()),
            parent_context=ParentContextMode.WINDOW,
        )

        # The score and citable chunk stay the match's; the expanded passage adds
        # exactly one neighbour on each side, in document order.
        assert results[0].content == "c2"
        assert results[0].expanded_content == "c1\n\nc2\n\nc3"

    async def test_window_clamps_at_the_document_edges(self):
        store = MagicMock()
        store.search = AsyncMock(return_value=[_match(0)])
        store.get_document_chunks = AsyncMock(return_value=_document(0, 1, 2))

        results = await _service(store, window_size=1).retrieve(
            query="q",
            collection_name="col",
            scope=TenantScope(organization_id=uuid4()),
            parent_context=ParentContextMode.WINDOW,
        )

        assert results[0].expanded_content == "c0\n\nc1"

    async def test_a_match_absent_from_the_document_is_left_unexpanded(self):
        store = MagicMock()
        store.search = AsyncMock(return_value=[_match(9)])
        store.get_document_chunks = AsyncMock(return_value=_document(0, 1, 2))

        results = await _service(store).retrieve(
            query="q",
            collection_name="col",
            scope=TenantScope(organization_id=uuid4()),
            parent_context=ParentContextMode.WINDOW,
        )

        assert results[0].expanded_content is None


class TestParentAssembly:
    async def test_parent_returns_the_whole_document_in_order(self):
        store = MagicMock()
        store.search = AsyncMock(return_value=[_match(1)])
        store.get_document_chunks = AsyncMock(return_value=_document(0, 1, 2, 3))

        results = await _service(store).retrieve(
            query="q",
            collection_name="col",
            scope=TenantScope(organization_id=uuid4()),
            parent_context=ParentContextMode.PARENT,
        )

        assert results[0].expanded_content == "c0\n\nc1\n\nc2\n\nc3"

    async def test_a_result_without_a_parent_doc_id_is_skipped(self):
        store = MagicMock()
        orphan = SearchResult(content="x", score=0.5, parent_doc_id=None, metadata={})
        store.search = AsyncMock(return_value=[orphan])
        store.get_document_chunks = AsyncMock()

        results = await _service(store).retrieve(
            query="q",
            collection_name="col",
            scope=TenantScope(organization_id=uuid4()),
            parent_context=ParentContextMode.PARENT,
        )

        assert results[0].expanded_content is None
        store.get_document_chunks.assert_not_awaited()

    async def test_an_empty_document_leaves_the_result_unexpanded(self):
        store = MagicMock()
        store.search = AsyncMock(return_value=[_match(0)])
        store.get_document_chunks = AsyncMock(return_value=[])

        results = await _service(store).retrieve(
            query="q",
            collection_name="col",
            scope=TenantScope(organization_id=uuid4()),
            parent_context=ParentContextMode.PARENT,
        )

        assert results[0].expanded_content is None


class TestSizeBounding:
    async def test_a_result_is_capped_to_the_per_result_budget(self):
        store = MagicMock()
        # The matched chunk alone is longer than the per-result cap.
        store.search = AsyncMock(
            return_value=[
                SearchResult(
                    content="x" * 20,
                    score=0.9,
                    parent_doc_id="doc",
                    metadata={"page_num": 0, "chunk_num": 1},
                )
            ]
        )
        store.get_document_chunks = AsyncMock(
            return_value=[
                DocumentChunk(content="before", page_num=0, chunk_num=0),
                DocumentChunk(content="x" * 20, page_num=0, chunk_num=1),
                DocumentChunk(content="after", page_num=0, chunk_num=2),
            ]
        )

        results = await _service(store, per_result=8).retrieve(
            query="q",
            collection_name="col",
            scope=TenantScope(organization_id=uuid4()),
            parent_context=ParentContextMode.PARENT,
        )

        # Bounded to the cap, and it is the matched chunk that is kept - not the
        # document's opening ("before").
        assert results[0].expanded_content == "x" * 8

    async def test_the_matched_chunk_survives_when_earlier_context_would_fill_the_cap(self):
        store = MagicMock()
        # The match is the last chunk; the chunks before it already exceed the cap.
        # A join-then-truncate-from-the-end would return only the opening and drop
        # the match, leaving the result's citation pointing at text it no longer
        # carries. The match must be what survives.
        store.search = AsyncMock(
            return_value=[
                SearchResult(
                    content="the-match",
                    score=0.9,
                    parent_doc_id="doc",
                    metadata={"page_num": 0, "chunk_num": 2},
                )
            ]
        )
        store.get_document_chunks = AsyncMock(
            return_value=[
                DocumentChunk(content="a" * 30, page_num=0, chunk_num=0),
                DocumentChunk(content="b" * 30, page_num=0, chunk_num=1),
                DocumentChunk(content="the-match", page_num=0, chunk_num=2),
            ]
        )

        results = await _service(store, per_result=20).retrieve(
            query="q",
            collection_name="col",
            scope=TenantScope(organization_id=uuid4()),
            parent_context=ParentContextMode.PARENT,
        )

        assert results[0].expanded_content is not None
        assert "the-match" in results[0].expanded_content
        assert len(results[0].expanded_content) <= 20

    async def test_the_turn_budget_stops_expansion_across_results(self):
        store = MagicMock()
        # Two matches in different documents; the first fills the turn budget.
        store.search = AsyncMock(
            return_value=[_match(1, doc="doc-a", score=0.9), _match(1, doc="doc-b", score=0.8)]
        )
        store.get_document_chunks = AsyncMock(
            return_value=[DocumentChunk(content="a" * 6, page_num=0, chunk_num=1)]
        )

        results = await _service(store, per_result=100, per_turn=6).retrieve(
            query="q",
            collection_name="col",
            scope=TenantScope(organization_id=uuid4()),
            parent_context=ParentContextMode.PARENT,
        )

        # The first result fills the turn cap; the second sees no budget left and
        # is returned unexpanded rather than overflowing it.
        assert results[0].expanded_content == "a" * 6
        assert results[1].expanded_content is None


class TestReuseAndSharedBudget:
    async def test_a_document_is_fetched_once_for_several_matches(self):
        store = MagicMock()
        # Two matches from the same document: it must be read (and sorted) once,
        # not once per match.
        store.search = AsyncMock(return_value=[_match(1, score=0.9), _match(3, score=0.8)])
        store.get_document_chunks = AsyncMock(return_value=_document(0, 1, 2, 3, 4))

        await _service(store, window_size=1).retrieve(
            query="q",
            collection_name="col",
            scope=TenantScope(organization_id=uuid4()),
            parent_context=ParentContextMode.WINDOW,
        )

        assert store.get_document_chunks.await_count == 1

    async def test_the_turn_budget_is_shared_across_collections(self):
        store = MagicMock()
        org = uuid4()
        # One match per collection, each in its own document. The first collection
        # fills the shared per-turn budget; the second must then see none left,
        # rather than being granted a fresh budget of its own.
        store.search = AsyncMock(
            side_effect=lambda **kw: [_match(1, doc=f"doc-{kw['collection_name']}", score=0.9)]
        )
        store.get_document_chunks = AsyncMock(
            return_value=[DocumentChunk(content="a" * 6, page_num=0, chunk_num=1)]
        )

        results = await _service(store, per_result=100, per_turn=6).retrieve_multi(
            query="q",
            collection_names=["col-a", "col-b"],
            scopes={
                "col-a": TenantScope(organization_id=org),
                "col-b": TenantScope(organization_id=org),
            },
            parent_context=ParentContextMode.PARENT,
        )

        expanded = [r.expanded_content for r in results]
        assert expanded.count("a" * 6) == 1
        assert None in expanded


class TestDeduplicatingOverlappingWindows:
    async def test_an_overlapping_neighbour_is_not_repeated_but_the_match_is_kept(self):
        store = MagicMock()
        # Two adjacent matches in the same document: their windows overlap on c2.
        store.search = AsyncMock(return_value=[_match(1, score=0.9), _match(2, score=0.8)])
        store.get_document_chunks = AsyncMock(return_value=_document(0, 1, 2, 3))

        results = await _service(store, window_size=1).retrieve(
            query="q",
            collection_name="col",
            scope=TenantScope(organization_id=uuid4()),
            parent_context=ParentContextMode.WINDOW,
        )

        # First window: c0,c1,c2. Second window would be c1,c2,c3, but c1 was
        # already returned, so only its own match c2 and the new c3 remain -
        # each result still carries its own matched chunk.
        assert results[0].expanded_content == "c0\n\nc1\n\nc2"
        assert results[1].expanded_content == "c2\n\nc3"


@pytest.mark.security
class TestScopeIsPreservedOnTheSiblingFetch:
    async def test_the_tenants_organization_scopes_the_expansion_read(self):
        store = MagicMock()
        org = uuid4()
        store.search = AsyncMock(return_value=[_match(1)])
        store.get_document_chunks = AsyncMock(return_value=_document(0, 1, 2))

        await _service(store).retrieve(
            query="q",
            collection_name="col",
            scope=TenantScope(organization_id=org),
            parent_context=ParentContextMode.WINDOW,
        )

        # The sibling fetch is scoped to the same tenant `search` reads under, so
        # a shared collection name cannot expand into another org's chunks.
        assert store.get_document_chunks.await_args.args == ("col", "doc", org)

    async def test_an_app_scoped_search_expands_only_untagged_rows(self):
        store = MagicMock()
        store.search = AsyncMock(return_value=[_match(1)])
        store.get_document_chunks = AsyncMock(return_value=_document(0, 1, 2))

        await _service(store).retrieve(
            query="q",
            collection_name="col",
            scope=AppScope(),
            parent_context=ParentContextMode.WINDOW,
        )

        # `None` matches only the untagged, deployment-wide rows - the same rows
        # an app-scoped search matches.
        assert store.get_document_chunks.await_args.args == ("col", "doc", None)

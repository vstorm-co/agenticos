"""Parent-document (small-to-big) retrieval on the return path (#1651).

Matching and ranking always run on the small chunks; `parent_context` only
decides how much surrounding text each matched chunk is *returned* with. What
is held here:

- the matched chunk is never shortened - only added context is charged - so the
  mode can never make the model read less than `off` would;
- a passage is contiguous: a direction closes at the first chunk that does not
  fit or was already returned, so non-adjacent text is never joined;
- the read is bounded by position, never the whole document;
- `off` never reads anything, and scope decides which tenant a sibling is read under.

The store's positional read against real rows is
`tests/integration/test_rag_parent_context_scope.py`.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.capabilities.knowledge._search import _format_results
from app.services.rag.filters import AppScope, TenantScope, UnscopedScope
from app.services.rag.models import DocumentChunk, ParentContextMode, SearchResult
from app.services.rag.parent_context import (
    MAX_ADDED_CHARS_PER_RESULT,
    MAX_ADDED_CHARS_PER_TURN,
    PARENT_CHUNKS_EACH_SIDE,
    WINDOW_CHUNKS,
    assemble_passage,
    expand_context,
    expansion_tenant,
)
from app.services.rag.retrieval import RetrievalService

pytestmark = pytest.mark.anyio


def _chunk(n: int, *, size: int | None = None, page: int = 0) -> DocumentChunk:
    return DocumentChunk(
        content=f"c{n}" if size is None else f"c{n}".ljust(size, "x"), page_num=page, chunk_num=n
    )


def _match(n: int, *, doc: str = "doc", content: str | None = None) -> SearchResult:
    return SearchResult(
        content=content or f"c{n}",
        score=0.9,
        parent_doc_id=doc,
        metadata={"page_num": 0, "chunk_num": n},
    )


class _Document:
    """A `ChunkReader` over in-memory documents, recording every read."""

    def __init__(self, **documents: list[DocumentChunk]) -> None:
        self._documents = documents
        self.reads: list[tuple[str, str, object, int, int, int, int]] = []

    async def get_chunks_around(
        self,
        collection_name: str,
        document_id: str,
        tenant: object,
        *,
        page_num: int,
        chunk_num: int,
        before: int,
        after: int,
    ) -> list[DocumentChunk]:
        self.reads.append(
            (collection_name, document_id, tenant, page_num, chunk_num, before, after)
        )
        chunks = self._documents.get(document_id, [])
        at = next(
            (i for i, c in enumerate(chunks) if (c.page_num, c.chunk_num) == (page_num, chunk_num)),
            None,
        )
        if at is None:
            return []
        return chunks[max(0, at - before) : at + after + 1]


def _fetch(collection: str = "col", tenant: object = None):
    return lambda _result: (collection, tenant)


class TestAssemblingAPassage:
    def test_the_match_is_never_shortened_however_small_the_budget(self):
        """The defect the review measured: a cap cut the match itself, so the mode
        showed the model less than `off` would have."""
        chunks = [_chunk(0), _chunk(1, size=9000), _chunk(2)]

        assembled = assemble_passage(chunks, 1, "doc", set(), budget=10)

        assert assembled is not None
        passage, added = assembled
        assert chunks[1].content in passage
        assert added == len("\n\nc0") + len("\n\nc2")

    def test_nothing_added_leaves_the_result_unexpanded(self):
        chunks = [_chunk(0, size=100), _chunk(1), _chunk(2, size=100)]

        assert assemble_passage(chunks, 1, "doc", set(), budget=50) is None

    def test_a_chunk_already_returned_closes_its_direction_rather_than_splicing(self):
        """c3 must not be joined straight to c6 as if the text ran on."""
        chunks = [_chunk(n) for n in range(8)]
        emitted = {("doc", 0, 4), ("doc", 0, 5)}

        assembled = assemble_passage(chunks, 3, "doc", emitted, budget=1000)

        assert assembled is not None
        assert assembled[0] == "c0\n\nc1\n\nc2\n\nc3"

    def test_a_chunk_too_big_for_the_budget_stops_its_direction(self):
        chunks = [_chunk(0), _chunk(1, size=500), _chunk(2), _chunk(3)]

        assembled = assemble_passage(chunks, 2, "doc", set(), budget=20)

        assert assembled is not None
        assert assembled[0] == "c2\n\nc3"

    def test_what_is_kept_is_recorded_as_returned(self):
        emitted: set[tuple[str, int, int]] = set()

        assemble_passage([_chunk(0), _chunk(1)], 0, "doc", emitted, budget=100)

        assert emitted == {("doc", 0, 0), ("doc", 0, 1)}


class TestExpandingResults:
    async def test_off_reads_nothing(self):
        store = _Document(doc=[_chunk(0), _chunk(1)])
        results = [_match(0)]

        await expand_context(store, results, ParentContextMode.OFF, _fetch())

        assert store.reads == []
        assert results[0].expanded_content is None

    async def test_window_reads_one_neighbour_each_side_by_position(self):
        store = _Document(doc=[_chunk(n) for n in range(5)])
        results = [_match(2)]

        await expand_context(store, results, ParentContextMode.WINDOW, _fetch("col", "org"))

        assert results[0].content == "c2"
        assert results[0].expanded_content == "c1\n\nc2\n\nc3"
        assert store.reads == [("col", "doc", "org", 0, 2, WINDOW_CHUNKS, WINDOW_CHUNKS)]

    async def test_parent_reads_a_bounded_span_around_the_match(self):
        store = _Document(doc=[_chunk(n) for n in range(4)])
        results = [_match(1)]

        await expand_context(store, results, ParentContextMode.PARENT, _fetch())

        assert results[0].expanded_content == "c0\n\nc1\n\nc2\n\nc3"
        assert store.reads[0][5:] == (PARENT_CHUNKS_EACH_SIDE, PARENT_CHUNKS_EACH_SIDE)

    async def test_ordinary_sized_chunks_get_their_neighbours(self):
        """With 2500-character chunks the old caps added nothing in 71% of cases."""
        store = _Document(doc=[_chunk(n, size=2500) for n in range(5)])
        results = [_match(2, content="c2".ljust(2500, "x"))]

        await expand_context(store, results, ParentContextMode.WINDOW, _fetch())

        assert results[0].expanded_content is not None
        assert results[0].expanded_content.count("\n\n") == 2

    async def test_the_per_search_budget_is_shared_and_stops_expansion(self):
        size = MAX_ADDED_CHARS_PER_RESULT // 2 - 10
        documents = {f"d{i}": [_chunk(n, size=size) for n in range(3)] for i in range(10)}
        store = _Document(**documents)
        results = [_match(1, doc=f"d{i}", content="c1".ljust(size, "x")) for i in range(10)]

        await expand_context(store, results, ParentContextMode.WINDOW, _fetch())

        expanded = [r for r in results if r.expanded_content is not None]
        added = sum(len(r.expanded_content or "") - len(r.content) for r in expanded)
        # Each result adds about one per-result budget; the per-search budget holds three.
        assert added <= MAX_ADDED_CHARS_PER_TURN
        assert len(expanded) == MAX_ADDED_CHARS_PER_TURN // MAX_ADDED_CHARS_PER_RESULT

    async def test_a_spent_search_reads_no_further_documents(self, monkeypatch):
        """Once the added text fills the per-search cap, later results are not read."""
        monkeypatch.setattr(
            "app.services.rag.parent_context.MAX_ADDED_CHARS_PER_TURN", len("\n\nc0\n\nc2")
        )
        store = _Document(a=[_chunk(n) for n in range(3)], b=[_chunk(n) for n in range(3)])
        results = [_match(1, doc="a"), _match(1, doc="b")]

        await expand_context(store, results, ParentContextMode.WINDOW, _fetch())

        assert results[0].expanded_content == "c0\n\nc1\n\nc2"
        assert results[1].expanded_content is None
        assert [read[1] for read in store.reads] == ["a"]

    async def test_an_overlapping_neighbour_is_returned_once(self):
        store = _Document(doc=[_chunk(n) for n in range(4)])
        results = [_match(1), _match(2)]

        await expand_context(store, results, ParentContextMode.WINDOW, _fetch())

        assert results[0].expanded_content == "c0\n\nc1\n\nc2"
        # c2 is its own result and keeps its text; c1 was already returned, so
        # only c3 is added, and the passage never reaches back over c1.
        assert results[1].expanded_content == "c2\n\nc3"

    async def test_results_with_nothing_to_grow_from_are_left_alone(self):
        store = _Document(doc=[_chunk(0), _chunk(1)])
        no_document = SearchResult(content="x", score=0.5, metadata={})
        gone = _match(9)
        refused = _match(0)

        await expand_context(
            store,
            [no_document, gone, refused],
            ParentContextMode.WINDOW,
            lambda r: None if r is refused else ("col", None),
        )

        assert [r.expanded_content for r in (no_document, gone, refused)] == [None, None, None]
        assert [read[4] for read in store.reads] == [9]


class TestWhichTenantASiblingIsReadUnder:
    @pytest.mark.security
    def test_a_tenant_scope_reads_its_own_organization(self):
        org = uuid4()

        assert expansion_tenant(TenantScope(organization_id=org)) == (True, org)

    def test_an_app_scope_reads_only_untagged_rows(self):
        assert expansion_tenant(AppScope()) == (True, None)

    def test_an_unscoped_search_is_not_expanded(self):
        assert expansion_tenant(UnscopedScope()) == (False, None)


def _service(store: MagicMock) -> RetrievalService:
    settings = MagicMock()
    settings.enable_hybrid_search = False
    return RetrievalService(vector_store=store, settings=settings)


def _store(results: list[SearchResult], document: list[DocumentChunk]) -> MagicMock:
    reader = _Document(doc=document)
    store = MagicMock()
    store.search = AsyncMock(return_value=results)
    store.get_chunks_around = AsyncMock(side_effect=reader.get_chunks_around)
    store.reads = reader.reads
    return store


class TestThroughTheRetrievalService:
    async def test_off_is_the_default_and_reads_nothing(self):
        store = _store([_match(2)], [_chunk(n) for n in range(4)])

        results = await _service(store).retrieve(
            query="q", collection_name="col", scope=TenantScope(organization_id=uuid4())
        )

        assert results[0].expanded_content is None
        store.get_chunks_around.assert_not_awaited()

    @pytest.mark.security
    async def test_a_single_collection_reads_under_its_tenant(self):
        org = uuid4()
        store = _store([_match(2)], [_chunk(n) for n in range(4)])

        results = await _service(store).retrieve(
            query="q",
            collection_name="col",
            scope=TenantScope(organization_id=org),
            parent_context=ParentContextMode.WINDOW,
        )

        assert results[0].expanded_content == "c1\n\nc2\n\nc3"
        assert store.reads[0][:3] == ("col", "doc", org)

    async def test_several_collections_each_read_under_their_own_scope(self):
        org = uuid4()
        store = MagicMock()
        store.search = AsyncMock(
            side_effect=[
                [_match(1, doc="doc")],
                [
                    SearchResult(
                        content="c2",
                        score=0.8,
                        parent_doc_id="doc",
                        metadata={"page_num": 0, "chunk_num": 2},
                    )
                ],
            ]
        )
        reader = _Document(doc=[_chunk(n) for n in range(5)])
        store.get_chunks_around = AsyncMock(side_effect=reader.get_chunks_around)

        await _service(store).retrieve_multi(
            query="q",
            collection_names=["tenant_col", "app_col"],
            scopes={"tenant_col": TenantScope(organization_id=org), "app_col": AppScope()},
            parent_context=ParentContextMode.WINDOW,
        )

        assert sorted((read[0], read[2]) for read in reader.reads) == sorted(
            [("tenant_col", org), ("app_col", None)]
        )

    async def test_an_unscoped_collection_in_a_multi_search_is_not_expanded(self):
        store = _store([_match(1)], [_chunk(n) for n in range(3)])

        results = await _service(store).retrieve_multi(
            query="q",
            collection_names=["col"],
            scopes={"col": UnscopedScope()},
            parent_context=ParentContextMode.WINDOW,
        )

        assert results[0].expanded_content is None
        store.get_chunks_around.assert_not_awaited()


class TestWhatTheModelReads:
    def test_an_expanded_result_says_its_text_reaches_past_the_cited_chunk(self):
        expanded = _match(1)
        expanded.expanded_content = "c0\n\nc1\n\nc2"
        plain = _match(5)

        text = _format_results([expanded, plain])

        assert "chunk 1, with surrounding text" in text
        assert "c0\n\nc1\n\nc2" in text
        assert "chunk 5 (score" in text

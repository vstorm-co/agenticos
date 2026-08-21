"""How reranking changes what retrieval returns.

The reranker is injected as a resolver, so these drive it with a stub that
reorders a known candidate set. Two properties matter: with a reranker,
retrieval returns the reranked order truncated to the limit; without one, it is
byte-for-byte the by-distance path. And a multi-collection search reranks the
union of candidates once, not each collection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.rag.models import SearchResult
from app.services.rag.reranker import BaseReranker, CohereReranker
from app.services.rag.retrieval import RetrievalService

pytestmark = pytest.mark.anyio


class _ReverseReranker(BaseReranker):
    """Reorders candidates worst-first, so a test can see reranking happened.

    Counts its calls, so a multi-collection search can assert it ran once over
    the union rather than once per collection.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def rerank(
        self, query: str, results: list[SearchResult], top_n: int
    ) -> list[SearchResult]:
        self.calls += 1
        return list(reversed(results))[:top_n]


class _FailingReranker(BaseReranker):
    async def rerank(
        self, query: str, results: list[SearchResult], top_n: int
    ) -> list[SearchResult]:
        raise RuntimeError("cohere down")


def _store_returning(results: list[SearchResult]) -> MagicMock:
    store = MagicMock()
    store.search = AsyncMock(return_value=results)
    return store


def _service(store: MagicMock, reranker: BaseReranker | None) -> RetrievalService:
    settings = MagicMock()
    settings.enable_hybrid_search = False
    resolver = AsyncMock(return_value=reranker) if reranker is not None else None
    return RetrievalService(vector_store=store, settings=settings, reranker_resolver=resolver)


def _service_by_name(store: MagicMock, mapping: dict[str, BaseReranker | None]) -> RetrievalService:
    """A retrieval service whose reranker depends on which collection is asked."""
    settings = MagicMock()
    settings.enable_hybrid_search = False

    async def resolver(
        name: str, organization_id: object = None, knowledge_base_id: object = None
    ) -> BaseReranker | None:
        return mapping.get(name)

    return RetrievalService(vector_store=store, settings=settings, reranker_resolver=resolver)


def _hits(*names: str) -> list[SearchResult]:
    return [SearchResult(content=name, score=score) for score, name in enumerate(names)]


class TestSingleCollection:
    async def test_a_configured_collection_returns_the_reranked_order(self):
        store = _store_returning(_hits("a", "b", "c"))
        results = await _service(store, _ReverseReranker()).retrieve(
            "q", "kb", limit=3, organization_id=None
        )
        assert [r.content for r in results] == ["c", "b", "a"]

    async def test_it_truncates_to_the_limit_after_reranking(self):
        store = _store_returning(_hits("a", "b", "c", "d"))
        results = await _service(store, _ReverseReranker()).retrieve(
            "q", "kb", limit=2, organization_id=None
        )
        assert [r.content for r in results] == ["d", "c"]

    async def test_without_a_reranker_the_order_is_left_as_the_store_gave_it(self):
        store = _store_returning(_hits("a", "b", "c"))
        results = await _service(store, None).retrieve("q", "kb", limit=3, organization_id=None)
        assert [r.content for r in results] == ["a", "b", "c"]

    async def test_a_reranker_failure_falls_back_to_the_distance_order(self):
        store = _store_returning(_hits("a", "b", "c"))
        results = await _service(store, _FailingReranker()).retrieve(
            "q", "kb", limit=2, organization_id=None
        )
        assert [r.content for r in results] == ["a", "b"]


class TestMultiCollection:
    async def test_it_reranks_the_union_once_not_each_collection(self):
        store = _store_returning(_hits("a", "b"))
        reranker = _ReverseReranker()
        await _service(store, reranker).retrieve_multi(
            "q", collection_names=["kb_a", "kb_b"], limit=3, organization_id=None
        )
        assert reranker.calls == 1

    async def test_the_collection_stamp_survives_reranking(self):
        store = _store_returning(_hits("a"))
        results = await _service(store, _ReverseReranker()).retrieve(
            "q", "handbook", limit=1, organization_id=None
        )
        assert results[0].metadata["collection"] == "handbook"


class TestAuthorizedKnowledgeBaseIsPinned:
    """The authorized KB id reaches resolution, so a shared collection name
    resolves the row access granted rather than one re-looked-up by name (#913)."""

    @staticmethod
    def _svc(store: MagicMock, resolver: AsyncMock) -> RetrievalService:
        settings = MagicMock()
        settings.enable_hybrid_search = False
        return RetrievalService(vector_store=store, settings=settings, reranker_resolver=resolver)

    async def test_retrieve_threads_the_kb_id_to_the_resolver_and_the_store(self):
        store = _store_returning(_hits("a"))
        resolver = AsyncMock(return_value=None)
        kb = uuid4()

        await self._svc(store, resolver).retrieve(
            "q", "handbook", limit=1, organization_id=None, knowledge_base_id=kb
        )

        assert resolver.await_args.args == ("handbook", None, kb)
        assert store.search.await_args.kwargs["knowledge_base_id"] == kb

    async def test_retrieve_multi_pins_each_collection_to_its_own_kb_id(self):
        store = _store_returning(_hits("a"))
        resolver = AsyncMock(return_value=None)
        a, b = uuid4(), uuid4()

        await self._svc(store, resolver).retrieve_multi(
            "q",
            collection_names=["kb_a", "kb_b"],
            limit=1,
            organization_id=None,
            knowledge_base_ids=[a, b],
        )

        resolved = {call.args[0]: call.args[2] for call in resolver.await_args_list}
        assert resolved == {"kb_a": a, "kb_b": b}

    async def test_no_kb_id_falls_back_to_the_organization_scope(self):
        store = _store_returning(_hits("a"))
        resolver = AsyncMock(return_value=None)

        await self._svc(store, resolver).retrieve("q", "handbook", limit=1, organization_id=None)

        assert resolver.await_args.args == ("handbook", None, None)


class TestMixedRerankConfig:
    """A union is reranked only when every collection agrees on one reranker.

    A set whose collections disagree - one reranking, one not, or two on
    different keys - is left in distance order rather than reranked on a
    credential that is not the collection's own.
    """

    async def test_a_differently_keyed_set_is_not_reranked(self):
        store = _store_returning(_hits("a", "b"))
        r1, r2 = _ReverseReranker(), _ReverseReranker()
        svc = _service_by_name(store, {"kb_a": r1, "kb_b": r2})
        await svc.retrieve_multi(
            "q", collection_names=["kb_a", "kb_b"], limit=3, organization_id=None
        )
        assert r1.calls == 0
        assert r2.calls == 0

    async def test_one_unconfigured_collection_disables_reranking_for_the_union(self):
        store = _store_returning(_hits("a", "b"))
        r = _ReverseReranker()
        svc = _service_by_name(store, {"kb_a": r, "kb_b": None})
        await svc.retrieve_multi(
            "q", collection_names=["kb_a", "kb_b"], limit=3, organization_id=None
        )
        assert r.calls == 0


class TestSharedReranker:
    """`_shared_reranker` decides whether one reranker may reorder the union."""

    def test_distinct_objects_with_one_config_are_shared(self):
        a = CohereReranker("rerank-v3.5", "k")
        b = CohereReranker("rerank-v3.5", "k")
        assert RetrievalService._shared_reranker([a, b]) is a

    def test_a_differing_key_is_not_shared(self):
        a = CohereReranker("rerank-v3.5", "k1")
        b = CohereReranker("rerank-v3.5", "k2")
        assert RetrievalService._shared_reranker([a, b]) is None

    def test_an_unconfigured_collection_in_the_set_disables_it(self):
        a = CohereReranker("rerank-v3.5", "k")
        assert RetrievalService._shared_reranker([a, None]) is None

    def test_an_all_unconfigured_set_has_no_reranker(self):
        assert RetrievalService._shared_reranker([None, None]) is None

    def test_an_empty_set_has_no_reranker(self):
        assert RetrievalService._shared_reranker([]) is None

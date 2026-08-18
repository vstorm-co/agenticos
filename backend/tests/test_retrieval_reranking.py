"""How reranking changes what retrieval returns.

The reranker is injected as a resolver, so these drive it with a stub that
reorders a known candidate set. Two properties matter: with a reranker,
retrieval returns the reranked order truncated to the limit; without one, it is
byte-for-byte the by-distance path. And a multi-collection search reranks the
union of candidates once, not each collection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rag.models import SearchResult
from app.services.rag.reranker import BaseReranker
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


def _hits(*names: str) -> list[SearchResult]:
    return [SearchResult(content=name, score=score) for score, name in enumerate(names)]


class TestSingleCollection:
    async def test_a_configured_collection_returns_the_reranked_order(self):
        store = _store_returning(_hits("a", "b", "c"))
        results = await _service(store, _ReverseReranker()).retrieve("q", "kb", limit=3)
        assert [r.content for r in results] == ["c", "b", "a"]

    async def test_it_truncates_to_the_limit_after_reranking(self):
        store = _store_returning(_hits("a", "b", "c", "d"))
        results = await _service(store, _ReverseReranker()).retrieve("q", "kb", limit=2)
        assert [r.content for r in results] == ["d", "c"]

    async def test_without_a_reranker_the_order_is_left_as_the_store_gave_it(self):
        store = _store_returning(_hits("a", "b", "c"))
        results = await _service(store, None).retrieve("q", "kb", limit=3)
        assert [r.content for r in results] == ["a", "b", "c"]

    async def test_a_reranker_failure_falls_back_to_the_distance_order(self):
        store = _store_returning(_hits("a", "b", "c"))
        results = await _service(store, _FailingReranker()).retrieve("q", "kb", limit=2)
        assert [r.content for r in results] == ["a", "b"]


class TestMultiCollection:
    async def test_it_reranks_the_union_once_not_each_collection(self):
        store = _store_returning(_hits("a", "b"))
        reranker = _ReverseReranker()
        await _service(store, reranker).retrieve_multi(
            "q", collection_names=["kb_a", "kb_b"], limit=3
        )
        assert reranker.calls == 1

    async def test_the_collection_stamp_survives_reranking(self):
        store = _store_returning(_hits("a"))
        results = await _service(store, _ReverseReranker()).retrieve("q", "handbook", limit=1)
        assert results[0].metadata["collection"] == "handbook"

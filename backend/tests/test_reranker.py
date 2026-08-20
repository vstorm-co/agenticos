"""Tests for the RAG reranker.

Two properties carry the weight: the reranker reorders and re-scores the
candidates it is given, and its per-search cost is booked to whatever ledger is
metering the search - priced, because it is computed here rather than looked up
in a price table that does not know rerank models.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.budget import SpendLedger, metered_by
from app.services.rag.models import SearchResult
from app.services.rag.reranker import CohereReranker, build_reranker
from app.services.rerank_resolution import ResolvedReranker

pytestmark = pytest.mark.anyio


def _results(*contents: str) -> list[SearchResult]:
    return [SearchResult(content=c, score=0.0, metadata={"i": i}) for i, c in enumerate(contents)]


def _client_returning(*ranked: tuple[int, float]) -> AsyncMock:
    """A fake Cohere client whose rerank returns these (index, score) items."""
    response = SimpleNamespace(
        results=[SimpleNamespace(index=index, relevance_score=score) for index, score in ranked]
    )
    client = AsyncMock()
    client.rerank = AsyncMock(return_value=response)
    return client


def _reranker(client: AsyncMock) -> CohereReranker:
    return CohereReranker(model="rerank-v3.5", api_key="co-key", client=client)


class TestReordering:
    async def test_it_returns_the_candidates_in_the_rerankers_order(self):
        client = _client_returning((2, 0.9), (0, 0.5), (1, 0.1))
        results = _results("first", "second", "third")

        reranked = await _reranker(client).rerank("q", results, top_n=3)

        assert [r.content for r in reranked] == ["third", "first", "second"]

    async def test_the_returned_score_is_the_rerankers_not_the_distance(self):
        client = _client_returning((0, 0.87))
        reranked = await _reranker(client).rerank("q", _results("only"), top_n=1)

        assert reranked[0].score == 0.87
        assert reranked[0].metadata == {"i": 0}

    async def test_it_asks_cohere_for_at_most_the_candidates_it_has(self):
        client = _client_returning((0, 0.9))
        await _reranker(client).rerank("q", _results("only"), top_n=5)

        assert client.rerank.await_args.kwargs["top_n"] == 1
        assert client.rerank.await_args.kwargs["documents"] == ["only"]

    async def test_no_candidates_returns_nothing_and_never_calls_cohere(self):
        client = _client_returning()
        reranked = await _reranker(client).rerank("q", [], top_n=5)

        assert reranked == []
        client.rerank.assert_not_awaited()


class TestSpend:
    async def test_a_rerank_books_a_priced_nonzero_cost_to_the_active_ledger(self):
        client = _client_returning((0, 0.9))
        ledger = SpendLedger()

        with metered_by(ledger):
            await _reranker(client).rerank("q", _results("a", "b"), top_n=2)

        assert len(ledger.entries) == 1
        assert ledger.entries[0].priced
        assert ledger.total_usd == Decimal("0.002")

    async def test_more_than_one_hundred_documents_bills_more_than_one_search_unit(self):
        client = _client_returning((0, 0.9))
        ledger = SpendLedger()

        with metered_by(ledger):
            await _reranker(client).rerank("q", _results(*(str(n) for n in range(250))), top_n=5)

        assert ledger.total_usd == Decimal("0.006")

    async def test_a_failed_call_books_nothing_and_propagates(self):
        client = AsyncMock()
        client.rerank = AsyncMock(side_effect=RuntimeError("cohere down"))
        ledger = SpendLedger()

        with metered_by(ledger), pytest.raises(RuntimeError):
            await _reranker(client).rerank("q", _results("a"), top_n=1)

        assert ledger.entries == []


class TestClientConstruction:
    def test_the_client_is_built_lazily_from_the_key(self):
        """No key is used and no client is built until the first rerank."""
        reranker = CohereReranker(model="rerank-v3.5", api_key="co-key")
        assert reranker._client is None
        assert reranker.client is not None


class TestConfigEquality:
    """Two rerankers are equal when they name the same model and key.

    Retrieval leans on this to decide whether a multi-collection union shares
    one reranker; the client is irrelevant to the comparison.
    """

    def test_same_model_and_key_are_equal(self):
        assert CohereReranker("rerank-v3.5", "k") == CohereReranker("rerank-v3.5", "k")

    def test_the_client_does_not_affect_equality(self):
        a = CohereReranker("rerank-v3.5", "k", client=AsyncMock())
        b = CohereReranker("rerank-v3.5", "k")
        assert a == b
        assert hash(a) == hash(b)

    def test_a_different_key_is_not_equal(self):
        assert CohereReranker("rerank-v3.5", "k1") != CohereReranker("rerank-v3.5", "k2")

    def test_a_non_reranker_is_not_equal(self):
        assert CohereReranker("rerank-v3.5", "k") != object()


class TestBuildReranker:
    """The one composition point both retrieval paths share."""

    async def test_an_unconfigured_collection_gets_no_reranker(self):
        with patch(
            "app.services.rag.reranker.reranker_for_collection",
            new=AsyncMock(return_value=None),
        ):
            assert await build_reranker("handbook") is None

    async def test_a_configured_collection_gets_a_cohere_reranker(self):
        with patch(
            "app.services.rag.reranker.reranker_for_collection",
            new=AsyncMock(return_value=ResolvedReranker(model="rerank-v3.5", api_key="co-key")),
        ):
            reranker = await build_reranker("handbook")
        assert isinstance(reranker, CohereReranker)
        assert reranker.model == "rerank-v3.5"


class TestBothPathsRerankThroughOneResolver:
    """Done-when #3: spend is recorded on the agent-run path AND /rag/search.

    Both build their RetrievalService with the same `build_reranker`, so an
    agent's knowledge search reranks exactly as the route does. Before this the
    agent-run path built a RetrievalService with no resolver and never reranked.
    """

    def test_the_request_route_wires_build_reranker(self):
        from app.api.deps import get_retrieval_service

        service = get_retrieval_service(MagicMock())
        assert service._reranker_resolver is build_reranker

    def test_the_agent_run_knowledge_tool_wires_build_reranker(self):
        from app.agents.capabilities.knowledge import _search

        _search._retrieval_service = None
        try:
            service = _search.get_retrieval_service()
            assert service._reranker_resolver is build_reranker
        finally:
            _search._retrieval_service = None

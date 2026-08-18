"""Tests for the RAG reranker.

Two properties carry the weight: the reranker reorders and re-scores the
candidates it is given, and its per-search cost is booked to whatever ledger is
metering the search - priced, because it is computed here rather than looked up
in a price table that does not know rerank models.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.capabilities.budget import SpendLedger, metered_by
from app.services.rag.models import SearchResult
from app.services.rag.reranker import CohereReranker

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

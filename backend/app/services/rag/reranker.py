"""Reordering retrieved candidates by a model's judgement, not by distance.

Vector search sorts by embedding distance, which is a proxy for relevance and
sometimes a poor one. A reranker is a second pass: a cross-encoder scores each
candidate against the query directly and reorders them. Retrieval overfetches,
hands the candidates here, and truncates to the caller's limit afterwards, so a
better answer sitting tenth by distance can surface in the top few.

Cohere is the only provider today. A second one is a second :class:`BaseReranker`
- the interface is what retrieval depends on, and a collection's resolved
credential is what decides which implementation, if any, it gets
(:mod:`app.services.rerank_resolution`).

Spend is booked here, not through :func:`record_ambient_usage`: a rerank call is
priced per search, not per token, and `genai-prices` - which prices everything
else this platform meters - does not know rerank models and would book it
`cost_usd=0, priced=False`. So the cost is computed from Cohere's published
per-search price and handed to :func:`book_ambient_spend` already finished,
landing on whichever ledger is metering the search.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from math import ceil
from typing import TYPE_CHECKING
from uuid import UUID

import cohere

from app.agents.capabilities.budget import SpendEntry, book_ambient_spend
from app.services.rag.models import SearchResult
from app.services.rerank_resolution import reranker_for_collection

if TYPE_CHECKING:
    from cohere import AsyncClientV2

logger = logging.getLogger(__name__)

# Cohere bills reranking per "search unit": one query with up to this many
# documents. The billed figure comes from the response; this is only the
# fallback estimate when the response omits it - one unit per this many
# candidates, which ignores the document-splitting the real figure accounts for.
_DOCS_PER_SEARCH_UNIT = 100

# USD per search unit. Cohere Rerank 3.5 is $2.00 per 1,000 searches.
# Confirmed against https://cohere.com/pricing on 2026-08-18; genai-prices does
# not carry rerank models, so this is the one price in the metering path that
# lives in this repository. A maintainer changing the model or seeing the bill
# drift should re-check that page and this number together.
_PRICE_PER_SEARCH_UNIT_USD = Decimal("0.002")


class BaseReranker(ABC):
    """Reorders retrieved candidates against the query. What retrieval depends on."""

    @abstractmethod
    async def rerank(
        self, query: str, results: list[SearchResult], top_n: int
    ) -> list[SearchResult]:
        """Return the `top_n` most relevant candidates, most relevant first.

        The returned results carry the reranker's relevance score, not the
        vector distance they arrived with, so a caller ordering or thresholding
        on `score` reads the reranker's judgement.
        """


class CohereReranker(BaseReranker):
    """Cohere's rerank endpoint behind :class:`BaseReranker`.

    The client is built on first use and can be injected, so a test drives the
    reranker without a network or a key. A reranker is built per search and
    reranks once, so a client it builds itself is request-scoped: `rerank`
    closes it before returning rather than leaving the httpx connection pool
    open. Nothing else does - the process-wide retrieval service builds a fresh
    reranker every search - so an unclosed client would accumulate one pool per
    query. An injected client belongs to its caller and is left open.
    """

    def __init__(self, model: str, api_key: str, client: AsyncClientV2 | None = None) -> None:
        self.model = model
        self._api_key = api_key
        self._client = client
        self._owns_client = client is None

    def __eq__(self, other: object) -> bool:
        # Two rerankers are the same reranker when they name the same model and
        # pay with the same key. Retrieval compares them across a multi-collection
        # union to decide whether the bound collections share one configuration -
        # only then may one reranker reorder the whole union on one credential.
        if not isinstance(other, CohereReranker):
            return NotImplemented
        return self.model == other.model and self._api_key == other._api_key

    def __hash__(self) -> int:
        return hash((self.model, self._api_key))

    @property
    def client(self) -> AsyncClientV2:
        if self._client is None:
            self._client = cohere.AsyncClientV2(api_key=self._api_key)
        return self._client

    async def rerank(
        self, query: str, results: list[SearchResult], top_n: int
    ) -> list[SearchResult]:
        if not results:
            return []

        client = self.client
        try:
            response = await client.rerank(
                model=self.model,
                query=query,
                documents=[r.content for r in results],
                top_n=min(top_n, len(results)),
            )

            # Booked only once the call has returned: Cohere does not bill a
            # failed request, and a raise propagates to retrieval, which degrades
            # to the un-reranked order rather than failing the search.
            book_ambient_spend(self._spend_entry(response, len(results)))

            return [
                SearchResult(
                    content=results[item.index].content,
                    score=item.relevance_score,
                    metadata=results[item.index].metadata,
                    parent_doc_id=results[item.index].parent_doc_id,
                )
                for item in response.results
            ]
        finally:
            await self._release(client)

    async def _release(self, client: AsyncClientV2) -> None:
        """Close a client this reranker built; leave an injected one alone.

        Best-effort: a failure to return the connection pool is logged, never
        raised, so it cannot mask the rerank's own result or exception.
        """
        if not self._owns_client:
            return
        self._client = None
        try:
            await client.__aexit__(None, None, None)
        except Exception:
            logger.warning("[RERANK] Closing the Cohere client failed", exc_info=True)

    def _spend_entry(self, response: object, candidate_count: int) -> SpendEntry:
        return SpendEntry(
            model_name=self.model,
            input_tokens=0,
            output_tokens=0,
            cost_usd=_PRICE_PER_SEARCH_UNIT_USD * self._billed_units(response, candidate_count),
            priced=True,
        )

    @staticmethod
    def _billed_units(response: object, candidate_count: int) -> int:
        """The search units Cohere actually billed, or an estimate from the count.

        Cohere splits a document past its token threshold into several billable
        documents, so a request with fewer than `_DOCS_PER_SEARCH_UNIT`
        candidates can still cost more than one unit - the ingestion config
        allows chunks large enough for this to happen. The response carries the
        real figure at `meta.billed_units.search_units`; every level of that
        chain is optional, so when it is absent fall back to estimating one unit
        per `_DOCS_PER_SEARCH_UNIT` candidates.
        """
        meta = getattr(response, "meta", None)
        billed = getattr(meta, "billed_units", None)
        search_units = getattr(billed, "search_units", None)
        if search_units is not None:
            return ceil(search_units)
        return ceil(candidate_count / _DOCS_PER_SEARCH_UNIT)


async def build_reranker(
    collection_name: str, organization_id: UUID | None, knowledge_base_id: UUID | None = None
) -> BaseReranker | None:
    """Bind a collection's resolved rerank credential to a concrete reranker.

    The one composition point for reranking: resolution answers whether a
    collection is configured and with whose key, and this turns that into the
    single implementation there is. Shared by every path that retrieves - the
    `/rag/search` route and the agent-run knowledge tool alike - so reranking is
    wired the same way in both, and a second provider is a branch here rather
    than a change at each call site.

    `knowledge_base_id` pins resolution to the knowledge base the caller was
    authorized against, rather than one looked up by the non-unique collection
    name (#913); see `reranker_for_collection`.
    """
    resolved = await reranker_for_collection(collection_name, organization_id, knowledge_base_id)
    if resolved is None:
        return None
    return CohereReranker(model=resolved.model, api_key=resolved.api_key)

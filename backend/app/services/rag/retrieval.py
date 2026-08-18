from __future__ import annotations

import hashlib
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from rank_bm25 import BM25Okapi

from app.services.rag.config import RAGSettings
from app.services.rag.models import SearchResult
from app.services.rag.reranker import BaseReranker
from app.services.rag.vectorstore import BaseVectorStore

logger = logging.getLogger(__name__)

# How a retrieval service learns whether a collection reranks, and with what.
# Async because the answer lives in the database, injected so the store never
# imports platform policy - the same shape as the embedding resolver.
RerankerResolver = Callable[[str], Awaitable[BaseReranker | None]]

# Recall overfetches so min-score filtering and dedup still leave `limit`
# results. A reranker wants a wider net than that - the point of it is to
# surface a good answer sitting well below the top by distance - so it fetches
# more and truncates after reordering.
_DEFAULT_FETCH_MULTIPLIER = 2
_RERANK_FETCH_MULTIPLIER = 4


def _result_key(r: SearchResult) -> str:
    if r.parent_doc_id:
        return f"{r.parent_doc_id}:{r.metadata.get('chunk_num', '')}"
    return hashlib.md5(r.content.encode()).hexdigest()


class BaseRetrievalService(ABC):
    @abstractmethod
    async def retrieve(
        self,
        query: str,
        collection_name: str,
        limit: int = 5,
        min_score: float = 0.0,
        filter: str = "",
    ) -> list[SearchResult]:
        pass


class RetrievalService(BaseRetrievalService):
    def __init__(
        self,
        vector_store: BaseVectorStore,
        settings: RAGSettings,
        reranker_resolver: RerankerResolver | None = None,
    ):
        self.store = vector_store
        self.settings = settings
        self._hybrid_enabled = settings.enable_hybrid_search
        # None leaves retrieval byte-for-byte its pre-reranker self: every path
        # resolves no reranker and truncates by distance, exactly as before.
        self._reranker_resolver = reranker_resolver

    @staticmethod
    def _rrf_fuse(
        vector_results: list[SearchResult],
        bm25_results: list[SearchResult],
        k: int = 60,
    ) -> list[SearchResult]:
        """Reciprocal Rank Fusion of vector and BM25 results."""
        scores: dict[str, float] = {}
        result_map: dict[str, SearchResult] = {}

        for rank, r in enumerate(vector_results):
            key = _result_key(r)
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
            result_map[key] = r

        for rank, r in enumerate(bm25_results):
            key = _result_key(r)
            scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
            if key not in result_map:
                result_map[key] = r

        sorted_keys = sorted(scores, key=lambda x: scores[x], reverse=True)
        return [
            SearchResult(
                content=result_map[key].content,
                score=scores[key],
                metadata=result_map[key].metadata,
                parent_doc_id=result_map[key].parent_doc_id,
            )
            for key in sorted_keys
        ]

    async def _bm25_search(
        self, query: str, collection_name: str, limit: int
    ) -> list[SearchResult]:
        docs = await self.store.get_documents(collection_name)
        if not docs:
            return []

        all_results = await self.store.search(
            collection_name=collection_name, query=query, limit=min(limit * 10, 100)
        )
        if not all_results:
            return []

        corpus = [r.content.lower().split() for r in all_results]
        bm25 = BM25Okapi(corpus)
        query_tokens = query.lower().split()
        bm25_scores = bm25.get_scores(query_tokens)

        scored = sorted(zip(all_results, bm25_scores), key=lambda x: x[1], reverse=True)
        return [
            SearchResult(
                content=r.content,
                score=float(s),
                metadata=r.metadata,
                parent_doc_id=r.parent_doc_id,
            )
            for r, s in scored[:limit]
            if s > 0
        ]

    async def _reranker_for(self, collection_name: str) -> BaseReranker | None:
        """The reranker one collection uses, or None when none is configured.

        None whenever no resolver was injected, so a service built without one
        never reranks and never touches the database looking for a key.
        """
        if self._reranker_resolver is None:
            return None
        return await self._reranker_resolver(collection_name)

    @staticmethod
    async def _rank_and_truncate(
        reranker: BaseReranker | None,
        query: str,
        candidates: list[SearchResult],
        limit: int,
    ) -> list[SearchResult]:
        """Rerank the candidates and keep the top `limit`, or just keep the top.

        A reranker failure degrades to the by-distance order rather than failing
        the search: reranking is an improvement on a working retrieval, and a
        Cohere outage must not take knowledge search down with it. The
        misconfiguration cases never reach here - resolution already turned
        those into no reranker at all - so a raise here is a runtime fault worth
        a log line.
        """
        if reranker is None:
            return candidates[:limit]
        try:
            return await reranker.rerank(query, candidates, limit)
        except Exception:
            logger.warning("[RETRIEVAL] Reranking failed; falling back to distance order")
            return candidates[:limit]

    async def retrieve(
        self,
        query: str,
        collection_name: str,
        limit: int = 5,
        min_score: float = 0.0,
        filter: str = "",
    ) -> list[SearchResult]:
        reranker = await self._reranker_for(collection_name)
        multiplier = _RERANK_FETCH_MULTIPLIER if reranker else _DEFAULT_FETCH_MULTIPLIER
        candidates = await self._recall(
            query, collection_name, limit, min_score, filter, fetch_multiplier=multiplier
        )
        return await self._rank_and_truncate(reranker, query, candidates, limit)

    async def _recall(
        self,
        query: str,
        collection_name: str,
        limit: int,
        min_score: float,
        filter: str,
        *,
        fetch_multiplier: int,
    ) -> list[SearchResult]:
        """Vector (and optionally BM25) recall, filtered and deduplicated.

        Everything retrieval does before ranking: the candidate set, tagged with
        the collection each result came from, not yet truncated to `limit`. Held
        apart from `retrieve` so a multi-collection search can gather candidates
        from several collections and rerank the union once, rather than reranking
        each collection and merging the winners.
        """
        logger.info(
            "[RETRIEVAL] Query: '%.50s...', collection: %s, limit: %d, filter: '%s'",
            query,
            collection_name,
            limit,
            filter,
        )

        start_time = time.time()

        pipeline_results = await self.store.search(
            collection_name=collection_name,
            query=query,
            filter_expr=filter,
            limit=limit * fetch_multiplier,
        )

        search_time = time.time() - start_time
        logger.info(
            "[RETRIEVAL] Vector search completed in %.3fs, found %d results",
            search_time,
            len(pipeline_results),
        )

        if self._hybrid_enabled:
            bm25_results = await self._bm25_search(query, collection_name, limit * fetch_multiplier)
            if bm25_results:
                pipeline_results = self._rrf_fuse(pipeline_results, bm25_results)
                logger.info("[RETRIEVAL] Hybrid search: fused %d results", len(pipeline_results))

        for i, r in enumerate(pipeline_results[:3]):
            logger.debug(
                "[RETRIEVAL] Initial result #%d: score=%.4f, content='%.50s...'",
                i + 1,
                r.score,
                r.content,
            )

        filtered_results = [res for res in pipeline_results if res.score >= min_score]

        seen_keys: set[str] = set()
        deduped_results: list[SearchResult] = []
        for r in filtered_results:
            key = _result_key(r)
            if key not in seen_keys:
                seen_keys.add(key)
                deduped_results.append(r)

        if len(deduped_results) < len(filtered_results):
            logger.info(
                "[RETRIEVAL] Deduplicated: %d -> %d results",
                len(filtered_results),
                len(deduped_results),
            )

        for i, r in enumerate(deduped_results[:3]):
            logger.debug(
                "[RETRIEVAL] Final result #%d: score=%.4f, content='%.50s...'",
                i + 1,
                r.score,
                r.content,
            )

        # Which collection answered, on every result rather than only when several
        # were searched. A caller cannot derive it - one search may span bases and
        # two bases may share a collection - and a chunk whose origin is unknown
        # cannot be cited, which is the whole job of a retrieval result. Stamped
        # here on every candidate so it survives reranking, which builds fresh
        # results carrying this metadata forward.
        for r in deduped_results:
            r.metadata["collection"] = collection_name

        total_time = time.time() - start_time
        logger.info(
            "[RETRIEVAL] Total recall time: %.3fs, %d candidates",
            total_time,
            len(deduped_results),
        )

        return deduped_results

    async def retrieve_multi(
        self,
        query: str,
        collection_names: list[str],
        limit: int = 5,
        min_score: float = 0.0,
    ) -> list[SearchResult]:
        """Search several collections and merge what they return.

        A collection that fails takes the whole search with it. Skipping it would
        answer 200 with the collections that happened to work, and a partial
        answer presented as a complete one is the same untruth as an empty state
        standing in for an error - worse here, because the caller is asking "is
        this in our knowledge" and would read a shortfall as "no".

        A collection nobody has ingested into is not a failure: its table does
        not exist yet, and the store reports that as no results.

        When a reranker is configured it runs once over the union of every
        collection's candidates, not per collection: the bound collections of
        one agent share one organization and so one reranker, and reranking each
        collection separately then merging the winners would rank against the
        wrong pool. Absent a reranker this is byte-for-byte the previous merge -
        each collection's top `limit`, fused, sorted, deduplicated, truncated.
        """
        reranker = await self._reranker_for(collection_names[0]) if collection_names else None
        multiplier = _RERANK_FETCH_MULTIPLIER if reranker else _DEFAULT_FETCH_MULTIPLIER

        all_results: list[SearchResult] = []
        for name in collection_names:
            recalled = await self._recall(
                query, name, limit, min_score, "", fetch_multiplier=multiplier
            )
            all_results.extend(recalled if reranker else recalled[:limit])

        all_results.sort(key=lambda r: r.score, reverse=True)

        seen_keys: set[str] = set()
        deduped: list[SearchResult] = []
        for r in all_results:
            key = _result_key(r)
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(r)

        return await self._rank_and_truncate(reranker, query, deduped, limit)

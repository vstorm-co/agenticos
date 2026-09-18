from __future__ import annotations

import hashlib
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from uuid import UUID

from rank_bm25 import BM25Okapi

from app.services.rag.config import RAGSettings
from app.services.rag.filters import (
    RetrievalFilters,
    RetrievalQuery,
    RetrievalScope,
    compose,
    scope_for_tenant,
)
from app.services.rag.models import SearchResult
from app.services.rag.vectorstore import BaseVectorStore

logger = logging.getLogger(__name__)


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
        *,
        scope: RetrievalScope,
        filters: RetrievalFilters | None = None,
        limit: int = 5,
        min_score: float = 0.0,
    ) -> list[SearchResult]:
        pass


class RetrievalService(BaseRetrievalService):
    def __init__(
        self,
        vector_store: BaseVectorStore,
        settings: RAGSettings,
    ):
        self.store = vector_store
        self.settings = settings
        self._hybrid_enabled = settings.enable_hybrid_search

    async def resolve_scope(
        self, collection_name: str, organization_id: UUID | None
    ) -> RetrievalScope:
        """The scope a search of this collection should carry, resolved by name.

        For a caller that holds only a collection name and its own organization -
        the agent capability, the CLI - not an already-authorized knowledge base
        row. It asks the store's own `resolve_tenant` (its own organization for an
        org base, `None` for an app-scoped one every organization reads or a
        collection no base claims, #1684) and converts that into the matching
        scope shape (`TenantScope` or `AppScope`, FA-039). A caller that already
        resolved and authorized the base for this name - the `/search` route,
        through `CollectionAccessService` - builds its scope directly from that
        base's own `vector_tenant` with `scope_for_tenant` instead, so it never
        re-resolves a name the resolver could prefer a different, same-named base
        for (#1684).
        """
        tenant = await self.store.resolve_tenant(collection_name, organization_id)
        return scope_for_tenant(tenant)

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
        self, query: str, collection_name: str, limit: int, query_filter: RetrievalQuery
    ) -> list[SearchResult]:
        """Rerank the vector store's own filtered candidates by BM25 score.

        This is **rerank-over-filtered-candidates**, not a corpus-wide keyword
        search: it scores only the rows the vector `store.search` returns
        (`limit=min(limit*10,100)`), and those are already restricted by the same
        `query_filter` the vector leg used. So the security guarantee holds - the
        candidate set is pre-filtered before BM25 sees it, and fusion can never
        reintroduce an out-of-scope row. A true corpus-wide keyword query is
        deferred (and is where an OpenSearch adapter would land). The old unscoped
        `get_documents()` non-empty probe was removed: on a shared table it read
        across tenants, and an empty `store.search` already answers the same
        "nothing to rank" question fail-closed.
        """
        all_results = await self.store.search(
            collection_name=collection_name,
            query=query,
            query_filter=query_filter,
            limit=min(limit * 10, 100),
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

    async def retrieve(
        self,
        query: str,
        collection_name: str,
        *,
        scope: RetrievalScope,
        filters: RetrievalFilters | None = None,
        limit: int = 5,
        min_score: float = 0.0,
    ) -> list[SearchResult]:
        # Overfetch so min-score filtering and dedup still leave `limit` results.
        fetch_multiplier = 2

        # Composed once and threaded through every candidate-producing query
        # (the vector leg and the BM25 rerank), so no path can skip enforcement.
        query_filter = compose(scope, filters)

        logger.info(
            "[RETRIEVAL] Query: '%.50s...', collection: %s, limit: %d",
            query,
            collection_name,
            limit,
        )

        start_time = time.time()

        pipeline_results = await self.store.search(
            collection_name=collection_name,
            query=query,
            query_filter=query_filter,
            limit=limit * fetch_multiplier,
        )

        search_time = time.time() - start_time
        logger.info(
            "[RETRIEVAL] Vector search completed in %.3fs, found %d results",
            search_time,
            len(pipeline_results),
        )

        if self._hybrid_enabled:
            bm25_results = await self._bm25_search(
                query, collection_name, limit * fetch_multiplier, query_filter
            )
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

        final_results = deduped_results[:limit]

        # Which collection answered, on every result rather than only when several
        # were searched. A caller cannot derive it - one search may span bases and
        # two bases may share a collection - and a chunk whose origin is unknown
        # cannot be cited, which is the whole job of a retrieval result.
        for r in final_results:
            r.metadata["collection"] = collection_name

        total_time = time.time() - start_time
        logger.info(
            "[RETRIEVAL] Total retrieval time: %.3fs, returning %d results",
            total_time,
            len(final_results),
        )

        return final_results

    async def retrieve_multi(
        self,
        query: str,
        collection_names: list[str],
        *,
        scopes: Mapping[str, RetrievalScope],
        filters: RetrievalFilters | None = None,
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

        `scopes` maps each name to the `RetrievalScope` the caller resolved and
        authorized for it - its own `TenantScope` for an org base, `AppScope` for
        an app-scoped one (#1684, FA-039) - so each collection is read under the
        scope that matches its own rows rather than one shared scope built from
        the caller's raw organization, which cannot match an app-scoped base's
        untagged rows.

        One per name, with no fallback: a shared default would read a collection
        whose scope the caller did not resolve under a *different* collection's
        tenant, which is the one mistake this whole parameter exists to prevent.
        A name with no scope is refused instead.

        Raises:
            AssertionError: A name in `collection_names` has no scope. Not a
                caller's input error - both in-tree callers build the map from
                the same bases they build the name list from - so it is a bug in
                a caller rather than something to answer with a 4xx.
        """
        missing = [name for name in collection_names if name not in scopes]
        if missing:
            raise AssertionError(f"no retrieval scope resolved for: {', '.join(sorted(missing))}")
        all_results: list[SearchResult] = []
        for name in collection_names:
            this_scope = scopes[name]
            all_results.extend(
                await self.retrieve(
                    query=query,
                    collection_name=name,
                    scope=this_scope,
                    filters=filters,
                    limit=limit,
                    min_score=min_score,
                )
            )

        all_results.sort(key=lambda r: r.score, reverse=True)

        seen_keys: set[str] = set()
        deduped: list[SearchResult] = []
        for r in all_results:
            key = _result_key(r)
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(r)

        return deduped[:limit]

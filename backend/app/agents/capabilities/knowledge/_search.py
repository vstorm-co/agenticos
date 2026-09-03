"""RAG tool for agent knowledge base search."""

import contextvars
import logging
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.core.exceptions import AppException, ExternalServiceError
from app.db.session import on_the_pooled_loop
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.retrieval import RetrievalService
from app.services.rag.vectorstore import process_vector_store, unpooled_vector_store

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.rag.retrieval import BaseRetrievalService

_pooled_service: "BaseRetrievalService | None" = None
_unpooled_service: "BaseRetrievalService | None" = None


def get_retrieval_service() -> "BaseRetrievalService":
    """The retrieval service for the loop this search is running on.

    An agent is the one vector caller that does not know which loop it is on: it
    runs on the API's loop in one process and on a Prefect flow's loop in
    another. That decides which engine its store may ride, because a pooled
    asyncpg connection belongs to the loop that opened it - a store cached for
    the life of the process and shared by two loops in one worker handed the
    second a connection the first had opened, and the search failed with
    `InterfaceError: attached to a different loop`, intermittently and invisibly
    to any test with one loop in it (#1079).

    So: on the loop that owns the process's pools, the store the API means -
    `vector_engine`, bounded by `DB_POOL_SIZE + DB_MAX_OVERFLOW`, the same store
    the lifespan and every request use. Anywhere else, a store on the pool-less
    engine, which caches no connection and so has none to hand to the wrong
    loop. Both are held for the life of the process rather than rebuilt per
    search, which would rebuild the embedding client per turn; neither builds a
    pool of its own, which is the second pool #948 removed.

    Keeping the pooled store for the API is what bounds this. `NullPool` opens a
    connection per checkout and caps nothing, so serving the API from it would
    let a burst of concurrent runs reach `max_connections` where the pool used to
    queue. Off that loop the bound is the worker's own flow concurrency.
    """
    global _pooled_service, _unpooled_service
    rag_settings = settings.rag

    if on_the_pooled_loop():
        if _pooled_service is None:
            _pooled_service = RetrievalService(
                process_vector_store(rag_settings, EmbeddingService(rag_settings)), rag_settings
            )
        return _pooled_service

    if _unpooled_service is None:
        _unpooled_service = RetrievalService(
            unpooled_vector_store(rag_settings, EmbeddingService(rag_settings)), rag_settings
        )
    return _unpooled_service


def reset_retrieval_service() -> None:
    """Forget both cached stores, at shutdown.

    A store is built on the first knowledge search and then held for the life of
    the process; what a shutdown owes is only that the next search builds
    afresh, so a shutdown followed by more work - a test, a reload - does not
    search through a store whose engine `close_db` has disposed. Neither store
    owns a pool of its own, so there is nothing here to close.
    """
    global _pooled_service, _unpooled_service
    _pooled_service = None
    _unpooled_service = None


def _format_results(results: list[Any]) -> str:
    if not results:
        return "No relevant documents found in the knowledge base."
    formatted = []
    for i, result in enumerate(results, start=1):
        source = result.metadata.get("filename", "unknown")
        page = result.metadata.get("page_num", "")
        chunk = result.metadata.get("chunk_num", "")
        col = result.metadata.get("collection", "")
        page_info = f", page {page}" if page else ""
        chunk_info = f", chunk {chunk}" if chunk else ""
        col_info = f" [{col}]" if col else ""
        formatted.append(
            f"[{i}] Source: {source}{page_info}{chunk_info}{col_info} (score: {result.score:.3f})\n"
            f"{result.content}"
        )
    return (
        "Search results (cite inline using [1], [2], etc. - do NOT list sources at the end):\n\n"
        + "\n\n".join(formatted)
    )


# ContextVar set by non-PydanticAI frameworks before each agent invocation so that
# the tool can read the active KB collections without needing explicit Deps injection.
# Default is None (not []) - mutable defaults on ContextVar are a foot-gun
# because every reader gets the same shared list. Callers should treat None
# as "no collections active".
_active_kb_collections: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "_active_kb_collections", default=None
)


async def search_knowledge_base(
    query: str,
    kb_collection_names: list[str] | None = None,
    top_k: int = 5,
) -> str:
    """Search the knowledge base and return formatted results.

    Args:
        query: The search query string.
        kb_collection_names: Vector-store collection names resolved server-side from the
            agent's spec. Never supplied by the LLM directly - injected via
            PydanticAI Deps or the _active_kb_collections ContextVar.
        top_k: Number of top results to retrieve (default: 5).
    """
    resolved = kb_collection_names if kb_collection_names else (_active_kb_collections.get() or [])
    if not resolved:
        return "No active knowledge bases selected for this conversation."

    service: Any = get_retrieval_service()
    one_collection = len(resolved) == 1
    try:
        if one_collection:
            results = await service.retrieve(query=query, collection_name=resolved[0], limit=top_k)
        else:
            results = await service.retrieve_multi(
                query=query, collection_names=resolved, limit=top_k
            )
    except AppException:
        # Already an account of what is wrong and what to do about it - an
        # unconfigured embedding credential names the setting to set. Rewrapping
        # it as "search failed" would replace that with a symptom.
        raise
    except Exception as e:
        # The upstream text stays here and goes no further. `details` is
        # serialized into the response body, and `str(e)` on an embedding or
        # vector-store client is not a controlled string: provider SDKs put the
        # failing request URL in the message, and a URL carries a key in its
        # query string. What the caller can act on is which collections were
        # searched and how, so that is what the refusal carries (agenticos#342).
        logger.exception("Knowledge base search failed")
        raise ExternalServiceError(
            message="Knowledge base search failed",
            details={
                "collections": resolved,
                "operation": "retrieve" if one_collection else "retrieve_multi",
            },
        ) from e

    return _format_results(results)


__all__ = ["search_knowledge_base"]

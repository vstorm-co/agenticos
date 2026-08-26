"""RAG tool for agent knowledge base search."""

import asyncio
import contextvars
import logging
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.core.exceptions import AppException, ExternalServiceError
from app.services.embedding_resolution import embeddings_for_collection
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.retrieval import RetrievalService
from app.services.rag.vectorstore import PgVectorStore

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.rag.retrieval import BaseRetrievalService

    _Cache = tuple[BaseRetrievalService, PgVectorStore, asyncio.AbstractEventLoop]

# The service, its store, and the loop they belong to - held as one value so it
# is published and read in a single reference assignment. Three separate globals
# could interleave under two threads-with-loops: A stores its service, B replaces
# all three for loop B, A then overwrites only the loop tag with loop A, and a
# later call on loop A reads B's loop-bound store back (#1079 review). One tuple
# cannot half-update.
_cache: "_Cache | None" = None


def get_retrieval_service() -> "BaseRetrievalService":
    """The retrieval service for the running event loop, built once per loop.

    The store owns a pooled SQLAlchemy engine, and a pooled asyncpg connection
    is bound to the loop that opened it. A single process-wide singleton is
    right for the API, which serves every request on one long-lived loop - but
    agents also run inside the Prefect worker, where a second flow run can reach
    this from a *different* loop, and a store checked out there would hand it a
    connection made on the first loop (`InterfaceError: attached to a different
    loop`, intermittent and invisible to any single-loop test) (#1079).

    So the store is keyed on the running loop rather than held unconditionally.
    The common paths keep one store: the API builds it once and disposes it at
    shutdown, and the worker's usual one-loop-per-flow-subprocess run builds one
    per process. A worker that runs two flows on two loops in one process builds
    one per loop; the store from a loop that has moved on is dropped rather than
    reused - its pool cannot be disposed from another loop, so this trades a
    bounded, at-most-one-behind leak for never handing a live loop a dead one's
    connection. `get_worker_db_context` in `app/db/session.py` states the same
    cross-loop rule for the pool it hands out.
    """
    global _cache
    loop = asyncio.get_running_loop()
    cached = _cache
    if cached is not None and cached[2] is loop:
        return cached[0]

    rag_settings = settings.rag
    embedding_service = EmbeddingService(rag_settings)
    vector_store = PgVectorStore(
        rag_settings, embedding_service, resolver=embeddings_for_collection
    )
    service = RetrievalService(vector_store, rag_settings)
    _cache = (service, vector_store, loop)
    return service


async def aclose_retrieval_service() -> None:
    """Release the pool this module's store opened, at shutdown.

    The store is built on the first knowledge search and then held for the life
    of the loop that built it, which is right - rebuilding it per search would
    open a connection pool per turn. What was missing is the other end: nothing
    released it, so a second pool sat beside the one the lifespan built and
    outlived the shutdown that disposed that one (#948).

    Called from the lifespan on the API's own loop, so it disposes the store
    that loop built. Clearing the cache makes the next search build a fresh
    store, so a shutdown that is followed by more work - a test, a reload - does
    not search through a disposed one.
    """
    global _cache
    cached, _cache = _cache, None
    if cached is not None:
        await cached[1].aclose()


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

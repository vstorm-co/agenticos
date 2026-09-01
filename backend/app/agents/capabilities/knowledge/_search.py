"""RAG tool for agent knowledge base search."""

import contextvars
import logging
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.core.exceptions import AppException, ExternalServiceError
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.retrieval import RetrievalService
from app.services.rag.vectorstore import unpooled_vector_store

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.rag.retrieval import BaseRetrievalService

_retrieval_service: "BaseRetrievalService | None" = None


def get_retrieval_service() -> "BaseRetrievalService":
    """Get or create the retrieval service singleton, on any event loop.

    The store builds no pool of its own - it used to, which put a second
    `DB_POOL_SIZE + DB_MAX_OVERFLOW` pool beside the application's in every
    process that ever searched (#948, #12) - and it does not take the process's
    vector pool either, which is what `unpooled_vector_store` buys here.

    An agent is the one vector caller that does not know which loop it is on: it
    runs on the API's loop in one process and on a Prefect flow's loop in
    another. A pooled store cached for the life of the process is right for the
    first and wrong for the second, because a pooled asyncpg connection belongs
    to the loop that opened it - so a worker running two flows in one process
    handed the second loop a connection made on the first, and the search failed
    with `InterfaceError: attached to a different loop`, intermittently and
    invisibly to any single-loop test (#1079). On `NullPool` there is no cached
    connection to hand to the wrong loop, so one singleton serves every loop and
    a search costs one connect - beside an embedding request an order of
    magnitude dearer.
    """
    global _retrieval_service
    if _retrieval_service is not None:
        return _retrieval_service

    rag_settings = settings.rag
    embedding_service = EmbeddingService(rag_settings)
    _retrieval_service = RetrievalService(
        unpooled_vector_store(rag_settings, embedding_service), rag_settings
    )
    return _retrieval_service


def reset_retrieval_service() -> None:
    """Forget the cached store, at shutdown.

    The store is built on the first knowledge search and then held for the life
    of the process, which is right - rebuilding it per search would rebuild its
    embedding client per turn - and it is held across event loops, which
    `unpooled_vector_store` is what makes safe (#1079). It owns no pool of its
    own; what a shutdown owes is only that the next search builds afresh, so a
    shutdown followed by more work - a test, a reload - does not search through
    a store whose engine `close_db` has disposed.
    """
    global _retrieval_service
    _retrieval_service = None


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

"""RAG tool for agent knowledge base search."""

import contextvars
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.config import settings
from app.core.exceptions import AppException, ExternalServiceError
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.reranker import build_reranker
from app.services.rag.retrieval import RetrievalService
from app.services.rag.vectorstore import process_vector_store

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.rag.retrieval import BaseRetrievalService

_retrieval_service: "BaseRetrievalService | None" = None


def get_retrieval_service() -> "BaseRetrievalService":
    """Get or create retrieval service singleton.

    The store rides the process's own engine rather than building a pool of its
    own - it used to, which put a second `DB_POOL_SIZE + DB_MAX_OVERFLOW` pool
    beside the application's in every process that ever searched (#948, #12).
    """
    global _retrieval_service
    if _retrieval_service is not None:
        return _retrieval_service

    rag_settings = settings.rag
    embedding_service = EmbeddingService(rag_settings)
    # The reranker resolver is wired here too, not only on the /rag/search
    # route: an agent's knowledge search reranks when its collection is
    # configured, and the run's open ledger books the cost - which is the
    # agent-run half of "spend recorded on both paths".
    _retrieval_service = RetrievalService(
        process_vector_store(rag_settings, embedding_service),
        rag_settings,
        reranker_resolver=build_reranker,
    )
    return _retrieval_service


def reset_retrieval_service() -> None:
    """Forget the cached store, at shutdown.

    The store is built on the first knowledge search and then held for the life
    of the process, which is right - rebuilding it per search would rebuild its
    embedding client per turn. It owns no pool of its own any more; what a
    shutdown owes is only that the next search builds afresh, so a shutdown
    followed by more work - a test, a reload - does not search through a store
    whose engine `close_db` has disposed.
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
    *,
    organization_id: UUID | None,
    kb_collection_ids: list[UUID] | None = None,
) -> str:
    """Search the knowledge base and return formatted results.

    Args:
        query: The search query string.
        kb_collection_names: Vector-store collection names resolved server-side from the
            agent's spec. Never supplied by the LLM directly - injected via
            PydanticAI Deps or the _active_kb_collections ContextVar.
        top_k: Number of top results to retrieve (default: 5).
        organization_id: The organization the run acts for, so a collection name
            shared across tenants resolves this one's embedding and rerank config
            rather than another's (#913).
        kb_collection_ids: The bound knowledge base id for each name, aligned by
            index, so a name shared by another row in the same organization
            resolves the bound row rather than whichever the name selects first
            (#913). Absent - the ContextVar fallback, which carries no ids - each
            collection falls back to the organization-scoped lookup.
    """
    resolved = kb_collection_names if kb_collection_names else (_active_kb_collections.get() or [])
    if not resolved:
        return "No active knowledge bases selected for this conversation."

    ids = kb_collection_ids or []
    aligned_ids = ids if len(ids) == len(resolved) else None

    service: Any = get_retrieval_service()
    one_collection = len(resolved) == 1
    try:
        if one_collection:
            results = await service.retrieve(
                query=query,
                collection_name=resolved[0],
                limit=top_k,
                organization_id=organization_id,
                knowledge_base_id=aligned_ids[0] if aligned_ids else None,
            )
        else:
            results = await service.retrieve_multi(
                query=query,
                collection_names=resolved,
                limit=top_k,
                organization_id=organization_id,
                knowledge_base_ids=aligned_ids,
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

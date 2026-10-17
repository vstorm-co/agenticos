"""D3 slice 8 — Shop widget FAQ answers via Agentra RAG (no multi-agent LLM)."""

from __future__ import annotations

import logging
from functools import lru_cache
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.commands.rag import get_rag_services
from app.core.config import settings
from app.services.rag.models import SearchResult
from app.services.rag.retrieval import RetrievalService
from app.services.shop_tenant_knowledge import resolve_shop_tenant_kb

logger = logging.getLogger(__name__)

_FAQ_MIN_SCORE = 0.25
_FAQ_LIMIT = 4


def shop_native_widget_faq_rag_enabled() -> bool:
    return settings.SHOP_AI_NATIVE_WIDGET_FAQ_RAG_ENABLED


@lru_cache(maxsize=1)
def _cached_retrieval() -> RetrievalService:
    _, vector_store, _, retrieval, _ = get_rag_services()
    _ = vector_store  # keep reference with retrieval
    return retrieval


async def try_widget_faq_rag_reply(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    message: str,
    kb_id: UUID | None,
) -> str | None:
    """Vector search over shop org KBs; returns a short Vietnamese reply or None."""
    if not shop_native_widget_faq_rag_enabled():
        return None

    ctx = await resolve_shop_tenant_kb(db, tenant_id=tenant_id, kb_id=kb_id)
    if ctx is None:
        return None

    query = (message or "").strip()
    if not query:
        return None

    retrieval = _cached_retrieval()
    try:
        if len(ctx.collection_names) > 1:
            results = await retrieval.retrieve_multi(
                query,
                ctx.collection_names,
                scopes=ctx.scopes,
                limit=_FAQ_LIMIT,
                min_score=_FAQ_MIN_SCORE,
            )
        else:
            name = ctx.collection_names[0]
            results = await retrieval.retrieve(
                query,
                name,
                scope=ctx.scopes[name],
                limit=_FAQ_LIMIT,
                min_score=_FAQ_MIN_SCORE,
            )
    except Exception:
        logger.warning(
            "widget_faq_rag_search_failed",
            extra={
                "tenant_id": str(tenant_id),
                "kb_id": str(ctx.effective_kb.id),
            },
            exc_info=True,
        )
        return None

    return _format_faq_reply(results)


async def retrieve_faq_rag_draft_text(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    question: str,
    kb_id: UUID | None = None,
) -> str | None:
    """Top KB excerpts as plain text (Studio FAQ suggestion draft, B57)."""
    if not shop_native_widget_faq_rag_enabled():
        return None

    ctx = await resolve_shop_tenant_kb(db, tenant_id=tenant_id, kb_id=kb_id)
    if ctx is None:
        return None

    query = (question or "").strip()
    if not query:
        return None

    retrieval = _cached_retrieval()
    try:
        if len(ctx.collection_names) > 1:
            results = await retrieval.retrieve_multi(
                query,
                ctx.collection_names,
                scopes=ctx.scopes,
                limit=_FAQ_LIMIT,
                min_score=_FAQ_MIN_SCORE,
            )
        else:
            name = ctx.collection_names[0]
            results = await retrieval.retrieve(
                query,
                name,
                scope=ctx.scopes[name],
                limit=_FAQ_LIMIT,
                min_score=_FAQ_MIN_SCORE,
            )
    except Exception:
        logger.warning(
            "faq_rag_draft_search_failed",
            extra={"tenant_id": str(tenant_id), "kb_id": str(ctx.effective_kb.id)},
            exc_info=True,
        )
        return None

    chunks: list[str] = []
    for hit in results[:3]:
        text = (hit.content or "").strip()
        if text and text not in chunks:
            chunks.append(text)
    if not chunks:
        return None
    return "\n\n".join(chunks)


def _format_faq_reply(results: list[SearchResult]) -> str | None:
    chunks: list[str] = []
    for hit in results[:3]:
        text = (hit.content or "").strip()
        if text and text not in chunks:
            chunks.append(text)
    if not chunks:
        return None
    body = "\n\n".join(chunks)
    return f"Dạ, theo thông tin shop:\n\n{body}"


def reset_widget_faq_rag_cache_for_tests() -> None:
    _cached_retrieval.cache_clear()

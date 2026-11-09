"""Ingestion spend repository (PostgreSQL async)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.ingestion_spend import IngestionSpend
from app.db.models.organization import Organization
from app.db.models.rag_document import RAGDocument


async def record(
    db: AsyncSession,
    *,
    organization_id: UUID | None,
    rag_document_id: UUID | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: Decimal,
    cost_is_partial: bool,
    improvement_run_id: UUID | None = None,
) -> IngestionSpend | None:
    """Write one window's spend, against its document if that is still there.

    A document deleted while it was being indexed still spent what it spent, so
    the row is written against no document rather than refused by the foreign
    key - which failed the ingest after its chunks were written, before the
    settlement that removes them could run (#2565). The row is held `FOR KEY
    SHARE` to the insert's commit: a delete arriving after the check waits, then
    sets this row's reference to `NULL` as it does every other's. The
    organization is held first. An organization's purge, and an account
    deletion (#2638), lock the two in that order; taken the other way round,
    they and this insert deadlocked.

    An organization deleted meanwhile is the one case that writes nothing and
    returns `None`. Its spend rows `CASCADE` with it, so this row would have gone
    had it been written a moment earlier, and the insert would otherwise fail the
    foreign key and the ingest with it.
    """
    if organization_id is not None:
        held = await db.scalar(
            select(Organization.id)
            .where(Organization.id == organization_id)
            .with_for_update(read=True, key_share=True)
        )
        if held is None:
            return None
    if rag_document_id is not None:
        rag_document_id = await db.scalar(
            select(RAGDocument.id)
            .where(RAGDocument.id == rag_document_id)
            .with_for_update(read=True, key_share=True)
        )
    spend = IngestionSpend(
        organization_id=organization_id,
        rag_document_id=rag_document_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        cost_is_partial=cost_is_partial,
        improvement_run_id=improvement_run_id,
    )
    db.add(spend)
    await db.flush()
    await db.refresh(spend)
    return spend


async def sum_cost_since(
    db: AsyncSession, *, organization_id: UUID, since: datetime, until: datetime | None = None
) -> Decimal:
    """Total ingestion spend in a window - the half of a monthly budget runs cannot see."""
    query = select(func.coalesce(func.sum(IngestionSpend.cost_usd), 0)).where(
        IngestionSpend.organization_id == organization_id,
        IngestionSpend.created_at >= since,
    )
    if until is not None:
        query = query.where(IngestionSpend.created_at < until)
    result = await db.scalar(query)
    return Decimal(result or 0)


async def sum_cost_window(
    db: AsyncSession, *, organization_id: UUID, start: datetime, end: datetime
) -> Decimal:
    """Ingestion spend inside a closed window - the dashboard's half of the bill.

    Distinct from :func:`sum_cost_since`, which is open-ended and feeds budget
    enforcement: a cap is measured against the calendar month, a dashboard
    period against whatever window its filter chose. Half-open at the end, the
    same way `agent_run_repo.sum_cost_window` is, so a document indexed at
    23:59:59 on the last day counts once and only once.
    """
    result = await db.scalar(
        select(func.coalesce(func.sum(IngestionSpend.cost_usd), 0)).where(
            IngestionSpend.organization_id == organization_id,
            IngestionSpend.created_at >= start,
            IngestionSpend.created_at < end,
        )
    )
    return Decimal(result or 0)

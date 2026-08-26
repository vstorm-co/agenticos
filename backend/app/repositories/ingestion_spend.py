"""Ingestion spend repository (PostgreSQL async)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.ingestion_spend import IngestionSpend, SpendSource


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
    source: SpendSource = SpendSource.INGESTION,
) -> IngestionSpend:
    spend = IngestionSpend(
        organization_id=organization_id,
        rag_document_id=rag_document_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        cost_is_partial=cost_is_partial,
        source=source.value,
    )
    db.add(spend)
    await db.flush()
    await db.refresh(spend)
    return spend


async def sum_cost_since(db: AsyncSession, *, organization_id: UUID, since: datetime) -> Decimal:
    """Total non-run RAG spend in a window - the half of a monthly budget runs cannot see.

    Every source: indexing and a direct search both count toward the cap, so
    this is deliberately unfiltered where the dashboard split is not.
    """
    result = await db.scalar(
        select(func.coalesce(func.sum(IngestionSpend.cost_usd), 0)).where(
            IngestionSpend.organization_id == organization_id,
            IngestionSpend.created_at >= since,
        )
    )
    return Decimal(result or 0)


async def sum_cost_window(
    db: AsyncSession,
    *,
    organization_id: UUID,
    start: datetime,
    end: datetime,
    source: SpendSource | None = None,
) -> Decimal:
    """Non-run RAG spend inside a closed window - the dashboard's half of the bill.

    Distinct from :func:`sum_cost_since`, which is open-ended and feeds budget
    enforcement: a cap is measured against the calendar month, a dashboard
    period against whatever window its filter chose. Half-open at the end, the
    same way `agent_run_repo.sum_cost_window` is, so a document indexed at
    23:59:59 on the last day counts once and only once.

    `source` narrows to indexing or retrieval; the dashboard sums each on its
    own so a search is not reported as indexing. `None` sums both.
    """
    conditions = [
        IngestionSpend.organization_id == organization_id,
        IngestionSpend.created_at >= start,
        IngestionSpend.created_at < end,
    ]
    if source is not None:
        conditions.append(IngestionSpend.source == source.value)
    result = await db.scalar(
        select(func.coalesce(func.sum(IngestionSpend.cost_usd), 0)).where(*conditions)
    )
    return Decimal(result or 0)

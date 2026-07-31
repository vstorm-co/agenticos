"""Ingestion spend repository (PostgreSQL async)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.ingestion_spend import IngestionSpend


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
) -> IngestionSpend:
    spend = IngestionSpend(
        organization_id=organization_id,
        rag_document_id=rag_document_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        cost_is_partial=cost_is_partial,
    )
    db.add(spend)
    await db.flush()
    await db.refresh(spend)
    return spend


async def sum_cost_since(db: AsyncSession, *, organization_id: UUID, since: datetime) -> Decimal:
    """Total ingestion spend in a window - the half of a monthly budget runs cannot see."""
    result = await db.scalar(
        select(func.coalesce(func.sum(IngestionSpend.cost_usd), 0)).where(
            IngestionSpend.organization_id == organization_id,
            IngestionSpend.created_at >= since,
        )
    )
    return Decimal(result or 0)

"""Shop FAQ entry repository (D3 B57)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.shop_faq_entry import ShopFaqEntry


async def list_for_kb(
    db: AsyncSession,
    *,
    kb_id: UUID,
    minerp_tenant_id: UUID,
) -> list[ShopFaqEntry]:
    result = await db.execute(
        select(ShopFaqEntry)
        .where(
            ShopFaqEntry.knowledge_base_id == kb_id,
            ShopFaqEntry.minerp_tenant_id == minerp_tenant_id,
        )
        .order_by(ShopFaqEntry.sort_order.asc(), ShopFaqEntry.created_at.asc())
    )
    return list(result.scalars().all())


async def get_by_id(
    db: AsyncSession,
    *,
    entry_id: UUID,
    kb_id: UUID,
    minerp_tenant_id: UUID,
) -> ShopFaqEntry | None:
    result = await db.execute(
        select(ShopFaqEntry).where(
            ShopFaqEntry.id == entry_id,
            ShopFaqEntry.knowledge_base_id == kb_id,
            ShopFaqEntry.minerp_tenant_id == minerp_tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    *,
    minerp_tenant_id: UUID,
    organization_id: UUID,
    knowledge_base_id: UUID,
    question: str,
    answer: str,
    sort_order: int = 0,
    is_published: bool = True,
) -> ShopFaqEntry:
    row = ShopFaqEntry(
        minerp_tenant_id=minerp_tenant_id,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        question=question,
        answer=answer,
        sort_order=sort_order,
        is_published=is_published,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def update(
    db: AsyncSession,
    entry: ShopFaqEntry,
    *,
    question: str | None = None,
    answer: str | None = None,
    sort_order: int | None = None,
    is_published: bool | None = None,
) -> ShopFaqEntry:
    if question is not None:
        entry.question = question
    if answer is not None:
        entry.answer = answer
    if sort_order is not None:
        entry.sort_order = sort_order
    if is_published is not None:
        entry.is_published = is_published
    entry.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(entry)
    return entry


async def delete(db: AsyncSession, entry: ShopFaqEntry) -> None:
    await db.delete(entry)
    await db.flush()


async def next_sort_order(db: AsyncSession, *, kb_id: UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(ShopFaqEntry.sort_order), -1))
        .select_from(ShopFaqEntry)
        .where(ShopFaqEntry.knowledge_base_id == kb_id)
    )
    return int(result.scalar_one()) + 1

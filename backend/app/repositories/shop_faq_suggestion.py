"""Shop FAQ suggestion repository (D3 B56)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.shop_faq_suggestion import ShopFaqSuggestion


async def list_all_for_kb(
    db: AsyncSession,
    *,
    kb_id: UUID,
    minerp_tenant_id: UUID,
) -> list[ShopFaqSuggestion]:
    result = await db.execute(
        select(ShopFaqSuggestion).where(
            ShopFaqSuggestion.knowledge_base_id == kb_id,
            ShopFaqSuggestion.minerp_tenant_id == minerp_tenant_id,
        )
    )
    return list(result.scalars().all())


async def list_for_kb(
    db: AsyncSession,
    *,
    kb_id: UUID,
    minerp_tenant_id: UUID,
    status: str = "pending",
) -> list[ShopFaqSuggestion]:
    result = await db.execute(
        select(ShopFaqSuggestion)
        .where(
            ShopFaqSuggestion.knowledge_base_id == kb_id,
            ShopFaqSuggestion.minerp_tenant_id == minerp_tenant_id,
            ShopFaqSuggestion.status == status,
        )
        .order_by(
            ShopFaqSuggestion.occurrence_count.desc(),
            ShopFaqSuggestion.last_seen_at.desc(),
        )
    )
    return list(result.scalars().all())


async def get_by_fingerprint(
    db: AsyncSession,
    *,
    minerp_tenant_id: UUID,
    kb_id: UUID,
    fingerprint: str,
) -> ShopFaqSuggestion | None:
    result = await db.execute(
        select(ShopFaqSuggestion).where(
            ShopFaqSuggestion.minerp_tenant_id == minerp_tenant_id,
            ShopFaqSuggestion.knowledge_base_id == kb_id,
            ShopFaqSuggestion.question_fingerprint == fingerprint,
        )
    )
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    *,
    minerp_tenant_id: UUID,
    organization_id: UUID,
    knowledge_base_id: UUID,
    question_fingerprint: str,
    question_text: str,
    source: str,
) -> ShopFaqSuggestion:
    now = datetime.now(UTC)
    row = ShopFaqSuggestion(
        minerp_tenant_id=minerp_tenant_id,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        question_fingerprint=question_fingerprint,
        question_text=question_text,
        source=source,
        status="pending",
        occurrence_count=1,
        last_seen_at=now,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_by_id(
    db: AsyncSession,
    *,
    suggestion_id: UUID,
    kb_id: UUID,
    minerp_tenant_id: UUID,
) -> ShopFaqSuggestion | None:
    result = await db.execute(
        select(ShopFaqSuggestion).where(
            ShopFaqSuggestion.id == suggestion_id,
            ShopFaqSuggestion.knowledge_base_id == kb_id,
            ShopFaqSuggestion.minerp_tenant_id == minerp_tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def update_status(
    db: AsyncSession,
    suggestion: ShopFaqSuggestion,
    *,
    status: str,
) -> ShopFaqSuggestion:
    suggestion.status = status
    suggestion.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(suggestion)
    return suggestion


async def set_suggested_answer(
    db: AsyncSession,
    suggestion: ShopFaqSuggestion,
    *,
    answer: str,
    auto: bool = False,
) -> ShopFaqSuggestion:
    suggestion.suggested_answer = answer
    suggestion.suggested_answer_auto = auto
    suggestion.suggested_answer_at = datetime.now(UTC)
    suggestion.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(suggestion)
    return suggestion


async def bump_occurrence(
    db: AsyncSession,
    suggestion: ShopFaqSuggestion,
    *,
    question_text: str,
) -> ShopFaqSuggestion:
    suggestion.occurrence_count += 1
    suggestion.question_text = question_text
    suggestion.last_seen_at = datetime.now(UTC)
    suggestion.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(suggestion)
    return suggestion

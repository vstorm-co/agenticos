"""Shop AI tenant settings repository (D3 B58)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.shop_ai_settings import ShopAiSettings


async def get(db: AsyncSession, minerp_tenant_id: UUID) -> ShopAiSettings | None:
    return await db.get(ShopAiSettings, minerp_tenant_id)


async def get_or_create(
    db: AsyncSession,
    *,
    minerp_tenant_id: UUID,
    organization_id: UUID,
) -> ShopAiSettings:
    row = await get(db, minerp_tenant_id)
    if row is not None:
        return row
    now = datetime.now(UTC)
    row = ShopAiSettings(
        minerp_tenant_id=minerp_tenant_id,
        organization_id=organization_id,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def set_default_faq_suggestion_kb_id(
    db: AsyncSession,
    minerp_tenant_id: UUID,
    *,
    organization_id: UUID,
    kb_id: UUID | None,
) -> ShopAiSettings:
    row = await get_or_create(
        db, minerp_tenant_id=minerp_tenant_id, organization_id=organization_id
    )
    row.default_faq_suggestion_kb_id = kb_id
    row.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(row)
    return row


async def set_auto_draft_faq_min_occurrences(
    db: AsyncSession,
    minerp_tenant_id: UUID,
    *,
    organization_id: UUID,
    min_occurrences: int,
) -> ShopAiSettings:
    row = await get_or_create(
        db, minerp_tenant_id=minerp_tenant_id, organization_id=organization_id
    )
    row.auto_draft_faq_min_occurrences = max(0, min_occurrences)
    row.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(row)
    return row

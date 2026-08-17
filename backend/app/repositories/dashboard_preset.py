"""Data access for a person's named dashboard presets (PostgreSQL async).

Every query is filtered on **both** `user_id` and `organization_id`, the same
tenant boundary as the active layout: a preset saved in one organization must
not list, apply or delete from another, even for the person who owns the row.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dashboard_preset import DashboardPreset


async def list_for_user(
    db: AsyncSession, *, user_id: UUID, organization_id: UUID
) -> list[DashboardPreset]:
    result = await db.execute(
        select(DashboardPreset)
        .where(
            DashboardPreset.user_id == user_id,
            DashboardPreset.organization_id == organization_id,
        )
        .order_by(DashboardPreset.name)
    )
    return list(result.scalars().all())


async def get(
    db: AsyncSession, *, preset_id: UUID, user_id: UUID, organization_id: UUID
) -> DashboardPreset | None:
    result = await db.execute(
        select(DashboardPreset).where(
            DashboardPreset.id == preset_id,
            DashboardPreset.user_id == user_id,
            DashboardPreset.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_name(
    db: AsyncSession, *, user_id: UUID, organization_id: UUID, name: str
) -> DashboardPreset | None:
    result = await db.execute(
        select(DashboardPreset).where(
            DashboardPreset.user_id == user_id,
            DashboardPreset.organization_id == organization_id,
            DashboardPreset.name == name,
        )
    )
    return result.scalar_one_or_none()


async def count_for_user(db: AsyncSession, *, user_id: UUID, organization_id: UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(DashboardPreset)
        .where(
            DashboardPreset.user_id == user_id,
            DashboardPreset.organization_id == organization_id,
        )
    )
    return int(result.scalar_one())


async def create(
    db: AsyncSession,
    *,
    user_id: UUID,
    organization_id: UUID,
    name: str,
    entries: list[dict[str, Any]],
) -> DashboardPreset:
    preset = DashboardPreset(
        user_id=user_id, organization_id=organization_id, name=name, entries=entries
    )
    db.add(preset)
    await db.flush()
    await db.refresh(preset)
    return preset


async def delete(db: AsyncSession, *, db_preset: DashboardPreset) -> None:
    await db.delete(db_preset)
    await db.flush()

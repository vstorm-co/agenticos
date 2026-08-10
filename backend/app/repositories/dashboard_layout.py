"""Data access for a person's saved dashboard arrangement (PostgreSQL async).

Every read is filtered on **both** `user_id` and `organization_id`. That
pair is the tenant boundary here: a layout saved for one organization must not
surface when the same person is looking at another, and dropping either half of
the predicate is a cross-tenant read that "the query ran" would never notice.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dashboard_layout import DashboardLayout


async def get(db: AsyncSession, *, user_id: UUID, organization_id: UUID) -> DashboardLayout | None:
    result = await db.execute(
        select(DashboardLayout).where(
            DashboardLayout.user_id == user_id,
            DashboardLayout.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert(
    db: AsyncSession,
    *,
    user_id: UUID,
    organization_id: UUID,
    entries: list[dict[str, Any]],
) -> DashboardLayout:
    """Store the arrangement, creating the row or replacing its entries.

    One row per `(user_id, organization_id)` — enforced by the unique
    constraint — so this reads the existing row and overwrites its entries
    rather than inserting a second.
    """
    existing = await get(db, user_id=user_id, organization_id=organization_id)
    if existing is not None:
        existing.entries = entries
        await db.flush()
        await db.refresh(existing)
        return existing
    layout = DashboardLayout(user_id=user_id, organization_id=organization_id, entries=entries)
    db.add(layout)
    await db.flush()
    await db.refresh(layout)
    return layout


async def delete(db: AsyncSession, *, db_layout: DashboardLayout) -> None:
    await db.delete(db_layout)
    await db.flush()

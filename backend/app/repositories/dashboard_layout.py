"""Data access for a person's saved dashboard arrangement (PostgreSQL async).

Every read is filtered on **both** `user_id` and `organization_id`. That
pair is the tenant boundary here: a layout saved for one organization must not
surface when the same person is looking at another, and dropping either half of
the predicate is a cross-tenant read that "the query ran" would never notice.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
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

    One row per `(user_id, organization_id)`, enforced by the unique constraint.
    A read-then-insert would race itself — the same person saving from two tabs
    both read no row, and the second insert hits `uq_dashboard_layout_user_org`
    as a 500 that no handler translates — so the write is a single atomic
    `INSERT ... ON CONFLICT DO UPDATE` on that constraint. `updated_at` is set
    explicitly because the model's `onupdate` fires only on an ORM flush, not on
    a Core upsert.
    """
    stmt = (
        insert(DashboardLayout)
        .values(user_id=user_id, organization_id=organization_id, entries=entries)
        .on_conflict_do_update(
            constraint="uq_dashboard_layout_user_org",
            set_={"entries": entries, "updated_at": func.now()},
        )
        .returning(DashboardLayout)
    )
    return (await db.execute(stmt)).scalar_one()


async def delete(db: AsyncSession, *, db_layout: DashboardLayout) -> None:
    await db.delete(db_layout)
    await db.flush()

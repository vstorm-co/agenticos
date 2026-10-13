"""Data access for a person's saved browser sign-ins (#2129)."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.browser_sign_in import BrowserSignIn


async def list_for(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> Sequence[BrowserSignIn]:
    """One person's sign-ins in one organization, by site."""
    result = await db.execute(
        select(BrowserSignIn)
        .where(
            BrowserSignIn.organization_id == organization_id,
            BrowserSignIn.user_id == user_id,
        )
        .order_by(BrowserSignIn.site)
    )
    return result.scalars().all()


async def get(
    db: AsyncSession, sign_in_id: UUID, *, organization_id: UUID, user_id: UUID
) -> BrowserSignIn | None:
    """One sign-in, only if it is this person's in this organization."""
    result = await db.execute(
        select(BrowserSignIn).where(
            BrowserSignIn.id == sign_in_id,
            BrowserSignIn.organization_id == organization_id,
            BrowserSignIn.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def save(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    site: str,
    sealed_state: str,
    key_version: int,
) -> BrowserSignIn:
    """Keep a sign-in, replacing the person's earlier one to the same site."""
    result = await db.execute(
        select(BrowserSignIn).where(
            BrowserSignIn.organization_id == organization_id,
            BrowserSignIn.user_id == user_id,
            BrowserSignIn.site == site,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = BrowserSignIn(organization_id=organization_id, user_id=user_id, site=site)
        db.add(row)
    row.sealed_state = sealed_state
    row.secret_key_version = key_version
    await db.flush()
    await db.refresh(row)
    return row


async def mark_used(db: AsyncSession, sign_in_ids: Sequence[UUID]) -> None:
    """Record that these sign-ins were handed to a browse just now."""
    await db.execute(
        update(BrowserSignIn)
        .where(BrowserSignIn.id.in_(sign_in_ids))
        .values(last_used_at=datetime.now(UTC))
    )
    await db.flush()


async def delete(db: AsyncSession, *, db_sign_in: BrowserSignIn) -> None:
    """Forget one sign-in."""
    await db.delete(db_sign_in)
    await db.flush()

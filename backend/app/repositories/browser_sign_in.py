"""Data access for a person's saved browser sign-ins (#2129)."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
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
    """Keep a sign-in, replacing the person's earlier one to the same site.

    One statement, so two hand-backs of the same site at once - two live browsers
    given back together - both land, the later replacing the earlier, where a
    read-then-insert let both see no row and the second fail on the unique key.
    `populate_existing`: a row this session already holds is refreshed from
    `RETURNING` rather than handed back with its old values.
    """
    statement = (
        insert(BrowserSignIn)
        .values(
            organization_id=organization_id,
            user_id=user_id,
            site=site,
            sealed_state=sealed_state,
            secret_key_version=key_version,
        )
        .on_conflict_do_update(
            index_elements=[
                BrowserSignIn.organization_id,
                BrowserSignIn.user_id,
                BrowserSignIn.site,
            ],
            set_={
                "sealed_state": sealed_state,
                "secret_key_version": key_version,
                "updated_at": func.now(),
            },
        )
        .returning(BrowserSignIn)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(statement)).scalar_one()


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

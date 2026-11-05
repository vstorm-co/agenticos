"""Owner-scoped coding accounts; no credential lookup without the owner and tenant."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.coding_account import CodingAccount


async def list_for(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> Sequence[CodingAccount]:
    result = await db.execute(
        select(CodingAccount)
        .where(CodingAccount.organization_id == organization_id, CodingAccount.user_id == user_id)
        .order_by(CodingAccount.harness)
    )
    return result.scalars().all()


async def get(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    account_id: UUID | None = None,
    harness: str | None = None,
    locked: bool = False,
) -> CodingAccount | None:
    query = select(CodingAccount).where(
        CodingAccount.organization_id == organization_id, CodingAccount.user_id == user_id
    )
    if account_id is not None:
        query = query.where(CodingAccount.id == account_id)
    if harness is not None:
        query = query.where(CodingAccount.harness == harness)
    if locked:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create(db: AsyncSession, row: CodingAccount) -> CodingAccount:
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def delete(db: AsyncSession, row: CodingAccount) -> None:
    await db.delete(row)
    await db.flush()


async def delete_for_member(db: AsyncSession, *, organization_id: UUID, user_id: UUID) -> None:
    """Remove consent and credentials together; an old task generation cannot be revived."""
    await db.execute(
        sa_delete(CodingAccount).where(
            CodingAccount.organization_id == organization_id,
            CodingAccount.user_id == user_id,
        )
    )
    await db.flush()

"""Data access for a person's pinned sidebar items (PostgreSQL async).

Every statement filters on **both** `user_id` and `organization_id`: that pair
is the tenant boundary, and a pin list saved in one organization must not
surface in another.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.nav_pins import NavPins


async def get(db: AsyncSession, *, user_id: UUID, organization_id: UUID) -> NavPins | None:
    result = await db.execute(
        select(NavPins).where(
            NavPins.user_id == user_id, NavPins.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def upsert(
    db: AsyncSession, *, user_id: UUID, organization_id: UUID, item_ids: list[str]
) -> NavPins:
    """Replace the pin list in one atomic `INSERT ... ON CONFLICT DO UPDATE`.

    Two tabs saving at once must not race a read-then-insert into the unique
    constraint. `updated_at` is set explicitly because `onupdate` fires only on
    an ORM flush, not on a Core upsert.
    """
    stmt = (
        insert(NavPins)
        .values(user_id=user_id, organization_id=organization_id, item_ids=item_ids)
        .on_conflict_do_update(
            constraint="uq_nav_pins_user_org",
            set_={"item_ids": item_ids, "updated_at": func.now()},
        )
        .returning(NavPins)
    )
    return (await db.execute(stmt)).scalar_one()

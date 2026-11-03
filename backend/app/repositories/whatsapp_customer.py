"""WhatsApp customer and held-run repositories - the 24-hour window's record (#2076).

`lock` takes the customer's row `FOR UPDATE`; the route's upsert (`record_inbound`)
is a write to the same row, so a hold or a claim and a new message serialize on it.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.whatsapp_customer import WhatsAppCustomer, WhatsAppHeldRun

_CUSTOMER_KEY = "uq_whatsapp_customer_bot_bsuid"


async def record_inbound(
    db: AsyncSession, *, organization_id: UUID, bot_id: UUID, bsuid: str, sent_at: datetime
) -> None:
    """Keep the latest Meta message timestamp for a customer, creating the record on first sight.

    `GREATEST` in SQL keeps it monotonic: an older message delivered late, or two
    batches racing, can never move it back. A new message does not clear
    `window_closed_at`; the window rule compares the two.
    """
    statement = pg_insert(WhatsAppCustomer).values(
        organization_id=organization_id, bot_id=bot_id, bsuid=bsuid, last_inbound_at=sent_at
    )
    await db.execute(
        statement.on_conflict_do_update(
            constraint=_CUSTOMER_KEY,
            set_={
                "last_inbound_at": func.greatest(
                    WhatsAppCustomer.last_inbound_at, statement.excluded.last_inbound_at
                )
            },
        )
    )


async def get(db: AsyncSession, *, bot_id: UUID, bsuid: str) -> WhatsAppCustomer | None:
    result = await db.execute(
        select(WhatsAppCustomer).where(
            WhatsAppCustomer.bot_id == bot_id, WhatsAppCustomer.bsuid == bsuid
        )
    )
    return result.scalar_one_or_none()


async def lock(
    db: AsyncSession, *, organization_id: UUID, bot_id: UUID, bsuid: str
) -> WhatsAppCustomer:
    """The customer's row, locked until the transaction ends; created bare when there is none.

    An `INSERT ... ON CONFLICT DO NOTHING` first, so a customer who never wrote
    still has a row to lock, then `SELECT ... FOR UPDATE`. Anything that reads the
    window to decide must do it after this, in the same transaction.
    """
    await db.execute(
        pg_insert(WhatsAppCustomer)
        .values(organization_id=organization_id, bot_id=bot_id, bsuid=bsuid)
        .on_conflict_do_nothing(constraint=_CUSTOMER_KEY)
    )
    result = await db.execute(
        select(WhatsAppCustomer)
        .where(WhatsAppCustomer.bot_id == bot_id, WhatsAppCustomer.bsuid == bsuid)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def update(
    db: AsyncSession, *, customer: WhatsAppCustomer, update_data: dict[str, Any]
) -> WhatsAppCustomer:
    for field, value in update_data.items():
        setattr(customer, field, value)
    db.add(customer)
    await db.flush()
    await db.refresh(customer)
    return customer


async def hold_run(
    db: AsyncSession, *, customer: WhatsAppCustomer, run_id: UUID, answer: bool, files: bool
) -> bool:
    """Hold a run for this customer; holding it again ORs what it owes. True when the row is new."""
    statement = pg_insert(WhatsAppHeldRun).values(
        organization_id=customer.organization_id,
        customer_id=customer.id,
        run_id=run_id,
        held_answer=answer,
        held_files=files,
    )
    result = await db.execute(
        statement.on_conflict_do_update(
            constraint="uq_whatsapp_held_run_customer_run",
            set_={
                "held_answer": WhatsAppHeldRun.held_answer | statement.excluded.held_answer,
                "held_files": WhatsAppHeldRun.held_files | statement.excluded.held_files,
            },
        ).returning(text("(xmax = 0)"))
    )
    return bool(result.scalar_one())


async def held_runs(
    db: AsyncSession, *, customer: WhatsAppCustomer, claimable_before: datetime
) -> list[WhatsAppHeldRun]:
    """The customer's held runs that are unclaimed or whose claim is older than `claimable_before`, oldest first."""
    result = await db.execute(
        select(WhatsAppHeldRun)
        .where(
            WhatsAppHeldRun.customer_id == customer.id,
            or_(
                WhatsAppHeldRun.claimed_at.is_(None),
                WhatsAppHeldRun.claimed_at < claimable_before,
            ),
        )
        .order_by(WhatsAppHeldRun.created_at, WhatsAppHeldRun.id)
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


async def update_held(
    db: AsyncSession, *, held: WhatsAppHeldRun, update_data: dict[str, Any]
) -> WhatsAppHeldRun:
    for field, value in update_data.items():
        setattr(held, field, value)
    db.add(held)
    await db.flush()
    await db.refresh(held)
    return held


async def delete_held(db: AsyncSession, *, held_id: UUID) -> None:
    await db.execute(sql_delete(WhatsAppHeldRun).where(WhatsAppHeldRun.id == held_id))


async def has_held(db: AsyncSession, *, bot_id: UUID, bsuid: str) -> bool:
    result = await db.execute(
        select(WhatsAppHeldRun.id)
        .join(WhatsAppCustomer, WhatsAppCustomer.id == WhatsAppHeldRun.customer_id)
        .where(WhatsAppCustomer.bot_id == bot_id, WhatsAppCustomer.bsuid == bsuid)
        .limit(1)
    )
    return result.first() is not None

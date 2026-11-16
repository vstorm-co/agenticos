"""WhatsApp customer and held-run repositories - the 24-hour window's record (#2076).

`lock` takes the customer's row `FOR UPDATE`; the route's upsert (`record_inbound`)
is a write to the same row, so a hold or a claim and a new message serialize on it.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, String, cast, exists, func, or_, select, text
from sqlalchemy import delete as sql_delete
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.channel_session import ChannelSession
from app.db.models.organization import OrganizationMember
from app.db.models.user import User
from app.db.models.whatsapp_customer import WhatsAppCustomer, WhatsAppHeldRun
from app.services.channels.whatsapp_window import NUDGE_AFTER, WINDOW, WINDOW_MARGIN, nudge_due

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


@dataclass(frozen=True)
class CustomerRow:
    """A customer of a bot, with the chat account row for their BSUID when there is one."""

    customer: WhatsAppCustomer
    identity: ChannelIdentity | None


def _active_members(organization_id: UUID) -> Select[UUID]:
    """The accounts with an active membership here: what `member_repo.get_active` accepts."""
    return (
        select(OrganizationMember.user_id)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == organization_id, User.is_active.is_(True))
    )


async def set_phone(
    db: AsyncSession, *, organization_id: UUID, bot_id: UUID, bsuid: str, phone: str
) -> None:
    """Keep a stranger's number on their record; the row is not created here."""
    await db.execute(
        sql_update(WhatsAppCustomer)
        .where(
            WhatsAppCustomer.organization_id == organization_id,
            WhatsAppCustomer.bot_id == bot_id,
            WhatsAppCustomer.bsuid == bsuid,
            # A number is kept only for people with no account: never once it is linked
            # to an active member. A departed member is a stranger again.
            ~exists().where(
                ChannelIdentity.platform == "whatsapp",
                ChannelIdentity.platform_user_id == f"{organization_id}:{bsuid}",
                ChannelIdentity.user_id.in_(_active_members(organization_id)),
            ),
        )
        .values(phone=phone)
    )


async def clear_phone(db: AsyncSession, *, organization_id: UUID, bsuid: str) -> None:
    """Drop the number from this customer's record on every bot of the organization."""
    await db.execute(
        sql_update(WhatsAppCustomer)
        .where(
            WhatsAppCustomer.organization_id == organization_id,
            WhatsAppCustomer.bsuid == bsuid,
            WhatsAppCustomer.phone.is_not(None),
        )
        .values(phone=None)
    )


def _with_identity() -> Select[WhatsAppCustomer, ChannelIdentity]:
    namespaced = cast(WhatsAppCustomer.organization_id, String) + ":" + WhatsAppCustomer.bsuid
    return select(WhatsAppCustomer, ChannelIdentity).outerjoin(
        ChannelIdentity,
        (ChannelIdentity.platform == "whatsapp") & (ChannelIdentity.platform_user_id == namespaced),
    )


async def list_for_bot(
    db: AsyncSession, *, organization_id: UUID, bot_id: UUID, skip: int, limit: int
) -> tuple[list[CustomerRow], int]:
    """A bot's customers, newest message first, and how many there are."""
    where = (WhatsAppCustomer.organization_id == organization_id, WhatsAppCustomer.bot_id == bot_id)
    total = await db.scalar(select(func.count()).select_from(WhatsAppCustomer).where(*where))
    result = await db.execute(
        _with_identity()
        .where(*where)
        .order_by(WhatsAppCustomer.last_inbound_at.desc().nulls_last(), WhatsAppCustomer.id)
        .offset(skip)
        .limit(limit)
    )
    return [CustomerRow(c, i) for c, i in result.all()], total or 0


async def find_by_phone(
    db: AsyncSession, *, organization_id: UUID, bot_id: UUID, phone: str
) -> list[CustomerRow]:
    """The customers of this bot with this number (digits only)."""
    result = await db.execute(
        _with_identity().where(
            WhatsAppCustomer.organization_id == organization_id,
            WhatsAppCustomer.bot_id == bot_id,
            WhatsAppCustomer.phone == phone,
            # Never confirms whose number a linked member's is.
            or_(
                ChannelIdentity.user_id.is_(None),
                ChannelIdentity.user_id.not_in(_active_members(organization_id)),
            ),
        )
    )
    return [CustomerRow(c, i) for c, i in result.all()]


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


async def get_in_bot(
    db: AsyncSession, *, organization_id: UUID, bot_id: UUID, customer_id: UUID
) -> WhatsAppCustomer | None:
    """One customer by id, only when they belong to this bot of this organization."""
    result = await db.execute(
        select(WhatsAppCustomer).where(
            WhatsAppCustomer.id == customer_id,
            WhatsAppCustomer.bot_id == bot_id,
            WhatsAppCustomer.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def lock_existing(
    db: AsyncSession, *, organization_id: UUID, bsuid: str
) -> list[WhatsAppCustomer]:
    """The customer's rows on every bot of the organization, locked, in bot order.

    No row is created: `lock` makes one for a customer who never wrote, and erasing
    somebody must not leave a row behind to lock.
    """
    result = await db.execute(
        select(WhatsAppCustomer)
        .where(WhatsAppCustomer.organization_id == organization_id, WhatsAppCustomer.bsuid == bsuid)
        .order_by(WhatsAppCustomer.bot_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


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
    db: AsyncSession,
    *,
    customer: WhatsAppCustomer,
    run_id: UUID,
    answer: bool,
    files: bool,
    message_id: UUID | None = None,
    notice: str | None = None,
) -> bool:
    """Hold a run for this customer; True when the row is new.

    One row per (customer, run, saved answer): holding the same answer again ORs what
    it owes, and another answer of the run is a row of its own. `message_id` is `None`
    for the run's prompts, and a `notice` (the key of a fixed sentence) rides on that
    row: a newer notice replaces the one held, and a hold with none keeps it.
    """
    statement = pg_insert(WhatsAppHeldRun).values(
        organization_id=customer.organization_id,
        customer_id=customer.id,
        run_id=run_id,
        message_id=message_id,
        held_answer=answer,
        held_files=files,
        held_notice=notice,
    )
    result = await db.execute(
        statement.on_conflict_do_update(
            constraint="uq_whatsapp_held_run_customer_run_message",
            set_={
                "held_answer": WhatsAppHeldRun.held_answer | statement.excluded.held_answer,
                "held_files": WhatsAppHeldRun.held_files | statement.excluded.held_files,
                "held_notice": func.coalesce(
                    statement.excluded.held_notice, WhatsAppHeldRun.held_notice
                ),
                "hold_version": WhatsAppHeldRun.hold_version + 1,
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


async def lock_held(db: AsyncSession, *, held_id: UUID) -> WhatsAppHeldRun | None:
    """The held row, locked until the transaction ends, or `None` when it is gone."""
    result = await db.execute(
        select(WhatsAppHeldRun)
        .where(WhatsAppHeldRun.id == held_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def holds_claim(db: AsyncSession, *, held_id: UUID, claimed_at: datetime | None) -> bool:
    """Whether the held row exists and carries this claim, without locking it."""
    result = await db.execute(
        select(WhatsAppHeldRun.id).where(
            WhatsAppHeldRun.id == held_id, WhatsAppHeldRun.claimed_at == claimed_at
        )
    )
    return result.first() is not None


async def delete_held(db: AsyncSession, *, held_id: UUID) -> None:
    await db.execute(sql_delete(WhatsAppHeldRun).where(WhatsAppHeldRun.id == held_id))


async def run_owes_answer(db: AsyncSession, *, run_id: UUID) -> bool:
    """Whether any held row of the run still owes an answer or files."""
    result = await db.execute(
        select(WhatsAppHeldRun.id)
        .where(
            WhatsAppHeldRun.run_id == run_id,
            or_(WhatsAppHeldRun.held_answer, WhatsAppHeldRun.held_files),
        )
        .limit(1)
    )
    return result.first() is not None


async def has_held(
    db: AsyncSession, *, bot_id: UUID, bsuid: str, claimable_before: datetime
) -> bool:
    """Whether a message should wait for a delivery: a run it could claim, or a claim still owing an answer or a notice.

    A claim that owes only prompts spans the routed turn, so it is not counted: a message
    arriving during that turn must reach the router and steer it.
    """
    result = await db.execute(
        select(WhatsAppHeldRun.id)
        .join(WhatsAppCustomer, WhatsAppCustomer.id == WhatsAppHeldRun.customer_id)
        .where(
            WhatsAppCustomer.bot_id == bot_id,
            WhatsAppCustomer.bsuid == bsuid,
            or_(
                WhatsAppHeldRun.claimed_at.is_(None),
                WhatsAppHeldRun.claimed_at < claimable_before,
                WhatsAppHeldRun.held_answer,
                WhatsAppHeldRun.held_files,
                WhatsAppHeldRun.held_notice.is_not(None),
            ),
        )
        .limit(1)
    )
    return result.first() is not None


async def nudge_candidates(
    db: AsyncSession, *, now: datetime, limit: int = 100
) -> list[WhatsAppCustomer]:
    """Customers of an active WhatsApp bot to nudge now, oldest message first.

    A customer whose run waits on an approval and continues in their chat, whose
    window is open and past `NUDGE_AFTER`, and who has not been nudged in it. The
    window rule is `whatsapp_window.nudge_due` written in SQL; `mark_nudged` checks it
    again under the row lock.
    """
    waiting = (
        select(AgentRun.id)
        .join(ChannelSession, ChannelSession.conversation_id == AgentRun.conversation_id)
        .where(
            AgentRun.surface == "whatsapp",
            AgentRun.status == RunStatus.AWAITING_APPROVAL.value,
            AgentRun.paused_state["channel_destination"].astext.is_not(None),
            AgentRun.organization_id == WhatsAppCustomer.organization_id,
            ChannelSession.bot_id == WhatsAppCustomer.bot_id,
            ChannelSession.platform_chat_id == WhatsAppCustomer.bsuid,
        )
    )
    result = await db.execute(
        select(WhatsAppCustomer)
        .join(ChannelBot, ChannelBot.id == WhatsAppCustomer.bot_id)
        .where(
            ChannelBot.platform == "whatsapp",
            ChannelBot.is_active,
            WhatsAppCustomer.last_inbound_at <= now - NUDGE_AFTER,
            WhatsAppCustomer.last_inbound_at > now - WINDOW + WINDOW_MARGIN,
            or_(
                WhatsAppCustomer.window_closed_at.is_(None),
                WhatsAppCustomer.window_closed_at <= WhatsAppCustomer.last_inbound_at,
            ),
            or_(
                WhatsAppCustomer.nudged_at.is_(None),
                WhatsAppCustomer.nudged_at < WhatsAppCustomer.last_inbound_at,
            ),
            exists(waiting),
        )
        .order_by(WhatsAppCustomer.last_inbound_at, WhatsAppCustomer.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def mark_nudged(db: AsyncSession, *, customer_id: UUID, now: datetime) -> bool:
    """Record a nudge sent at `now`; False when another sweep got there or the window moved.

    The row is locked and the rule is read again from it, so two sweeps (or a sweep
    and a customer's new message) cannot both win the same window.
    """
    result = await db.execute(
        select(WhatsAppCustomer)
        .where(WhatsAppCustomer.id == customer_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    customer = result.scalar_one_or_none()
    if customer is None or not nudge_due(
        last_inbound_at=customer.last_inbound_at,
        window_closed_at=customer.window_closed_at,
        nudged_at=customer.nudged_at,
        now=now,
    ):
        return False
    customer.nudged_at = now
    await db.flush()
    return True

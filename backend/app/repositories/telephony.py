"""Tenant-scoped phone state; provider effects never run inside the repository."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, exists, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_embed import AgentEmbed
from app.db.models.outcome import Outcome
from app.db.models.telephony import PhoneCall, PhoneContact, PhoneEndpoint

TERMINAL = frozenset({"completed", "failed", "cancelled"})


async def endpoint(
    db: AsyncSession, identifier: UUID, *, organization_id: UUID | None = None, lock: bool = False
) -> PhoneEndpoint | None:
    query = select(PhoneEndpoint).where(PhoneEndpoint.id == identifier)
    if organization_id is not None:
        query = query.where(PhoneEndpoint.organization_id == organization_id)
    if lock:
        query = query.with_for_update()
    return await db.scalar(query.execution_options(populate_existing=True))


async def endpoint_for_bot(
    db: AsyncSession, bot_id: UUID, *, organization_id: UUID
) -> PhoneEndpoint | None:
    return await db.scalar(
        select(PhoneEndpoint)
        .where(PhoneEndpoint.bot_id == bot_id, PhoneEndpoint.organization_id == organization_id)
        .execution_options(populate_existing=True)
    )


async def endpoints(db: AsyncSession, organization_id: UUID) -> list[PhoneEndpoint]:
    return list(
        await db.scalars(
            select(PhoneEndpoint)
            .where(PhoneEndpoint.organization_id == organization_id)
            .order_by(PhoneEndpoint.created_at)
            .limit(100)
        )
    )


async def contact(db: AsyncSession, *, organization_id: UUID, user_id: UUID) -> PhoneContact | None:
    return await db.scalar(
        select(PhoneContact)
        .where(PhoneContact.organization_id == organization_id, PhoneContact.user_id == user_id)
        .execution_options(populate_existing=True)
    )


async def contact_by_id(
    db: AsyncSession, identifier: UUID, *, organization_id: UUID
) -> PhoneContact | None:
    return await db.scalar(
        select(PhoneContact)
        .where(PhoneContact.id == identifier, PhoneContact.organization_id == organization_id)
        .execution_options(populate_existing=True)
    )


async def transfer_contacts(db: AsyncSession, organization_id: UUID) -> list[PhoneContact]:
    return list(
        await db.scalars(
            select(PhoneContact)
            .where(
                PhoneContact.organization_id == organization_id,
                PhoneContact.allow_transfers.is_(True),
            )
            .limit(100)
        )
    )


async def call(
    db: AsyncSession, identifier: UUID, *, organization_id: UUID | None = None, lock: bool = False
) -> PhoneCall | None:
    query = select(PhoneCall).where(PhoneCall.id == identifier)
    if organization_id is not None:
        query = query.where(PhoneCall.organization_id == organization_id)
    if lock:
        query = query.with_for_update()
    return await db.scalar(query.execution_options(populate_existing=True))


async def request(db: AsyncSession, organization_id: UUID, request_key: UUID) -> PhoneCall | None:
    return await db.scalar(
        select(PhoneCall).where(
            PhoneCall.organization_id == organization_id, PhoneCall.request_key == request_key
        )
    )


async def recent_calls(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID | None
) -> list[PhoneCall]:
    query = select(PhoneCall).where(PhoneCall.organization_id == organization_id)
    if user_id is not None:
        query = query.where(PhoneCall.user_id == user_id)
    return list(await db.scalars(query.order_by(PhoneCall.created_at.desc()).limit(50)))


async def allowance(db: AsyncSession, endpoint_id: UUID) -> tuple[int, int, int, Decimal]:
    now = datetime.now(UTC)
    hour = now - timedelta(hours=1)
    day = now - timedelta(days=1)
    row = (
        await db.execute(
            select(
                func.count().filter(PhoneCall.created_at >= hour),
                func.count().filter(PhoneCall.created_at >= day),
                func.count().filter(PhoneCall.status.not_in(TERMINAL), PhoneCall.expires_at > now),
                func.coalesce(
                    func.sum(PhoneCall.estimated_cost_usd).filter(PhoneCall.created_at >= day), 0
                ),
            ).where(PhoneCall.endpoint_id == endpoint_id)
        )
    ).one()
    return int(row[0]), int(row[1]), int(row[2]), Decimal(row[3])


async def contact_calls_today(
    db: AsyncSession, contact_id: UUID, *, exclude: UUID | None = None
) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(PhoneCall)
            .where(
                (PhoneCall.contact_id == contact_id)
                | (PhoneCall.transferred_contact_id == contact_id),
                PhoneCall.created_at >= datetime.now(UTC) - timedelta(days=1),
                PhoneCall.id != exclude if exclude is not None else true(),
            )
        )
        or 0
    )


async def save[T: PhoneEndpoint | PhoneContact | PhoneCall](db: AsyncSession, row: T) -> T:
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def public_embeds(db: AsyncSession, organization_id: UUID) -> list[AgentEmbed]:
    return list(
        await db.scalars(
            select(AgentEmbed)
            .where(
                AgentEmbed.organization_id == organization_id,
                AgentEmbed.auth_mode == "public",
                AgentEmbed.is_active.is_(True),
                AgentEmbed.kind.in_(["widget", "page"]),
            )
            .limit(100)
        )
    )


async def call_by_sid(db: AsyncSession, endpoint_id: UUID, sid: str) -> PhoneCall | None:
    return await db.scalar(
        select(PhoneCall).where(PhoneCall.endpoint_id == endpoint_id, PhoneCall.provider_sid == sid)
    )


async def live_page(db: AsyncSession, *, after: UUID | None = None) -> list[UUID]:
    query = (
        select(PhoneCall.id)
        .where(PhoneCall.status.not_in(TERMINAL))
        .order_by(PhoneCall.id)
        .limit(100)
    )
    if after is not None:
        query = query.where(PhoneCall.id > after)
    return list(await db.scalars(query))


async def purge_receipts(db: AsyncSession) -> None:
    await db.execute(
        delete(PhoneCall).where(PhoneCall.finished_at < datetime.now(UTC) - timedelta(days=30))
    )


async def own_case(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, outcome_id: UUID
) -> Outcome | None:
    from app.db.models.outcome import Outcome

    return await db.scalar(
        select(Outcome)
        .where(
            Outcome.id == outcome_id,
            Outcome.organization_id == organization_id,
            Outcome.user_id == user_id,
        )
        .execution_options(populate_existing=True)
    )


async def case_notification_time(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, outcome_id: UUID
) -> datetime | None:
    from app.db.models.notification import Notification

    return await db.scalar(
        select(func.min(Notification.created_at)).where(
            Notification.organization_id == organization_id,
            Notification.recipient_user_id == user_id,
            Notification.outcome_id == outcome_id,
            Notification.read_at.is_(None),
            Notification.dismissed_at.is_(None),
        )
    )


async def call_for_case(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, outcome_id: UUID
) -> PhoneCall | None:
    return await db.scalar(
        select(PhoneCall)
        .where(
            PhoneCall.organization_id == organization_id,
            PhoneCall.user_id == user_id,
            PhoneCall.outcome_id == outcome_id,
            PhoneCall.purpose == "important",
        )
        .limit(1)
    )


async def open_phone_cases(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    agent_id: UUID,
    conversation_id: UUID | None,
) -> list[Outcome]:
    from app.db.models.agent_run import AgentRun
    from app.db.models.outcome import Outcome

    return list(
        await db.scalars(
            select(Outcome)
            .join(AgentRun, AgentRun.id == Outcome.source_run_id)
            .where(
                Outcome.organization_id == organization_id,
                Outcome.user_id == user_id,
                Outcome.status == "open",
                Outcome.source_conversation_id == conversation_id,
                AgentRun.organization_id == organization_id,
                AgentRun.agent_id == agent_id,
                AgentRun.user_id == user_id,
            )
            .order_by(Outcome.created_at.desc())
            .limit(20)
        )
    )


async def lock_case_admission(db: AsyncSession, row: PhoneCall) -> None:
    """Use settlement's case → notification → receipt lock order before dialing."""
    from app.db.models.notification import Notification
    from app.db.models.outcome import Outcome

    await db.execute(
        select(Outcome.id)
        .where(Outcome.id == row.outcome_id, Outcome.organization_id == row.organization_id)
        .with_for_update()
    )
    await db.execute(
        select(Notification.id)
        .where(
            Notification.outcome_id == row.outcome_id,
            Notification.organization_id == row.organization_id,
            Notification.recipient_user_id == row.user_id,
        )
        .order_by(Notification.id)
        .with_for_update()
    )


async def cancel_case_calls(
    db: AsyncSession, outcome_id: UUID, *, at: datetime
) -> list[tuple[UUID, UUID]]:
    from sqlalchemy import update

    await db.execute(
        update(PhoneCall)
        .where(PhoneCall.outcome_id == outcome_id, PhoneCall.status == "queued")
        .values(status="cancelled", finished_at=at, estimated_cost_usd=Decimal(0))
    )
    result = await db.execute(
        update(PhoneCall)
        .where(PhoneCall.outcome_id == outcome_id, PhoneCall.status.not_in((*TERMINAL, "queued")))
        .values(status="ending")
        .returning(PhoneCall.id, PhoneCall.organization_id)
    )
    return [(identifier, organization_id) for identifier, organization_id in result.all()]


async def mark_case_phone_attempt(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, outcome_id: UUID, at: datetime
) -> bool:
    from sqlalchemy import update

    changed = await db.scalar(
        update(Outcome)
        .where(
            Outcome.id == outcome_id,
            Outcome.organization_id == organization_id,
            Outcome.user_id == user_id,
            Outcome.status == "open",
            Outcome.phone_attempted_at.is_(None),
        )
        .values(phone_attempted_at=at)
        .returning(Outcome.id)
    )
    return changed is not None


async def call_for_source(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    source_run_id: UUID,
    endpoint_id: UUID,
) -> PhoneCall | None:
    return await db.scalar(
        select(PhoneCall)
        .where(
            PhoneCall.organization_id == organization_id,
            PhoneCall.user_id == user_id,
            PhoneCall.source_run_id == source_run_id,
            PhoneCall.endpoint_id == endpoint_id,
            PhoneCall.purpose != "important",
        )
        .limit(1)
    )


async def bot_has_unfinished_calls(
    db: AsyncSession, *, organization_id: UUID, bot_id: UUID
) -> bool:
    """A live receipt must retain its endpoint and cleanup credentials until termination."""
    return bool(
        await db.scalar(
            select(
                exists().where(
                    PhoneCall.endpoint_id == PhoneEndpoint.id,
                    PhoneEndpoint.bot_id == bot_id,
                    PhoneEndpoint.organization_id == organization_id,
                    PhoneCall.finished_at.is_(None),
                )
            )
        )
    )


async def user_has_unfinished_calls(db: AsyncSession, user_id: UUID) -> bool:
    """Whether account deletion would orphan a provider call still needing cleanup."""
    return bool(
        await db.scalar(
            select(exists().where(PhoneCall.user_id == user_id, PhoneCall.finished_at.is_(None)))
        )
    )


async def organization_has_unfinished_calls(db: AsyncSession, organization_id: UUID) -> bool:
    """Whether cascading an organization would discard live provider receipts."""
    return bool(
        await db.scalar(
            select(
                exists().where(
                    PhoneCall.organization_id == organization_id, PhoneCall.finished_at.is_(None)
                )
            )
        )
    )


async def delete_member_contact(db: AsyncSession, *, organization_id: UUID, user_id: UUID) -> None:
    """Remove organization-specific telephone opt-ins when membership ends."""
    await db.execute(
        delete(PhoneContact).where(
            PhoneContact.organization_id == organization_id, PhoneContact.user_id == user_id
        )
    )
    await db.flush()

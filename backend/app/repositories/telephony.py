"""Tenant-scoped phone state; provider effects never run inside the repository."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_embed import AgentEmbed
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

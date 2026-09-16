"""Notification repository (PostgreSQL async) (#1598)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.announcement import Announcement
from app.db.models.notification import Notification
from app.db.models.notification_delivery import DeliveryStatus, NotificationDelivery
from app.db.models.notification_preference import NotificationChannelPreference
from app.db.models.user import NotificationPreference, User


async def insert_notification_if_new(db: AsyncSession, notification: Notification) -> bool:
    """Insert `notification`, or do nothing if its dedup key already exists.

    `INSERT ... ON CONFLICT (recipient_user_id, event_type, occurrence_id) DO
    NOTHING` rather than a plain insert relying on the unique constraint to
    raise (Decision 2) - the duplicate case this is built for is expected to
    happen routinely (a retried budget check, a redelivered webhook), so it is
    an ordinary no-op here, not an exception a caller has to catch on every
    retry.
    """
    stmt = (
        pg_insert(Notification)
        .values(
            id=notification.id,
            organization_id=notification.organization_id,
            recipient_user_id=notification.recipient_user_id,
            event_type=notification.event_type,
            occurrence_id=notification.occurrence_id,
            summary=notification.summary,
            context_url=notification.context_url,
            render_context=notification.render_context,
            in_app_visible=notification.in_app_visible,
            announcement_id=notification.announcement_id,
        )
        .on_conflict_do_nothing(index_elements=["recipient_user_id", "event_type", "occurrence_id"])
        .returning(Notification.id)
    )
    result = await db.execute(stmt)
    return result.first() is not None


async def insert_delivery(
    db: AsyncSession, *, notification_id: uuid.UUID, channel: str
) -> NotificationDelivery:
    delivery = NotificationDelivery(
        id=uuid.uuid4(), notification_id=notification_id, channel=channel
    )
    db.add(delivery)
    await db.flush()
    return delivery


async def get_channel_preference(
    db: AsyncSession, *, user_id: uuid.UUID, event_type: str, channel: str
) -> bool | None:
    """The stored preference for one `(user, event_type, channel)`, or `None` if unset.

    `None` means "no row yet" - Decision 4's default-enabled is applied by the
    caller, not baked in here, so a caller that must tell "explicitly off" from
    "never asked" can.
    """
    return await db.scalar(
        select(NotificationChannelPreference.enabled).where(
            NotificationChannelPreference.user_id == user_id,
            NotificationChannelPreference.event_type == event_type,
            NotificationChannelPreference.channel == channel,
        )
    )


async def get_legacy_email_preference(
    db: AsyncSession, *, user_id: uuid.UUID, column: NotificationPreference
) -> bool | None:
    """One of the three legacy boolean columns on `User` - still authoritative
    for the email channel of the three agent-lifecycle events they cover
    (Decision 4). `None` only when the user row itself is gone."""
    return await db.scalar(select(getattr(User, column)).where(User.id == user_id))


async def list_inbox_page(
    db: AsyncSession,
    *,
    recipient_id: uuid.UUID,
    organization_id: uuid.UUID,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[Notification]:
    """A page of the inbox, newest first - `id` breaks a `created_at` tie one
    transaction writing several recipients' rows at once can produce."""
    conditions = [
        Notification.recipient_user_id == recipient_id,
        Notification.in_app_visible.is_(True),
        or_(
            Notification.organization_id == organization_id, Notification.organization_id.is_(None)
        ),
    ]
    if after is not None:
        after_created_at, after_id = after
        conditions.append(
            or_(
                Notification.created_at < after_created_at,
                and_(Notification.created_at == after_created_at, Notification.id < after_id),
            )
        )
    result = await db.execute(
        select(Notification)
        .where(*conditions)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_unread(
    db: AsyncSession, *, recipient_id: uuid.UUID, organization_id: uuid.UUID, cap: int
) -> list[Notification]:
    """Candidate unread rows, newest first, up to `cap`.

    The unread badge and mark-all-read both need the gate-aware predicate
    (Decision 7), which cannot be expressed as a plain `COUNT`/`UPDATE` - each
    candidate row is re-checked in the service layer. `cap` bounds that work
    for an account with an unbounded backlog.
    """
    result = await db.execute(
        select(Notification)
        .where(
            Notification.recipient_user_id == recipient_id,
            Notification.in_app_visible.is_(True),
            Notification.read_at.is_(None),
            or_(
                Notification.organization_id == organization_id,
                Notification.organization_id.is_(None),
            ),
        )
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(cap)
    )
    return list(result.scalars().all())


async def get_own(
    db: AsyncSession,
    *,
    notification_id: uuid.UUID,
    recipient_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> Notification | None:
    return await db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_user_id == recipient_id,
            Notification.in_app_visible.is_(True),
            or_(
                Notification.organization_id == organization_id,
                Notification.organization_id.is_(None),
            ),
        )
    )


async def mark_read(
    db: AsyncSession, notification: Notification, *, read_at: datetime
) -> Notification:
    notification.read_at = read_at
    await db.flush()
    await db.refresh(notification)
    return notification


async def mark_ids_read(db: AsyncSession, *, ids: list[uuid.UUID], read_at: datetime) -> int:
    if not ids:
        return 0
    result = await db.execute(
        update(Notification)
        .where(Notification.id.in_(ids), Notification.read_at.is_(None))
        .values(read_at=read_at)
    )
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


async def get_announcement(db: AsyncSession, announcement_id: uuid.UUID) -> Announcement | None:
    return await db.get(Announcement, announcement_id)


async def get_notification(db: AsyncSession, notification_id: uuid.UUID) -> Notification | None:
    """An unscoped lookup - the sweep operates with the platform's own trust,
    not a caller's, so it is not filtered to one recipient the way `get_own` is."""
    return await db.get(Notification, notification_id)


async def get_delivery(db: AsyncSession, delivery_id: uuid.UUID) -> NotificationDelivery | None:
    return await db.get(NotificationDelivery, delivery_id)


async def claim_pending_deliveries(
    db: AsyncSession, *, now: datetime, max_attempts: int, limit: int = 100
) -> list[NotificationDelivery]:
    """Deliveries due to send, locked so a second sweep tick takes none of them.

    `FOR UPDATE SKIP LOCKED` mirrors `agent_trigger_repo.claim_due` (Decision
    3): two concurrent sweeps take disjoint rows rather than both sending the
    same one. Select-and-lock only - the caller stamps `claimed_at`/
    `claimed_until` and increments `attempts` on the returned rows and flushes
    them under this same lock, the way `AgentTriggerService.claim_and_advance`
    does for a trigger.
    """
    result = await db.execute(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.status == DeliveryStatus.PENDING.value,
            NotificationDelivery.attempts < max_attempts,
            (NotificationDelivery.claimed_until.is_(None))
            | (NotificationDelivery.claimed_until <= now),
        )
        .order_by(NotificationDelivery.created_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def settle_delivery(
    db: AsyncSession,
    *,
    delivery_id: uuid.UUID,
    claimed_at: datetime,
    status: str,
    last_error: str | None = None,
) -> bool:
    """Write a claimed delivery's outcome - but only while still holding the claim.

    Conditioned on `claimed_at` matching the token this worker was issued
    (Decision 3): a worker whose lease lapsed and was reclaimed by a second
    sweep matches zero rows here and its late outcome is discarded, rather
    than overwriting the second worker's.
    """
    result = await db.execute(
        update(NotificationDelivery)
        .where(
            NotificationDelivery.id == delivery_id, NotificationDelivery.claimed_at == claimed_at
        )
        .values(status=status, last_error=last_error)
    )
    return bool(result.rowcount)  # ty: ignore[unresolved-attribute]


async def reap_exhausted_deliveries(
    db: AsyncSession, *, now: datetime, max_attempts: int
) -> list[uuid.UUID]:
    """Deliveries that exhausted their claims with no recorded outcome.

    A worker that dies on a row's *last* allowed claim leaves it `pending`,
    unclaimable (`attempts` already at the bound) and never reaching a
    terminal state - invisible to both the claim query and the
    failed-deliveries view. This settles it `failed` outright, no claim
    needed since the row is already unclaimable, modelled on
    `RunReaperService.reap_stale` (Decision 3).
    """
    result = await db.execute(
        update(NotificationDelivery)
        .where(
            NotificationDelivery.status == DeliveryStatus.PENDING.value,
            NotificationDelivery.attempts >= max_attempts,
            NotificationDelivery.claimed_until < now,
        )
        .values(
            status=DeliveryStatus.FAILED.value,
            last_error="exhausted without a recorded outcome",
        )
        .returning(NotificationDelivery.id)
    )
    return [row[0] for row in result.all()]


async def list_failed_deliveries(
    db: AsyncSession, *, skip: int, limit: int
) -> tuple[list[tuple[NotificationDelivery, Notification]], int]:
    """Terminally failed deliveries, deployment-wide, newest first.

    Joined to `notifications` for the event type and recipient the admin view
    shows - a `NotificationDelivery` row carries neither on its own. The total
    is `count(*) OVER()` on the same statement as the rows, not a second query
    - a window function is evaluated before `LIMIT`/`OFFSET`, so the total is
    the whole match from the same snapshot the page came from - *when* a row
    survives to carry it. `OFFSET` past the last match (`skip` beyond the
    total) discards every row the window function ran on along with it, so an
    empty page falls back to a plain `COUNT`: the one shape that still
    answers "how many" when the page itself has nothing to answer with.
    """
    result = await db.execute(
        select(NotificationDelivery, Notification, func.count().over().label("total"))
        .join(Notification, Notification.id == NotificationDelivery.notification_id)
        .where(NotificationDelivery.status == DeliveryStatus.FAILED.value)
        .order_by(NotificationDelivery.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = result.all()
    if rows:
        return [(row[0], row[1]) for row in rows], rows[0].total
    total = await db.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(NotificationDelivery.status == DeliveryStatus.FAILED.value)
    )
    return [], total or 0

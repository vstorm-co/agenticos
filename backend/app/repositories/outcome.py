"""The shared state of what needs a person's attention (PostgreSQL async)."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.notification import Notification
from app.db.models.notification_delivery import DeliveryStatus, NotificationDelivery
from app.db.models.outcome import Outcome
from app.db.models.suggestion import Suggestion

SETTLED_REASON = "outcome settled"


async def open_or_find(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    kind: str,
    dedupe_key: str,
    summary: str,
    context_url: str | None,
    source_run_id: UUID | None,
    source_conversation_id: UUID | None,
) -> Outcome:
    """The person's outcome for this cause - opened now, or the one that already exists.

    The unique key picks one winner when two producers reach the same cause together; the
    loser's insert does nothing and both read the winner's row.
    """
    await db.execute(
        pg_insert(Outcome)
        .values(
            organization_id=organization_id,
            user_id=user_id,
            kind=kind,
            dedupe_key=dedupe_key,
            summary=summary,
            context_url=context_url,
            status="open",
            source_run_id=source_run_id,
            source_conversation_id=source_conversation_id,
        )
        .on_conflict_do_nothing(constraint="uq_outcome_person_key")
    )
    outcome = await db.scalar(
        select(Outcome)
        .where(
            Outcome.organization_id == organization_id,
            Outcome.user_id == user_id,
            Outcome.dedupe_key == dedupe_key,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert outcome is not None
    return outcome


async def get_own_for_update(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, outcome_id: UUID
) -> Outcome | None:
    return await db.scalar(
        select(Outcome)
        .where(
            Outcome.id == outcome_id,
            Outcome.organization_id == organization_id,
            Outcome.user_id == user_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def list_for_user(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    statuses: Sequence[str],
    conversation_id: UUID | None,
    limit: int,
) -> list[Outcome]:
    """The person's outcomes in these states, newest first."""
    query = select(Outcome).where(
        Outcome.organization_id == organization_id,
        Outcome.user_id == user_id,
        Outcome.status.in_(list(statuses)),
    )
    if conversation_id is not None:
        query = query.where(Outcome.source_conversation_id == conversation_id)
    result = await db.execute(query.order_by(Outcome.created_at.desc(), Outcome.id).limit(limit))
    return list(result.scalars().all())


async def set_status(
    db: AsyncSession,
    outcome: Outcome,
    *,
    status: str,
    settled_at: datetime | None,
    via: str | None,
) -> Outcome:
    outcome.status = status
    outcome.settled_at = settled_at
    outcome.settled_via = via
    db.add(outcome)
    await db.flush()
    return outcome


async def is_settled(db: AsyncSession, *, outcome_id: UUID) -> bool:
    """Whether the outcome has been acknowledged or closed since a delivery was queued."""
    status = await db.scalar(select(Outcome.status).where(Outcome.id == outcome_id))
    return status is not None and status != "open"


async def open_for_run(db: AsyncSession, *, run_id: UUID, kind: str) -> list[Outcome]:
    """Outcomes of this kind still asking about this run."""
    result = await db.execute(
        select(Outcome)
        .where(
            Outcome.source_run_id == run_id,
            Outcome.kind == kind,
            Outcome.status.in_(["open", "acknowledged"]),
        )
        .order_by(Outcome.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().all())


async def link_notification(
    db: AsyncSession, *, notification_id: UUID, outcome_id: UUID, cleared_at: datetime | None
) -> None:
    """Tie a delivery to its outcome, already read and cleared when the cause is muted."""
    values: dict[str, object] = {"outcome_id": outcome_id}
    if cleared_at is not None:
        values.update(read_at=cleared_at, dismissed_at=cleared_at)
    await db.execute(
        update(Notification).where(Notification.id == notification_id).values(**values)
    )


async def settle_notifications(
    db: AsyncSession, *, outcome_id: UUID, at: datetime, dismiss: bool
) -> int:
    """Mark every delivery of the outcome read, and cleared too when it is closed."""
    values: dict[str, object] = {"read_at": func.coalesce(Notification.read_at, at)}
    if dismiss:
        values["dismissed_at"] = func.coalesce(Notification.dismissed_at, at)
    result = await db.execute(
        update(Notification).where(Notification.outcome_id == outcome_id).values(**values)
    )
    return int(result.rowcount)  # ty: ignore[unresolved-attribute]


async def skip_unsent_deliveries(
    db: AsyncSession, *, outcome_id: UUID, reason: str = SETTLED_REASON
) -> int:
    """Cancel external deliveries still waiting to go out for this outcome.

    A delivery a worker holds right now is left to it: it re-checks the outcome before
    sending, and one already sent cannot be recalled.
    """
    result = await db.execute(
        update(NotificationDelivery)
        .where(
            NotificationDelivery.status == DeliveryStatus.PENDING.value,
            or_(
                NotificationDelivery.claimed_until.is_(None),
                NotificationDelivery.claimed_until < func.now(),
                NotificationDelivery.retry_safe.is_(True),
            ),
            NotificationDelivery.notification_id.in_(
                select(Notification.id).where(Notification.outcome_id == outcome_id)
            ),
        )
        .values(status=DeliveryStatus.SKIPPED.value, retry_safe=False, last_error=reason)
    )
    return int(result.rowcount)  # ty: ignore[unresolved-attribute]


async def for_watch_findings(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, watch_id: UUID
) -> list[Outcome]:
    """Lock the person's cases before their watch and Inbox projections disappear."""
    result = await db.scalars(
        select(Outcome)
        .join(Suggestion, Suggestion.outcome_id == Outcome.id)
        .where(
            Outcome.organization_id == organization_id,
            Outcome.user_id == user_id,
            Suggestion.organization_id == organization_id,
            Suggestion.user_id == user_id,
            Suggestion.watch_id == watch_id,
        )
        .order_by(Outcome.id)
        .with_for_update(of=Outcome)
        .execution_options(populate_existing=True)
    )
    return list(result.all())


async def open_for_cause_prefix(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    prefix: str,
) -> list[Outcome]:
    """The person's still actionable cases for this platform-owned cause prefix."""
    result = await db.scalars(
        select(Outcome)
        .where(
            Outcome.organization_id == organization_id,
            Outcome.user_id == user_id,
            Outcome.dedupe_key.startswith(prefix, autoescape=True),
            Outcome.status.in_(["open", "acknowledged"]),
        )
        .order_by(Outcome.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(result.all())


async def for_cause(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    dedupe_key: str,
) -> Outcome | None:
    """Serialize a producer or recovery against the person's current case decision."""
    return await db.scalar(
        select(Outcome)
        .where(
            Outcome.organization_id == organization_id,
            Outcome.user_id == user_id,
            Outcome.dedupe_key == dedupe_key,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def observe_failure(
    db: AsyncSession,
    *,
    outcome: Outcome,
    at: datetime,
    run_id: UUID | None = None,
    summary: str,
) -> None:
    """The caller holds the case lock; retries cannot move its evidence backward."""
    if outcome.last_observed_at is None or at > outcome.last_observed_at:
        outcome.last_observed_at = at
        outcome.summary = summary
        outcome.source_run_id = run_id
        await db.flush()


async def observe_recovery(db: AsyncSession, *, outcome: Outcome, at: datetime) -> None:
    if outcome.last_recovered_at is None or at > outcome.last_recovered_at:
        outcome.last_recovered_at = at
        await db.flush()


async def refresh_context(
    db: AsyncSession,
    outcome: Outcome,
    *,
    summary: str,
    context_url: str | None,
    source_run_id: UUID | None,
    source_conversation_id: UUID | None,
) -> None:
    """A reopened case points to the incident that reopened it, not its old transcript."""
    outcome.summary = summary
    outcome.context_url = context_url
    outcome.source_run_id = source_run_id
    outcome.source_conversation_id = source_conversation_id
    await db.flush()

"""One outcome, settled once, wherever the person met it (#2575).

The Inbox row, the card in the chat, the push and the e-mail are deliveries of one
outcome. Settling it - acknowledge, resolve or mute - clears them all and cancels the
ones that have not gone out yet; deciding the approval it asked about resolves it without
the person touching the Inbox.

States only move forward: open → acknowledged → resolved or muted. A resolved or muted
outcome is final; the same cause arriving again opens a fresh one, except a muted cause,
which stays muted so it does not ask again.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.notification import Notification
from app.db.models.outcome import Outcome, OutcomeStatus
from app.repositories import outcome_repo
from app.schemas.outcome import OutcomeAction

_FINAL = (OutcomeStatus.RESOLVED.value, OutcomeStatus.MUTED.value)
_TARGET: dict[str, OutcomeStatus] = {
    "acknowledge": OutcomeStatus.ACKNOWLEDGED,
    "resolve": OutcomeStatus.RESOLVED,
    "mute": OutcomeStatus.MUTED,
}

OUTCOME_EVENTS = frozenset(
    {"approval_requested", "run_failed", "finding", "background_task_paused"}
)
"""The notification events that are somebody's to act on, rather than news."""


def cause_of(event_type: str, occurrence_id: str, render_context: dict[str, object] | None) -> str:
    """The key that makes two notifications one outcome.

    A producer that knows the cause is bigger than one occurrence - the same routine failing
    every night - names it in `render_context["cause"]`; otherwise the occurrence is the cause.
    """
    cause = (render_context or {}).get("cause")
    return f"{event_type}:{cause if isinstance(cause, str) and cause else occurrence_id}"[:300]


def _uuid_of(render_context: dict[str, object] | None, key: str) -> UUID | None:
    raw = (render_context or {}).get(key)
    try:
        return UUID(str(raw)) if raw else None
    except ValueError:
        return None


def _caller(ctx: AuthContext) -> UUID:
    """An outcome is addressed to a person; a key that is nobody has none."""
    if ctx.user_id is None:
        raise AuthorizationError(message="Outcomes require a signed-in caller")
    return ctx.user_id


class OutcomeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def attach(self, notification: Notification) -> Outcome | None:
        """Tie a freshly written notification to its outcome, opening one when it is the first.

        A muted cause is cleared at once so it does not ask again; a settled outcome that
        the cause brings back reopens.
        """
        if notification.event_type not in OUTCOME_EVENTS or notification.organization_id is None:
            return None
        context = notification.render_context
        outcome = await outcome_repo.open_or_find(
            self.db,
            organization_id=notification.organization_id,
            user_id=notification.recipient_user_id,
            kind=notification.event_type,
            dedupe_key=cause_of(notification.event_type, notification.occurrence_id, context),
            summary=notification.summary,
            context_url=notification.context_url,
            source_run_id=_uuid_of(context, "run_id"),
            source_conversation_id=_uuid_of(context, "conversation_id"),
        )
        if outcome.status in (OutcomeStatus.RESOLVED.value, OutcomeStatus.ACKNOWLEDGED.value):
            await outcome_repo.set_status(
                self.db, outcome, status=OutcomeStatus.OPEN.value, settled_at=None, via=None
            )
        # An UPDATE, not the ORM: the notification was inserted with `ON CONFLICT DO NOTHING`
        # and is not tracked by the session, so adding it would insert it a second time.
        muted = outcome.status == OutcomeStatus.MUTED.value
        cleared_at = datetime.now(UTC) if muted else None
        await outcome_repo.link_notification(
            self.db,
            notification_id=notification.id,
            outcome_id=outcome.id,
            cleared_at=cleared_at,
        )
        notification.outcome_id = outcome.id
        if cleared_at is not None:
            notification.read_at = notification.dismissed_at = cleared_at
        return outcome

    async def list_mine(
        self, ctx: AuthContext, *, open_only: bool, conversation_id: UUID | None, limit: int = 50
    ) -> list[Outcome]:
        statuses = (
            [OutcomeStatus.OPEN.value, OutcomeStatus.ACKNOWLEDGED.value]
            if open_only
            else [status.value for status in OutcomeStatus]
        )
        return await outcome_repo.list_for_user(
            self.db,
            organization_id=ctx.organization_id,
            user_id=_caller(ctx),
            statuses=statuses,
            conversation_id=conversation_id,
            limit=limit,
        )

    async def settle(
        self, ctx: AuthContext, outcome_id: UUID, action: OutcomeAction, *, via: str
    ) -> Outcome:
        """Acknowledge, resolve or mute the person's own outcome.

        Raises:
            NotFoundError: It is not theirs, or does not exist - the two look alike.
            ConflictError: It is already closed, and `action` would change how.
        """
        outcome = await outcome_repo.get_own(
            self.db,
            organization_id=ctx.organization_id,
            user_id=_caller(ctx),
            outcome_id=outcome_id,
        )
        if outcome is None:
            raise NotFoundError(message="Outcome not found")
        target = _TARGET[action]
        if outcome.status == target.value:
            return outcome
        if outcome.status in _FINAL:
            raise ConflictError(
                message=f"This is already {outcome.status}", details={"status": outcome.status}
            )
        return await self._move(outcome, target, via=via)

    async def resolve_run_approvals(self, run_id: UUID, *, via: str = "approval") -> int:
        """The run's approvals were decided: whoever was still being asked is not any more."""
        settled = 0
        for outcome in await outcome_repo.open_for_run(
            self.db, run_id=run_id, kind="approval_requested"
        ):
            await self._move(outcome, OutcomeStatus.RESOLVED, via=via)
            settled += 1
        return settled

    async def _move(self, outcome: Outcome, target: OutcomeStatus, *, via: str) -> Outcome:
        now = datetime.now(UTC)
        closing = target is not OutcomeStatus.ACKNOWLEDGED
        await outcome_repo.set_status(
            self.db, outcome, status=target.value, settled_at=now, via=via
        )
        await outcome_repo.settle_notifications(
            self.db, outcome_id=outcome.id, at=now, dismiss=closing
        )
        await outcome_repo.skip_unsent_deliveries(self.db, outcome_id=outcome.id)
        return outcome

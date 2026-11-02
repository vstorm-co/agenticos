"""One outcome, settled once, wherever the person met it (#2575).

The Inbox row, the card in the chat, the push and the e-mail are deliveries of one
outcome. Settling it - acknowledge, resolve or mute - clears them all and cancels the
ones that have not gone out yet; deciding the approval it asked about resolves it without
the person touching the Inbox.

Decisions move open → acknowledged → resolved or muted. Other causes may reopen
when reported again; repeated findings retain their decision. Only an explicit
restore of a dismissed finding reopens its case without replaying old deliveries.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.notification import Notification
from app.db.models.outcome import Outcome, OutcomeStatus
from app.db.models.suggestion import Suggestion, SuggestionKind, SuggestionStatus
from app.repositories import outcome_repo, suggestion_repo
from app.schemas.outcome import OutcomeAction

_OBSERVED_AT = TypeAdapter(AwareDatetime)

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


def routine_failure_cause(
    kind: Literal["trigger", "watch"], origin: UUID, reason: Literal["run", "check", "delivery"]
) -> str:
    # Retain the existing watch-failure case identity.
    return (
        f"watch:{origin}"
        if kind == "watch" and reason == "check"
        else f"routine:{kind}:{origin}:{reason}"
    )


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

        A muted cause is cleared at once. Other settled causes may reopen; a finding
        retains its decision across all deliveries.
        """
        context = notification.render_context
        budget_pause = (
            notification.event_type == "budget_exceeded"
            and (context or {}).get("routine_budget_paused") is True
        )
        runtime_budget = notification.event_type == "budget_exceeded" and (context or {}).get(
            "routine_failure_owner_id"
        ) == str(notification.recipient_user_id)
        if (
            notification.event_type not in OUTCOME_EVENTS
            and not budget_pause
            and not runtime_budget
        ) or notification.organization_id is None:
            return None
        finding: Suggestion | None = None
        if notification.event_type == "finding":
            try:
                identifier = UUID(notification.occurrence_id)
            except ValueError:
                identifier = None
            if identifier is not None:
                finding = await suggestion_repo.get_own(
                    self.db,
                    identifier,
                    organization_id=notification.organization_id,
                    user_id=notification.recipient_user_id,
                )
        if finding is not None:
            outcome = await self.track_finding(
                finding,
                run_id=_uuid_of(context, "run_id"),
                conversation_id=_uuid_of(context, "conversation_id"),
            )
        else:
            outcome = await outcome_repo.open_or_find(
                self.db,
                organization_id=notification.organization_id,
                user_id=notification.recipient_user_id,
                kind="run_failed" if runtime_budget else notification.event_type,
                dedupe_key=cause_of(
                    "run_failed" if runtime_budget else notification.event_type,
                    notification.occurrence_id,
                    context,
                ),
                summary=notification.summary,
                context_url=notification.context_url,
                source_run_id=_uuid_of(context, "run_id"),
                source_conversation_id=_uuid_of(context, "conversation_id"),
            )
            if outcome.status in (OutcomeStatus.RESOLVED.value, OutcomeStatus.ACKNOWLEDGED.value):
                await outcome_repo.set_status(
                    self.db, outcome, status=OutcomeStatus.OPEN.value, settled_at=None, via=None
                )
        observed = (context or {}).get("routine_observed_at")
        if observed is not None and "routine_failure_reason" in (context or {}):
            observed_at = _OBSERVED_AT.validate_python(observed)
            await outcome_repo.observe_failure(
                self.db,
                outcome=outcome,
                at=observed_at,
                run_id=_uuid_of(context, "run_id"),
                summary=notification.summary,
            )
        cleared = outcome.status != OutcomeStatus.OPEN.value
        cleared_at = datetime.now(UTC) if cleared else None
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
        outcome = await outcome_repo.get_own_for_update(
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
        if outcome.kind == SuggestionKind.FINDING.value and target in (
            OutcomeStatus.RESOLVED,
            OutcomeStatus.MUTED,
        ):
            await suggestion_repo.project_outcome_status(
                self.db,
                outcome_id=outcome.id,
                organization_id=outcome.organization_id,
                user_id=outcome.user_id,
                status=SuggestionStatus.DISMISSED
                if target is OutcomeStatus.MUTED
                else SuggestionStatus.ACCEPTED,
                at=now,
            )
        await outcome_repo.settle_notifications(
            self.db, outcome_id=outcome.id, at=now, dismiss=closing
        )
        await outcome_repo.skip_unsent_deliveries(self.db, outcome_id=outcome.id)
        return outcome

    async def track_finding(
        self,
        finding: Suggestion,
        *,
        run_id: UUID | None = None,
        conversation_id: UUID | None = None,
    ) -> Outcome:
        """The finding and every delivery share one case, including nonurgent findings."""
        if finding.kind != SuggestionKind.FINDING.value:
            raise ConflictError(message="Only a finding can have a finding outcome")
        outcome = await outcome_repo.open_or_find(
            self.db,
            organization_id=finding.organization_id,
            user_id=finding.user_id,
            kind=SuggestionKind.FINDING.value,
            dedupe_key=f"finding:{finding.id}",
            summary=finding.title,
            context_url="/inbox?view=watches",
            source_run_id=run_id,
            source_conversation_id=conversation_id,
        )
        # The case lock serializes all decisions; discard a pre-lock Inbox snapshot.
        await self.db.refresh(finding)
        if finding.outcome_id is None:
            await suggestion_repo.link_outcome(self.db, suggestion=finding, outcome_id=outcome.id)
        elif finding.outcome_id != outcome.id:
            raise ConflictError(message="The finding is linked to a different outcome")
        if finding.status != SuggestionStatus.OPEN.value and outcome.status in (
            OutcomeStatus.OPEN.value,
            OutcomeStatus.ACKNOWLEDGED.value,
        ):
            await self._move(outcome, OutcomeStatus.RESOLVED, via="inbox")
        return outcome

    async def restore_finding(self, ctx: AuthContext, finding: Suggestion) -> None:
        """Explicit undo reopens the same case; it never replays its old deliveries."""
        if finding.organization_id != ctx.organization_id or finding.user_id != _caller(ctx):
            raise NotFoundError(message="Finding not found")
        outcome = await self.track_finding(finding)
        if finding.status != SuggestionStatus.DISMISSED.value:
            raise NotFoundError(message="No such dismissed finding")
        await outcome_repo.set_status(
            self.db, outcome, status=OutcomeStatus.OPEN.value, settled_at=None, via=None
        )

    async def routine_failure_occurrence(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        cause: str,
        observed_at: datetime,
        summary: str,
        run_id: UUID | None = None,
    ) -> str | None:
        """One alert per incident; retries and pre-decision events cannot reopen it."""
        outcome = await outcome_repo.for_cause(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            dedupe_key=f"run_failed:{cause}",
        )
        if outcome is None:
            return f"{cause}:initial"
        if outcome.last_observed_at is not None and observed_at <= outcome.last_observed_at:
            return None
        if outcome.status != OutcomeStatus.RESOLVED.value:
            await outcome_repo.observe_failure(
                self.db, outcome=outcome, at=observed_at, run_id=run_id, summary=summary
            )
            return None
        assert outcome.settled_at is not None, "Resolved routine cases retain their settlement time"
        barriers = [outcome.last_recovered_at]
        if outcome.settled_via != "routine":
            barriers.append(outcome.settled_at)
        if any(barrier is not None and observed_at <= barrier for barrier in barriers):
            await outcome_repo.observe_failure(
                self.db, outcome=outcome, at=observed_at, run_id=run_id, summary=summary
            )
            return None
        # New-incident observation is recorded only with its notification's successful write.
        return f"{cause}:{outcome.settled_at.isoformat()}"

    async def resolve_routine_failure(
        self,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        routine_id: UUID,
        routine_kind: Literal["trigger", "watch"],
        reason: Literal["run", "check", "delivery"],
        recovered_at: datetime | None = None,
    ) -> None:
        if user_id is None:
            return
        cause = routine_failure_cause(routine_kind, routine_id, reason)
        outcome = await outcome_repo.for_cause(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            dedupe_key=f"run_failed:{cause}",
        )
        if outcome is None or outcome.status == OutcomeStatus.MUTED.value:
            return
        if recovered_at is not None:
            await outcome_repo.observe_recovery(self.db, outcome=outcome, at=recovered_at)
            if outcome.last_observed_at is not None and recovered_at < outcome.last_observed_at:
                return
        if outcome.status in (OutcomeStatus.OPEN.value, OutcomeStatus.ACKNOWLEDGED.value):
            await self._move(
                outcome,
                OutcomeStatus.RESOLVED,
                via="routine" if recovered_at is not None else "routine_stop",
            )

    async def resolve_routine_attention(
        self,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        routine_id: UUID,
        routine_kind: Literal["trigger", "watch"],
    ) -> None:
        """Ending or removing a responsibility closes its outstanding blockers."""
        await self.resolve_routine_budget(
            organization_id=organization_id,
            user_id=user_id,
            routine_id=routine_id,
            routine_kind=routine_kind,
        )
        reasons: tuple[Literal["run", "check", "delivery"], ...] = (
            ("run", "delivery") if routine_kind == "trigger" else ("check", "delivery")
        )
        for reason in reasons:
            await self.resolve_routine_failure(
                organization_id=organization_id,
                user_id=user_id,
                routine_id=routine_id,
                routine_kind=routine_kind,
                reason=reason,
            )

    async def resolve_routine_budget(
        self,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        routine_id: UUID,
        routine_kind: Literal["trigger", "watch"],
    ) -> None:
        """A changed limit, new period or removed routine no longer needs this decision."""
        if user_id is None:
            return
        prefix = f"budget_exceeded:routine:{routine_kind}:{routine_id}:budget:"
        for outcome in await outcome_repo.open_for_cause_prefix(
            self.db, organization_id=organization_id, user_id=user_id, prefix=prefix
        ):
            await self._move(outcome, OutcomeStatus.RESOLVED, via="routine")

    async def resolve_watch_findings(
        self, *, organization_id: UUID, user_id: UUID, watch_id: UUID
    ) -> None:
        for outcome in await outcome_repo.for_watch_findings(
            self.db, organization_id=organization_id, user_id=user_id, watch_id=watch_id
        ):
            if outcome.status not in _FINAL:
                await self._move(outcome, OutcomeStatus.RESOLVED, via="watch")

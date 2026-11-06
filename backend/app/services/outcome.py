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
from app.repositories import conversation_repo, outcome_repo, suggestion_repo
from app.schemas.outcome import OutcomeAction, OutcomeSource

_OBSERVED_AT = TypeAdapter(AwareDatetime)

_FINAL = (OutcomeStatus.RESOLVED.value, OutcomeStatus.MUTED.value)
_TARGET: dict[str, OutcomeStatus] = {
    "acknowledge": OutcomeStatus.ACKNOWLEDGED,
    "resolve": OutcomeStatus.RESOLVED,
    "mute": OutcomeStatus.MUTED,
}

OUTCOME_EVENTS = frozenset({"approval_requested", "run_failed", "finding"})
"""Tenant-bound actionable cases. Deployment-wide job alerts retain notification read/dismiss state."""


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
    if (
        ctx.user_id is None
        or ctx.subject_is_publisher_fallback
        or ctx.routine_id is not None
        or ctx.fired_as_creator is not None
        or (
            (ctx.api_key_id is not None or ctx.key_scopes is not None)
            and ctx.source_conversation_id is None
        )
    ):
        raise AuthorizationError(
            message="Inbox cases require a signed-in person in their private chat or console"
        )
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
                identifier = UUID(
                    str((context or {}).get("finding_id", notification.occurrence_id))
                )
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
                await outcome_repo.refresh_context(
                    self.db,
                    outcome,
                    summary=notification.summary,
                    context_url=notification.context_url,
                    source_run_id=_uuid_of(context, "run_id"),
                    source_conversation_id=_uuid_of(context, "conversation_id"),
                )
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
        if not cleared and "routine_auto_stopped_at" in (context or {}):
            # Replace the earlier notice, keeping one actionable Inbox entry
            # and the same case decision across chat and notification channels.
            stopped_at = _OBSERVED_AT.validate_python((context or {})["routine_auto_stopped_at"])
            await outcome_repo.settle_notifications(
                self.db, outcome_id=outcome.id, at=stopped_at, dismiss=True
            )
            await outcome_repo.skip_unsent_deliveries(
                self.db, outcome_id=outcome.id, reason="superseded by automatic pause"
            )
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

    async def _require_private_chat(self, ctx: AuthContext) -> None:
        if ctx.api_key_id is None and ctx.key_scopes is None:
            return
        _caller(ctx)
        # _caller already refuses a key without its private source conversation.
        assert ctx.source_conversation_id is not None
        conversation = await conversation_repo.get_conversation_by_id(
            self.db, ctx.source_conversation_id, fresh=True
        )
        if (
            conversation is None
            or conversation.organization_id != ctx.organization_id
            or conversation.user_id != ctx.user_id
            or conversation.is_archived
        ):
            raise AuthorizationError(
                message="Inbox cases require the person's own private conversation"
            )

    async def list_mine(
        self, ctx: AuthContext, *, open_only: bool, conversation_id: UUID | None, limit: int = 50
    ) -> list[Outcome]:
        _caller(ctx)
        await self._require_private_chat(ctx)
        if ctx.api_key_id is not None or ctx.key_scopes is not None:
            if conversation_id is not None and conversation_id != ctx.source_conversation_id:
                raise NotFoundError(message="Conversation not found")
            conversation_id = ctx.source_conversation_id
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

    async def finding_sources(
        self, ctx: AuthContext, outcomes: list[Outcome]
    ) -> dict[UUID, OutcomeSource]:
        """Source addresses needed to continue a draft, without reopening another transcript."""
        await self._require_private_chat(ctx)
        payloads = await suggestion_repo.finding_sources(
            self.db,
            organization_id=ctx.organization_id,
            user_id=_caller(ctx),
            outcome_ids=[outcome.id for outcome in outcomes],
        )
        sources: dict[UUID, OutcomeSource] = {}
        for identifier, payload in payloads.items():
            key, revision, url = (
                payload.get("source_item_id"),
                payload.get("revision"),
                payload.get("url"),
            )
            if isinstance(key, str) and isinstance(revision, str):
                sources[identifier] = OutcomeSource(
                    item_id=key, revision=revision, url=url if isinstance(url, str) else None
                )
        return sources

    async def settle(
        self, ctx: AuthContext, outcome_id: UUID, action: OutcomeAction, *, via: str
    ) -> Outcome:
        """Acknowledge, resolve or mute the person's own outcome.

        Raises:
            NotFoundError: It is not theirs, or does not exist - the two look alike.
            ConflictError: It is already closed, and `action` would change how.
        """
        await self._require_private_chat(ctx)
        from app.repositories import task as task_repo

        await task_repo.lock_case_task(self.db, outcome_id, ctx.organization_id)
        outcome = await outcome_repo.get_own_for_update(
            self.db,
            organization_id=ctx.organization_id,
            user_id=_caller(ctx),
            outcome_id=outcome_id,
        )
        if outcome is None or (
            (ctx.api_key_id is not None or ctx.key_scopes is not None)
            and outcome.source_conversation_id != ctx.source_conversation_id
        ):
            raise NotFoundError(message="Outcome not found")
        target = _TARGET[action]
        if outcome.status == target.value:
            return outcome
        if outcome.status in _FINAL:
            raise ConflictError(
                message=f"This is already {outcome.status}", details={"status": outcome.status}
            )
        return await self._move(outcome, target, via=via)

    async def resolve_task(
        self, outcome_id: UUID, *, organization_id: UUID, project_task: bool = True
    ) -> None:
        """Project an authorized task completion onto its linked attention case."""
        from app.repositories import task as task_repo

        case = await task_repo.case(self.db, outcome_id, organization_id)
        if case is not None and case.status not in _FINAL:
            await self._move(case, OutcomeStatus.RESOLVED, via="task", project_task=project_task)

    async def resolve_run_approvals(self, run_id: UUID, *, via: str = "approval") -> int:
        """The run's approvals were decided: whoever was still being asked is not any more."""
        settled = 0
        for outcome in await outcome_repo.open_for_run(
            self.db, run_id=run_id, kind="approval_requested"
        ):
            await self._move(outcome, OutcomeStatus.RESOLVED, via=via)
            settled += 1
        return settled

    async def _move(
        self, outcome: Outcome, target: OutcomeStatus, *, via: str, project_task: bool = True
    ) -> Outcome:
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
        from app.services.telephony.cases import cancel_pending_case_calls

        await cancel_pending_case_calls(self.db, outcome.id, at=now)
        if project_task and target in (OutcomeStatus.RESOLVED, OutcomeStatus.MUTED):
            from app.services.task_execution import TaskExecution

            await TaskExecution(self.db).settled(outcome)
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
        from app.repositories import task as task_repo

        if finding.outcome_id is not None:
            await task_repo.lock_case_task(self.db, finding.outcome_id, finding.organization_id)
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
        from app.services.task_execution import TaskExecution

        await TaskExecution(self.db).restored(
            ctx, outcome, task_id=_uuid_of(finding.payload, "task_id")
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
        escalation_at: datetime | None = None,
    ) -> str | None:
        """One incident, with one additional notice when it causes an automatic pause."""
        outcome = await outcome_repo.for_cause(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            dedupe_key=f"run_failed:{cause}",
        )
        if outcome is None:
            return (
                f"{cause}:auto-stop:{escalation_at.isoformat()}"
                if escalation_at is not None
                else f"{cause}:initial"
            )
        if outcome.last_observed_at is not None and observed_at <= outcome.last_observed_at:
            return None
        if outcome.status != OutcomeStatus.RESOLVED.value:
            if escalation_at is not None and outcome.status == OutcomeStatus.OPEN.value:
                # The notification links to the existing case. Record its new
                # observation only when that notification is successfully written.
                return f"{cause}:auto-stop:{escalation_at.isoformat()}"
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

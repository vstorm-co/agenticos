"""Queue a resumed answer with its terminal write, never another model call."""

import hashlib
import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, ConflictError
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.outcome import OutcomeStatus
from app.db.models.suggestion import SuggestionKind, SuggestionStatus
from app.repositories import conversation_repo, outcome_repo, suggestion_repo
from app.repositories import routine_delivery as delivery_repo
from app.schemas.routine_notifications import (
    RoutineFinding,
    RoutineFindingPublish,
    RoutineFindingReceipt,
)
from app.services.background_jobs import enqueue
from app.services.change_feed import announce_conversation
from app.services.notifications import NotificationService
from app.services.outcome import OutcomeService
from app.services.telephony.cases import cancel_pending_case_calls
from app.worker.jobs import DELIVER_ROUTINE_ANSWER, DeliverRoutineAnswer

logger = logging.getLogger(__name__)


class RoutineDeliveryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def queue(self, run: AgentRun, *, answer: str) -> None:
        if (
            run.status
            not in {
                RunStatus.COMPLETED.value,
                RunStatus.RUNNING.value,
                RunStatus.AWAITING_APPROVAL.value,
                RunStatus.AWAITING_ANSWER.value,
            }
            and run.parent_run_id is None
            and run.routine_kind == "trigger"
            and run.routine_origin_id is not None
        ):
            from app.repositories import agent_trigger_repo
            from app.services.task_execution import TaskExecution

            trigger = await agent_trigger_repo.get(
                self.db, run.routine_origin_id, organization_id=run.organization_id
            )
            if trigger is not None and trigger.one_shot is True:
                await TaskExecution(self.db).finished(trigger, run)
        if (
            run.status != RunStatus.COMPLETED.value
            or run.parent_run_id is not None
            or run.routine_kind != "trigger"
            or run.routine_origin_id is None
            or run.user_id is None
        ):
            return
        if not await delivery_repo.create(
            self.db,
            run_id=run.id,
            organization_id=run.organization_id,
            trigger_id=run.routine_origin_id,
            answer=answer,
        ):
            return
        await enqueue(
            self.db,
            DELIVER_ROUTINE_ANSWER,
            DeliverRoutineAnswer(run_id=run.id, organization_id=run.organization_id),
            organization_id=run.organization_id,
            dedupe_key=f"routine-answer:{run.id}",
        )


class RoutineFindingService:
    """Publish one source item as a private working chat and one shared Inbox case."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def publish_for_run(
        self, ctx: AuthContext, item: RoutineFindingPublish
    ) -> RoutineFindingReceipt:
        """Only a live run credential may report to its own routine's owner.

        No recipient, organization, routine or run id is accepted from the model.
        The current membership and admitted sources are checked again on each call.
        """
        from app.repositories import agent_run_repo
        from app.services.routine_authority import RoutineAuthority

        if not ctx.key_internal or ctx.source_run_id is None or ctx.user_id is None:
            raise AuthorizationError(message="Publishing a finding needs a live routine run")
        run = await agent_run_repo.get_run(
            self.db, ctx.source_run_id, organization_id=ctx.organization_id, for_update=True
        )
        if (
            run is None
            or run.user_id != ctx.user_id
            or run.status != RunStatus.RUNNING.value
            or run.routine_origin_id is None
            or run.parent_run_id is not None
        ):
            raise AuthorizationError(message="This credential cannot publish for this run")
        authority = await RoutineAuthority.capture(self.db, ctx, agent_id=run.agent_id, run=run)
        if authority is None:
            raise AuthorizationError(message="Only a routine or monitor may publish a finding")
        urgent = item.urgent
        if authority.routine_kind == "watch":
            from app.repositories import watch_repo

            watch = await watch_repo.get_by_id(self.db, authority.routine_id, fresh=True)
            if watch is None:
                raise AuthorizationError(message="The monitor is no longer available")
            urgent = urgent and watch.urgent
        target = await self.publish(
            run=run,
            user_id=authority.user_id,
            origin_id=authority.routine_id,
            origin_kind=authority.routine_kind,
            item=RoutineFinding.model_validate(item.model_dump(exclude={"urgent"})),
            urgent=urgent,
            notify=authority.routine_kind == "trigger" or urgent,
            max_findings=8,
        )
        return RoutineFindingReceipt(
            conversation_id=target,
            status="published" if target is not None else "unchanged_or_muted",
        )

    async def publish(
        self,
        *,
        run: AgentRun,
        user_id: UUID,
        origin_id: UUID,
        origin_kind: Literal["trigger", "watch"],
        item: RoutineFinding,
        notify: bool = True,
        urgent: bool = False,
        max_findings: int | None = None,
    ) -> UUID | None:
        """Return the working chat for a new revision, or None for unchanged/muted work.

        The caller checks the live routine authority before publishing. The source
        identity, scoped to its routine and owner, survives decisions and worker retries.
        A changed revision reopens the same case and appends to the same owned chat.
        """
        identity = (
            "finding:" + hashlib.sha256(f"{origin_id}\x1f{item.key}".encode()).hexdigest()[:48]
            if origin_kind == "watch"
            else hashlib.sha256(f"{origin_kind}:{origin_id}:{item.key}".encode()).hexdigest()
        )
        finding = await suggestion_repo.propose(
            self.db,
            organization_id=run.organization_id,
            user_id=user_id,
            kind=SuggestionKind.FINDING.value,
            title=item.title,
            detail=item.detail,
            payload={"revision": item.revision},
            dedupe_key=identity,
            watch_id=origin_id if origin_kind == "watch" else None,
            urgent=urgent,
        )
        created = finding is not None
        if finding is None:
            finding = await suggestion_repo.for_key(
                self.db, organization_id=run.organization_id, user_id=user_id, dedupe_key=identity
            )
        if finding is None:
            raise RuntimeError("The routine finding disappeared after its identity was claimed")
        outcomes = OutcomeService(self.db)
        outcome = await outcomes.track_finding(finding)
        if outcome.status == OutcomeStatus.MUTED.value:
            return None
        if not await suggestion_repo.claim_finding_revision(
            self.db, finding_id=finding.id, revision=item.revision
        ):
            return None
        if (
            max_findings is not None
            and outcome.source_run_id != run.id
            and await outcome_repo.count_run_findings(
                self.db, organization_id=run.organization_id, user_id=user_id, run_id=run.id
            )
            >= max_findings
        ):
            raise ConflictError(
                message="This run has already published eight findings; group related work."
            )
        conversation = None
        if outcome.source_conversation_id is not None:
            conversation = await conversation_repo.get_conversation_by_id(
                self.db, outcome.source_conversation_id, fresh=True
            )
            if (
                conversation is None
                or conversation.organization_id != run.organization_id
                or conversation.user_id != user_id
                or conversation.is_archived
            ):
                raise ConflictError(message="The finding's working conversation is unavailable")
        if conversation is None:
            conversation = await conversation_repo.create_conversation(
                self.db, organization_id=run.organization_id, user_id=user_id, title=item.title
            )
        await outcome_repo.refresh_context(
            self.db,
            outcome,
            summary=item.title,
            context_url=f"/chat/{conversation.id}",
            source_run_id=run.id,
            source_conversation_id=conversation.id,
        )
        if not created:
            await outcome_repo.settle_notifications(
                self.db, outcome_id=outcome.id, at=datetime.now(UTC), dismiss=True
            )
            await outcome_repo.skip_unsent_deliveries(
                self.db, outcome_id=outcome.id, reason="new source revision"
            )
            await cancel_pending_case_calls(self.db, outcome.id, at=datetime.now(UTC))
            await outcome_repo.set_status(
                self.db, outcome, status=OutcomeStatus.OPEN.value, settled_at=None, via=None
            )
        finding.urgent = urgent
        finding.briefed_at = datetime.now(UTC) if notify else None
        finding.title = item.title
        finding.detail = item.detail
        finding.status = SuggestionStatus.OPEN.value
        finding.decided_at = None
        finding.payload = {
            "source_item_id": item.key,
            "revision": item.revision,
            "conversation_id": str(conversation.id),
            "url": str(item.url) if item.url is not None else None,
            "routine_id": str(origin_id),
            "routine_kind": origin_kind,
        }
        from app.core.permissions import Perm
        from app.services.access import member_context
        from app.services.tasks import TaskService

        owner = await member_context(self.db, organization_id=run.organization_id, user_id=user_id)
        if owner is not None and owner.has(Perm.TABLES_CREATE):
            from app.services.virtual_tables.exceptions import QuotaExceededError

            try:
                async with self.db.begin_nested():
                    task = await TaskService(self.db).finding(
                        owner,
                        outcome_id=outcome.id,
                        conversation_id=conversation.id,
                        title=item.title,
                        description=item.detail or "",
                        agent_id=run.agent_id,
                    )
            except QuotaExceededError:
                logger.info("routine_task_projection_quota", extra={"run_id": str(run.id)})
            else:
                finding.payload = {
                    **finding.payload,
                    "task_id": str(task.id),
                    "table_id": str(task.table_id),
                }
        await conversation_repo.create_message(
            self.db,
            conversation_id=conversation.id,
            role="assistant",
            content=f"**{item.title}**\n\n{item.content}"
            + (f"\n\n{item.url}" if item.url is not None else ""),
            agent_id=run.agent_id,
            agent_version_id=run.agent_version_id,
            model_name=run.model_label,
            run_id=run.id,
        )
        await self.db.flush()
        announce_conversation(
            self.db,
            organization_id=run.organization_id,
            conversation_id=conversation.id,
            actor_user_id=user_id,
        )
        if notify:
            await NotificationService(self.db).finding(
                organization_id=run.organization_id,
                user_id=user_id,
                finding_id=finding.id,
                title=finding.title,
                conversation_id=conversation.id,
                run_id=run.id,
                routine_id=origin_id,
                routine_kind=origin_kind,
                revision=item.revision,
            )
        from app.services.proactive import ProactiveService

        await ProactiveService(self.db).queue_context_change(run.organization_id, user_id)
        return conversation.id

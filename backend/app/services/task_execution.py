"""Deferred work reuses the routine runner; human reminders never call a model."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.outcome import Outcome, OutcomeStatus
from app.db.models.task_board import TaskBoard, TaskLink
from app.db.models.virtual_table import VirtualTableRecord
from app.repositories import agent_trigger_repo
from app.repositories import task as task_repo
from app.schemas.agent_trigger import TriggerCreate
from app.schemas.conversation import ConversationCreate
from app.schemas.task import TaskFields, TaskStatus
from app.schemas.virtual_table import RecordUpdate
from app.services.access import member_context
from app.services.background_jobs import enqueue
from app.services.task_columns import from_cells
from app.worker.jobs import FIRE_TRIGGER, WAKE_TASK, WakeTask

_TERMINAL = {"done", "cancelled"}
_SETTLED = {OutcomeStatus.RESOLVED.value, OutcomeStatus.MUTED.value}


class TaskExecution:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def restored_table(self, table_id: UUID, organization_id: UUID) -> None:
        """Catch a restored board up with the authoritative state of its linked cases.

        A case settled while the board was archived could not move its task, so the
        task takes that outcome now. Planned human reminders consumed meanwhile are
        rearmed.
        """
        from app.repositories import background_job as job_repo

        board = await task_repo.for_table(self.db, table_id, organization_id)
        if board is None:
            return
        for link in await task_repo.board_links(self.db, board):
            record = await task_repo.record(self.db, link.record_id, organization_id, lock=True)
            if record is None:
                continue
            fields = from_cells(board, record.values)
            if link.outcome_id is not None and fields.status not in _TERMINAL:
                case = await task_repo.case(self.db, link.outcome_id, organization_id)
                # Settlement can be stamped before an archive wins the board lock.
                if case is not None and case.status in _SETTLED:
                    await self.settled(case)
                    continue
            if fields.next_actor != "user" or fields.status != "planned" or fields.start_at is None:
                continue
            await job_repo.cancel_queued_for_payload(
                self.db,
                kind=WAKE_TASK.kind,
                organization_id=organization_id,
                payload_key="task_id",
                payload_value=record.id,
            )
            await enqueue(
                self.db,
                WAKE_TASK,
                WakeTask(
                    organization_id=organization_id, task_id=record.id, revision=record.revision
                ),
                organization_id=organization_id,
                run_after=fields.start_at,
                dedupe_key=f"task:{record.id}:{record.revision}",
            )

    async def changed(
        self,
        ctx: AuthContext,
        board: TaskBoard,
        record: VirtualTableRecord,
        link: TaskLink,
        fields: TaskFields,
        *,
        publish_attention: bool = True,
    ) -> None:
        terminal = fields.status in _TERMINAL
        if (
            ctx.routine_id is not None
            and ctx.routine_id == link.trigger_id
            and fields.status not in {"planned", "in_progress"}
        ):
            raise AuthorizationError(
                message="The task runner publishes its result for review; its executing agent cannot close or cancel its own task"
            )
        if terminal or fields.status in {"waiting_for_user", "blocked"}:
            await self._stop(link, ctx.organization_id)
            if publish_attention and fields.status in {"waiting_for_user", "blocked"}:
                case = (
                    await task_repo.case(self.db, link.outcome_id, ctx.organization_id)
                    if link.outcome_id is not None
                    else None
                )
                recipient = fields.assignee_user_id or link.creator_user_id
                if recipient is not None and (
                    case is None
                    or case.user_id != recipient
                    or case.status in {"resolved", "muted"}
                ):
                    if case is not None and case.user_id != recipient:
                        from app.services.outcome import OutcomeService

                        link.outcome_id = None
                        await task_repo.flush(self.db)
                        await OutcomeService(self.db).resolve_task(
                            case.id, organization_id=ctx.organization_id
                        )
                    await self._attention(board, record, link, recipient, fields.title)
            if terminal and link.outcome_id is not None:
                from app.services.outcome import OutcomeService

                await OutcomeService(self.db).resolve_task(
                    link.outcome_id, organization_id=ctx.organization_id
                )
            return
        signature = hashlib.sha256(
            json.dumps(
                {
                    "title": fields.title,
                    "description": fields.description,
                    "agent": str(fields.assignee_agent_id),
                    "person": str(fields.assignee_user_id),
                    "next_actor": fields.next_actor,
                    "start": fields.start_at.isoformat() if fields.start_at else None,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if link.execution_hash == signature:
            if (
                fields.next_actor == "user"
                and fields.start_at is not None
                and fields.status == "planned"
            ):
                from app.repositories import background_job as job_repo

                await job_repo.cancel_queued_for_payload(
                    self.db,
                    kind=WAKE_TASK.kind,
                    organization_id=ctx.organization_id,
                    payload_key="task_id",
                    payload_value=record.id,
                )
                await enqueue(
                    self.db,
                    WAKE_TASK,
                    WakeTask(
                        organization_id=ctx.organization_id,
                        task_id=record.id,
                        revision=record.revision,
                    ),
                    organization_id=ctx.organization_id,
                    run_after=fields.start_at,
                    dedupe_key=f"task:{record.id}:{record.revision}",
                )
            return
        if fields.next_actor == "agent":
            if fields.assignee_user_id != ctx.user_id:
                raise AuthorizationError(
                    message="Agent work must be started by its human owner using their own account. Choose Person as the next step until that person starts it."
                )
            if link.creator_user_id != ctx.user_id:
                if link.trigger_id is not None:
                    raise AuthorizationError(
                        message="Stop the current execution before taking over this task"
                    )
                link.creator_user_id = ctx.user_id
                link.conversation_id = None
        elif link.creator_user_id != ctx.user_id and link.trigger_id is not None:
            raise AuthorizationError(
                message="Stop the current agent execution before changing its instructions"
            )
        if link.outcome_id is not None:
            from app.services.outcome import OutcomeService

            previous_case = await task_repo.case(self.db, link.outcome_id, ctx.organization_id)
            previous_id = link.outcome_id
            if previous_case is not None and previous_case.user_id != (
                fields.assignee_user_id or link.creator_user_id
            ):
                link.outcome_id = None
                await task_repo.flush(self.db)
            await OutcomeService(self.db).resolve_task(
                previous_id, organization_id=ctx.organization_id, project_task=False
            )
        await self._stop(link, ctx.organization_id)
        link.execution_hash = signature
        if fields.next_actor == "agent" and fields.assignee_agent_id is not None:
            from app.services.agent_registry import AgentRegistryService
            from app.services.agent_trigger import AgentTriggerService
            from app.services.conversation import ConversationService

            resolved = await AgentRegistryService(self.db).get_runnable_spec(
                ctx, fields.assignee_agent_id
            )
            if link.conversation_id is None:
                conversation = await ConversationService(self.db).create_conversation(
                    ConversationCreate(
                        organization_id=ctx.organization_id,
                        user_id=ctx.subject_id,
                        title=fields.title,
                        project_id=board.scope_id if board.scope_kind == "project" else None,
                    )
                )
                link.conversation_id = conversation.id
            trigger = await AgentTriggerService(self.db).create(
                ctx,
                fields.assignee_agent_id,
                TriggerCreate(
                    name=fields.title[:120],
                    prompt=f"Work on task {record.id}: {fields.title}\n\n{fields.description}\n\nKeep drafts in the working conversation. Do not send or publish a draft without the user's authorization. Report what needs review; only claim success after the relevant tool succeeds. Do not close, cancel, reschedule or resolve this task yourself. The platform publishes your final answer and places the task in waiting-for-review state.",
                    interval_seconds=3600,
                    pinned_version_id=resolved[2],
                    runs_as_creator=True,
                    project_id=board.scope_id if board.scope_kind == "project" else None,
                    answer_to="conversation",
                    delivery_conversation_id=link.conversation_id,
                    notification_channels=[],
                ),
                run_once_at=fields.start_at or datetime.now(UTC),
            )
            link.trigger_id = trigger.id
            if fields.start_at is None or fields.start_at <= datetime.now(UTC):
                trigger.next_fire_at = None
                await task_repo.flush(self.db)
                await AgentTriggerService(self.db).queue_fire(
                    trigger.id, organization_id=ctx.organization_id
                )
        elif fields.start_at is not None:
            await enqueue(
                self.db,
                WAKE_TASK,
                WakeTask(
                    organization_id=ctx.organization_id, task_id=record.id, revision=record.revision
                ),
                organization_id=ctx.organization_id,
                run_after=fields.start_at,
                dedupe_key=f"task:{record.id}:{record.revision}",
            )
        await task_repo.flush(self.db)

    async def _stop(self, link: TaskLink, organization_id: UUID) -> None:
        from app.repositories import background_job as job_repo

        await job_repo.cancel_queued_for_payload(
            self.db,
            kind=WAKE_TASK.kind,
            organization_id=organization_id,
            payload_key="task_id",
            payload_value=link.record_id,
        )
        if link.trigger_id is not None:
            await job_repo.cancel_queued_for_payload(
                self.db,
                kind=FIRE_TRIGGER.kind,
                organization_id=organization_id,
                payload_key="trigger_id",
                payload_value=link.trigger_id,
            )
            trigger = await agent_trigger_repo.get_by_id(self.db, link.trigger_id)
            if trigger is not None:
                trigger.is_active = False
            from app.services.agent_runner import AgentRunnerService

            runner = AgentRunnerService(self.db)
            run_ids = await task_repo.parked_runs(self.db, organization_id, link.trigger_id)
            await runner.stop_parked_for_workflow(
                run_ids, organization_id=organization_id, reason="Stopped: task execution changed"
            )
            link.trigger_id = None
            await task_repo.flush(self.db)
            # Task record revisions retain the user action that ended these runs.
            # No audit lock here: the enclosing mutation still owns row work.
        link.execution_hash = None

    async def deleted(self, ctx: AuthContext, record: VirtualTableRecord) -> None:
        link = await task_repo.link(self.db, record.id)
        if link is None:
            return
        await self._forget_link(link, ctx.organization_id)

    async def purge_board(self, board: TaskBoard) -> None:
        for link in await task_repo.board_links(self.db, board):
            await self._forget_link(link, board.organization_id)

    async def _forget_link(self, link: TaskLink, organization_id: UUID) -> None:
        await self._stop(link, organization_id)
        if link.outcome_id is not None:
            from app.services.outcome import OutcomeService

            outcome_id = link.outcome_id
            link.outcome_id = None
            await task_repo.flush(self.db)
            await OutcomeService(self.db).resolve_task(outcome_id, organization_id=organization_id)

    async def wake(self, payload: WakeTask) -> None:
        from app.services.task_access import board_allows

        record = await self._locked_record(payload.task_id, payload.organization_id)
        if record is None:
            return
        link = await task_repo.link(self.db, record.id)
        board = await task_repo.for_table(self.db, record.table_id, payload.organization_id)
        if board is None or link is None:
            return
        fields = from_cells(board, record.values)
        # Edits invalidate a queued occurrence; there is no scan of everyone's TODOs.
        if (
            record.revision != payload.revision
            or fields.status != "planned"
            or fields.next_actor != "user"
            or fields.start_at is None
            or fields.start_at > datetime.now(UTC)
        ):
            return
        ctx = (
            (
                await member_context(
                    self.db, organization_id=payload.organization_id, user_id=link.creator_user_id
                )
            )
            if link.creator_user_id is not None
            else None
        )
        if ctx is None or not await board_allows(self.db, ctx, board, Perm.TABLES_EDIT):
            await self._stop(link, payload.organization_id)
            await self._project(board, record, "blocked", actor=None)
            recipient = fields.assignee_user_id
            if recipient is not None:
                reviewer = await member_context(
                    self.db, organization_id=payload.organization_id, user_id=recipient
                )
                if reviewer is not None and await board_allows(
                    self.db, reviewer, board, Perm.TABLES_EDIT
                ):
                    await self._attention(
                        board,
                        record,
                        link,
                        recipient,
                        fields.title,
                        detail="The reminder's creator no longer has access. Review this blocked task and take over its next step.",
                    )
            return

        table = await self._live_table(board)
        if not table:
            return
        recipient = fields.assignee_user_id or ctx.subject_id
        recipient_ctx = await member_context(
            self.db, organization_id=payload.organization_id, user_id=recipient
        )
        if recipient_ctx is None or not await board_allows(
            self.db, recipient_ctx, board, Perm.TABLES_EDIT
        ):
            await self._stop(link, payload.organization_id)
            await self._project(board, record, "blocked", actor=None)
            await self._attention(
                board,
                record,
                link,
                ctx.subject_id,
                fields.title,
                detail="The assigned reviewer no longer has access. Choose another person for the next step.",
            )
            return
        await self._state(
            ctx,
            board,
            record,
            fields.model_copy(update={"status": "waiting_for_user", "next_actor": "user"}),
        )
        await self._attention(board, record, link, recipient, fields.title)

    async def _live_table(self, board: TaskBoard) -> bool:
        from app.repositories import virtual_table_repo

        table = await virtual_table_repo.get_table(
            self.db, board.table_id, organization_id=board.organization_id
        )
        return table is not None and table.archived_at is None

    async def started(self, ctx: AuthContext, trigger: AgentTrigger) -> bool:
        from app.services.task_access import execution_allows

        if not await execution_allows(self.db, ctx, trigger.id):
            return False
        link = await task_repo.for_trigger(self.db, trigger.id)
        if link is None:
            return False
        record = await self._locked_record(link.record_id, ctx.organization_id)
        if record is None:
            return False
        board = await task_repo.for_table(self.db, record.table_id, ctx.organization_id)
        if board is None:
            return False
        await self._state(
            ctx,
            board,
            record,
            from_cells(board, record.values).model_copy(update={"status": "in_progress"}),
        )
        return True

    async def unavailable(self, trigger: AgentTrigger) -> None:
        link = await task_repo.for_trigger(self.db, trigger.id)
        if link is None:
            return
        record = await self._locked_record(link.record_id, trigger.organization_id)
        if record is None:
            return
        board = await task_repo.for_table(self.db, record.table_id, trigger.organization_id)
        if board is None or from_cells(board, record.values).status not in {
            "planned",
            "in_progress",
        }:
            return
        await self._stop(link, trigger.organization_id)
        await self._project(board, record, "blocked", actor=None)

    async def finished(self, trigger: AgentTrigger, run: AgentRun) -> None:
        if run.status in {
            RunStatus.RUNNING.value,
            RunStatus.AWAITING_APPROVAL.value,
            RunStatus.AWAITING_ANSWER.value,
        }:
            return
        link = await task_repo.for_trigger(self.db, trigger.id)
        trigger.is_active = False
        if link is None or link.creator_user_id is None:
            return
        record = await self._locked_record(link.record_id, trigger.organization_id)
        if record is None:
            return
        board = await task_repo.for_table(self.db, record.table_id, trigger.organization_id)
        ctx = await member_context(
            self.db, organization_id=trigger.organization_id, user_id=link.creator_user_id
        )
        from app.core.permissions import Perm
        from app.services.task_access import board_allows

        if (
            board is None
            or ctx is None
            or not await self._live_table(board)
            or not await board_allows(self.db, ctx, board, Perm.TABLES_EDIT)
        ):
            await self.unavailable(trigger)
            return
        fields = from_cells(board, record.values)
        if fields.status in _TERMINAL:
            return
        status = "waiting_for_user" if run.status == RunStatus.COMPLETED.value else "blocked"
        recipient = fields.assignee_user_id or link.creator_user_id
        reviewer = await member_context(
            self.db, organization_id=trigger.organization_id, user_id=recipient
        )
        if reviewer is None or not await board_allows(self.db, reviewer, board, Perm.TABLES_EDIT):
            await self._stop(link, trigger.organization_id)
            await self._project(board, record, "blocked", actor=None)
            await self._attention(
                board,
                record,
                link,
                ctx.subject_id,
                fields.title,
                detail="The assigned reviewer no longer has access. Choose another person for the next step.",
            )
        else:
            await self._state(
                ctx,
                board,
                record,
                fields.model_copy(update={"status": status, "next_actor": "user"}),
            )
            await self._attention(board, record, link, recipient, fields.title)

    async def _state(
        self, ctx: AuthContext, board: TaskBoard, record: VirtualTableRecord, fields: TaskFields
    ) -> None:
        from app.services.virtual_tables import VirtualTableService

        await VirtualTableService(self.db).update_record(
            ctx,
            board.table_id,
            record.id,
            RecordUpdate(
                values={
                    board.column_ids["status"]: board.status_ids[fields.status],
                    board.column_ids["next_actor"]: board.status_ids[f"actor:{fields.next_actor}"],
                },
                expected_revision=record.revision,
            ),
        )

    async def settled(self, outcome: Outcome) -> None:
        """The Inbox and table complete the same commitment, preserving record history."""
        link = await task_repo.for_outcome(self.db, outcome.id)
        if link is None:
            return
        record = await self._locked_record(link.record_id, outcome.organization_id)
        if record is None:
            return
        board = await task_repo.for_table(self.db, record.table_id, outcome.organization_id)
        if board is None:
            return
        fields = from_cells(board, record.values)
        actor = await member_context(
            self.db, organization_id=outcome.organization_id, user_id=outcome.user_id
        )
        from app.core.permissions import Perm
        from app.services.task_access import board_allows

        is_reviewer = outcome.user_id == (fields.assignee_user_id or link.creator_user_id) or (
            fields.status == "blocked" and outcome.user_id == link.creator_user_id
        )
        if (
            actor is None
            or not is_reviewer
            or not await board_allows(self.db, actor, board, Perm.TABLES_EDIT)
        ):
            link.outcome_id = None
            await self._stop(link, outcome.organization_id)
            await self._project(board, record, "blocked", actor=None)
            owner = (
                await member_context(
                    self.db, organization_id=outcome.organization_id, user_id=link.creator_user_id
                )
                if link.creator_user_id is not None
                else None
            )
            if owner is not None and await board_allows(self.db, owner, board, Perm.TABLES_EDIT):
                await self._attention(
                    board,
                    record,
                    link,
                    owner.subject_id,
                    fields.title,
                    detail="The previous reviewer is no longer responsible or no longer has access. Choose who takes the next step.",
                )
            return
        status = "cancelled" if outcome.status == "muted" else "done"
        if fields.status in _TERMINAL:
            return
        await self._stop(link, outcome.organization_id)
        await self._project(board, record, status, actor=outcome.user_id)

    async def restored(self, ctx: AuthContext, outcome: Outcome, *, task_id: UUID | None) -> None:
        from app.core.exceptions import ConflictError
        from app.core.permissions import Perm
        from app.services.task_access import board_allows

        link = await task_repo.for_outcome(self.db, outcome.id)
        if link is None:
            if task_id is not None:
                raise ConflictError(
                    message="This task was deleted or handed off. Open its current task table instead."
                )
            return
        record = await self._locked_record(link.record_id, outcome.organization_id)
        board = (
            await task_repo.for_table(self.db, record.table_id, outcome.organization_id)
            if record
            else None
        )
        if (
            board is None
            or record is None
            or not await board_allows(self.db, ctx, board, Perm.TABLES_EDIT)
        ):
            raise ConflictError(message="This task is no longer available in your scope")
        if not await self._live_table(board):
            from app.services.virtual_tables.exceptions import TableArchivedError

            raise TableArchivedError(table_id=board.table_id)
        await self._stop(link, outcome.organization_id)
        await self._project(board, record, "waiting_for_user", actor=ctx.user_id)

    async def _locked_record(
        self, record_id: UUID, organization_id: UUID
    ) -> VirtualTableRecord | None:
        """The task's record, row-locked once its board's table is locked FOR SHARE.

        Table before record, the order every record write takes and the one restoring
        a board needs: it holds the table and then locks each task, so a task moved
        while holding its record first and waiting on the table would deadlock with it.
        """
        from app.repositories import virtual_table_repo

        found = await task_repo.record(self.db, record_id, organization_id)
        if found is None:
            return None
        await virtual_table_repo.get_table(
            self.db, found.table_id, organization_id=organization_id, for_share=True
        )
        return await task_repo.record(self.db, record_id, organization_id, lock=True)

    async def _project(
        self,
        board: TaskBoard,
        record: VirtualTableRecord,
        status: TaskStatus,
        *,
        actor: UUID | None,
    ) -> None:
        """Move the task to `status` - unless its board is archived, which takes no writes.

        Settling a case is not refused for that: the decision stands, and
        `restored_table` brings the task up to date if the board comes back.
        """
        from app.repositories import virtual_table_repo
        from app.services.virtual_tables.record_sources import SYSTEM_SOURCE, person_source

        table = await virtual_table_repo.get_table(
            self.db, board.table_id, organization_id=board.organization_id, for_share=True
        )
        if table is None or table.archived_at is not None:
            return
        source = SYSTEM_SOURCE if actor is None else await person_source(self.db, actor)
        before = dict(record.values)
        values = {
            **before,
            board.column_ids["status"]: board.status_ids[status],
            board.column_ids["next_actor"]: board.status_ids["actor:user"],
        }
        await virtual_table_repo.update_record(
            self.db,
            record=record,
            values=values,
            schema_version=record.schema_version,
            updated_by=actor,
            source=source.stored(),
        )
        await virtual_table_repo.add_history(
            self.db,
            organization_id=board.organization_id,
            table_id=board.table_id,
            record_id=record.id,
            revision=record.revision,
            operation="update",
            actor_user_id=actor,
            before=before,
            after=values,
        )
        await virtual_table_repo.add_outbox(
            self.db,
            organization_id=board.organization_id,
            table_id=board.table_id,
            record_id=record.id,
            event_type="table.record.updated",
            payload={
                "table_id": str(board.table_id),
                "record_id": str(record.id),
                "external_id": record.external_id,
                "schema_version": record.schema_version,
                "revision": record.revision,
                "before": before,
                "after": values,
            },
        )

    async def _attention(
        self,
        board: TaskBoard,
        record: VirtualTableRecord,
        link: TaskLink,
        recipient: UUID,
        title: str,
        detail: str | None = None,
    ) -> None:
        from app.db.models.outcome import OutcomeStatus
        from app.db.models.suggestion import SuggestionKind, SuggestionStatus
        from app.repositories import conversation_repo, outcome_repo, suggestion_repo
        from app.services.notifications import NotificationService
        from app.services.outcome import OutcomeService

        working_conversation_id = link.conversation_id
        if working_conversation_id is not None:
            working = await conversation_repo.get_conversation_by_id(
                self.db, working_conversation_id
            )
            if (
                working is None
                or working.organization_id != board.organization_id
                or working.user_id != recipient
                or working.is_archived
            ):
                working_conversation_id = None
        finding = (
            await task_repo.finding_for_case(
                self.db, link.outcome_id, board.organization_id, recipient
            )
            if link.outcome_id is not None
            else None
        )
        if finding is None:
            finding = await suggestion_repo.propose(
                self.db,
                organization_id=board.organization_id,
                user_id=recipient,
                kind=SuggestionKind.FINDING.value,
                title=title,
                detail=None,
                payload={},
                dedupe_key=f"task:{record.id}",
                urgent=False,
            )
        if finding is None:
            finding = await suggestion_repo.for_key(
                self.db,
                organization_id=board.organization_id,
                user_id=recipient,
                dedupe_key=f"task:{record.id}",
            )
        if finding is None:
            raise RuntimeError("Task attention could not be persisted")
        finding.status = SuggestionStatus.OPEN.value
        finding.title = title
        finding.detail = detail
        finding.decided_at = None
        finding.briefed_at = datetime.now(UTC)
        finding.payload = {
            **finding.payload,
            "task_id": str(record.id),
            "table_id": str(board.table_id),
            "conversation_id": str(working_conversation_id) if working_conversation_id else None,
        }
        case = await OutcomeService(self.db).track_finding(
            finding, conversation_id=working_conversation_id
        )
        await outcome_repo.set_status(
            self.db, case, status=OutcomeStatus.OPEN.value, settled_at=None, via=None
        )
        await outcome_repo.refresh_context(
            self.db,
            case,
            summary=title,
            context_url=f"/chat/{working_conversation_id}"
            if working_conversation_id
            else f"/tables/{board.table_id}",
            source_run_id=case.source_run_id,
            source_conversation_id=working_conversation_id,
        )
        link.outcome_id = case.id
        await NotificationService(self.db).finding(
            organization_id=board.organization_id,
            user_id=recipient,
            finding_id=finding.id,
            title=title,
            conversation_id=working_conversation_id,
            revision=f"task:{record.revision}",
        )
        await task_repo.flush(self.db)

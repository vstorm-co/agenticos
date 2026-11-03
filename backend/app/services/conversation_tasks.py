"""Explicit background delegation, with durable completion in the source topic.

The source version and device are fixed at admission. Workers recheck membership,
conversation/project access and run permission before spending. A lost attempt is
reported as interrupted; it is never replayed over unknown external side effects.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.locks import LockScope, hold_subject
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.conversation_task import ConversationTask
from app.db.session import get_db_context
from app.repositories import agent as agent_repo
from app.repositories import agent_run as run_repo
from app.repositories import background_job as job_repo
from app.repositories import conversation_task as task_repo
from app.schemas.conversation import ConversationCreate, MessageCreate
from app.schemas.conversation_task import ConversationTaskRead, StartConversationTask
from app.schemas.local_target import LocalTarget
from app.services.access import acting_member
from app.services.agent_registry import AgentRegistryService
from app.services.background_jobs import enqueue
from app.services.conversation import ConversationService
from app.worker.jobs import RETURN_CONVERSATION_TASK, RUN_CONVERSATION_TASK, ConversationTaskJob

TERMINAL = frozenset({"completed", "failed", "cancelled", "interrupted"})
MAX_ACTIVE = 4


CANCEL_POLL_SECONDS = 2.0


class ConversationTaskStopped(Exception):
    """This execution lost its task, or its member explicitly stopped it."""


async def _check_execution(task_id: UUID, organization_id: UUID, run_id: UUID) -> None:
    async with get_db_context() as db:
        task = await task_repo.get(db, task_id, organization_id=organization_id)
        if task is None or (
            task.delivery in {"interrupted", "withdrawn", "delivered"}
            if task.return_run_id == run_id
            else task.status in TERMINAL
        ):
            raise ConversationTaskStopped


async def _watch_execution(task_id: UUID, organization_id: UUID, run_id: UUID) -> None:
    while True:
        await asyncio.sleep(CANCEL_POLL_SECONDS)
        await _check_execution(task_id, organization_id, run_id)


@asynccontextmanager
async def task_execution(
    task_id: UUID | None, organization_id: UUID, run_id: UUID
) -> AsyncGenerator[None]:
    """Own cancellation monitoring for every segment, including HTTP resumes."""
    if task_id is None:
        yield
        return
    await _check_execution(task_id, organization_id, run_id)
    try:
        async with asyncio.TaskGroup() as group:
            watcher = group.create_task(_watch_execution(task_id, organization_id, run_id))
            try:
                yield
            finally:
                watcher.cancel()
    except BaseExceptionGroup as group_error:
        # A task group wraps a body exception even when it is the only error.
        # Keep budget/guardrail stops typed for the runner; retain concurrent
        # failures together instead of hiding a cleanup failure behind Stop.
        if len(group_error.exceptions) == 1:
            raise group_error.exceptions[0] from None
        raise


class ConversationTaskService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.conversations = ConversationService(db)

    async def _topic(
        self, ctx: AuthContext, conversation_id: UUID, *, for_write: bool = False
    ) -> None:
        await self.conversations.get_conversation(
            conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            for_write=for_write,
            turn=True,
            include_favourite=False,
            ctx=ctx,
        )

    async def start(
        self,
        ctx: AuthContext,
        *,
        source_run_id: UUID,
        tool_call_id: str,
        request: StartConversationTask,
        local: LocalTarget | None = None,
        model_profile_id: UUID | None = None,
    ) -> ConversationTaskRead:
        """Start one fresh topic, idempotently for a model's source tool call."""
        source = await run_repo.get_run(self.db, source_run_id, organization_id=ctx.organization_id)
        if (
            source is None
            or source.user_id != ctx.subject_id
            or source.conversation_id is None
            or source.agent_id is None
            or source.agent_version_id is None
        ):
            raise NotFoundError(message="Source conversation run not found")
        if (
            source.surface != RunSurface.WEB.value
            or source.parent_run_id is not None
            or source.is_test
        ):
            raise BadRequestError(
                message="Background topics can be started from a published agent in the console"
            )
        if (
            await task_repo.for_run(self.db, source.id, organization_id=ctx.organization_id)
            is not None
        ):
            raise BadRequestError(
                message="A background task or its result cannot start another background task"
            )
        await self._topic(ctx, source.conversation_id, for_write=True)
        conversation = await self.conversations.get_conversation(
            source.conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            include_favourite=False,
            ctx=ctx,
        )
        if conversation.user_id != ctx.subject_id:
            raise AuthorizationError(message="Start background topics from your own conversation")
        version = await agent_repo.get_version(
            self.db, source.agent_version_id, organization_id=ctx.organization_id
        )
        if version is None:
            raise NotFoundError(message="Source agent version not found")
        spec = AgentSpec.model_validate(version.spec)
        if not any(
            binding.id == "background_tasks" and binding.enabled for binding in spec.capabilities
        ):
            raise AuthorizationError(message="This agent does not allow background topics")
        allowed_agents = {ref.agent_id: ref.agent_version_id for ref in spec.subagents}
        agent_id = request.agent_id or source.agent_id
        if agent_id != source.agent_id and agent_id not in allowed_agents:
            raise AuthorizationError(
                message="That agent is not configured for background delegation"
            )
        await AgentRegistryService(self.db).get_runnable_spec(ctx, agent_id)
        await hold_subject(self.db, LockScope.CONVERSATION_TASKS, ctx.subject_id)
        existing = await task_repo.for_call(
            self.db,
            source_run_id=source.id,
            tool_call_id=tool_call_id,
            organization_id=ctx.organization_id,
        )
        if existing is not None:
            if (
                existing.title,
                existing.prompt,
                existing.agent_id,
                existing.local_target,
                existing.source_model_profile_id,
            ) != (
                request.title,
                request.prompt,
                agent_id,
                None if local is None else local.model_dump(mode="json"),
                model_profile_id,
            ):
                raise AlreadyExistsError(message="That tool call already started a different task")
            return ConversationTaskRead.model_validate(existing)
        if (
            await task_repo.active_count(
                self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
            )
            >= MAX_ACTIVE
        ):
            raise AlreadyExistsError(
                message="Four tasks are already active. Finish or stop one before starting another."
            )
        if local is not None and (local.computer_grant is not None or local.device_id is None):
            raise BadRequestError(
                message="Choose an approved folder and a specific computer before delegating local work"
            )
        topic = await self.conversations.create_conversation(
            ConversationCreate(
                organization_id=ctx.organization_id,
                user_id=ctx.subject_id,
                project_id=conversation.project_id,
                title=request.title,
            )
        )
        await self.conversations.add_message(
            topic.id,
            MessageCreate(
                role="assistant",
                content=f"**Delegated task** · [Source conversation](/chat?id={source.conversation_id})\n\n{request.prompt}",
                agent_id=source.agent_id,
                agent_version_id=source.agent_version_id,
            ),
            organization_id=ctx.organization_id,
        )
        task = ConversationTask(
            id=uuid4(),
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            source_conversation_id=source.conversation_id,
            conversation_id=topic.id,
            source_run_id=source.id,
            source_agent_id=source.agent_id,
            source_version_id=source.agent_version_id,
            agent_id=agent_id,
            version_id=source.agent_version_id
            if agent_id == source.agent_id
            else allowed_agents[agent_id],
            source_model_profile_id=model_profile_id,
            tool_call_id=tool_call_id,
            title=request.title,
            prompt=request.prompt,
            local_target=None if local is None else local.model_dump(mode="json"),
            status="queued",
            delivery="pending",
        )
        await task_repo.add(self.db, task)
        task.job_id = await enqueue(
            self.db,
            RUN_CONVERSATION_TASK,
            ConversationTaskJob(task_id=task.id, organization_id=ctx.organization_id),
            organization_id=ctx.organization_id,
            idempotency_key=f"conversation-task:{task.id}",
        )
        await task_repo.save(self.db, task)
        return ConversationTaskRead.model_validate(task)

    async def authority(self, task: ConversationTask) -> AuthContext:
        ctx = await acting_member(self.db, task.organization_id, str(task.user_id))
        if ctx is None:
            raise AuthorizationError(
                message="The member who started this task can no longer run it"
            )
        await self._topic(ctx, task.source_conversation_id, for_write=True)
        await self._topic(ctx, task.conversation_id, for_write=True)
        registry = AgentRegistryService(self.db)
        await registry.get_runnable_spec(ctx, task.agent_id)
        await registry.get_runnable_spec(ctx, task.source_agent_id)
        return ctx

    async def list_for_member(
        self, ctx: AuthContext, *, conversation_id: UUID | None = None
    ) -> list[ConversationTaskRead]:
        if conversation_id is not None:
            await self._topic(ctx, conversation_id)
        rows = await task_repo.list_for_person(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            conversation_id=conversation_id,
        )
        # Private topics are selected by ownership at both ends. Projects take
        # their current grants, in one bulk resolution for the polling surface.
        project_ids = {
            project_id
            for row in rows
            for project_id in (row.source_project_id, row.project_id)
            if project_id is not None
        }
        visible_projects = (
            set(
                await self.conversations.visible_project_ids(
                    ctx.subject_id, ctx.organization_id, reader=ctx
                )
            )
            if project_ids
            else set()
        )
        return [
            ConversationTaskRead.model_validate(row.task)
            for row in rows
            if all(
                project_id is None or project_id in visible_projects
                for project_id in (row.source_project_id, row.project_id)
            )
        ]

    async def get(self, ctx: AuthContext, task_id: UUID, *, lock: bool = False) -> ConversationTask:
        task = await task_repo.get(self.db, task_id, organization_id=ctx.organization_id, lock=lock)
        if task is None or task.user_id != ctx.subject_id:
            raise NotFoundError(message="Task not found")
        await self._topic(ctx, task.source_conversation_id)
        await self._topic(ctx, task.conversation_id)
        return task

    async def stop(self, ctx: AuthContext, task_id: UUID) -> ConversationTaskRead:
        task = await self.get(ctx, task_id)
        if task.status not in TERMINAL:
            if task.run_id is not None:
                run = await run_repo.get_run(
                    self.db, task.run_id, organization_id=task.organization_id
                )
                if run is not None and run.status in {"awaiting_approval", "awaiting_answer"}:
                    from app.services.agent_runner import AgentRunnerService

                    await AgentRunnerService(self.db).cancel_parked(ctx, run.id)
            task = await self.get(ctx, task_id, lock=True)
            if task.status in TERMINAL:
                return ConversationTaskRead.model_validate(task)
            task.status = "cancelled"
            if task.job_id is not None:
                await job_repo.cancel_queued(self.db, task.job_id)
            task.outcome = "Stopped by the person who started it."
            await self.queue_return(task)
        await task_repo.save(self.db, task)
        return ConversationTaskRead.model_validate(task)

    async def queue_return(self, task: ConversationTask, *, delay_seconds: int = 0) -> None:
        if task.delivery != "pending":
            return
        await enqueue(
            self.db,
            RETURN_CONVERSATION_TASK,
            ConversationTaskJob(task_id=task.id, organization_id=task.organization_id),
            organization_id=task.organization_id,
            run_after=datetime.now(UTC) + timedelta(seconds=delay_seconds),
            dedupe_key=f"task-return:{task.id}",
            concurrency_key=f"task-return:{task.source_conversation_id}",
        )

    async def settle(self, run: AgentRun) -> None:
        task = await task_repo.for_run(self.db, run.id, organization_id=run.organization_id)
        if task is None:
            return
        parked = run.status in {RunStatus.AWAITING_APPROVAL.value, RunStatus.AWAITING_ANSWER.value}
        if task.return_run_id == run.id:
            if task.delivery == "running" and not parked:
                task.delivery = (
                    "delivered" if run.status == RunStatus.COMPLETED.value else "interrupted"
                )
        else:
            if task.status not in TERMINAL:
                task.status = (
                    run.status
                    if run.status
                    in {"completed", "cancelled", "awaiting_approval", "awaiting_answer"}
                    else "failed"
                )
            if not parked:
                await self.queue_return(task)
        await task_repo.save(self.db, task)

    async def interrupted(self, task_id: UUID, *, organization_id: UUID, returning: bool) -> None:
        task = await task_repo.get(self.db, task_id, organization_id=organization_id, lock=True)
        if task is None:
            return
        if returning:
            if task.delivery == "running":
                task.delivery = "interrupted"
        elif task.status not in TERMINAL:
            task.status = "interrupted"
            task.outcome = "The worker stopped. This task may have changed external state; it was not restarted automatically."
            await self.queue_return(task)
        await task_repo.save(self.db, task)

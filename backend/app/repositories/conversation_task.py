"""Tenant-scoped task records and the atomic admission of a turn."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import case, delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.locks import LockScope, hold_subject
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation
from app.db.models.conversation_task import ConversationTask, ConversationTurnClaim


async def get(
    db: AsyncSession, task_id: UUID, *, organization_id: UUID, lock: bool = False
) -> ConversationTask | None:
    query = select(ConversationTask).where(
        ConversationTask.id == task_id, ConversationTask.organization_id == organization_id
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(query)


async def for_call(
    db: AsyncSession, *, source_run_id: UUID, tool_call_id: str, organization_id: UUID
) -> ConversationTask | None:
    return await db.scalar(
        select(ConversationTask).where(
            ConversationTask.organization_id == organization_id,
            ConversationTask.source_run_id == source_run_id,
            ConversationTask.tool_call_id == tool_call_id,
        )
    )


async def for_run(
    db: AsyncSession, run_id: UUID, *, organization_id: UUID
) -> ConversationTask | None:
    return await db.scalar(
        select(ConversationTask)
        .where(
            ConversationTask.organization_id == organization_id,
            or_(ConversationTask.run_id == run_id, ConversationTask.return_run_id == run_id),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


@dataclass(frozen=True)
class ListedTask:
    task: ConversationTask
    source_project_id: UUID | None
    project_id: UUID | None


async def list_for_person(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, conversation_id: UUID | None = None
) -> list[ListedTask]:
    source, topic = aliased(Conversation), aliased(Conversation)
    query = (
        select(ConversationTask, source.project_id, topic.project_id)
        .join(source, source.id == ConversationTask.source_conversation_id)
        .join(topic, topic.id == ConversationTask.conversation_id)
        .where(
            ConversationTask.organization_id == organization_id,
            ConversationTask.user_id == user_id,
            source.user_id == user_id,
            topic.user_id == user_id,
        )
    )
    if conversation_id is not None:
        query = query.where(ConversationTask.source_conversation_id == conversation_id)
    active = case(
        (
            ConversationTask.status.in_(
                ("queued", "running", "awaiting_approval", "awaiting_answer")
            ),
            0,
        ),
        else_=1,
    )
    rows = await db.execute(
        query.order_by(
            active, ConversationTask.created_at.desc(), ConversationTask.id.desc()
        ).limit(50)
    )
    return [
        ListedTask(task, source_project, project) for task, source_project, project in rows.all()
    ]


async def active_count(db: AsyncSession, *, organization_id: UUID, user_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(ConversationTask)
            .where(
                ConversationTask.organization_id == organization_id,
                ConversationTask.user_id == user_id,
                ConversationTask.status.in_(
                    ("queued", "running", "awaiting_approval", "awaiting_answer")
                ),
            )
        )
        or 0
    )


async def add(db: AsyncSession, task: ConversationTask) -> ConversationTask:
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


async def save(db: AsyncSession, task: ConversationTask) -> None:
    db.add(task)
    await db.flush()


async def claim_turn(db: AsyncSession, conversation_id: UUID, *, background: bool) -> UUID | None:
    """Atomically share foreground admission, or exclusively admit a task return."""
    await hold_subject(db, LockScope.CONVERSATION_TURN, conversation_id)
    now = datetime.now(UTC)
    await db.execute(
        delete(ConversationTurnClaim).where(
            ConversationTurnClaim.conversation_id == conversation_id,
            ConversationTurnClaim.expires_at <= now,
        )
    )
    conflict = select(ConversationTurnClaim).where(
        ConversationTurnClaim.conversation_id == conversation_id
    )
    if not background:
        conflict = conflict.where(ConversationTurnClaim.background.is_(True))
    if await db.scalar(select(exists(conflict))):
        return None
    claim_id = uuid4()
    db.add(
        ConversationTurnClaim(
            id=claim_id,
            conversation_id=conversation_id,
            background=background,
            expires_at=now + timedelta(seconds=60),
        )
    )
    await db.flush()
    return claim_id


async def renew_turn(db: AsyncSession, claim_id: UUID) -> bool:
    now = datetime.now(UTC)
    result = await db.execute(
        update(ConversationTurnClaim)
        .where(ConversationTurnClaim.id == claim_id, ConversationTurnClaim.expires_at > now)
        .values(expires_at=now + timedelta(seconds=60))
        .returning(ConversationTurnClaim.id)
    )
    return result.scalar_one_or_none() is not None


async def release_turn(db: AsyncSession, claim_id: UUID) -> None:
    await db.execute(delete(ConversationTurnClaim).where(ConversationTurnClaim.id == claim_id))


async def pending_returns(db: AsyncSession) -> list[ConversationTask]:
    return list(
        (
            await db.scalars(
                select(ConversationTask)
                .join(AgentRun, AgentRun.id == ConversationTask.source_run_id)
                .where(
                    ConversationTask.delivery == "pending",
                    ConversationTask.status.in_(
                        ("completed", "failed", "cancelled", "interrupted")
                    ),
                    AgentRun.status.not_in(("running", "awaiting_approval", "awaiting_answer")),
                )
                .order_by(ConversationTask.created_at)
                .limit(100)
            )
        ).all()
    )


async def unsettled_runs(db: AsyncSession) -> list[tuple[ConversationTask, AgentRun]]:
    rows = await db.execute(
        select(ConversationTask, AgentRun)
        .join(AgentRun, AgentRun.id == ConversationTask.run_id)
        .where(
            ConversationTask.status.in_(("running", "awaiting_approval", "awaiting_answer")),
            AgentRun.status.not_in(("running", "awaiting_approval", "awaiting_answer")),
        )
        .limit(100)
    )
    return [(task, run) for task, run in rows.all()]

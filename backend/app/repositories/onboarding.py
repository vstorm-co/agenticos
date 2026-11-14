"""Scoped start preferences and evidence of real use; no prompts or secrets are stored."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import OrganizationMember
from app.schemas.onboarding import OnboardingUpdate


async def save(db: AsyncSession, *, member: OrganizationMember, data: OnboardingUpdate) -> None:
    if "goal" in data.model_fields_set:
        member.onboarding_goal = data.goal
    if data.dismissed is not None:
        member.onboarding_dismissed_at = datetime.now(UTC) if data.dismissed else None
    if data.completed:
        member.onboarding_completed_at = member.onboarding_completed_at or datetime.now(UTC)
        member.onboarding_dismissed_at = None
    await db.flush()
    await db.refresh(member)


async def latest_result(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> AgentRun | None:
    """Only the person's own surviving chat, excluding automation and publisher fallbacks."""
    result = await db.execute(
        select(AgentRun)
        .join(Conversation, Conversation.id == AgentRun.conversation_id)
        .where(
            AgentRun.organization_id == organization_id,
            AgentRun.user_id == user_id,
            AgentRun.initiated_by_publisher_fallback.is_(False),
            AgentRun.parent_run_id.is_(None),
            AgentRun.status == RunStatus.COMPLETED.value,
            AgentRun.surface == RunSurface.WEB.value,
            Conversation.organization_id == organization_id,
            Conversation.user_id == user_id,
        )
        .order_by(AgentRun.ended_at.desc(), AgentRun.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def has_activity(db: AsyncSession, *, organization_id: UUID, user_id: UUID) -> bool:
    """Recognize existing personal chat use, including history predating agent runs.

    A user's message counts even if its run failed. Empty chats, other people's
    chats and activity in another organization do not establish this membership.
    This is a reason to stop offering onboarding, never evidence of a successful run.
    """
    statement = select(
        select(Conversation.id)
        .where(
            Conversation.organization_id == organization_id,
            Conversation.user_id == user_id,
            select(Message.id)
            .where(Message.conversation_id == Conversation.id, Message.role == "user")
            .exists(),
        )
        .exists()
    )
    return bool(await db.scalar(statement))

"""Scoped start preferences and evidence of real use; no prompts or secrets are stored."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.conversation import Conversation
from app.db.models.organization import OrganizationMember
from app.schemas.onboarding import OnboardingUpdate


async def save(db: AsyncSession, *, member: OrganizationMember, data: OnboardingUpdate) -> None:
    if "goal" in data.model_fields_set:
        member.onboarding_goal = data.goal
    if data.dismissed is not None:
        member.onboarding_dismissed_at = datetime.now(UTC) if data.dismissed else None
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

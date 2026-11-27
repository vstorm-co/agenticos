"""Scoped start preferences and evidence of real use; no prompts or secrets are stored."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.conversation import Conversation, Message
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.organization import Organization, OrganizationMember, OrganizationOnboardingStep
from app.db.models.user import User
from app.schemas.onboarding import OnboardingScopeUpdate, OnboardingUpdate


async def save(db: AsyncSession, *, member: OrganizationMember, data: OnboardingUpdate) -> None:
    if "goal" in data.model_fields_set:
        member.onboarding_goal = data.goal
    if data.dismissed is not None:
        member.onboarding_dismissed_at = datetime.now(UTC) if data.dismissed else None
    if (
        "current_step" in data.model_fields_set
        and member.onboarding_completed_at is None
        and member.onboarding_current_step != data.current_step
    ):
        member.onboarding_current_step = data.current_step
        member.onboarding_updated_at = datetime.now(UTC)
    if data.completed:
        member.onboarding_current_step = None
        if member.onboarding_completed_at is None:
            member.onboarding_completed_at = datetime.now(UTC)
            member.onboarding_updated_at = member.onboarding_completed_at
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


def effective_completed_at(
    member: OrganizationMember, account_completed_at: datetime | None
) -> datetime | None:
    """Honor legacy account completion only for memberships already present then."""
    if member.onboarding_completed_at is not None:
        return member.onboarding_completed_at
    if account_completed_at is not None and member.joined_at <= account_completed_at:
        return account_completed_at
    return None


async def deployment_for_update(db: AsyncSession) -> DeploymentSettings:
    """Create the singleton race-safely, then serialize shared progress writes."""
    await db.execute(insert(DeploymentSettings).values(singleton=True).on_conflict_do_nothing())
    result = await db.execute(
        select(DeploymentSettings).with_for_update().execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def save_shared(
    db: AsyncSession, *, row: DeploymentSettings | Organization, data: OnboardingScopeUpdate
) -> None:
    """The caller holds this scope's row lock; completion is monotonic and idempotent."""
    now = datetime.now(UTC)
    if row.onboarding_completed_at is None:
        if data.completed:
            row.onboarding_completed_at = now
            row.onboarding_current_step = None
            row.onboarding_updated_at = now
        elif (
            "current_step" in data.model_fields_set
            and row.onboarding_current_step != data.current_step
        ):
            if isinstance(row, DeploymentSettings):
                row.onboarding_current_step = TypeAdapter(
                    Literal["admin.deployment"] | None
                ).validate_python(data.current_step)
            else:
                row.onboarding_current_step = TypeAdapter(
                    OrganizationOnboardingStep | None
                ).validate_python(data.current_step)
            row.onboarding_updated_at = now
    await db.flush()
    await db.refresh(row)


async def organization_for_update(db: AsyncSession, organization_id: UUID) -> Organization | None:
    """Refresh a previously read tenant after waiting for another administrator."""
    result = await db.execute(
        select(Organization)
        .where(Organization.id == organization_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def shared_identity(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> tuple[OrganizationMember, User] | None:
    """Recheck and hold live authority after waiting for the shared progress lock."""
    result = await db.execute(
        select(OrganizationMember, User)
        .join(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
        .with_for_update(read=True, of=(OrganizationMember, User))
        .execution_options(populate_existing=True)
    )
    row = result.one_or_none()
    return None if row is None else (row[0], row[1])


async def deployment_actor(db: AsyncSession, user_id: UUID) -> User | None:
    """Hold the current administrator flag until this installation progress write commits."""
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()

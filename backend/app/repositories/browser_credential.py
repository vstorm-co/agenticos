"""Tenant-scoped rows; transaction ownership remains with the service boundary."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.browser_fill import ACTIVE_FILL_STATES, BrowserFillReason, BrowserFillState
from app.db.models.agent_run import AgentRun
from app.db.models.browser_credential import (
    BrowserCredentialAgentGrant,
    BrowserCredentialMemberGrant,
    BrowserCredentialPlan,
    BrowserCredentialPolicy,
)
from app.db.models.conversation import Conversation
from app.db.models.conversation_share import ConversationShare
from app.db.models.organization_secret import OrganizationSecret


async def secret(
    db: AsyncSession, organization_id: UUID, secret_id: UUID, *, locked: bool = False
) -> OrganizationSecret | None:
    query = select(OrganizationSecret).where(
        OrganizationSecret.organization_id == organization_id,
        OrganizationSecret.id == secret_id,
    )
    if locked:
        query = query.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(query)).scalar_one_or_none()


async def private_conversation(
    db: AsyncSession, organization_id: UUID, conversation_id: UUID, user_id: UUID
) -> bool:
    shared = (
        select(ConversationShare.id)
        .where(ConversationShare.conversation_id == Conversation.id)
        .exists()
    )
    return (
        await db.scalar(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.organization_id == organization_id,
                Conversation.user_id == user_id,
                Conversation.project_id.is_(None),
                Conversation.workflow_id.is_(None),
                Conversation.is_archived.is_(False),
                ~shared,
            )
        )
        is not None
    )


async def policy_exists(db: AsyncSession, organization_id: UUID, secret_id: UUID) -> bool:
    return (
        await db.scalar(
            select(BrowserCredentialPolicy.secret_id).where(
                BrowserCredentialPolicy.organization_id == organization_id,
                BrowserCredentialPolicy.secret_id == secret_id,
            )
        )
        is not None
    )


async def policy_ids(db: AsyncSession, organization_id: UUID, secret_ids: list[UUID]) -> set[UUID]:
    if not secret_ids:
        return set()
    return set(
        await db.scalars(
            select(BrowserCredentialPolicy.secret_id).where(
                BrowserCredentialPolicy.organization_id == organization_id,
                BrowserCredentialPolicy.secret_id.in_(secret_ids),
            )
        )
    )


async def granted(
    db: AsyncSession, organization_id: UUID, secret_id: UUID, agent_id: UUID, user_id: UUID
) -> bool:
    return (
        await db.scalar(
            select(BrowserCredentialAgentGrant.secret_id)
            .join(
                BrowserCredentialMemberGrant,
                (
                    BrowserCredentialMemberGrant.organization_id
                    == BrowserCredentialAgentGrant.organization_id
                )
                & (BrowserCredentialMemberGrant.secret_id == BrowserCredentialAgentGrant.secret_id),
            )
            .where(
                BrowserCredentialAgentGrant.organization_id == organization_id,
                BrowserCredentialAgentGrant.secret_id == secret_id,
                BrowserCredentialAgentGrant.agent_id == agent_id,
                BrowserCredentialMemberGrant.user_id == user_id,
            )
        )
        is not None
    )


async def grants(
    db: AsyncSession, organization_id: UUID, secret_id: UUID
) -> tuple[list[UUID], list[UUID]]:
    agents = await db.scalars(
        select(BrowserCredentialAgentGrant.agent_id)
        .where(
            BrowserCredentialAgentGrant.organization_id == organization_id,
            BrowserCredentialAgentGrant.secret_id == secret_id,
        )
        .order_by(BrowserCredentialAgentGrant.agent_id)
    )
    members = await db.scalars(
        select(BrowserCredentialMemberGrant.user_id)
        .where(
            BrowserCredentialMemberGrant.organization_id == organization_id,
            BrowserCredentialMemberGrant.secret_id == secret_id,
        )
        .order_by(BrowserCredentialMemberGrant.user_id)
    )
    return list(agents), list(members)


async def replace_policy(
    db: AsyncSession,
    *,
    organization_id: UUID,
    secret_id: UUID,
    shared: bool,
    agent_ids: tuple[UUID, ...],
    member_ids: tuple[UUID, ...],
) -> None:
    """The caller holds the secret row while rewrapping it and rotating authority."""
    await db.execute(
        delete(BrowserCredentialPolicy).where(
            BrowserCredentialPolicy.organization_id == organization_id,
            BrowserCredentialPolicy.secret_id == secret_id,
        )
    )
    if shared:
        db.add(BrowserCredentialPolicy(organization_id=organization_id, secret_id=secret_id))
        await db.flush()
        db.add_all(
            BrowserCredentialAgentGrant(
                organization_id=organization_id, secret_id=secret_id, agent_id=agent_id
            )
            for agent_id in agent_ids
        )
        db.add_all(
            BrowserCredentialMemberGrant(
                organization_id=organization_id, secret_id=secret_id, user_id=user_id
            )
            for user_id in member_ids
        )
    await db.flush()


async def plan(
    db: AsyncSession, organization_id: UUID, plan_id: UUID, *, locked: bool = False
) -> BrowserCredentialPlan | None:
    query = select(BrowserCredentialPlan).where(
        BrowserCredentialPlan.organization_id == organization_id,
        BrowserCredentialPlan.id == plan_id,
    )
    if locked:
        query = query.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(query)).scalar_one_or_none()


async def lock_run(db: AsyncSession, organization_id: UUID, run_id: UUID) -> None:
    """Serialize short plan transitions before acquiring secret and plan row locks."""
    await db.execute(
        select(AgentRun.id)
        .where(AgentRun.organization_id == organization_id, AgentRun.id == run_id)
        .with_for_update()
    )


async def active_for_view(
    db: AsyncSession, organization_id: UUID, run_id: UUID, call_id: str
) -> BrowserCredentialPlan | None:
    return (
        await db.execute(
            select(BrowserCredentialPlan)
            .where(
                BrowserCredentialPlan.organization_id == organization_id,
                BrowserCredentialPlan.run_id == run_id,
                BrowserCredentialPlan.call_id == call_id,
                BrowserCredentialPlan.state.in_(ACTIVE_FILL_STATES),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def list_for_run(
    db: AsyncSession, organization_id: UUID, run_id: UUID, user_id: UUID
) -> list[BrowserCredentialPlan]:
    rows = await db.scalars(
        select(BrowserCredentialPlan)
        .where(
            BrowserCredentialPlan.organization_id == organization_id,
            BrowserCredentialPlan.run_id == run_id,
            BrowserCredentialPlan.user_id == user_id,
        )
        .order_by(BrowserCredentialPlan.created_at.desc(), BrowserCredentialPlan.id)
        .limit(20)
    )
    return list(rows)


async def submission(
    db: AsyncSession, organization_id: UUID, parent_plan_id: UUID
) -> BrowserCredentialPlan | None:
    return await db.scalar(
        select(BrowserCredentialPlan).where(
            BrowserCredentialPlan.organization_id == organization_id,
            BrowserCredentialPlan.parent_plan_id == parent_plan_id,
        )
    )


async def create(db: AsyncSession, row: BrowserCredentialPlan) -> BrowserCredentialPlan:
    db.add(row)
    await db.flush()
    return row


async def finish(
    db: AsyncSession,
    *,
    organization_id: UUID,
    plan_id: UUID,
    controller_id: UUID,
    attempt_id: UUID,
    state: BrowserFillState,
    reason: BrowserFillReason | None,
    now: datetime,
) -> bool:
    """Only the persisted attempt may settle its claim; a duplicate changes nothing."""
    changed = await db.scalar(
        update(BrowserCredentialPlan)
        .where(
            BrowserCredentialPlan.organization_id == organization_id,
            BrowserCredentialPlan.id == plan_id,
            BrowserCredentialPlan.controller_id == controller_id,
            BrowserCredentialPlan.attempt_id == attempt_id,
            BrowserCredentialPlan.state == BrowserFillState.CLAIMED,
        )
        .values(
            state=state.value, reason_code=None if reason is None else reason.value, finished_at=now
        )
        .returning(BrowserCredentialPlan.id)
    )
    return changed is not None

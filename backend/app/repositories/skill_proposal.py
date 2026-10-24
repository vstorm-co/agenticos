"""Data access for agent-authored skill changes."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.skill_proposal import ProposalStatus, SkillProposal


async def get(
    db: AsyncSession, proposal_id: UUID, *, organization_id: UUID
) -> SkillProposal | None:
    """One proposal, inside its organization.

    Scoped for the same reason every other lookup here is: applying a proposal
    writes a skill, and a skill is instructions every agent bound to it follows.
    """
    result = await db.execute(
        select(SkillProposal).where(
            SkillProposal.id == proposal_id,
            SkillProposal.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_pending_for_skill(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skill_id: UUID | None,
    name: str,
    agent_id: UUID,
) -> SkillProposal | None:
    """The proposal this agent should overwrite instead of duplicating.

    A conversation that edits one skill over three turns should leave one
    proposal behind, not three: a reviewer asked the same question three times
    has been given more work, not more information. Keyed on the skill where
    there is one and on the name where there is not, because a new skill has no
    id until somebody accepts it - and on the agent that proposed it, so one
    agent's newer proposal never replaces another's and takes its attribution.
    """
    statement = select(SkillProposal).where(
        SkillProposal.organization_id == organization_id,
        SkillProposal.status == ProposalStatus.PENDING.value,
        SkillProposal.agent_id == agent_id,
    )
    if skill_id is None:
        statement = statement.where(SkillProposal.skill_id.is_(None), SkillProposal.name == name)
    else:
        statement = statement.where(SkillProposal.skill_id == skill_id)
    result = await db.execute(
        statement.order_by(SkillProposal.created_at.desc(), SkillProposal.id).execution_options(
            populate_existing=True
        )
    )
    return result.scalars().first()


async def list_for_organization(
    db: AsyncSession, *, organization_id: UUID, status: str | None = None
) -> list[SkillProposal]:
    statement = select(SkillProposal).where(SkillProposal.organization_id == organization_id)
    if status is not None:
        statement = statement.where(SkillProposal.status == status)
    result = await db.execute(statement.order_by(SkillProposal.created_at.desc()))
    return list(result.scalars().all())


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skill_id: UUID | None,
    agent_id: UUID | None,
    conversation_id: UUID | None,
    name: str,
    description: str,
    content: str,
    resources: dict[str, Any],
) -> SkillProposal:
    proposal = SkillProposal(
        organization_id=organization_id,
        skill_id=skill_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        name=name,
        description=description,
        content=content,
        resources=resources,
    )
    db.add(proposal)
    await db.flush()
    await db.refresh(proposal)
    return proposal


async def replace_body(
    db: AsyncSession,
    *,
    proposal: SkillProposal,
    description: str,
    content: str,
    resources: dict[str, Any],
    conversation_id: UUID | None,
) -> SkillProposal | None:
    """Rewrite a pending proposal in place, so one edit session is one proposal.

    Its revision moves, so a decision made on what it said before is refused. Only
    while it is pending as read: `None` once a decision or another rewrite changed
    it since, and the caller makes a new proposal instead of writing over that.
    """
    result = await db.execute(
        sql_update(SkillProposal)
        .where(
            SkillProposal.id == proposal.id,
            SkillProposal.organization_id == proposal.organization_id,
            SkillProposal.status == ProposalStatus.PENDING.value,
            SkillProposal.revision == proposal.revision,
        )
        .values(
            description=description,
            content=content,
            resources=resources,
            conversation_id=conversation_id,
            revision=SkillProposal.revision + 1,
        )
        .returning(SkillProposal)
        .execution_options(populate_existing=True)
    )
    return result.scalars().first()


async def annotate(
    db: AsyncSession, *, proposal: SkillProposal, values: dict[str, Any]
) -> SkillProposal:
    """Attach what an evidence-backed proposal carries beyond its body."""
    for field, value in values.items():
        setattr(proposal, field, value)
    await db.flush()
    await db.refresh(proposal)
    return proposal


async def decide_if(
    db: AsyncSession,
    *,
    proposal_id: UUID,
    organization_id: UUID,
    revision: int,
    status: ProposalStatus,
    decided_by: UUID | None,
) -> SkillProposal | None:
    """Decide a proposal only while it is pending at `revision`, or `None` when it is not.

    One conditional update, so of two decisions made at once exactly one changes
    the row - and a decision on a revision a newer run replaced changes nothing.
    """
    result = await db.execute(
        sql_update(SkillProposal)
        .where(
            SkillProposal.id == proposal_id,
            SkillProposal.organization_id == organization_id,
            SkillProposal.status == ProposalStatus.PENDING.value,
            SkillProposal.revision == revision,
        )
        .values(status=status.value, decided_by_user_id=decided_by, decided_at=datetime.now(UTC))
        .returning(SkillProposal)
        .execution_options(populate_existing=True)
    )
    return result.scalars().first()


async def replace_pending(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skill_id: UUID | None,
    name: str,
    agent_id: UUID,
    description: str,
    content: str,
    resources: dict[str, Any],
    conversation_id: UUID | None,
) -> SkillProposal | None:
    """Rewrite the waiting proposal for this skill, or `None` when none is left to rewrite.

    A decision or another rewrite that changed the one read in between sends it
    back to read again, as often as that happens - each miss is somebody else's
    write landing - so turns at once still leave one proposal waiting.
    """
    while True:
        pending = await get_pending_for_skill(
            db, organization_id=organization_id, skill_id=skill_id, name=name, agent_id=agent_id
        )
        if pending is None:
            return None
        rewritten = await replace_body(
            db,
            proposal=pending,
            description=description,
            content=content,
            resources=resources,
            conversation_id=conversation_id,
        )
        if rewritten is not None:
            return rewritten

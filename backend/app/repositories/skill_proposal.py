"""Data access for agent-authored skill changes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
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
    db: AsyncSession, *, organization_id: UUID, skill_id: UUID | None, name: str
) -> SkillProposal | None:
    """The proposal this run should overwrite instead of duplicating.

    A conversation that edits one skill over three turns should leave one
    proposal behind, not three: a reviewer asked the same question three times
    has been given more work, not more information. Keyed on the skill where
    there is one and on the name where there is not, because a new skill has no
    id until somebody accepts it.
    """
    statement = select(SkillProposal).where(
        SkillProposal.organization_id == organization_id,
        SkillProposal.status == ProposalStatus.PENDING.value,
    )
    if skill_id is None:
        statement = statement.where(SkillProposal.skill_id.is_(None), SkillProposal.name == name)
    else:
        statement = statement.where(SkillProposal.skill_id == skill_id)
    result = await db.execute(statement)
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
) -> SkillProposal:
    """Update a pending proposal in place, so one edit session is one proposal."""
    proposal.description = description
    proposal.content = content
    proposal.resources = resources
    proposal.conversation_id = conversation_id
    await db.flush()
    await db.refresh(proposal)
    return proposal


async def decide(
    db: AsyncSession, *, proposal: SkillProposal, status: ProposalStatus, decided_by: UUID | None
) -> SkillProposal:
    proposal.status = status.value
    proposal.decided_by_user_id = decided_by
    proposal.decided_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(proposal)
    return proposal

"""Accepting or discarding what an agent wrote to a skill.

The recording half runs inside a run, with no user watching: it takes what
`skill_workspace.collect_changes` found and stores it. The deciding half runs from
a form, needs `skills:edit`, and is the only path by which an agent's writing
reaches the skill every other agent reads.

Two properties hold the design together.

*A decision is final.* Applying a proposal twice would bump a skill's version
against a body already stored; discarding one that was applied would tell a
reader it never landed. `AlreadyExistsError` on a decided proposal, the same rule
approvals follow.

*Recording never breaks a run.* This is called from the same `finally` that
records what a run cost, so a failure here has to be logged rather than raised -
otherwise a full workspace or a name collision replaces whatever actually
happened to the run.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.skill_proposal import ProposalStatus, SkillProposal
from app.repositories import skill_proposal_repo
from app.services.skill_workspace import SkillChange
from app.services.skills import SkillService

logger = logging.getLogger(__name__)


class SkillProposalService:
    """Records what an agent proposed, and applies what a person accepts."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.skills = SkillService(db)

    # -- written by a run ------------------------------------------------

    async def record(
        self,
        ctx: AuthContext,
        changes: list[SkillChange],
        *,
        agent_id: UUID,
        conversation_id: UUID | None,
    ) -> list[SkillProposal]:
        """Store what a run left different, one proposal per skill.

        A pending proposal for the same skill is overwritten rather than joined
        by a second: three turns of one conversation refining a checklist should
        leave a reviewer one decision, not three versions of the same one.
        """
        recorded: list[SkillProposal] = []
        for change in changes:
            existing = await skill_proposal_repo.get_pending_for_skill(
                self.db,
                organization_id=ctx.organization_id,
                skill_id=change.skill_id,
                name=change.name,
            )
            if existing is not None:
                recorded.append(
                    await skill_proposal_repo.replace_body(
                        self.db,
                        proposal=existing,
                        description=change.description,
                        content=change.content,
                        resources=change.resources,
                        conversation_id=conversation_id,
                    )
                )
                continue
            recorded.append(
                await skill_proposal_repo.create(
                    self.db,
                    organization_id=ctx.organization_id,
                    skill_id=change.skill_id,
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                    name=change.name,
                    description=change.description,
                    content=change.content,
                    resources=change.resources,
                )
            )
        if recorded:
            await record_audit(
                self.db,
                actor_user_id=ctx.subject_id,
                organization_id=ctx.organization_id,
                action="skill.change_proposed",
                target_type="agent",
                target_id=str(agent_id),
                details={"skills": [proposal.name for proposal in recorded]},
            )
        return recorded

    # -- decided by a person ---------------------------------------------

    async def list_proposals(
        self, ctx: AuthContext, *, status: str | None = None
    ) -> list[SkillProposal]:
        return await skill_proposal_repo.list_for_organization(
            self.db, organization_id=ctx.organization_id, status=status
        )

    async def get(self, ctx: AuthContext, proposal_id: UUID) -> SkillProposal:
        proposal = await skill_proposal_repo.get(
            self.db, proposal_id, organization_id=ctx.organization_id
        )
        if proposal is None:
            raise NotFoundError(
                message="Skill change not found", details={"proposal_id": str(proposal_id)}
            )
        return proposal

    async def apply(self, ctx: AuthContext, proposal_id: UUID) -> SkillProposal:
        """Accept a change: write it to the skill, then mark it applied.

        In that order deliberately. If the write fails - a name taken since, the
        skill deleted - the proposal stays pending and the reviewer sees why,
        rather than reading "applied" beside a skill that never moved.

        Raises:
            AlreadyExistsError: If it was already decided.
            NotFoundError: If the proposal is not this organization's.
        """
        proposal = await self.get(ctx, proposal_id)
        self._refuse_second_decision(proposal)

        if proposal.skill_id is None:
            skill = await self.skills.create(
                ctx,
                name=proposal.name,
                description=proposal.description,
                content=proposal.content,
            )
        else:
            skill = await self.skills.update(
                ctx,
                proposal.skill_id,
                {"description": proposal.description, "content": proposal.content},
            )

        if proposal.resources:
            await self.skills.put_resources(
                ctx,
                skill.id,
                [
                    (name, content.encode("utf-8"))
                    for name, content in sorted(proposal.resources.items())
                ],
            )

        decided = await skill_proposal_repo.decide(
            self.db,
            proposal=proposal,
            status=ProposalStatus.APPLIED,
            decided_by=ctx.subject_id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.change_applied",
            target_type="skill",
            target_id=str(skill.id),
            details={"name": skill.name, "proposal_id": str(proposal_id)},
        )
        return decided

    async def discard(self, ctx: AuthContext, proposal_id: UUID) -> SkillProposal:
        """Refuse a change, keeping the record of what was proposed.

        Kept rather than deleted: an agent that keeps proposing the same edit is
        telling somebody something about the skill, and a deleted row is how that
        pattern becomes invisible.
        """
        proposal = await self.get(ctx, proposal_id)
        self._refuse_second_decision(proposal)
        decided = await skill_proposal_repo.decide(
            self.db,
            proposal=proposal,
            status=ProposalStatus.DISCARDED,
            decided_by=ctx.subject_id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.change_discarded",
            target_type="skill",
            target_id=str(proposal.skill_id) if proposal.skill_id else None,
            details={"name": proposal.name, "proposal_id": str(proposal_id)},
        )
        return decided

    @staticmethod
    def _refuse_second_decision(proposal: SkillProposal) -> None:
        if proposal.status != ProposalStatus.PENDING.value:
            raise AlreadyExistsError(
                message=(
                    f"This change was already {proposal.status}. A second decision would "
                    "either apply it twice or overrule whoever decided first."
                ),
                details={"proposal_id": str(proposal.id), "status": proposal.status},
            )

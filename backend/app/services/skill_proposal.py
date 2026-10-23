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

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, ConcurrentChangeError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.skill_proposal import ProposalStatus, SkillProposal
from app.repositories import skill_proposal_repo, skill_repo
from app.schemas.resource_usage import ProposalDecision
from app.schemas.skill import SkillUpdate
from app.schemas.skill_proposal import SkillProposalRead
from app.services import proposal_reach
from app.services.notifications import NotificationService
from app.services.skill_workspace import SkillChange
from app.services.skills import SkillService

logger = logging.getLogger(__name__)


class SkillProposalService:
    """Records what an agent proposed, and applies what a person accepts."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.skills = SkillService(db)

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
            rewritten = await skill_proposal_repo.replace_pending(
                self.db,
                organization_id=ctx.organization_id,
                skill_id=change.skill_id,
                name=change.name,
                agent_id=agent_id,
                description=change.description,
                content=change.content,
                resources=change.resources,
                conversation_id=conversation_id,
            )
            if rewritten is not None:
                recorded.append(rewritten)
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

    async def list_proposals(
        self, ctx: AuthContext, *, status: str | None = None
    ) -> list[SkillProposal]:
        return await skill_proposal_repo.list_for_organization(
            self.db, organization_id=ctx.organization_id, status=status
        )

    async def list_read(
        self, ctx: AuthContext, *, status: str | None = None
    ) -> list[SkillProposalRead]:
        """Every proposal as a reviewer reads it - see :meth:`read`."""
        proposals = await self.list_proposals(ctx, status=status)
        reaches = await self._reaches(ctx, proposals)
        return [await self._readable(ctx, proposal, reaches) for proposal in proposals]

    async def read(self, ctx: AuthContext, proposal_id: UUID) -> SkillProposalRead:
        """One proposal as a reviewer reads it.

        The evidence an assistant cited quotes conversations, so a reviewer
        without `runs:view` gets the run ids and not the words. A waiting change
        to a skill says which agents applying it goes live for, and where.
        """
        proposal = await self.get(ctx, proposal_id)
        return await self._readable(ctx, proposal, await self._reaches(ctx, [proposal]))

    async def _reaches(
        self, ctx: AuthContext, proposals: list[SkillProposal]
    ) -> dict[UUID, list[proposal_reach.Reach]]:
        waiting = sorted(
            {
                proposal.skill_id
                for proposal in proposals
                if proposal.skill_id is not None and proposal.status == ProposalStatus.PENDING.value
            }
        )
        return await proposal_reach.reach(
            self.db, organization_id=ctx.organization_id, kind="skill", resource_ids=waiting
        )

    async def _readable(
        self,
        ctx: AuthContext,
        proposal: SkillProposal,
        reaches: dict[UUID, list[proposal_reach.Reach]],
    ) -> SkillProposalRead:
        read = SkillProposalRead.model_validate(proposal)
        skill_id = proposal.skill_id
        pending = proposal.status == ProposalStatus.PENDING.value
        if skill_id is not None and pending:
            reached, hidden_agents = await proposal_reach.reached(self.db, ctx, reaches[skill_id])
            read = read.model_copy(update={"reaches": reached, "reaches_hidden": hidden_agents})
        if ctx.has(Perm.RUNS_VIEW):
            return read
        hidden = [{"run_id": item.get("run_id"), "quote": None} for item in read.evidence]
        return read.model_copy(update={"evidence": hidden})

    async def get(self, ctx: AuthContext, proposal_id: UUID) -> SkillProposal:
        proposal = await skill_proposal_repo.get(
            self.db, proposal_id, organization_id=ctx.organization_id
        )
        if proposal is None:
            raise NotFoundError(
                message="Skill change not found", details={"proposal_id": str(proposal_id)}
            )
        return proposal

    async def apply(
        self, ctx: AuthContext, proposal_id: UUID, decision: ProposalDecision
    ) -> SkillProposal:
        """Accept a change: mark it applied at the revision read, then write it to the skill.

        One transaction: if the write fails - a name taken since, the skill
        deleted - nothing of it stays, and the proposal is still pending. The
        mark is a conditional update, so of two decisions made at once exactly
        one wins. It goes live at once for every agent whose served version reads
        the skill: their suites are queued with the edit, their owners notified.

        A proposal that records the version it was written against applies only
        while the skill is still at it: a body reviewed against v3 must not
        silently replace a v4 somebody wrote meanwhile.

        Raises:
            AlreadyExistsError: If it was already decided.
            NotFoundError: If the proposal is not this organization's.
            ConcurrentChangeError: If the skill moved past the version it was written
                against, or the proposal since the reviewer read it.
        """
        proposal = await self.get(ctx, proposal_id)
        self._refuse_second_decision(proposal, decision.revision)

        if proposal.skill_id is not None and proposal.base_version is not None:
            current = await self.skills.get(ctx, proposal.skill_id, perm=Perm.SKILLS_EDIT)
            # Locking re-reads the row into `current`: every edit writes the skill
            # row, so an edit or a second apply committed meanwhile is seen, not overwritten.
            await skill_repo.lock(self.db, current.id)
            if current.version != proposal.base_version:
                raise ConcurrentChangeError(
                    message=(
                        f"'{current.name}' changed since this was proposed "
                        f"(v{proposal.base_version}, now v{current.version}). Compare the two "
                        "and edit the skill by hand, or ask the assistant again."
                    ),
                    details={
                        "proposal_id": proposal.id,
                        "base_version": proposal.base_version,
                        "version": current.version,
                    },
                )

        decided = await self._claim(ctx, proposal, decision, ProposalStatus.APPLIED)
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
                SkillUpdate(description=proposal.description, content=proposal.content),
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

        reaches = (
            await proposal_reach.reach(
                self.db, organization_id=ctx.organization_id, kind="skill", resource_ids=[skill.id]
            )
        )[skill.id]
        notifications = NotificationService(self.db)
        for item in reaches:
            await notifications.shared_change_applied(
                agent=item.agent,
                kind="skill",
                name=skill.name,
                occurrence=f"{decided.id}:{decided.revision}",
                actor_user_id=ctx.user_id,
            )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.change_applied",
            target_type="skill",
            target_id=str(skill.id),
            details={
                "name": skill.name,
                "proposal_id": str(proposal_id),
                "revision": decided.revision,
                "agents": sorted(str(item.agent.id) for item in reaches),
            },
        )
        return decided

    async def discard(
        self, ctx: AuthContext, proposal_id: UUID, decision: ProposalDecision
    ) -> SkillProposal:
        """Refuse a change, keeping the record of what was proposed.

        Kept rather than deleted: an agent that keeps proposing the same edit is
        telling somebody something about the skill, and a deleted row is how that
        pattern becomes invisible.
        """
        proposal = await self.get(ctx, proposal_id)
        self._refuse_second_decision(proposal, decision.revision)
        decided = await self._claim(ctx, proposal, decision, ProposalStatus.DISCARDED)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.change_discarded",
            target_type="skill",
            target_id=str(proposal.skill_id) if proposal.skill_id else None,
            details={
                "name": proposal.name,
                "proposal_id": str(proposal_id),
                "revision": decided.revision,
            },
        )
        return decided

    async def _claim(
        self,
        ctx: AuthContext,
        proposal: SkillProposal,
        decision: ProposalDecision,
        status: ProposalStatus,
    ) -> SkillProposal:
        """Decide the proposal if it is still pending at the revision read, or refuse."""
        decided = await skill_proposal_repo.decide_if(
            self.db,
            proposal_id=proposal.id,
            organization_id=ctx.organization_id,
            revision=decision.revision,
            status=status,
            decided_by=ctx.subject_id,
        )
        if decided is None:
            raise _changed(proposal)
        return decided

    @staticmethod
    def _refuse_second_decision(proposal: SkillProposal, revision: int) -> None:
        if proposal.status != ProposalStatus.PENDING.value:
            raise AlreadyExistsError(
                message=(
                    f"This change was already {proposal.status}. A second decision would "
                    "either apply it twice or overrule whoever decided first."
                ),
                details={"proposal_id": str(proposal.id), "status": proposal.status},
            )
        if proposal.revision != revision:
            raise _changed(proposal)


def _changed(proposal: SkillProposal) -> ConcurrentChangeError:
    return ConcurrentChangeError(
        message="The proposal changed since you opened it. Review the new version.",
        details={"proposal_id": proposal.id, "reason": "proposal_changed"},
    )

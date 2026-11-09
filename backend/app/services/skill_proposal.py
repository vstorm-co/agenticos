"""Accepting or discarding what an agent wrote to a skill.

The recording half runs inside a run, with no user watching: it takes what
`skill_workspace.collect_changes` found and stores it. The deciding half runs from
a form, needs `skills:edit`, and is the only path by which an agent's writing
reaches the skill every other agent reads.

Two properties hold the design together.

*A decision is final.* Applying a proposal twice would save a second version of
a body already stored; discarding one that was applied would tell a
reader it never landed. `AlreadyExistsError` on a decided proposal, the same rule
approvals follow.

*Recording never breaks a run.* This is called from the same `finally` that
records what a run cost, so a failure here has to be logged rather than raised -
otherwise a full workspace or a name collision replaces whatever actually
happened to the run.

*Whoever reads a proposal is whoever may decide it.* A proposal carries the full
body an agent wrote for a skill, so it is listed and read only by a caller who may
edit that skill - grants included, as `resolve_access` decides - and is reported
as missing to anyone else (#2422). A proposal for a new skill has no skill to ask,
and is anyone's who holds `skills:edit`, which the routes already require.
"""

import logging
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.skill import Skill
from app.db.models.skill_proposal import ProposalStatus, SkillProposal
from app.db.models.skill_version import SkillFork, SkillVersionSource
from app.repositories import skill_proposal_repo, skill_repo, skill_version_repo
from app.schemas.resource_usage import ProposalDecision
from app.schemas.skill import SkillUpdate
from app.schemas.skill_proposal import SkillProposalRead
from app.services import proposal_reach
from app.services.access import SKILL, accessible_ids, resolve_access
from app.services.notifications import NotificationService
from app.services.skill_versions import SkillVersionService, manifest_of
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
        forks: Mapping[UUID, UUID] | None = None,
    ) -> list[SkillProposal]:
        """Store what a run left different, one proposal per skill.

        `forks` names the fork the run was bound to for each skill it read from one.
        A fork with no versions of its own serves the main version it started from, so
        the version alone cannot say the change is for the fork.

        A pending proposal for the same skill is overwritten rather than joined
        by a second: three turns of one conversation refining a checklist should
        leave a reviewer one decision, not three versions of the same one.
        """
        bases = await skill_version_repo.get_versions(
            self.db,
            {change.base_version_id for change in changes if change.base_version_id},
            organization_id=ctx.organization_id,
        )
        recorded: list[SkillProposal] = []
        for change in changes:
            base = bases.get(change.base_version_id) if change.base_version_id else None
            fork_id = (forks or {}).get(change.skill_id) or (None if base is None else base.fork_id)
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
                base_version=change.base_version,
                base_version_id=change.base_version_id,
                fork_id=fork_id,
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
                    base_version=change.base_version,
                    base_version_id=change.base_version_id,
                    fork_id=fork_id,
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
        """The proposals the caller could decide: those for skills they may edit.

        A proposal for a skill nobody has written yet is one anybody who may create
        skills could accept - the route's own `skills:edit` - so it is listed for them.
        """
        if not ctx.has(Perm.RUNS_VIEW):
            return []
        proposals = await skill_proposal_repo.list_for_organization(
            self.db, organization_id=ctx.organization_id, status=status
        )
        skills = await skill_repo.get_many(
            self.db,
            sorted({proposal.skill_id for proposal in proposals if proposal.skill_id is not None}),
            organization_id=ctx.organization_id,
        )
        editable = await accessible_ids(
            self.db, ctx, list(skills.values()), Perm.SKILLS_EDIT, resource_type=SKILL
        )
        return [
            proposal
            for proposal in proposals
            if proposal.skill_id is None or proposal.skill_id in editable
        ]

    async def list_read(
        self, ctx: AuthContext, *, status: str | None = None
    ) -> list[SkillProposalRead]:
        """Every proposal as a reviewer reads it - see :meth:`read`."""
        proposals = await self.list_proposals(ctx, status=status)
        reaches = await self._reaches(ctx, proposals)
        return [await self._readable(ctx, proposal, reaches) for proposal in proposals]

    async def read(self, ctx: AuthContext, proposal_id: UUID) -> SkillProposalRead:
        """One proposal as a reviewer reads it.

        The proposed text can repeat conversations, so reading it requires
        `runs:view` even when explicit evidence quotes are absent. A waiting change
        to a skill says which agents applying it goes live for, and where.
        """
        proposal = await self.get(ctx, proposal_id)
        return await self._readable(ctx, proposal, await self._reaches(ctx, [proposal]))

    async def _reaches(
        self, ctx: AuthContext, proposals: list[SkillProposal]
    ) -> dict[UUID, list[proposal_reach.Reach]]:
        """For each waiting proposal, the agents on the line it would change."""
        waiting = [
            proposal
            for proposal in proposals
            if proposal.skill_id is not None and proposal.status == ProposalStatus.PENDING.value
        ]
        by_proposal: dict[UUID, list[proposal_reach.Reach]] = {}
        for fork_id in dict.fromkeys(proposal.fork_id for proposal in waiting):
            on_line = [proposal for proposal in waiting if proposal.fork_id == fork_id]
            found = await proposal_reach.reach(
                self.db,
                organization_id=ctx.organization_id,
                kind="skill",
                resource_ids=sorted(
                    {proposal.skill_id for proposal in on_line if proposal.skill_id}
                ),
                fork_id=fork_id,
            )
            for proposal in on_line:
                assert proposal.skill_id is not None, "only proposals for a skill wait here"
                by_proposal[proposal.id] = found[proposal.skill_id]
        return by_proposal

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
            reached, hidden_agents = await proposal_reach.reached(
                self.db, ctx, reaches[proposal.id]
            )
            read = read.model_copy(update={"reaches": reached, "reaches_hidden": hidden_agents})
        return read

    async def get(self, ctx: AuthContext, proposal_id: UUID) -> SkillProposal:
        """One proposal the caller could decide - see :meth:`list_proposals`.

        Raises:
            NotFoundError: No such proposal in the organization, or one for a skill
                the caller may not edit - which they may not learn exists.
        """
        proposal = await skill_proposal_repo.get(
            self.db, proposal_id, organization_id=ctx.organization_id
        )
        if proposal is None or not await self._may_decide(ctx, proposal):
            raise NotFoundError(
                message="Skill change not found", details={"proposal_id": str(proposal_id)}
            )
        if not ctx.has(Perm.RUNS_VIEW):
            raise AuthorizationError(message="Reading assistant suggestions requires runs:view")
        return proposal

    async def _may_decide(self, ctx: AuthContext, proposal: SkillProposal) -> bool:
        if proposal.skill_id is None:
            return True
        skill = await skill_repo.get(
            self.db, proposal.skill_id, organization_id=ctx.organization_id
        )
        return skill is not None and await resolve_access(
            self.db, ctx, skill, Perm.SKILLS_EDIT, resource_type=SKILL
        )

    async def apply(
        self,
        ctx: AuthContext,
        proposal_id: UUID,
        decision: ProposalDecision,
        *,
        checked: bool = False,
    ) -> SkillProposal:
        """Accept a change: mark it applied at the revision read, then write it to the skill.

        One transaction: if the write fails - a name taken since, the skill
        deleted - nothing of it stays, and the proposal is still pending. The
        mark is a conditional update, so of two decisions made at once exactly
        one wins. It goes live at once for every agent whose served version reads
        the skill: their suites are queued with the edit, their owners notified.

        A proposal applies only while the skill is still at the version it was
        written against: a body reviewed against v3 must not silently replace a v4
        somebody wrote meanwhile.

        A change to an existing skill goes live only through a check of it on
        every agent of its line: `decision.check_id` names that check, and the
        change is applied by it, under its rule. `checked` is the check itself
        applying the change.

        Raises:
            AlreadyExistsError: If it was already decided.
            NotFoundError: If the proposal is not this organization's.
            ConcurrentChangeError: If the skill moved past the version it was written
                against, or the proposal since the reviewer read it.
            BadRequestError: A change to a skill with no check of it, or one whose
                check does not allow applying it as it stands.
        """
        proposal = await self.get(ctx, proposal_id)
        self._refuse_second_decision(proposal, decision.revision)
        if proposal.skill_id is not None and not checked:
            from app.schemas.skill_check import SkillCheckApply
            from app.services.skill_check import SkillCheckService

            if decision.check_id is None:
                raise refused_field(
                    "check_id", "Check this change on the agents of its line before applying it"
                )
            checks = SkillCheckService(self.db)
            check = await checks.passed_for(ctx, proposal, decision.check_id)
            await checks.apply(ctx, check.skill_id, check.id, SkillCheckApply())
            return await self.get(ctx, proposal_id)

        source = version_source(proposal)
        fork = None
        if proposal.skill_id is not None:
            current = await self.skills.get(ctx, proposal.skill_id, perm=Perm.SKILLS_EDIT)
            # Locking re-reads the row into `current`: every edit writes the skill
            # row, so an edit or a second apply committed meanwhile is seen, not overwritten.
            await skill_repo.lock(self.db, current.id)
            if proposal.fork_id is not None:
                fork = await skill_version_repo.get_fork(
                    self.db,
                    proposal.fork_id,
                    organization_id=ctx.organization_id,
                    skill_id=current.id,
                    lock=True,
                )
                assert fork is not None, "a proposal goes with its fork"
                SkillVersionService.refuse_archived(fork)
            if _moved_since(proposal, current, SkillVersionService.line_latest(current, fork)):
                raise ConcurrentChangeError(
                    message=(
                        f"'{current.name}' changed since this was proposed "
                        f"(now v{current.version}). Compare the two and edit the skill "
                        "by hand, or ask again."
                    ),
                    details={
                        "proposal_id": proposal.id,
                        "base_version": proposal.base_version,
                        "version": current.version,
                    },
                )

        decided = await self._claim(ctx, proposal, decision, ProposalStatus.APPLIED)
        files = [
            (name, content.encode("utf-8")) for name, content in sorted(proposal.resources.items())
        ]
        removed: list[str] = []
        if fork is None and proposal.skill_id is not None and replaces_files(proposal):
            removed = await self.skills.drop_resources(
                ctx, proposal.skill_id, keep=set(proposal.resources)
            )
        if fork is not None:
            skill = current
            await self._apply_to_fork(ctx, fork, proposal, source)
        elif proposal.skill_id is None:
            skill = await self.skills.create(
                ctx,
                name=proposal.name,
                description=proposal.description,
                content=proposal.content,
                source=None if files else source,
                proposal_id=proposal.id,
            )
        else:
            skill = await self.skills.update(
                ctx,
                proposal.skill_id,
                SkillUpdate(description=proposal.description, content=proposal.content),
                source=None if files or removed else source,
                proposal_id=proposal.id,
            )
        if files and fork is None:
            await self.skills.put_resources(
                ctx, skill.id, files, source=source, proposal_id=proposal.id
            )
        elif removed:
            await self.skills.record_files(ctx, skill.id, source=source, proposal_id=proposal.id)

        reaches = (
            await proposal_reach.reach(
                self.db,
                organization_id=ctx.organization_id,
                kind="skill",
                resource_ids=[skill.id],
                fork_id=None if fork is None else fork.id,
            )
        )[skill.id]
        notifications = NotificationService(self.db)
        for item in reaches:
            await notifications.shared_change_applied(
                agent=item.agent,
                kind="skill",
                resource=skill,
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

    async def _apply_to_fork(
        self,
        ctx: AuthContext,
        fork: SkillFork,
        proposal: SkillProposal,
        source: SkillVersionSource,
    ) -> None:
        """Write the change as the fork's next version: its files are the fork's newest
        version's, with the ones the change wrote replaced or added."""
        latest_id = fork.latest_version_id or fork.base_version_id
        latest = (
            await skill_version_repo.get_versions(
                self.db, [latest_id], organization_id=ctx.organization_id
            )
        )[latest_id]
        manifest, bodies = manifest_of(
            (
                name,
                latest.resources[name]["description"] if name in latest.resources else None,
                content,
            )
            for name, content in sorted(proposal.resources.items())
        )
        await skill_version_repo.put_files(
            self.db, organization_id=ctx.organization_id, skill_id=fork.skill_id, bodies=bodies
        )
        await SkillVersionService(self.db).record_fork(
            ctx,
            fork,
            description=proposal.description,
            content=proposal.content,
            resources={**latest.resources, **manifest},
            source=source,
            proposal_id=proposal.id,
        )

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
        if proposal.skill_id is not None:
            from app.services.skill_check import SkillCheckService

            await SkillCheckService(self.db).stop_for_proposal(ctx, proposal.skill_id, proposal_id)
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

    async def mark_forked(
        self, ctx: AuthContext, proposal_id: UUID, decision: ProposalDecision
    ) -> SkillProposal:
        """Decide a change that a check made a fork of instead of applying it to its line."""
        proposal = await self.get(ctx, proposal_id)
        self._refuse_second_decision(proposal, decision.revision)
        decided = await self._claim(ctx, proposal, decision, ProposalStatus.APPLIED)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.change_forked",
            target_type="skill",
            target_id=str(proposal.skill_id) if proposal.skill_id else None,
            details={"proposal_id": str(proposal_id), "revision": decided.revision},
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


def replaces_files(proposal: SkillProposal) -> bool:
    """Whether the proposal's files are the skill's whole set rather than changes to it.

    A library update carries every file the bundled skill has, so one it dropped goes.
    """
    return proposal.source == SkillVersionSource.LIBRARY.value


def version_source(proposal: SkillProposal) -> SkillVersionSource:
    """What a version made from this proposal says it came from."""
    if proposal.source is not None:
        return SkillVersionSource(proposal.source)
    if proposal.authoring_request_id is None:
        return SkillVersionSource.WORKSPACE
    return SkillVersionSource.IMPROVE


def _moved_since(proposal: SkillProposal, skill: Skill, latest: UUID | None) -> bool:
    """Whether the line is no longer at the version the proposal was written against.

    A proposal with only a version number was written before skills were versioned,
    against a text that versioning recorded as v1 only if it was still current - in
    which case the migration gave it that version. Any other one has moved. A
    workspace change recorded before proposals kept a version at all has only its
    age to go by, so any write to the skill after it was proposed counts as moving it.
    """
    if proposal.base_version_id is not None:
        return proposal.base_version_id != latest
    if proposal.base_version is not None:
        return True
    return skill.updated_at is not None and skill.updated_at > proposal.created_at


def _changed(proposal: SkillProposal) -> ConcurrentChangeError:
    return ConcurrentChangeError(
        message="The proposal changed since you opened it. Review the new version.",
        details={"proposal_id": proposal.id, "reason": "proposal_changed"},
    )

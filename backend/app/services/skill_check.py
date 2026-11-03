"""Checking a skill change on every agent of the line it would change.

A skill is shared, so a change is judged on every agent that would read it: on
main, the agents following main's newest version; on a fork, the fork's agents.
Agents pinned to an older version, and the agents of other lines, are not run -
the change does not reach them.

**What runs.** Each agent's published version answers twice per question, with
the line's newest text and with the candidate, through the ordinary paired eval
run with the candidate served in place of the stored text. First the skill's
own test questions, the same set on every agent; then the agent's own: in a
`quick` check at most four of its dataset's questions on which its newest answer
loaded the skill, in a `thorough` one its whole dataset. A change to the
description is always thorough, because the description decides when every
agent opens the skill at all.

**Who pays and who may.** Each agent's share is its own eval runs, billed to that
agent like any other. Starting needs `runs:view` and edit access to the skill.
An agent the person may not run is not run: it stays `unknown`, named if they
may see it and counted if not, and they acknowledge it before applying. There is
no path by which a check runs an agent its starter could not.

**Deciding.** `skill_check_rules` reads the result. A person then applies the
change - pinning first, in the same transaction, the agents it made worse to the
version they read now - makes it a fork for the agents it helped, or discards it.
"""

import hashlib
import json
import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.skills import SkillBody, SkillBodyFile
from app.core.exceptions import (
    AlreadyExistsError,
    AppException,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.dataset import Dataset
from app.db.models.eval_run import EvalRunPurpose, EvalRunStatus
from app.db.models.skill import Skill
from app.db.models.skill_check import (
    AgentState,
    CheckMode,
    CheckOutcome,
    CheckSource,
    CheckStatus,
    CheckVerdict,
    SampleKind,
    SkillCheck,
    SkillCheckAgent,
    UnknownReason,
)
from app.db.models.skill_proposal import ProposalStatus, SkillProposal
from app.db.models.skill_version import SkillFork, SkillVersion, SkillVersionSource
from app.repositories import (
    agent_repo,
    conversation_repo,
    dataset_repo,
    eval_run_repo,
    skill_check_repo,
    skill_proposal_repo,
    skill_repo,
    skill_version_repo,
)
from app.schemas.dataset import AnswerAs, DatasetCreate, DatasetRead
from app.schemas.eval_run import EvalRunRequest, ProposalCheckRecord
from app.schemas.resource_usage import ProposalDecision
from app.schemas.skill_check import (
    AgentRef,
    CandidateText,
    CheckStage,
    LineRef,
    SkillCheckAgentRead,
    SkillCheckApplied,
    SkillCheckApply,
    SkillCheckEstimate,
    SkillCheckFork,
    SkillCheckForked,
    SkillCheckList,
    SkillCheckRead,
    SkillCheckStart,
    SkillTestSetStart,
    SkillUpdateCheck,
    StageKind,
)
from app.schemas.skill_version import (
    SkillBindingChange,
    SkillForkCreate,
    SkillVersionCreate,
    VersionRef,
)
from app.services import skill_check_rules as rules
from app.services.access import AGENT, DATASET, accessible_ids
from app.services.api_key import job_context
from app.services.background_jobs import enqueue
from app.services.dataset import DatasetService
from app.services.eval_run import EvalRunService
from app.services.improvement_states import CheckResult
from app.services.skill_agents import LineAgent, SkillAgentService
from app.services.skill_versions import SkillVersionService, manifest_of

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(hours=24)
"""How long a check may run before the sweep ends it: an eval run is minutes, a day is lost."""

TEST_SET_FROM_EVIDENCE = 12
"""How many recent answers a skill's first test questions are made from."""

_SETTLED_RUNS = (EvalRunStatus.COMPLETED, EvalRunStatus.CANCELLED, EvalRunStatus.FAILED)


@dataclass(frozen=True)
class Candidate:
    """The text a check measures, and what it was written against."""

    description: str
    content: str
    resources: tuple[SkillBodyFile, ...] | None = None

    def body(self) -> SkillBody:
        return SkillBody(
            description=self.description, content=self.content, resources=self.resources
        )

    def digest(self) -> str:
        document = {
            "description": self.description,
            "content": self.content,
            "resources": None
            if self.resources is None
            else [[item.name, item.description, item.content] for item in self.resources],
        }
        return hashlib.sha256(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class Stage:
    kind: StageKind
    dataset: Dataset
    case_ids: list[UUID] | None = None


@dataclass
class Planned:
    """One agent of the line as the check would run it."""

    agent: Agent
    agent_version: int
    via_specialist: str | None
    stages: list[Stage] = field(default_factory=list)
    sample: SampleKind | None = None
    unknown: UnknownReason | None = None
    expected: Decimal = Decimal(0)
    at_most: Decimal = Decimal(0)


@dataclass(frozen=True)
class Plan:
    skill: Skill
    fork: SkillFork | None
    base: SkillVersion
    candidate: Candidate
    mode: CheckMode
    description_changed: bool
    agents: list[Planned]
    org_remaining: Decimal | None
    proposal: SkillProposal | None
    excluded: tuple[UUID, ...] = ()
    skill_set_case_ids: list[UUID] | None = None
    served: tuple[SkillBodyFile, ...] | None = None
    agent_id: UUID | None = None
    candidate_version_id: UUID | None = None


def _proposal_candidate(proposal: SkillProposal) -> Candidate:
    files = (
        tuple(
            SkillBodyFile(name=name, description=None, content=text)
            for name, text in sorted(proposal.resources.items())
        )
        if proposal.resources
        else None
    )
    return Candidate(proposal.description, proposal.content, files)


def _proposal_digest(proposal: SkillProposal) -> str:
    """The digest a check of this proposal records, so a later decision can tell it apart."""
    return _proposal_candidate(proposal).digest()


class SkillCheckService:
    """Plan, run, read and decide checks of a skill change."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.versions = SkillVersionService(db)
        self.agents = SkillAgentService(db)
        self.evals = EvalRunService(db)
        self.datasets = DatasetService(db)

    async def _line(
        self, ctx: AuthContext, skill: Skill, fork_id: UUID | None
    ) -> tuple[SkillFork | None, SkillVersion]:
        fork = None
        if fork_id is not None:
            fork = await skill_version_repo.get_fork(
                self.db, fork_id, organization_id=ctx.organization_id, skill_id=skill.id
            )
            if fork is None:
                raise refused_field("fork_id", "This skill has no such fork")
            SkillVersionService.refuse_archived(fork)
        latest = SkillVersionService.line_latest(skill, fork)
        assert latest is not None, "every line serves a version"
        base = await skill_version_repo.get_version(
            self.db, latest, organization_id=ctx.organization_id, skill_id=skill.id
        )
        assert base is not None, "a line's newest version exists"
        return fork, base

    async def _candidate(
        self, ctx: AuthContext, skill: Skill, data: SkillCheckStart
    ) -> tuple[Candidate, SkillProposal | None, UUID | None]:
        """The text to check, the proposal it is, and the fork that proposal is for."""
        if data.candidate is not None:
            return _from_text(data.candidate), None, data.fork_id
        assert data.proposal_id is not None, "a start names a text or a proposal"
        proposal = await skill_proposal_repo.get(
            self.db, data.proposal_id, organization_id=ctx.organization_id
        )
        if (
            proposal is None
            or proposal.skill_id != skill.id
            or proposal.status != ProposalStatus.PENDING.value
        ):
            raise NotFoundError(
                message="No change to this skill is waiting", details={"skill_id": skill.id}
            )
        if proposal.fork_id != data.fork_id:
            raise refused_field("fork_id", "The proposal is for another line of this skill")
        return _proposal_candidate(proposal), proposal, proposal.fork_id

    async def _served(
        self, candidate: Candidate, base: SkillVersion
    ) -> tuple[SkillBodyFile, ...] | None:
        """The files a candidate is served with: the line's, with its own replacing or added.

        The same files applying it writes, so the check measures what would ship.
        """
        if candidate.resources is None:
            return None
        files = {
            name: SkillBodyFile(name=name, description=entry["description"], content="")
            for name, entry in base.resources.items()
        }
        for name, content in (await self.versions.files_of(base)).items():
            files[name] = SkillBodyFile(
                name=name, description=files[name].description, content=content
            )
        # Main keeps a replaced file's description (`put_resources`); a fork's version
        # takes the change's files as written (`_apply_to_fork`).
        keep = base.fork_id is None
        for item in candidate.resources:
            kept = files[item.name].description if keep and item.name in files else None
            files[item.name] = SkillBodyFile(name=item.name, description=kept, content=item.content)
        return tuple(files[name] for name in sorted(files))

    async def _test_set(self, ctx: AuthContext, skill: Skill) -> Dataset | None:
        return await dataset_repo.for_skill(self.db, skill.id, organization_id=ctx.organization_id)

    async def _plan(
        self,
        ctx: AuthContext,
        skill_id: UUID,
        data: SkillCheckStart,
        *,
        only: Sequence[UUID] | None = None,
        holdout: Mapping[UUID, Collection[UUID]] | None = None,
        exclude_conversations: Sequence[UUID] = (),
        pinned: UUID | None = None,
    ) -> Plan:
        """What a check would run, refusing what could not; nothing is written.

        `pinned` checks main's newest version on that one agent, against the version
        it is pinned to, in place of a change to a line; `data` gives only the mode.

        `only` narrows the agents to those named, for a caller checking one pinned
        agent's update rather than a line. `holdout` limits a dataset, by its id, to
        the questions a session keeps aside for measuring; `exclude_conversations`
        leaves out the questions taken from the conversations a change learned from.
        """
        if not ctx.has(Perm.RUNS_VIEW):
            raise AuthorizationError(
                message="Checking a skill change needs runs:view",
                details={"permission": "runs:view"},
            )
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_EDIT)
        proposal: SkillProposal | None = None
        fork: SkillFork | None = None
        target: SkillVersion | None = None
        if pinned is None:
            candidate, proposal, fork_id = await self._candidate(ctx, skill, data)
            fork, base = await self._line(ctx, skill, fork_id)
            if proposal is not None and proposal.base_version_id != base.id:
                raise ConcurrentChangeError(
                    message=(
                        f"'{skill.name}' changed since this was proposed. Compare the two and "
                        "edit the skill by hand, or ask again."
                    ),
                    details={"proposal_id": proposal.id, "version": base.number},
                )
            users = await self.agents.line_agents(skill, None if fork is None else fork.id)
            if only is not None:
                users = [user for user in users if user.agent.id in set(only)]
            served = await self._served(candidate, base)
        else:
            user, base, target = await self._pinned(ctx, skill, pinned)
            candidate = await self._version_candidate(target)
            users, served = [user], candidate.resources
        changed = candidate.description != base.description
        mode = CheckMode.THOROUGH if changed else data.mode
        runnable = await accessible_ids(
            self.db, ctx, [user.agent for user in users], Perm.AGENTS_RUN, resource_type=AGENT
        )
        test_set = await self._test_set(ctx, skill)
        body = {
            skill.id: SkillBody(
                description=candidate.description, content=candidate.content, resources=served
            )
        }
        planned: list[Planned] = []
        org_remaining: Decimal | None = None
        changed_words = rules.changed_words(
            f"{base.description}\n{base.content}", f"{candidate.description}\n{candidate.content}"
        )
        for user in users:
            row = Planned(user.agent, user.agent_version, user.via_specialist)
            planned.append(row)
            if user.agent.id not in runnable:
                row.unknown = UnknownReason.NO_ACCESS
                continue
            row.stages = await self._stages(
                ctx, skill, user, test_set, mode, changed_words, row, holdout or {}
            )
            if not row.stages:
                row.unknown = UnknownReason.NO_QUESTIONS
                continue
            remaining: Decimal | None = None
            for stage in row.stages:
                try:
                    quote = await self.evals.estimate(
                        ctx,
                        user.agent.id,
                        _request(stage, user.agent_version),
                        purpose=EvalRunPurpose.GATE,
                        candidate_skills=body,
                        exclude_conversations=exclude_conversations,
                    )
                except AuthorizationError, NotFoundError:
                    row.unknown = UnknownReason.NO_ACCESS
                    break
                row.expected += quote.total_usd
                row.at_most += quote.total_usd + quote.rerun_ceiling_usd
                remaining = quote.agent_remaining_usd
                org_remaining = quote.org_remaining_usd
            if row.unknown is None and remaining is not None and row.at_most > remaining:
                row.unknown = UnknownReason.NO_BUDGET
        return Plan(
            skill=skill,
            fork=fork,
            base=base,
            candidate=candidate,
            mode=mode,
            description_changed=changed,
            agents=planned,
            org_remaining=org_remaining,
            proposal=proposal,
            excluded=tuple(exclude_conversations),
            skill_set_case_ids=_kept(test_set, holdout or {}),
            served=served,
            agent_id=pinned,
            candidate_version_id=None if target is None else target.id,
        )

    async def _pinned(
        self, ctx: AuthContext, skill: Skill, agent_id: UUID
    ) -> tuple[LineAgent, SkillVersion, SkillVersion]:
        """The pinned agent as it runs, the version it stays on, and main's newest.

        Raises:
            NotFoundError: The caller may not see the agent.
            BadRequestError: The agent's served version does not stay on a main version.
            AlreadyExistsError: It stays on main's newest version already.
        """
        agent = await self.agents.registry.get(ctx, agent_id)
        found = await self.agents.pinned_agent(skill, agent.id)
        if isinstance(found, str):
            raise BadRequestError(
                message=(
                    f"'{skill.name}' is pinned in the specialist '{found}' of '{agent.name}'. "
                    "Change its version in the agent's Builder."
                ),
                details={"agent_id": agent.id, "skill_id": skill.id, "specialist": found},
            )
        if found is None:
            raise BadRequestError(
                message=f"'{agent.name}' is not pinned to a version of '{skill.name}'",
                details={"agent_id": agent.id, "skill_id": skill.id},
            )
        user, number = found
        pinned = (
            await skill_version_repo.get_by_numbers(
                self.db,
                organization_id=ctx.organization_id,
                skill_id=skill.id,
                fork_id=None,
                numbers={number},
            )
        ).get(number)
        assert pinned is not None, "a published binding names a version the skill has"
        assert skill.latest_version_id is not None, "every skill has a main version"
        if pinned.id == skill.latest_version_id:
            raise AlreadyExistsError(
                message=f"'{agent.name}' reads the newest version of '{skill.name}' already",
                details={"agent_id": agent.id, "version": pinned.number},
            )
        newest = await skill_version_repo.get_version(
            self.db, skill.latest_version_id, organization_id=ctx.organization_id, skill_id=skill.id
        )
        assert newest is not None, "a skill's newest version exists"
        return user, pinned, newest

    async def _version_candidate(self, version: SkillVersion) -> Candidate:
        """A stored version as a check serves it: its text and every one of its files."""
        bodies = await self.versions.files_of(version)
        return Candidate(
            version.description,
            version.content,
            tuple(
                SkillBodyFile(
                    name=name,
                    description=version.resources[name]["description"],
                    content=bodies[name],
                )
                for name in sorted(bodies)
            ),
        )

    async def _stages(
        self,
        ctx: AuthContext,
        skill: Skill,
        user: LineAgent,
        test_set: Dataset | None,
        mode: CheckMode,
        changed_words: set[str],
        row: Planned,
        holdout: Mapping[UUID, Collection[UUID]],
    ) -> list[Stage]:
        """The skill's questions, then the agent's own, as far as each exists."""
        stages: list[Stage] = []
        kept = _kept(test_set, holdout)
        if test_set is not None and test_set.case_count and kept != []:
            stages.append(Stage("skill_set", test_set, kept))
        own = await dataset_repo.for_agent(
            self.db, user.agent.id, organization_id=ctx.organization_id
        )
        dataset = next((item for item in own if item.case_count and item.skill_id is None), None)
        if dataset is None:
            if mode is CheckMode.QUICK:
                row.sample = SampleKind.SKILL_SET_ONLY
            return stages
        if mode is CheckMode.THOROUGH:
            own_kept = _kept(dataset, holdout)
            if own_kept != []:
                stages.append(Stage("dataset", dataset, own_kept))
            return stages
        picked = await self._sample(
            ctx, skill, user.agent.id, dataset, changed_words, holdout.get(dataset.id)
        )
        if picked:
            row.sample = SampleKind.OWN_QUESTIONS
            stages.append(Stage("dataset_sample", dataset, picked))
        else:
            row.sample = SampleKind.SKILL_SET_ONLY
        return stages

    async def _sample(
        self,
        ctx: AuthContext,
        skill: Skill,
        agent_id: UUID,
        dataset: Dataset,
        changed_words: set[str],
        allowed: Collection[UUID] | None = None,
    ) -> list[UUID]:
        loaded = await skill_check_repo.loaded_cases(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            dataset_id=dataset.id,
            skill_id=skill.id,
        )
        if not loaded:
            return []
        version = await dataset_repo.get_version(
            self.db, dataset.id, dataset.latest_version, organization_id=ctx.organization_id
        )
        assert version is not None, "a dataset with cases has its latest version"
        texts = {
            case.case_id: case.input
            for case in await dataset_repo.list_cases(
                self.db, version.id, organization_id=ctx.organization_id, limit=None
            )
            if case.anonymised_at is None
        }
        return rules.sample(
            [
                rules.SampleCandidate(item.case_id, texts[item.case_id], item.answered_at)
                for item in loaded
                if item.case_id in texts and (allowed is None or item.case_id in allowed)
            ],
            changed_words,
        )

    async def _estimate(self, ctx: AuthContext, plan: Plan) -> SkillCheckEstimate:
        rows = [
            SkillCheckAgent(
                agent_id=item.agent.id,
                agent_version=item.agent_version,
                via_specialist=item.via_specialist,
                state=AgentState.UNKNOWN.value if item.unknown else AgentState.QUEUED.value,
                unknown_reason=item.unknown.value if item.unknown else None,
                sample=item.sample.value if item.sample else None,
                sample_case_ids=_sampled(item),
                dataset_id=_own_dataset(item),
                expected_usd=item.expected,
                at_most_usd=item.at_most,
            )
            for item in plan.agents
        ]
        stages = {item.agent.id: item.stages for item in plan.agents}
        expected, at_most = _priced(plan.agents)
        reads, hidden, hidden_unknown = await self._agent_reads(ctx, rows, stages)
        return SkillCheckEstimate(
            line=_line_ref(plan.fork),
            base_version=VersionRef(
                id=plan.base.id, number=plan.base.number, fork_id=plan.base.fork_id
            ),
            mode=plan.mode,
            description_changed=plan.description_changed,
            agents=reads,
            hidden=hidden,
            hidden_unknown=hidden_unknown,
            expected_usd=expected,
            at_most_usd=at_most,
            org_remaining_usd=plan.org_remaining,
            affordable=plan.org_remaining is None or at_most <= plan.org_remaining,
        )

    async def estimate(
        self,
        ctx: AuthContext,
        skill_id: UUID,
        data: SkillCheckStart,
        *,
        only: Sequence[UUID] | None = None,
        holdout: Mapping[UUID, Collection[UUID]] | None = None,
        exclude_conversations: Sequence[UUID] = (),
    ) -> SkillCheckEstimate:
        """What a check would run on each agent, and what it would cost, as `start` takes it."""
        plan = await self._plan(
            ctx,
            skill_id,
            data,
            only=only,
            holdout=holdout,
            exclude_conversations=exclude_conversations,
        )
        return await self._estimate(ctx, plan)

    async def estimate_update(
        self, ctx: AuthContext, skill_id: UUID, agent_id: UUID, data: SkillUpdateCheck
    ) -> SkillCheckEstimate:
        """What checking main's newest version on one pinned agent would run and cost."""
        plan = await self._plan(ctx, skill_id, _update_start(data), pinned=agent_id)
        return await self._estimate(ctx, plan)

    async def start_update(
        self, ctx: AuthContext, skill_id: UUID, agent_id: UUID, data: SkillUpdateCheck
    ) -> SkillCheckRead:
        """Check main's newest version on one agent pinned to an older one.

        Its result is accepted by moving the agent to main - see `checked_update` -
        never by changing the skill. Raises as :meth:`start` does, and as `_pinned`.
        """
        return await self.start(
            ctx, skill_id, _update_start(data), source=CheckSource.CATCH_UP, pinned=agent_id
        )

    async def start(
        self,
        ctx: AuthContext,
        skill_id: UUID,
        data: SkillCheckStart,
        *,
        source: CheckSource | None = None,
        only: Sequence[UUID] | None = None,
        holdout: Mapping[UUID, Collection[UUID]] | None = None,
        exclude_conversations: Sequence[UUID] = (),
        pinned: UUID | None = None,
    ) -> SkillCheckRead:
        """Write a check and start each agent's first stage.

        Raises:
            AuthorizationError: The caller lacks `runs:view`.
            NotFoundError: The skill, the proposal or the fork is not theirs to change.
            BadRequestError: The organization's remaining budget cannot cover the
                check at its most, or no agent of the line can be checked.
        """
        plan = await self._plan(
            ctx,
            skill_id,
            data,
            only=only,
            holdout=holdout,
            exclude_conversations=exclude_conversations,
            pinned=pinned,
        )
        expected, at_most = _priced(plan.agents)
        if plan.org_remaining is not None and at_most > plan.org_remaining:
            raise BadRequestError(
                message="The organization's budget left this month cannot cover this check",
                details={
                    "reason": "budget",
                    "at_most_usd": str(at_most),
                    "remaining_usd": str(plan.org_remaining),
                },
            )
        if plan.proposal is not None:
            for open_check in await skill_check_repo.open_for_proposal(
                self.db, plan.proposal.id, organization_id=ctx.organization_id
            ):
                # A finished check the line has moved past can no longer be decided, so
                # it does not stand in the way of checking the change again.
                if open_check.candidate_hash == plan.candidate.digest() and (
                    open_check.status == CheckStatus.RUNNING.value
                    or await self._drift(ctx, plan.skill, open_check) is None
                ):
                    raise AlreadyExistsError(
                        message="This change is checked already",
                        details={"check_id": open_check.id},
                    )
        if not any(item.unknown is None for item in plan.agents):
            raise BadRequestError(
                message="No agent of this line can be checked",
                details={"reason": "nothing_to_check", "skill_id": plan.skill.id},
            )
        check = await skill_check_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            check=SkillCheck(
                skill_id=plan.skill.id,
                fork_id=None if plan.fork is None else plan.fork.id,
                base_version_id=plan.base.id,
                agent_id=plan.agent_id,
                candidate_version_id=plan.candidate_version_id,
                candidate_description=plan.candidate.description,
                candidate_content=plan.candidate.content,
                candidate_resources=_resources_json(plan.served),
                candidate_hash=plan.candidate.digest(),
                description_changed=plan.description_changed,
                mode=plan.mode.value,
                source=(
                    source
                    or (CheckSource.PROPOSAL if plan.proposal is not None else CheckSource.MANUAL)
                ).value,
                proposal_id=None if plan.proposal is None else plan.proposal.id,
                excluded_conversation_ids=list(plan.excluded),
                skill_set_case_ids=plan.skill_set_case_ids,
                status=CheckStatus.RUNNING.value,
                expected_usd=expected,
                at_most_usd=at_most,
                created_by_user_id=ctx.user_id,
            ),
        )
        rows: list[SkillCheckAgent] = []
        for item in plan.agents:
            row = SkillCheckAgent(
                check_id=check.id,
                agent_id=item.agent.id,
                agent_version=item.agent_version,
                via_specialist=item.via_specialist,
                state=AgentState.UNKNOWN.value if item.unknown else AgentState.RUNNING.value,
                unknown_reason=item.unknown.value if item.unknown else None,
                sample=item.sample.value if item.sample else None,
                sample_case_ids=_sampled(item),
                dataset_id=_own_dataset(item),
                fixed=0,
                broken=0,
                held_out=0,
                fixed_confirmed=0,
                regressions_confirmed=0,
                noisy=False,
                expected_usd=item.expected,
                at_most_usd=item.at_most,
            )
            rows.append(row)
        await skill_check_repo.add_agents(self.db, organization_id=ctx.organization_id, rows=rows)
        for item, row in zip(plan.agents, rows, strict=True):
            if item.unknown is None:
                await self._run_stage(ctx, check, row, item.stages[0])
        await self._settle(check)
        return await self.read(ctx, skill_id, check.id)

    async def _run_stage(
        self, ctx: AuthContext, check: SkillCheck, row: SkillCheckAgent, stage: Stage
    ) -> None:
        """Start one stage of one agent; an agent whose run cannot start is unknown."""
        assert row.agent_version is not None, "only a published agent is run"
        try:
            run = await self.evals.start(
                ctx,
                row.agent_id,
                _request(stage, row.agent_version),
                purpose=EvalRunPurpose.GATE,
                candidate_skills={check.skill_id: _candidate_of(check).body()},
                exclude_conversations=check.excluded_conversation_ids,
                proposal_check=ProposalCheckRecord(
                    kind="skill",
                    base_version=row.agent_version,
                    suggestions=1,
                    skill_check_id=check.id,
                ),
            )
        except AppException as refused:
            logger.info(
                "skill_check_stage_refused",
                extra={"check_id": str(check.id), "agent_id": str(row.agent_id)},
            )
            reason = (
                UnknownReason.NO_BUDGET
                if refused.status_code == 402
                else UnknownReason.NO_ACCESS
                if isinstance(refused, (AuthorizationError, NotFoundError))
                else UnknownReason.FAILED
            )
            await skill_check_repo.update_agent(
                self.db,
                row=row,
                values={"state": AgentState.UNKNOWN.value, "unknown_reason": reason.value},
            )
            return
        column = "skill_set_run_id" if stage.kind == "skill_set" else "dataset_run_id"
        await skill_check_repo.update_agent(
            self.db, row=row, values={column: run.id, "state": AgentState.RUNNING.value}
        )

    async def advance(self, check_id: UUID, organization_id: UUID) -> None:
        """Move each agent on once its current stage's run has settled; finish when all have.

        Runs in the worker, as the person who started the check: a check whose
        starter may no longer act stops with its unfinished agents unknown.
        """
        check = await skill_check_repo.get(
            self.db, check_id, organization_id=organization_id, lock=True
        )
        if check is None or check.status != CheckStatus.RUNNING.value:
            return
        ctx = await job_context(
            self.db,
            organization_id=organization_id,
            user_id=check.created_by_user_id,
            api_key_id=None,
        )
        if check.created_at < datetime.now(UTC) - STALE_AFTER:
            await self._expire(check, ctx)
            return
        rows = await skill_check_repo.list_agents(
            self.db, [check.id], organization_id=organization_id
        )
        for row in rows:
            if row.state != AgentState.RUNNING.value:
                continue
            if ctx is None:
                await self._unknown(row, UnknownReason.FAILED)
                continue
            await self._advance_agent(ctx, check, row)
        await self._settle(check)

    async def _advance_agent(
        self, ctx: AuthContext, check: SkillCheck, row: SkillCheckAgent
    ) -> None:
        current = row.dataset_run_id or row.skill_set_run_id
        assert current is not None, "a running agent has a run"
        run = await eval_run_repo.get(self.db, current, organization_id=ctx.organization_id)
        if run is None or EvalRunStatus(run.status) not in _SETTLED_RUNS:
            return
        if run.status != EvalRunStatus.COMPLETED.value:
            await self._unknown(row, UnknownReason.FAILED)
            return
        try:
            await self._carry_on(ctx, check, row, current)
        except AuthorizationError, NotFoundError:
            # The starter may no longer read these runs or this agent: what they show
            # stays unread, and the agent is one nobody could check.
            await self._unknown(row, UnknownReason.NO_ACCESS)

    async def _carry_on(
        self, ctx: AuthContext, check: SkillCheck, row: SkillCheckAgent, current: UUID
    ) -> None:
        if row.dataset_run_id is None:
            first = await self._stage_result(ctx, current)
            stage = _next_stage(row, CheckMode(check.mode))
            if rules.stage_state(first) is not AgentState.WORSE and stage is not None:
                dataset = await dataset_repo.get(
                    self.db, stage[0], organization_id=ctx.organization_id
                )
                if dataset is not None:
                    await self._run_stage(ctx, check, row, Stage(stage[1], dataset, stage[2]))
                    return
        await self._judge(ctx, row)

    async def _stage_result(self, ctx: AuthContext, run_id: UUID) -> rules.StageResult:
        comparison = await self.evals.compare(ctx, run_id)
        mine, theirs = comparison.candidate_summary, comparison.baseline_summary
        return rules.StageResult(
            check=CheckResult(
                comparable=comparison.baseline is not None and comparison.verdict != "invalid",
                incomplete=mine.incomplete + (theirs.incomplete if theirs else 0),
                ungraded=mine.ungraded + (theirs.ungraded if theirs else 0),
                crashed=mine.crashed + (theirs.crashed if theirs else 0),
                regressions_confirmed=comparison.regressions_confirmed,
                fixed_confirmed=comparison.fixed_confirmed,
                candidate_pass_rate=mine.pass_rate,
                baseline_pass_rate=None if theirs is None else theirs.pass_rate,
            ),
            fixed_unconfirmed=comparison.fixed_unconfirmed,
            regressions_unconfirmed=comparison.regressions_unconfirmed,
            compared=comparison.compared,
        )

    async def _judge(self, ctx: AuthContext, row: SkillCheckAgent) -> None:
        """An agent's result from every stage it ran."""
        results = [
            await self._stage_result(ctx, run_id)
            for run_id in (row.skill_set_run_id, row.dataset_run_id)
            if run_id is not None
        ]
        state = rules.combined([rules.stage_state(result) for result in results])
        await skill_check_repo.update_agent(
            self.db,
            row=row,
            values={
                "state": state.value,
                "unknown_reason": UnknownReason.INCONCLUSIVE.value
                if state is AgentState.UNKNOWN
                else None,
                "fixed": sum(r.check.fixed_confirmed + r.fixed_unconfirmed for r in results),
                "broken": sum(
                    r.check.regressions_confirmed + r.regressions_unconfirmed for r in results
                ),
                "held_out": sum(r.compared for r in results),
                "fixed_confirmed": sum(r.check.fixed_confirmed for r in results),
                "regressions_confirmed": sum(r.check.regressions_confirmed for r in results),
                "noisy": any(rules.noisy(result) for result in results),
            },
        )

    async def _unknown(self, row: SkillCheckAgent, reason: UnknownReason) -> None:
        await skill_check_repo.update_agent(
            self.db,
            row=row,
            values={"state": AgentState.UNKNOWN.value, "unknown_reason": reason.value},
        )

    async def _settle(self, check: SkillCheck) -> None:
        """Finish a check once every agent has a result."""
        rows = await skill_check_repo.list_agents(
            self.db, [check.id], organization_id=check.organization_id
        )
        states = [AgentState(row.state) for row in rows]
        if not all(state.settled for state in states):
            return
        await skill_check_repo.update(
            self.db,
            row=check,
            values={
                "status": CheckStatus.DONE.value,
                "verdict": rules.verdict(states).value,
                "finished_at": datetime.now(UTC),
            },
        )

    async def sweep(self, *, limit: int = 50) -> int:
        """Queue one advance per running check, so one that fails rolls back alone."""
        from app.worker import jobs

        found = await skill_check_repo.running(self.db, limit=limit)
        for organization_id, check_id in found:
            await enqueue(
                self.db,
                jobs.ADVANCE_SKILL_CHECK,
                jobs.AdvanceSkillCheck(organization_id=organization_id, check_id=check_id),
                organization_id=organization_id,
                dedupe_key=f"{check_id}:sweep",
                dedupe_active=True,
            )
        return len(found)

    async def _expire(self, check: SkillCheck, ctx: AuthContext | None) -> None:
        """End a check whose agents never settled: their runs are stopped where the starter
        may still stop them, the agents are unknown, and the check is decided on."""
        unsettled = [
            row
            for row in await skill_check_repo.list_agents(
                self.db, [check.id], organization_id=check.organization_id
            )
            if not AgentState(row.state).settled
        ]
        if ctx is not None:
            await self._stop_runs(ctx, unsettled)
        for row in unsettled:
            await self._unknown(row, UnknownReason.FAILED)
        await self._settle(check)

    async def after_run(self, organization_id: UUID, eval_run_id: UUID) -> None:
        """Queue the check an eval run belonged to, once the run has settled."""
        from app.worker import jobs

        row = await skill_check_repo.agent_for_run(
            self.db, eval_run_id, organization_id=organization_id
        )
        if row is not None:
            await enqueue(
                self.db,
                jobs.ADVANCE_SKILL_CHECK,
                jobs.AdvanceSkillCheck(organization_id=organization_id, check_id=row.check_id),
                organization_id=organization_id,
                dedupe_key=f"{row.check_id}:{eval_run_id}",
            )

    async def _check(
        self, ctx: AuthContext, skill_id: UUID, check_id: UUID, *, lock: bool = False
    ) -> SkillCheck:
        check = await skill_check_repo.get(
            self.db, check_id, organization_id=ctx.organization_id, skill_id=skill_id, lock=lock
        )
        if check is None:
            raise NotFoundError(message="Check not found", details={"check_id": check_id})
        return check

    async def read(self, ctx: AuthContext, skill_id: UUID, check_id: UUID) -> SkillCheckRead:
        """One check as the caller may see it. Needs `runs:view` and `skills:view`."""
        await self._readable_skill(ctx, skill_id)
        check = await self._check(ctx, skill_id, check_id)
        [read] = await self._reads(ctx, [check])
        return read

    async def list_checks(
        self, ctx: AuthContext, skill_id: UUID, *, fork_id: UUID | None, skip: int, limit: int
    ) -> SkillCheckList:
        """A line's checks, newest first."""
        await self._readable_skill(ctx, skill_id)
        checks, total = await skill_check_repo.list_for_skill(
            self.db,
            organization_id=ctx.organization_id,
            skill_id=skill_id,
            fork_id=fork_id,
            skip=skip,
            limit=limit,
        )
        return SkillCheckList(items=await self._reads(ctx, checks), total=total)

    async def _readable_skill(self, ctx: AuthContext, skill_id: UUID) -> Skill:
        if not ctx.has(Perm.RUNS_VIEW):
            raise AuthorizationError(
                message="Reading a skill check needs runs:view",
                details={"permission": "runs:view"},
            )
        return await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)

    async def _reads(self, ctx: AuthContext, checks: Sequence[SkillCheck]) -> list[SkillCheckRead]:
        rows = await skill_check_repo.list_agents(
            self.db, [check.id for check in checks], organization_id=ctx.organization_id
        )
        by_check: dict[UUID, list[SkillCheckAgent]] = {}
        for row in rows:
            by_check.setdefault(row.check_id, []).append(row)
        reads: list[SkillCheckRead] = []
        for check in checks:
            mine = by_check.get(check.id, [])
            fork = (
                None
                if check.fork_id is None
                else await skill_version_repo.get_fork(
                    self.db,
                    check.fork_id,
                    organization_id=ctx.organization_id,
                    skill_id=check.skill_id,
                )
            )
            base = await skill_version_repo.get_version(
                self.db,
                check.base_version_id,
                organization_id=ctx.organization_id,
                skill_id=check.skill_id,
            )
            assert base is not None, "a check's base version goes with the check"
            stages = await self._stored_stages(ctx, check, mine)
            agents, hidden, hidden_unknown = await self._agent_reads(ctx, mine, stages)
            status = CheckStatus(check.status)
            verdict = None if check.verdict is None else CheckVerdict(check.verdict)
            reads.append(
                SkillCheckRead(
                    id=check.id,
                    skill_id=check.skill_id,
                    source=CheckSource(check.source),
                    agent_id=check.agent_id,
                    candidate_version_id=check.candidate_version_id,
                    status=status,
                    verdict=verdict,
                    warnings=["within_noise"]
                    if any(row.state == AgentState.WITHIN_NOISE.value or row.noisy for row in mine)
                    else [],
                    outcomes=(
                        rules.update_outcomes(verdict)
                        if check.agent_id is not None
                        else rules.outcomes(verdict, fork=check.fork_id is not None)
                    )
                    if status is CheckStatus.DONE and verdict is not None
                    else [],
                    outcome=None if check.outcome is None else CheckOutcome(check.outcome),
                    proposal_id=check.proposal_id,
                    applied_version_id=check.applied_version_id,
                    created_at=check.created_at,
                    finished_at=check.finished_at,
                    line=_line_ref(fork),
                    base_version=VersionRef(id=base.id, number=base.number, fork_id=base.fork_id),
                    mode=CheckMode(check.mode),
                    description_changed=check.description_changed,
                    agents=agents,
                    hidden=hidden,
                    hidden_unknown=hidden_unknown,
                    expected_usd=check.expected_usd,
                    at_most_usd=check.at_most_usd,
                    org_remaining_usd=None,
                    affordable=True,
                )
            )
        return reads

    async def _stored_stages(
        self, ctx: AuthContext, check: SkillCheck, rows: Sequence[SkillCheckAgent]
    ) -> dict[UUID, list[Stage]]:
        """Each agent's stages as the check ran them, read back from its rows."""
        skill = await skill_repo.get(self.db, check.skill_id, organization_id=ctx.organization_id)
        test_set = None if skill is None else await self._test_set(ctx, skill)
        ids = {row.dataset_id for row in rows if row.dataset_id is not None}
        datasets = {
            dataset.id: dataset
            for dataset_id in ids
            if (
                dataset := await dataset_repo.get(
                    self.db, dataset_id, organization_id=ctx.organization_id
                )
            )
        }
        stages: dict[UUID, list[Stage]] = {}
        for row in rows:
            mine: list[Stage] = []
            if row.skill_set_run_id is not None and test_set is not None:
                mine.append(Stage("skill_set", test_set, check.skill_set_case_ids))
            own = datasets.get(row.dataset_id) if row.dataset_id else None
            if own is not None and (
                row.dataset_run_id is not None or row.state in ("queued", "running")
            ):
                kind: StageKind = (
                    "dataset" if check.mode == CheckMode.THOROUGH.value else "dataset_sample"
                )
                mine.append(Stage(kind, own, row.sample_case_ids))
            stages[row.agent_id] = mine
        return stages

    async def _agent_reads(
        self,
        ctx: AuthContext,
        rows: Sequence[SkillCheckAgent],
        stages: dict[UUID, list[Stage]],
    ) -> tuple[list[SkillCheckAgentRead], int, int]:
        agents = await agent_repo.get_many(
            self.db, sorted({row.agent_id for row in rows}), organization_id=ctx.organization_id
        )
        visible = await accessible_ids(
            self.db, ctx, list(agents.values()), Perm.AGENTS_VIEW, resource_type=AGENT
        )
        datasets = {stage.dataset.id: stage.dataset for found in stages.values() for stage in found}
        readable = await accessible_ids(
            self.db, ctx, list(datasets.values()), Perm.DATASETS_VIEW, resource_type=DATASET
        )
        reads: list[SkillCheckAgentRead] = []
        hidden = hidden_unknown = 0
        for row in rows:
            agent = agents.get(row.agent_id)
            if agent is None or agent.id not in visible:
                hidden += 1
                hidden_unknown += row.state == AgentState.UNKNOWN.value
                continue
            reads.append(
                SkillCheckAgentRead(
                    agent=AgentRef(id=agent.id, name=agent.name),
                    via_specialist=row.via_specialist,
                    agent_version=row.agent_version,
                    state=AgentState(row.state),
                    unknown_reason=None
                    if row.unknown_reason is None
                    else UnknownReason(row.unknown_reason),
                    sample=None if row.sample is None else SampleKind(row.sample),
                    stages=[
                        CheckStage(
                            kind=stage.kind,
                            dataset_id=stage.dataset.id,
                            dataset_name=stage.dataset.name
                            if stage.dataset.id in readable
                            else None,
                            cases=len(stage.case_ids)
                            if stage.case_ids is not None
                            else stage.dataset.case_count,
                            eval_run_id=row.skill_set_run_id
                            if stage.kind == "skill_set"
                            else row.dataset_run_id,
                        )
                        for stage in stages.get(row.agent_id, [])
                    ],
                    fixed=row.fixed or 0,
                    broken=row.broken or 0,
                    held_out=row.held_out or 0,
                    fixed_confirmed=row.fixed_confirmed or 0,
                    regressions_confirmed=row.regressions_confirmed or 0,
                    noisy=bool(row.noisy),
                    expected_usd=row.expected_usd,
                    at_most_usd=row.at_most_usd,
                )
            )
        return reads, hidden, hidden_unknown

    async def cancel(self, ctx: AuthContext, skill_id: UUID, check_id: UUID) -> SkillCheckRead:
        """Stop a running check; the runs it started are cancelled with it."""
        await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_EDIT)
        check = await self._check(ctx, skill_id, check_id, lock=True)
        if check.status != CheckStatus.RUNNING.value:
            raise AlreadyExistsError(
                message="The check is not running", details={"check_id": check.id}
            )
        await self._stop_runs(
            ctx,
            await skill_check_repo.list_agents(
                self.db, [check.id], organization_id=ctx.organization_id
            ),
        )
        await skill_check_repo.update(
            self.db,
            row=check,
            values={"status": CheckStatus.CANCELLED.value, "finished_at": datetime.now(UTC)},
        )
        return await self.read(ctx, skill_id, check.id)

    async def _stop_runs(self, ctx: AuthContext, rows: Sequence[SkillCheckAgent]) -> None:
        """Cancel the eval runs of these agents still going, so they stop spending."""
        for row in rows:
            for run_id in (row.skill_set_run_id, row.dataset_run_id):
                if run_id is not None:
                    run = await eval_run_repo.get(
                        self.db, run_id, organization_id=ctx.organization_id
                    )
                    if run is not None and EvalRunStatus(run.status) not in _SETTLED_RUNS:
                        await self.evals.cancel(ctx, run_id)

    async def stop_for_proposal(self, ctx: AuthContext, skill_id: UUID, proposal_id: UUID) -> None:
        """Stop the running checks of a proposal withdrawn before anybody decided it."""
        for found in await skill_check_repo.open_for_proposal(
            self.db, proposal_id, organization_id=ctx.organization_id
        ):
            if found.status == CheckStatus.RUNNING.value:
                await self.cancel(ctx, skill_id, found.id)

    async def _decidable(
        self, ctx: AuthContext, skill_id: UUID, check_id: UUID, outcome: CheckOutcome | None
    ) -> tuple[Skill, SkillCheck, list[SkillCheckAgent]]:
        """A finished, undecided check that offers `outcome`, measured on the line as it is.

        Locks the skill, then the fork, then the check - the order every write to a
        skill's versions takes - so two decisions on one skill queue instead of
        deadlocking. `outcome` `None` asks only for a decidable check.

        Raises:
            NotFoundError: The skill or the check is not the caller's to change.
            AlreadyExistsError: It was decided already.
            ConcurrentChangeError: It is still running; the line, an agent of it or
                the proposal it checked changed since.
            BadRequestError: The outcome is not one this result offers.
        """
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_EDIT)
        await skill_repo.lock(self.db, skill.id)
        found = await self._check(ctx, skill_id, check_id)
        if found.fork_id is not None:
            await skill_version_repo.get_fork(
                self.db,
                found.fork_id,
                organization_id=ctx.organization_id,
                skill_id=skill.id,
                lock=True,
            )
        check = await self._check(ctx, skill_id, check_id, lock=True)
        status = CheckStatus(check.status)
        if status.decided:
            raise AlreadyExistsError(
                message="This check was already decided", details={"check_id": check.id}
            )
        if status is not CheckStatus.DONE or check.verdict is None:
            raise ConcurrentChangeError(
                message="The check has not finished", details={"check_id": check.id}
            )
        if outcome is not None and outcome not in (
            rules.update_outcomes(CheckVerdict(check.verdict))
            if check.agent_id is not None
            else rules.outcomes(CheckVerdict(check.verdict), fork=check.fork_id is not None)
        ):
            raise BadRequestError(
                message="This check's result does not offer that",
                details={"outcome": outcome.value, "verdict": check.verdict},
            )
        drift = await self._drift(ctx, skill, check)
        if drift is not None:
            raise drift
        await self._refuse_rewritten(ctx, check)
        rows = await skill_check_repo.list_agents(
            self.db, [check.id], organization_id=ctx.organization_id
        )
        return skill, check, rows

    async def _drift(
        self, ctx: AuthContext, skill: Skill, check: SkillCheck
    ) -> ConcurrentChangeError | None:
        """Why the line is no longer the one a check measured, or `None` when it still is:
        a newer version, or agents that started or stopped following it or were published
        again since."""
        if check.agent_id is not None:
            return await self._update_drift(ctx, skill, check)
        fork, base = await self._line(ctx, skill, check.fork_id)
        if base.id != check.base_version_id:
            return ConcurrentChangeError(
                message=(
                    f"'{skill.name}' changed since this was checked. Check the change again "
                    "against the newest version."
                ),
                details={"check_id": check.id, "version": base.number},
            )
        rows = await skill_check_repo.list_agents(
            self.db, [check.id], organization_id=ctx.organization_id
        )
        measured = {row.agent_id: row.agent_version for row in rows}
        now = {
            user.agent.id: (user.agent, user.agent_version)
            for user in await self.agents.line_agents(skill, None if fork is None else fork.id)
        }
        changed = [
            agent for agent_id, (agent, version) in now.items() if measured.get(agent_id) != version
        ]
        gone = await agent_repo.get_many(
            self.db,
            [agent_id for agent_id in measured if agent_id not in now],
            organization_id=ctx.organization_id,
        )
        changed += list(gone.values())
        if not changed:
            return None
        visible = await accessible_ids(self.db, ctx, changed, Perm.AGENTS_VIEW, resource_type=AGENT)
        return ConcurrentChangeError(
            message=(
                "The agents of this line changed since the check: some started or stopped "
                "following it, or were published again. Check the change again."
            ),
            details={
                "agents": [agent.name for agent in changed if agent.id in visible],
                "hidden": sum(agent.id not in visible for agent in changed),
            },
        )

    async def _update_drift(
        self, ctx: AuthContext, skill: Skill, check: SkillCheck
    ) -> ConcurrentChangeError | None:
        """Why a pinned agent's update no longer measures what it would do, or `None`.

        Takes the agent's lock after the check's, so nothing publishes or promotes it
        between this reading and the move. Accepting publishes from the agent's newest
        version, so a newer one than its served version is a change nobody measured.
        """
        assert check.agent_id is not None
        await agent_repo.get(
            self.db, check.agent_id, organization_id=ctx.organization_id, for_update=True
        )
        found = await self.agents.pinned_agent(skill, check.agent_id)
        newest = await agent_repo.newest_version(
            self.db, agent_id=check.agent_id, organization_id=ctx.organization_id
        )
        rows = await skill_check_repo.list_agents(
            self.db, [check.id], organization_id=ctx.organization_id
        )
        measured = {row.agent_id: row.agent_version for row in rows}
        if (
            isinstance(found, tuple)
            and newest is not None
            and newest.version == measured.get(check.agent_id)
        ):
            user, number = found
            pinned = await skill_version_repo.get_by_numbers(
                self.db,
                organization_id=ctx.organization_id,
                skill_id=skill.id,
                fork_id=None,
                numbers={number},
            )
            if (
                pinned.get(number) is not None
                and pinned[number].id == check.base_version_id
                and measured.get(user.agent.id) == user.agent_version
                and skill.latest_version_id == check.candidate_version_id
            ):
                return None
        return ConcurrentChangeError(
            message=(
                f"The agent or '{skill.name}' changed since this was checked: it was published "
                "or moved again, or main has a newer version. Check the update again."
            ),
            details={"check_id": check.id},
        )

    async def checked_update(
        self,
        ctx: AuthContext,
        skill_id: UUID,
        agent_id: UUID,
        check_id: UUID,
        *,
        acknowledged: bool,
    ) -> SkillCheck:
        """The finished check that lets this pinned agent move to main's newest version.

        Locks as :meth:`_decidable` does; the caller moves the agent and then records
        the decision with :meth:`record_decision`.

        Raises:
            NotFoundError: The skill or the check is not the caller's to change.
            BadRequestError: The check is of another agent or of a line's change, the
                update made the agent worse, or an unknown result was not acknowledged.
            ConcurrentChangeError: It is running, or the agent or main moved since.
            AlreadyExistsError: It was decided already.
        """
        _, check, rows = await self._decidable(ctx, skill_id, check_id, None)
        if check.agent_id is None or check.agent_id != agent_id:
            raise refused_field("check_id", "This check is not of this agent's update")
        if any(row.state == AgentState.WORSE.value for row in rows):
            raise refused_field(
                "check_id", "Main's newest version made this agent worse, so it stays pinned"
            )
        self._refuse_unacknowledged(check, rows, acknowledged)
        return check

    async def _refuse_rewritten(self, ctx: AuthContext, check: SkillCheck) -> None:
        """Refuse a check whose proposal says something else now than what it measured."""
        if check.proposal_id is None:
            return
        proposal = await skill_proposal_repo.get(
            self.db, check.proposal_id, organization_id=ctx.organization_id
        )
        if proposal is None or proposal.status != ProposalStatus.PENDING.value:
            raise ConcurrentChangeError(
                message="The change was decided elsewhere since it was checked.",
                details={"check_id": check.id, "proposal_id": check.proposal_id},
            )
        if _proposal_digest(proposal) != check.candidate_hash:
            raise ConcurrentChangeError(
                message="The change was rewritten since it was checked. Check it again.",
                details={"check_id": check.id, "proposal_id": proposal.id},
            )

    @staticmethod
    def _refuse_unacknowledged(
        check: SkillCheck, rows: Sequence[SkillCheckAgent], acknowledged: bool
    ) -> None:
        if not acknowledged and any(row.state == AgentState.UNKNOWN.value for row in rows):
            raise refused_field(
                "acknowledge_unknown",
                "Some agents could not be checked. Acknowledge them to go on",
            )

    async def apply(
        self, ctx: AuthContext, skill_id: UUID, check_id: UUID, data: SkillCheckApply
    ) -> SkillCheckApplied:
        """Make the checked text the line's newest version.

        A change that made agents worse is applied only with `pin_worse`, which
        first moves each of them, as a new published version, to the version it
        reads now - in this transaction, so none of them serves the change even once.

        Raises:
            AuthorizationError: `pin_worse` names agents the caller may not publish.
            BadRequestError: The result offers no apply, an agent was not acknowledged,
                or a worse agent reads the skill through a specialist.
        """
        skill, check, rows = await self._decidable(ctx, skill_id, check_id, None)
        _refuse_update(check)
        blocked = check.verdict == CheckVerdict.BLOCKED.value
        if blocked and not data.pin_worse:
            raise refused_field(
                "pin_worse", "The change made agents worse. Pin them, or pick another way"
            )
        outcome = CheckOutcome.APPLY_AND_PIN if blocked else CheckOutcome.APPLY
        if outcome not in rules.outcomes(
            CheckVerdict(check.verdict), fork=check.fork_id is not None
        ):
            raise BadRequestError(
                message="This check's result does not offer that",
                details={"outcome": outcome.value, "verdict": check.verdict},
            )
        self._refuse_unacknowledged(check, rows, data.acknowledge_unknown)
        pinned: list[AgentRef] = []
        if blocked:
            pinned = await self._pin_worse(ctx, skill, check, rows, note=data.note)
        if check.proposal_id is not None:
            from app.services.skill_proposal import SkillProposalService

            proposal = await skill_proposal_repo.get(
                self.db, check.proposal_id, organization_id=ctx.organization_id
            )
            assert proposal is not None, "a check keeps its proposal while it is pending"
            await SkillProposalService(self.db).apply(
                ctx, proposal.id, ProposalDecision(revision=proposal.revision), checked=True
            )
            fork, base = await self._line(ctx, skill, check.fork_id)
            version = base
        else:
            created = await self.versions.edit(
                ctx,
                skill.id,
                SkillVersionCreate(
                    fork_id=check.fork_id,
                    base_version_id=check.base_version_id,
                    description=check.candidate_description,
                    content=check.candidate_content,
                ),
            )
            version = await skill_version_repo.get_version(
                self.db, created.id, organization_id=ctx.organization_id, skill_id=skill.id
            )
            assert version is not None
        await self.record_decision(
            ctx, check, outcome, version.id, acknowledged=data.acknowledge_unknown
        )
        return SkillCheckApplied(
            version=await self.versions.read_version(ctx, skill.id, version.id), pinned=pinned
        )

    async def _pin_worse(
        self,
        ctx: AuthContext,
        skill: Skill,
        check: SkillCheck,
        rows: Sequence[SkillCheckAgent],
        *,
        note: str | None,
    ) -> list[AgentRef]:
        worse = [row for row in rows if row.state == AgentState.WORSE.value]
        agents = await agent_repo.get_many(
            self.db, [row.agent_id for row in worse], organization_id=ctx.organization_id
        )
        publishable = await accessible_ids(
            self.db, ctx, list(agents.values()), Perm.AGENTS_PUBLISH, resource_type=AGENT
        )
        refused = [agents[row.agent_id] for row in worse if row.agent_id not in publishable]
        if refused:
            visible = await accessible_ids(
                self.db, ctx, refused, Perm.AGENTS_VIEW, resource_type=AGENT
            )
            raise AuthorizationError(
                message=(
                    "Pinning the agents this change made worse needs publishing them. Ask "
                    "their owners, or pick another way."
                ),
                details={
                    "agents": [agent.name for agent in refused if agent.id in visible],
                    "hidden": sum(agent.id not in visible for agent in refused),
                },
            )
        through_specialist = [agents[row.agent_id].name for row in worse if row.via_specialist]
        if through_specialist:
            raise BadRequestError(
                message=(
                    "Some agents that got worse use the skill through a specialist, which is "
                    "changed in their Builder"
                ),
                details={"agents": through_specialist},
            )
        base = await skill_version_repo.get_version(
            self.db,
            check.base_version_id,
            organization_id=ctx.organization_id,
            skill_id=check.skill_id,
        )
        assert base is not None
        for row in worse:
            await self.agents.change_binding(
                ctx,
                skill.id,
                row.agent_id,
                SkillBindingChange(state="pinned", version=base.number, note=note),
            )
        return [AgentRef(id=row.agent_id, name=agents[row.agent_id].name) for row in worse]

    async def fork(
        self, ctx: AuthContext, skill_id: UUID, check_id: UUID, data: SkillCheckFork
    ) -> SkillCheckForked:
        """Make the checked text a new fork, and move the agents it helped onto it.

        Main stays as it is. An agent the caller may publish moves at once; one they
        may only edit moves in its draft; one they may not edit stays on main.
        """
        skill, check, rows = await self._decidable(
            ctx, skill_id, check_id, CheckOutcome.FORK_FOR_HELPED
        )
        self._refuse_unacknowledged(check, rows, data.acknowledge_unknown)
        created = await self.versions.create_fork(
            ctx, skill.id, SkillForkCreate(name=data.name, from_version_id=check.base_version_id)
        )
        fork = await skill_version_repo.get_fork(
            self.db, created.id, organization_id=ctx.organization_id, skill_id=skill.id, lock=True
        )
        assert fork is not None
        base = await skill_version_repo.get_version(
            self.db,
            check.base_version_id,
            organization_id=ctx.organization_id,
            skill_id=check.skill_id,
        )
        assert base is not None
        proposal = (
            None
            if check.proposal_id is None
            else await skill_proposal_repo.get(
                self.db, check.proposal_id, organization_id=ctx.organization_id
            )
        )
        from app.services.skill_proposal import version_source

        resources = base.resources
        if proposal is not None and proposal.resources:
            manifest, bodies = manifest_of(
                (name, base.resources.get(name, {}).get("description"), content)
                for name, content in sorted(proposal.resources.items())
            )
            await skill_version_repo.put_files(
                self.db, organization_id=ctx.organization_id, skill_id=skill.id, bodies=bodies
            )
            resources = {**base.resources, **manifest}
        version = await self.versions.record_fork(
            ctx,
            fork,
            description=check.candidate_description,
            content=check.candidate_content,
            resources=resources,
            source=version_source(proposal) if proposal is not None else _source_of(check),
            proposal_id=check.proposal_id,
        )
        helped = [
            row for row in rows if row.state == AgentState.BETTER.value and not row.via_specialist
        ]
        agents = await agent_repo.get_many(
            self.db, [row.agent_id for row in helped], organization_id=ctx.organization_id
        )
        editable = await accessible_ids(
            self.db, ctx, list(agents.values()), Perm.AGENTS_EDIT, resource_type=AGENT
        )
        moved: list[AgentRef] = []
        draft_only: list[AgentRef] = []
        for row in helped:
            if row.agent_id not in editable:
                continue
            changed = await self.agents.change_binding(
                ctx, skill.id, row.agent_id, SkillBindingChange(state="fork", fork_id=fork.id)
            )
            ref = AgentRef(id=row.agent_id, name=agents[row.agent_id].name)
            (moved if changed.published else draft_only).append(ref)
        if check.proposal_id is not None:
            await self._close_proposal(ctx, check.proposal_id, applied=True)
        await self.record_decision(
            ctx,
            check,
            CheckOutcome.FORK_FOR_HELPED,
            version.id,
            acknowledged=data.acknowledge_unknown,
        )
        forks = await self.versions.list_forks(ctx, skill.id)
        read = next(item for item in forks.items if item.id == fork.id)
        return SkillCheckForked(fork=read, moved=moved, draft_only=draft_only)

    async def discard(self, ctx: AuthContext, skill_id: UUID, check_id: UUID) -> SkillCheckRead:
        """Refuse the change; a pending proposal it checked is discarded with it."""
        await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_EDIT)
        check = await self._check(ctx, skill_id, check_id, lock=True)
        if CheckStatus(check.status).decided:
            raise AlreadyExistsError(
                message="This check was already decided", details={"check_id": check.id}
            )
        if check.status == CheckStatus.RUNNING.value:
            await self.cancel(ctx, skill_id, check.id)
        if check.proposal_id is not None:
            await self._close_proposal(ctx, check.proposal_id, applied=False)
        await skill_check_repo.update(
            self.db,
            row=check,
            values={
                "status": CheckStatus.DISCARDED.value,
                "outcome": CheckOutcome.DISCARD.value,
                "decided_at": datetime.now(UTC),
            },
        )
        return await self.read(ctx, skill_id, check.id)

    async def _close_proposal(self, ctx: AuthContext, proposal_id: UUID, *, applied: bool) -> None:
        from app.services.skill_proposal import SkillProposalService

        proposal = await skill_proposal_repo.get(
            self.db, proposal_id, organization_id=ctx.organization_id
        )
        if proposal is None or proposal.status != ProposalStatus.PENDING.value:
            return
        proposals = SkillProposalService(self.db)
        decision = ProposalDecision(revision=proposal.revision)
        if applied:
            await proposals.mark_forked(ctx, proposal.id, decision)
        else:
            await proposals.discard(ctx, proposal.id, decision)

    async def record_decision(
        self,
        ctx: AuthContext,
        check: SkillCheck,
        outcome: CheckOutcome,
        version_id: UUID,
        *,
        acknowledged: bool,
    ) -> None:
        """Close a check with what was done with it, and the version it left in place."""
        status = (
            CheckStatus.FORKED if outcome is CheckOutcome.FORK_FOR_HELPED else CheckStatus.APPLIED
        )
        await skill_check_repo.update(
            self.db,
            row=check,
            values={
                "status": status.value,
                "outcome": outcome.value,
                "applied_version_id": version_id,
                "decided_at": datetime.now(UTC),
                "acknowledged_unknown_by_user_id": ctx.user_id if acknowledged else None,
            },
        )

    async def passed_for(
        self, ctx: AuthContext, proposal: SkillProposal, check_id: UUID
    ) -> SkillCheck:
        """The finished check of exactly this proposal on the line's newest version.

        The gate every automatic change path goes through before it is live.

        Raises:
            BadRequestError: There is no such check, it measured another text or an
                older version, or its result does not allow applying.
        """
        check = await skill_check_repo.get(self.db, check_id, organization_id=ctx.organization_id)
        if (
            check is None
            or check.proposal_id != proposal.id
            or check.candidate_hash != _proposal_digest(proposal)
        ):
            raise refused_field("check_id", "Check this change on its agents before applying it")
        if check.status != CheckStatus.DONE.value or check.verdict in (
            None,
            CheckVerdict.NO_BETTER.value,
        ):
            raise refused_field("check_id", "This change's check does not allow applying it")
        return check

    async def test_set(self, ctx: AuthContext, skill_id: UUID) -> DatasetRead:
        """The skill's own test questions. Raises NotFoundError when it has none."""
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        dataset = await self._test_set(ctx, skill)
        if dataset is None:
            raise NotFoundError(
                message="This skill has no test questions yet", details={"skill_id": skill.id}
            )
        return await self.datasets.read(ctx, dataset.id)

    async def _add_evidence(
        self, ctx: AuthContext, skill: Skill, dataset_id: UUID, *, window_days: int
    ) -> None:
        """Add the questions of recent answers that loaded the skill, as test questions.

        A rated-up answer is kept as the reference, any other as the counter-example
        - an answer a person rated down or that failed is the one not to give.
        """
        from app.services.authoring_evidence import EvidenceService

        pack = await EvidenceService(self.db).for_skill(ctx, skill.id, window_days=window_days)
        answers = await conversation_repo.last_answers_of_runs(
            self.db, [run.run_id for run in pack.runs], organization_id=ctx.organization_id
        )
        ratings = {run.run_id: run.rating for run in pack.runs}
        answer_as: dict[UUID, AnswerAs] = {
            message_id: "reference_answer" if ratings[run_id] > 0 else "counter_example"
            for run_id, message_id in answers.items()
        }
        if answer_as:
            await self.datasets.add_from_messages(
                ctx, dataset_id, list(answer_as), answer_as=answer_as, limit=TEST_SET_FROM_EVIDENCE
            )

    async def create_test_set(
        self, ctx: AuthContext, skill_id: UUID, data: SkillTestSetStart
    ) -> DatasetRead:
        """Give the skill its test questions, empty or from recent answers that loaded it.

        Raises:
            AlreadyExistsError: The skill has its test questions already.
        """
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_EDIT)
        if await self._test_set(ctx, skill) is not None:
            raise AlreadyExistsError(
                message="This skill has its test questions already", details={"skill_id": skill.id}
            )
        created = await self.datasets.create(
            ctx,
            DatasetCreate(
                name=f"{skill.name} · test questions",
                description=f"Questions every agent using '{skill.name}' is checked on.",
            ),
            skill_id=skill.id,
        )
        if data.from_evidence:
            await self._add_evidence(ctx, skill, created.id, window_days=data.window_days)
            return await self.datasets.read(ctx, created.id)
        return created


def _update_start(data: SkillUpdateCheck) -> SkillCheckStart:
    """The start `_plan` reads for a pinned update: only its mode; the text is main's."""
    return SkillCheckStart.model_construct(
        fork_id=None, candidate=None, proposal_id=None, mode=data.mode
    )


def _refuse_update(check: SkillCheck) -> None:
    if check.agent_id is not None:
        raise BadRequestError(
            message="A pinned agent's update is accepted by moving the agent to main",
            details={"check_id": check.id, "agent_id": check.agent_id},
        )


def _from_text(text: CandidateText) -> Candidate:
    return Candidate(text.description, text.content)


def _candidate_of(check: SkillCheck) -> Candidate:
    files = check.candidate_resources
    return Candidate(
        check.candidate_description,
        check.candidate_content,
        None
        if files is None
        else tuple(
            SkillBodyFile(name=name, description=item.get("description"), content=item["content"])
            for name, item in sorted(files.items())
        ),
    )


def _resources_json(
    served: tuple[SkillBodyFile, ...] | None,
) -> dict[str, dict[str, str | None]] | None:
    if served is None:
        return None
    return {
        item.name: {"description": item.description, "content": item.content} for item in served
    }


def _request(stage: Stage, agent_version: int) -> EvalRunRequest:
    return EvalRunRequest(
        dataset_id=stage.dataset.id,
        version=agent_version,
        baseline_version=agent_version,
        paired_baseline=True,
        case_ids=stage.case_ids,
    )


def _sampled(item: Planned) -> list[UUID] | None:
    return next((stage.case_ids for stage in item.stages if stage.kind != "skill_set"), None)


def _kept(dataset: Dataset | None, holdout: Mapping[UUID, Collection[UUID]]) -> list[UUID] | None:
    """The questions of `dataset` a session keeps aside, or `None` to ask them all."""
    if dataset is None or dataset.id not in holdout:
        return None
    return sorted(holdout[dataset.id], key=str)


def _own_dataset(item: Planned) -> UUID | None:
    return next((stage.dataset.id for stage in item.stages if stage.kind != "skill_set"), None)


def _next_stage(
    row: SkillCheckAgent, mode: CheckMode
) -> tuple[UUID, StageKind, list[UUID] | None] | None:
    """The agent's own questions, once its skill-set stage is behind it."""
    if row.dataset_id is None or row.skill_set_run_id is None:
        return None
    kind: StageKind = "dataset_sample" if mode is CheckMode.QUICK else "dataset"
    return row.dataset_id, kind, row.sample_case_ids


def _priced(agents: Sequence[Planned]) -> tuple[Decimal, Decimal]:
    counted = [item for item in agents if item.unknown is None]
    return (
        rules.total(item.expected for item in counted),
        rules.total(item.at_most for item in counted),
    )


def _line_ref(fork: SkillFork | None) -> LineRef:
    return (
        LineRef(fork_id=None, name="main")
        if fork is None
        else LineRef(fork_id=fork.id, name=fork.name)
    )


def _source_of(check: SkillCheck) -> SkillVersionSource:
    return (
        SkillVersionSource.IMPROVE
        if check.source == CheckSource.SESSION.value
        else SkillVersionSource.EDIT
    )

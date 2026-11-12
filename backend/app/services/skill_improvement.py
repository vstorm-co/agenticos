"""Improve a skill line step by step: Understand, Changes, then a check across its agents.

A session belongs to one line of a skill - main, or one fork - because a skill has no
single agent. Its steps, stops, prices and expiry are an agent session's, and the
same rules (`app.services.improvement_states`) decide every move; what differs is
what each paid step reads and writes:

- **analyzing** gathers the bad answers in which a version of this line was loaded
  (`EvidenceService.for_skill`) and queues an `analyze` authoring request;
- **classifying** waits for it to group them into problems, then stops at
  **Understand**;
- **proposing**, the step a person takes, queues an `improve` request that writes
  edits to passages of the line's latest body, and at most one new description;
- **filtering** drops edits the policy refuses and stops at **Changes**.

A session whose purpose is a merge - a fork catching up with main, or a fork moving to
main - reads no runs. It starts with a three-way merge of the two lines
(`SkillCatchUpService`), **proposing** asks for a text for each conflict, and it stops
at **Changes** for a person to settle what is left. A catch-up is also checked with main
alone, so its result can offer moving the fork's agents back to main instead.

Nothing here writes a skill: a session ends at a person's decision at the latest.
"""

import hashlib
import json
import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic.main import IncEx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.skills import SkillBodyFile
from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
    PaymentRequiredError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.authoring import (
    AuthoringKind,
    AuthoringRequest,
    AuthoringStatus,
    HunkKind,
    SpecProposalHunk,
)
from app.db.models.improvement import DroppedHunk, ImprovementVerdict, StopReason
from app.db.models.improvement import ImprovementStage as Stage
from app.db.models.improvement import ImprovementStatus as Status
from app.db.models.skill import Skill
from app.db.models.skill_check import (
    AgentState,
    CheckMode,
    CheckOutcome,
    CheckSource,
    CheckStatus,
    CheckVerdict,
    SkillCheck,
)
from app.db.models.skill_improvement import (
    SkillImprovementIteration,
    SkillImprovementOutcome,
    SkillImprovementRun,
)
from app.db.models.skill_improvement import SkillImprovementPurpose as Purpose
from app.db.models.skill_merge import SkillMerge
from app.db.models.skill_version import SkillFork, SkillVersion
from app.repositories import (
    agent_repo,
    agent_run_repo,
    authoring_repo,
    skill_check_repo,
    skill_improvement_repo,
    skill_repo,
    skill_version_repo,
    user_repo,
)
from app.schemas.authoring import EvidenceItemRead, HunkRead
from app.schemas.improvement import (
    ChangeEdit,
    ImprovementDiscard,
    ImprovementEvent,
    ImprovementSelection,
)
from app.schemas.skill_check import (
    CandidateText,
    SkillCheckApply,
    SkillCheckEstimate,
    SkillCheckFork,
    SkillCheckRead,
    SkillCheckStart,
)
from app.schemas.skill_improvement import (
    MERGE_ASK,
    MergeOutcome,
    ProblemAgent,
    SkillContinuationConsent,
    SkillContinuationEstimate,
    SkillContinue,
    SkillImprovementApplied,
    SkillImprovementApply,
    SkillImprovementAwaiting,
    SkillImprovementEstimate,
    SkillImprovementFork,
    SkillImprovementForked,
    SkillImprovementIterationRead,
    SkillImprovementProblems,
    SkillImprovementRead,
    SkillImprovementReturn,
    SkillImprovementReturned,
    SkillImprovementStart,
    SkillImprovementTarget,
    SkillLine,
    SkillMergeEstimate,
    SkillMergeStart,
    SkillProblemExample,
    SkillProblemRead,
    SkillVersionRef,
)
from app.schemas.skill_version import PersonRef, ReturnToMain
from app.services import authoring_hunks
from app.services import improvement_states as rules
from app.services.access import AGENT, SKILL, accessible_ids, resolve_access
from app.services.api_key import job_context
from app.services.authoring import AuthoringService
from app.services.authoring_evidence import EvidencePack
from app.services.background_jobs import enqueue
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.improvement_skills import SkillSeed
from app.services.skill_agents import SkillAgentService
from app.services.skill_catch_up import MergeSides, SkillCatchUpService
from app.services.skill_check import SkillCheckService
from app.services.skill_versions import SkillVersionService
from app.worker.jobs import ADVANCE_SKILL_IMPROVEMENT, AdvanceSkillImprovement

logger = logging.getLogger(__name__)

_AWAITING_PERSON = (Status.WAITING.value, Status.READY.value)
_AWAITING_LIMIT = 20
_MERGE_WINDOW_DAYS = 30
"""A merge reads no runs; the column holds what an Improve on the line would read."""
_LINE_VERSIONS = 500
"""Versions of one line the evidence is read for; a line holds far fewer."""

_VERDICTS = {
    CheckVerdict.PASSED: ImprovementVerdict.BETTER,
    CheckVerdict.NEEDS_ACK: ImprovementVerdict.BETTER,
    CheckVerdict.BLOCKED: ImprovementVerdict.REGRESSION,
    CheckVerdict.NO_BETTER: ImprovementVerdict.NO_CHANGE,
}
"""A check's verdict in an agent session's words, so one wizard reads both."""


@dataclass(frozen=True)
class SkillStanding:
    """Whether the person a skill session acts for may still do what it does."""

    edits_skill: bool
    views_runs: bool

    @property
    def allowed(self) -> bool:
        return self.edits_skill and self.views_runs


_RESUMABLE = (StopReason.BUDGET.value, StopReason.PERMISSION.value)
"""Stops a person can lift - a higher limit, regained access - and take the same step again."""

_BEFORE_A_PROPOSAL = (Stage.ANALYZING.value, Stage.CLASSIFYING.value, Stage.PROPOSING.value)
"""Steps of an attempt that has not written its edits yet."""


@dataclass(frozen=True)
class SessionLine:
    """One line of a skill, as a session improves it."""

    skill: Skill
    fork: SkillFork | None

    @property
    def fork_id(self) -> UUID | None:
        return None if self.fork is None else self.fork.id

    @property
    def name(self) -> str:
        return "main" if self.fork is None else self.fork.name

    @property
    def latest(self) -> UUID | None:
        return SkillVersionService.line_latest(self.skill, self.fork)

    @property
    def archived(self) -> bool:
        return self.fork is not None and self.fork.archived_at is not None


def candidate_hash(description: str, content: str) -> str:
    """What a check of this exact skill text is keyed on."""
    payload = json.dumps({"description": description, "content": content}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


_UNPRICED: IncEx = {
    "expected_usd": True,
    "at_most_usd": True,
    "org_remaining_usd": True,
    "affordable": True,
    "agents": {"__all__": {"expected_usd", "at_most_usd"}},
}


def plan_hash(description: str, content: str, check: SkillCheckEstimate) -> str:
    """What a consent to a check is keyed on: the text and what the check runs on each
    agent, so an agent that joins, leaves or republishes, or a dataset that changes,
    asks again even when the price does not rise."""
    plan = check.model_dump(mode="json", exclude=_UNPRICED)
    payload = json.dumps(
        {"description": description, "content": content, "plan": plan}, sort_keys=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def merge_hash(
    starts: Sequence[tuple[SkillCheckStart, tuple[SkillBodyFile, ...]]],
    checks: Sequence[SkillCheckEstimate],
) -> str:
    """What a consent to a merge's checks is keyed on: each text with its files, and what
    each check runs."""
    payload = []
    for (start, files), check in zip(starts, checks, strict=True):
        assert start.candidate is not None, "a merge checks a text"
        payload.append(
            {
                "description": start.candidate.description,
                "content": start.candidate.content,
                "files": [[item.name, item.description, item.content] for item in files],
                "plan": check.model_dump(mode="json", exclude=_UNPRICED),
            }
        )
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _same_skill(
    description: str,
    content: str,
    files: Sequence[SkillBodyFile],
    version: SkillVersion,
    version_files: Sequence[SkillBodyFile],
) -> bool:
    def keyed(items: Sequence[SkillBodyFile]) -> dict[str, tuple[str | None, str]]:
        return {item.name: (item.description, item.content) for item in items}

    return (
        description == version.description
        and content == version.content
        and keyed(files) == keyed(version_files)
    )


def merge_outcomes(
    purpose: Purpose, merged: SkillCheckRead, alone: SkillCheckRead | None
) -> list[CheckOutcome | MergeOutcome]:
    """What a person may do with a merge's result.

    A move to main is decided as a change to main, by its check, but is never a fork
    and has no further round. A catch-up is taken in when nobody got worse, and its
    agents may return to main when main alone made nobody worse either.
    """
    if purpose is Purpose.TO_MAIN:
        return [
            outcome
            for outcome in merged.outcomes
            if outcome not in (CheckOutcome.FORK_FOR_HELPED, CheckOutcome.IMPROVE_FURTHER)
        ]
    found: list[CheckOutcome | MergeOutcome] = []
    if merged.verdict is not CheckVerdict.BLOCKED:
        found.append("catch_up")
    if alone is not None and alone.verdict not in (None, CheckVerdict.BLOCKED):
        found.append("return_to_main")
    found.append(CheckOutcome.DISCARD)
    return found


def candidate_text(base: SkillVersion, hunks: Sequence[SpecProposalHunk]) -> tuple[str, str] | None:
    """The base text with the chosen edits applied, a person's rewording first; `None` when
    an edit no longer finds its passage."""
    content, description = base.content, base.description
    for hunk in hunks:
        if hunk.kind == HunkKind.SKILL_DESCRIPTION.value:
            description = hunk.edited_text or hunk.new_description or description
            continue
        applied = authoring_hunks.apply_text(content, hunk, hunk.edited_text or hunk.new_text)
        if applied is None:
            return None
        content = applied
    return description, content


def filtered(
    hunks: Sequence[SpecProposalHunk], base: SkillVersion
) -> tuple[list[SpecProposalHunk], list[DroppedHunk]]:
    """The edits a session offers, and the ones its policy drops with why.

    An edit repeating one already kept is dropped, and so is one whose passage an
    edit kept before it already changed - both cannot be applied - and every
    description after the first.
    """
    kept: list[SpecProposalHunk] = []
    dropped: list[DroppedHunk] = []
    content = base.content
    seen: set[tuple[str, str]] = set()
    described = False
    for hunk in hunks:
        reason: str | None = None
        if hunk.kind == HunkKind.SKILL_DESCRIPTION.value:
            reason = "repeated" if described else None
            described = True
        elif (hunk.old_text, hunk.new_text) in seen:
            reason = "repeated"
        else:
            applied = authoring_hunks.apply_text(content, hunk, hunk.new_text)
            if applied is None:
                reason = "overlaps"
            else:
                content = applied
                seen.add((hunk.old_text, hunk.new_text))
        if reason is None:
            kept.append(hunk)
        else:
            dropped.append(DroppedHunk(hunk_id=str(hunk.id), reason=reason))
    return kept, dropped


class SkillImprovementService:
    """Start, follow and take a session on a skill line, a step at a time."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.versions = SkillVersionService(db)
        self.skill_agents = SkillAgentService(db)
        self.authoring = AuthoringService(db)
        self.checks = SkillCheckService(db)
        self.merges = SkillCatchUpService(db)

    async def estimate(
        self, ctx: AuthContext, skill_id: UUID, target: SkillImprovementTarget
    ) -> SkillImprovementEstimate:
        """What a session on the line would read and cost before it first waits for a person.

        With `from_run`, the line is the one the handing agent follows, whatever
        `fork_id` says.
        """
        estimate, _ = await self._estimate(ctx, skill_id, target)
        return estimate

    async def _estimate(
        self, ctx: AuthContext, skill_id: UUID, target: SkillImprovementTarget
    ) -> tuple[SkillImprovementEstimate, SkillSeed | None]:
        self._require_runs_view(ctx)
        await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_EDIT)
        if target.improver_agent_id is not None:
            await self._require_helper(ctx, target.improver_agent_id)
        seed = (
            None
            if target.from_run is None
            else await ImprovementPipelineService(self.db).skill_seed(
                ctx, target.from_run, skill_id
            )
        )
        fork_id = target.fork_id if seed is None else seed.fork_id
        line = await self._line(ctx, skill_id, fork_id, Perm.SKILLS_EDIT)
        if line.archived:
            raise refused_field("fork_id", "An archived fork cannot be improved")
        pack = await self._evidence(ctx, line, target.window_days)
        priced = await self.authoring.estimate_pack(
            ctx, pack, improver_agent_id=target.improver_agent_id
        )
        visible, hidden = await self._line_agents(ctx, line)
        base = await self._base(line)
        # An attempt's text is not known yet, so its check is priced on the line as it
        # is: the same agents and questions, at the most a quick check could cost.
        check = await self.checks.estimate(
            ctx,
            skill_id,
            SkillCheckStart(
                fork_id=line.fork_id,
                candidate=CandidateText(description=base.description, content=base.content),
                mode=CheckMode.QUICK,
            ),
            exclude_conversations=pack.conversation_ids,
        )
        estimate = SkillImprovementEstimate(
            line=SkillLine(fork_id=line.fork_id, name=line.name),
            base_version=SkillVersionRef(id=base.id, number=base.number),
            proposal_usd=priced.estimate_usd * 2,
            check_usd=check.at_most_usd,
            per_round_usd=priced.estimate_usd + check.at_most_usd,
            total_usd=priced.estimate_usd,
            max_iterations=target.max_iterations,
            evidence_runs=len(pack.runs),
            usage_unknown=pack.unknown_runs,
            agents=visible,
            hidden_agents=hidden,
            estimated_minutes=rules.estimated_minutes(
                rounds=target.max_iterations, answers=0, answer_seconds=None, concurrency=1
            ),
            affordable=priced.affordable,
            reason="no_evidence" if not pack.runs else None,
        )
        return estimate, seed

    async def start(
        self, ctx: AuthContext, skill_id: UUID, data: SkillImprovementStart
    ) -> SkillImprovementRead:
        """Queue a session on the line.

        Raises:
            AuthorizationError: The caller may not read runs.
            NotFoundError: No such skill or fork the caller may edit.
            BadRequestError: The fork is archived, or nothing in the window used this line.
            PaymentRequiredError: The budget, the improver's or the organization's, is too small.
            AlreadyExistsError: The line has an open session.
        """
        estimate, seed = await self._estimate(ctx, skill_id, data)
        line = await self._line(ctx, skill_id, estimate.line.fork_id, Perm.SKILLS_EDIT)
        if estimate.reason == "no_evidence":
            raise BadRequestError(
                message=(
                    "Nothing to learn from yet: no answer in this window that loaded this "
                    "line of the skill was rated down or failed"
                ),
                details={"reason": estimate.reason},
            )
        if not estimate.affordable or data.budget_usd < estimate.total_usd:
            raise PaymentRequiredError(
                message="The spending limit does not cover grouping the problems",
                details={
                    "estimate_usd": str(estimate.total_usd),
                    "budget_usd": str(data.budget_usd),
                },
            )
        try:
            async with self.db.begin_nested():
                run = await skill_improvement_repo.create_run(
                    self.db,
                    organization_id=ctx.organization_id,
                    skill_id=line.skill.id,
                    fork_id=line.fork_id,
                    base_version_id=estimate.base_version.id,
                    created_by_user_id=ctx.user_id,
                    created_by_api_key_id=ctx.api_key_id,
                    window_days=data.window_days,
                    max_iterations=data.max_iterations,
                    estimate_usd=estimate.total_usd,
                    budget_usd=data.budget_usd,
                    improver_agent_id=data.improver_agent_id,
                    seed=None
                    if seed is None
                    else {
                        "agent_id": str(seed.agent_id),
                        "run_ids": [str(run_id) for run_id in seed.run_ids],
                        "problems": list(seed.problems),
                        "quotes": list(seed.quotes),
                    },
                )
        except IntegrityError as exc:
            # The skill and its fork were read in this transaction, so the open-session
            # index is the one constraint the insert can break.
            raise AlreadyExistsError(
                message="This line of the skill already has an open improvement session",
                details={"skill_id": line.skill.id, "fork_id": line.fork_id},
            ) from exc
        await skill_improvement_repo.create_iteration(
            self.db, organization_id=ctx.organization_id, run_id=run.id, number=1, note=None
        )
        await self._audit(run, "started", actor_user_id=ctx.subject_id)
        await self._queue(run)
        return await self._read(ctx, run, line)

    async def estimate_merge(
        self, ctx: AuthContext, skill_id: UUID, fork_id: UUID, purpose: Purpose
    ) -> SkillMergeEstimate:
        """What catching a fork up with main, or moving it to main, would merge and cost
        before the merge waits at Changes.

        Raises:
            AuthorizationError: The caller may not read runs.
            NotFoundError: No such skill the caller may edit, or no such fork of it.
            BadRequestError: The fork is archived.
            ConcurrentChangeError: There is nothing to merge.
        """
        estimate, _, _, _ = await self._merge_estimate(ctx, skill_id, fork_id, purpose)
        return estimate

    async def start_merge(
        self,
        ctx: AuthContext,
        skill_id: UUID,
        fork_id: UUID,
        purpose: Purpose,
        data: SkillMergeStart,
    ) -> SkillImprovementRead:
        """Queue a catch-up of the fork, which runs on the fork, or its move to main, which
        runs on main; the merge is written with the session.

        Raises:
            AuthorizationError: The caller may not read runs.
            NotFoundError: No such skill the caller may edit, or no such fork of it.
            BadRequestError: The fork is archived.
            ConcurrentChangeError: There is nothing to merge.
            PaymentRequiredError: The spending limit does not cover proposing the
                conflicts' texts.
            AlreadyExistsError: The line the merge changes has an open session.
        """
        estimate, source, target, sides = await self._merge_estimate(
            ctx, skill_id, fork_id, purpose
        )
        if not estimate.affordable or data.budget_usd < estimate.total_usd:
            raise PaymentRequiredError(
                message="The spending limit does not cover proposing the conflicts' texts",
                details={
                    "estimate_usd": str(estimate.total_usd),
                    "budget_usd": str(data.budget_usd),
                },
            )
        assert source.fork is not None, "a merge starts from a fork"
        try:
            async with self.db.begin_nested():
                run = await skill_improvement_repo.create_run(
                    self.db,
                    organization_id=ctx.organization_id,
                    skill_id=target.skill.id,
                    fork_id=target.fork_id,
                    base_version_id=estimate.base_version.id,
                    created_by_user_id=ctx.user_id,
                    created_by_api_key_id=ctx.api_key_id,
                    window_days=_MERGE_WINDOW_DAYS,
                    max_iterations=1,
                    estimate_usd=estimate.total_usd,
                    budget_usd=data.budget_usd,
                    seed=None,
                    purpose=purpose.value,
                    source_fork_id=source.fork_id if purpose is Purpose.TO_MAIN else None,
                )
        except IntegrityError as exc:
            raise AlreadyExistsError(
                message="This line of the skill already has an open improvement session",
                details={"skill_id": target.skill.id, "fork_id": target.fork_id},
            ) from exc
        await skill_improvement_repo.create_iteration(
            self.db, organization_id=ctx.organization_id, run_id=run.id, number=1, note=None
        )
        await self.merges.build_merge(
            ctx, run=run, skill=source.skill, fork=source.fork, sides=sides
        )
        await self._audit(run, "started", actor_user_id=ctx.subject_id)
        await self._queue(run)
        return await self._read(ctx, run, target)

    async def _require_helper(self, ctx: AuthContext, agent_id: UUID) -> None:
        """Refuse a helper the caller may not see, or of another organization, as missing;
        whether it is an improver that can run is the authoring service's to say."""
        helper = await agent_repo.get(self.db, agent_id, organization_id=ctx.organization_id)
        if helper is None or not await resolve_access(
            self.db, ctx, helper, Perm.AGENTS_VIEW, resource_type=AGENT
        ):
            raise NotFoundError(message="No such helper", details={"improver_agent_id": agent_id})

    async def _merge_estimate(
        self, ctx: AuthContext, skill_id: UUID, fork_id: UUID, purpose: Purpose
    ) -> tuple[SkillMergeEstimate, SessionLine, SessionLine, MergeSides]:
        """The estimate, the fork merged from, the line the merge becomes a version of, and
        the merge the estimate priced."""
        self._require_runs_view(ctx)
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_EDIT)
        fork = await skill_version_repo.get_fork(
            self.db, fork_id, organization_id=ctx.organization_id, skill_id=skill.id
        )
        if fork is None:
            raise NotFoundError(message="Fork not found", details={"fork_id": fork_id})
        source = SessionLine(skill, fork)
        if source.archived:
            raise refused_field("fork_id", "An archived fork cannot be merged")
        sides = await self.merges.merge_sides(ctx, skill=skill, fork=fork, kind=purpose)
        target = source if purpose is Purpose.CATCH_UP else SessionLine(skill, None)
        priced = (
            await self.authoring.estimate_call(ctx, chars=len(MERGE_ASK) + len(sides.prompt))
            if sides.conflicts
            else None
        )
        visible, hidden = await self._line_agents(ctx, target)
        base = await self._base(target)
        estimate = SkillMergeEstimate(
            line=SkillLine(fork_id=target.fork_id, name=target.name),
            source_fork=None
            if purpose is Purpose.CATCH_UP
            else SkillLine(fork_id=source.fork_id, name=source.name),
            base_version=SkillVersionRef(id=base.id, number=base.number),
            conflicts=sides.conflicts,
            total_usd=Decimal(0) if priced is None else priced.estimate_usd,
            agents=visible,
            hidden_agents=hidden,
            affordable=priced is None or priced.affordable,
        )
        return estimate, source, target, sides

    async def list_for_skill(
        self,
        ctx: AuthContext,
        skill_id: UUID,
        *,
        fork_id: UUID | None,
        main_only: bool,
        skip: int,
        limit: int,
    ) -> list[SkillImprovementRead]:
        """A skill's sessions, newest first: all lines, main only, or one fork."""
        self._require_runs_view(ctx)
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        lines: list[UUID | None] | None = (
            [None] if main_only else None if fork_id is None else [fork_id]
        )
        rows = await skill_improvement_repo.list_runs(
            self.db,
            organization_id=ctx.organization_id,
            skill_id=skill.id,
            lines=lines,
            skip=skip,
            limit=limit,
        )
        people = await self.versions.people(ctx, [row.created_by_user_id for row in rows])
        # A page holds a handful of lines at most: each is read, and its agents counted, once.
        lines: dict[UUID | None, tuple[SessionLine, tuple[int, int]]] = {}
        reads: list[SkillImprovementRead] = []
        for row in rows:
            if row.fork_id not in lines:
                line = await self._line_of(skill, row)
                lines[row.fork_id] = (line, await self._line_agents(ctx, line))
            line, counted = lines[row.fork_id]
            reads.append(await self._read(ctx, row, line, people=people, line_agents=counted))
        return reads

    async def read(self, ctx: AuthContext, skill_id: UUID, run_id: UUID) -> SkillImprovementRead:
        self._require_runs_view(ctx)
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        run = await self._row(ctx, skill, run_id)
        return await self._read(ctx, run, await self._line_of(skill, run))

    async def awaiting(self, ctx: AuthContext) -> list[SkillImprovementAwaiting]:
        """Sessions waiting for a person - at a stop, or with a result - on skills the caller
        may read."""
        self._require_runs_view(ctx)
        awaiting: list[SkillImprovementAwaiting] = []
        readable: dict[UUID, Skill | None] = {}
        skip = 0
        while len(awaiting) < _AWAITING_LIMIT and (
            rows := await skill_improvement_repo.list_for_person(
                self.db,
                organization_id=ctx.organization_id,
                statuses=_AWAITING_PERSON,
                skip=skip,
                limit=_AWAITING_LIMIT,
            )
        ):
            skip += len(rows)
            for row in rows:
                if row.skill_id not in readable:
                    skill = await skill_repo.get(
                        self.db, row.skill_id, organization_id=ctx.organization_id
                    )
                    assert skill is not None, "a session goes with its skill"
                    readable[row.skill_id] = (
                        skill
                        if await resolve_access(
                            self.db, ctx, skill, Perm.SKILLS_VIEW, resource_type=SKILL
                        )
                        else None
                    )
                skill = readable[row.skill_id]
                if skill is None or len(awaiting) == _AWAITING_LIMIT:
                    continue
                line = await self._line_of(skill, row)
                awaiting.append(
                    SkillImprovementAwaiting(
                        id=row.id,
                        skill_id=skill.id,
                        skill_name=skill.name,
                        fork_id=row.fork_id,
                        line_name=line.name,
                        status=Status(row.status),
                        stage=None if row.stage is None else Stage(row.stage),
                        iteration=row.iteration,
                        max_iterations=row.max_iterations,
                        created_at=row.created_at,
                    )
                )
        return awaiting

    async def problems(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID
    ) -> SkillImprovementProblems:
        """Understand: the problems the bad answers show, with the agents each occurred in."""
        self._require_runs_view(ctx)
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        run = await self._row(ctx, skill, run_id)
        request = (
            None
            if run.analysis_request_id is None
            else await authoring_repo.get_request(
                self.db, run.analysis_request_id, organization_id=ctx.organization_id
            )
        )
        report = (request.report if request is not None else None) or {}
        found = [item for item in report.get("problems", []) if isinstance(item, dict)]
        run_ids = {UUID(run_id) for item in found for run_id in item.get("run_ids", [])}
        run_ids |= {UUID(quote["run_id"]) for item in found for quote in item.get("evidence", [])}
        owners = await agent_run_repo.agents_of_runs(
            self.db, list(run_ids), organization_id=ctx.organization_id
        )
        agents = await agent_repo.get_many(
            self.db, list(set(owners.values())), organization_id=ctx.organization_id
        )
        visible = await accessible_ids(
            self.db, ctx, list(agents.values()), Perm.AGENTS_VIEW, resource_type=AGENT
        )
        shown = {run_id for run_id, agent_id in owners.items() if agent_id in visible}
        problems: list[SkillProblemRead] = []
        for item in found:
            if item.get("cause") != "skill":
                continue
            per_agent = Counter(
                owners[UUID(run_id)] for run_id in item.get("run_ids", []) if UUID(run_id) in owners
            )
            problems.append(
                SkillProblemRead(
                    title=str(item.get("title", "")),
                    summary=str(item.get("summary", "")),
                    runs=len(item.get("run_ids", [])),
                    agents=[
                        ProblemAgent(id=agent_id, name=agents[agent_id].name, runs=count)
                        for agent_id, count in per_agent.most_common()
                        if agent_id in visible
                    ],
                    hidden_agents=sum(1 for agent_id in per_agent if agent_id not in visible),
                    examples=[
                        SkillProblemExample(run_id=UUID(quote["run_id"]), quote=quote["quote"])
                        for quote in item.get("evidence", [])
                        if UUID(quote["run_id"]) in shown
                    ],
                    hidden_examples=sum(
                        UUID(quote["run_id"]) not in shown for quote in item.get("evidence", [])
                    ),
                )
            )
        causes = Counter(str(item.get("cause")) for item in found)
        return SkillImprovementProblems(
            problems=problems,
            not_the_skill=causes["not_the_skill"],
            not_a_problem=causes["not_a_problem"],
            usage_unknown=int(report.get("usage_unknown", 0)),
        )

    async def changes(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, *, attempt: int | None = None
    ) -> list[HunkRead]:
        """The edits an attempt proposed - the current one by default - and whether each still
        finds its passage in the line's base text."""
        self._require_runs_view(ctx)
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        run = await self._row(ctx, skill, run_id)
        iteration = await skill_improvement_repo.get_iteration(
            self.db,
            organization_id=ctx.organization_id,
            run_id=run.id,
            number=attempt or run.iteration,
        )
        if iteration is None:
            raise NotFoundError(message="Attempt not found", details={"attempt": attempt})
        if iteration.batch_id is None:
            return []
        base = await self.base_of(run)
        hunks = await authoring_repo.list_hunks(
            self.db, organization_id=ctx.organization_id, batch_id=iteration.batch_id
        )
        shown = await self._shown_runs(
            ctx, {UUID(item["run_id"]) for hunk in hunks for item in hunk.evidence}
        )
        return [self._hunk(hunk, base, shown) for hunk in hunks]

    async def edit_change(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, hunk_id: UUID, data: ChangeEdit
    ) -> HunkRead:
        """Reword one proposed edit while the session waits at Changes; the check measures it."""
        line, run, iteration = await self._at_changes(ctx, skill_id, run_id)
        hunk = await authoring_repo.get_hunk(self.db, hunk_id, organization_id=ctx.organization_id)
        if hunk is None or hunk.batch_id != iteration.batch_id:
            raise NotFoundError(message="Change not found", details={"hunk_id": hunk_id})
        proposed = (
            hunk.new_description if hunk.kind == HunkKind.SKILL_DESCRIPTION.value else hunk.new_text
        )
        if hunk.kind == HunkKind.SKILL_DESCRIPTION.value and len(data.edited_text or "") > 500:
            raise refused_field("edited_text", "A description holds at most 500 characters")
        hunk.edited_text = None if data.edited_text == proposed else data.edited_text
        await self.db.flush()
        await self._remeasure(ctx, run, iteration)
        await self._audit(run, "change_edited", actor_user_id=ctx.subject_id)
        shown = await self._shown_runs(ctx, {UUID(item["run_id"]) for item in hunk.evidence})
        return self._hunk(hunk, await self.base_of(run), shown)

    async def choose_changes(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, data: ImprovementSelection
    ) -> SkillImprovementRead:
        """Choose which of the attempt's kept edits its check measures."""
        line, run, iteration = await self._at_changes(ctx, skill_id, run_id)
        assert iteration.batch_id is not None, "a session waits at Changes with its batch"
        hunks = await authoring_repo.list_hunks(
            self.db, organization_id=ctx.organization_id, batch_id=iteration.batch_id
        )
        offered = {hunk.id for hunk in hunks} - set(iteration.dropped_hunk_ids)
        chosen = list(dict.fromkeys(data.hunk_ids))
        unknown = [hunk_id for hunk_id in chosen if hunk_id not in offered]
        if unknown:
            raise refused_field("hunk_ids", "Choose among the changes this attempt offers")
        await skill_improvement_repo.update_iteration(
            self.db, iteration=iteration, values={"included_hunk_ids": chosen}
        )
        await self._remeasure(ctx, run, iteration)
        await self._audit(run, "changes_chosen", actor_user_id=ctx.subject_id)
        return await self._read(ctx, run, line)

    async def estimate_continuation(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, data: SkillContinue
    ) -> SkillContinuationEstimate:
        """The price of the step a person may take now: a proposal after Understand, the
        check of the chosen changes after Changes, or Try again after a stop or a result."""
        line, run = await self._editable_row(ctx, skill_id, run_id)
        if run.purpose != Purpose.IMPROVE.value:
            return await self._merge_continuation(
                ctx, line, run, mode=data.mode, main_alone=data.main_alone, budget=data.budget_usd
            )
        quote, _ = await self._continuation(ctx, line, run, mode=data.mode, budget=data.budget_usd)
        return quote

    async def continue_run(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, consent: SkillContinuationConsent
    ) -> SkillImprovementRead:
        """Take the next step, or try again with a note, at the price a person agreed to.

        A session already working is read back, not started twice. The check after
        Changes never asks the conversations the edits were written from, nor those of
        the runs an agent's Improve handed over: that is how a session keeps its
        evidence out of its measurement, rather than with a drawn held-out set.

        Raises:
            ConcurrentChangeError: The price or what it measures moved since it was quoted.
            PaymentRequiredError: The spending limit does not cover the step.
        """
        line, run = await self._editable_row(ctx, skill_id, run_id, lock=True)
        if Status(run.status).active:
            return await self._read(ctx, run, line)
        if run.purpose != Purpose.IMPROVE.value:
            await self._continue_merge(ctx, line, run, consent)
            return await self._read(ctx, run, line)
        quote, covered = await self._continuation(
            ctx, line, run, mode=consent.mode, budget=consent.budget_usd
        )
        moved = line.latest != run.base_version_id
        if consent.candidate_hash != quote.candidate_hash and moved:
            self._refuse_moved(run, line)
        if consent.candidate_hash != quote.candidate_hash or consent.estimate_usd < quote.total_usd:
            raise ConcurrentChangeError(
                message="The step's price changed since it was quoted; review it again",
                details={"estimate_usd": str(quote.total_usd)},
            )
        spent = await skill_improvement_repo.spent(
            self.db, run.id, organization_id=ctx.organization_id
        )
        budget = max(run.budget_usd, consent.budget_usd)
        if not rules.affordable(spent=spent, step_estimate=quote.total_usd, budget=budget):
            raise PaymentRequiredError(
                message="The spending limit does not cover this step",
                details={"estimate_usd": str(quote.total_usd), "budget_usd": str(budget)},
            )
        if not covered:
            raise PaymentRequiredError(
                message="The organization's budget, or the helper's, does not cover this step",
                details={"estimate_usd": str(quote.total_usd)},
            )
        values: dict[str, object] = {
            "budget_usd": budget,
            "actor_user_id": ctx.user_id,
            "actor_api_key_id": ctx.api_key_id,
        }
        if quote.mode == "next_round":
            await self._set_aside_checks(run)
            number = run.iteration + 1
            await skill_improvement_repo.create_iteration(
                self.db,
                organization_id=ctx.organization_id,
                run_id=run.id,
                number=number,
                note=consent.note,
            )
            values["iteration"] = number
        elif consent.note is not None:
            raise refused_field("note", "A note goes with Try again only")
        await skill_improvement_repo.update_run(self.db, run=run, values=values)
        if quote.check_estimate is not None:
            base = await self._base(line)
            if moved:
                await skill_improvement_repo.update_run(
                    self.db, run=run, values={"base_version_id": base.id}
                )
                await self._remeasure(ctx, run, await self._iteration(run))
            await self._start_check(ctx, run, line, consent.mode, base=base)
        else:
            stage = Stage(run.stage) if quote.mode == "resume" else Stage.PROPOSING
            await self._move(
                run, rules.Transition(Status.RUNNING, stage), actor_user_id=ctx.subject_id
            )
        return await self._read(ctx, run, line)

    async def apply(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, data: SkillImprovementApply
    ) -> SkillImprovementApplied:
        """Make the checked text the line's newest version, keeping the agents it made worse
        on theirs with `pin_worse`; the session is accepted in the same transaction.

        A catch-up makes the merge the fork's newest version and bases the fork on main's
        newest; a move to main makes it main's newest version, taken in from the fork.
        """
        line, run = await self._editable_row(ctx, skill_id, run_id, lock=True)
        check_id = await self._decidable(run)
        if run.purpose == Purpose.CATCH_UP.value:
            return await self._catch_up(ctx, line, run, check_id, data)
        merged_from_id = None
        if run.purpose == Purpose.TO_MAIN.value:
            merge = await self._merge(run)
            # The check is on main, so deciding it locks no fork: lock the skill and then the
            # fork, as every writer of the fork does, before reading whether it moved.
            await skill_repo.lock(self.db, run.skill_id)
            await skill_version_repo.get_fork(
                self.db,
                merge.fork_id,
                organization_id=run.organization_id,
                skill_id=run.skill_id,
                lock=True,
            )
            await self._refuse_merge_moved(run, line.skill)
            merged_from_id = merge.fork_version_id
        applied = await self.checks.apply(
            ctx,
            skill_id,
            check_id,
            SkillCheckApply(
                acknowledge_unknown=data.acknowledge_unknown,
                pin_worse=data.pin_worse,
                note=data.note,
            ),
            from_session=True,
            merged_from_id=merged_from_id,
        )
        outcome = (
            SkillImprovementOutcome.APPLIED_PINNED
            if applied.pinned
            else SkillImprovementOutcome.APPLIED
        )
        await self._decide(ctx, run, outcome, applied.version.id)
        return SkillImprovementApplied(
            session=await self._read(ctx, run, line),
            version_id=applied.version.id,
            version=applied.version.number,
            pinned=applied.pinned,
        )

    async def return_to_main(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, data: SkillImprovementReturn
    ) -> SkillImprovementReturned:
        """Move a caught-up fork's agents back to main, as its check of main alone allowed;
        the session is accepted, and the fork archived once nobody reads it.

        Raises:
            BadRequestError: The session is not a catch-up, main alone was not checked or
                made an agent worse, or it could not check some agents and that was not
                acknowledged; or no agent the fork still has could be moved, which leaves
                the session and its checks as they were.
            ConcurrentChangeError: The session has no result to decide on.
        """
        line, run = await self._editable_row(ctx, skill_id, run_id, lock=True)
        if run.purpose != Purpose.CATCH_UP.value:
            raise BadRequestError(
                message="Only a catch-up returns a fork's agents to main",
                details={"purpose": run.purpose},
            )
        await self._decidable(run)
        await self._refuse_merge_moved(run, line.skill)
        read = await self._read(ctx, run, line)
        if "return_to_main" not in read.outcomes:
            raise BadRequestError(
                message="Main alone was not checked, or made an agent worse; the fork's "
                "agents stay on it",
                details={"main_alone": read.main_alone},
            )
        assert run.fork_id is not None, "a catch-up runs on its fork"
        alone = await self._main_alone_check(run)
        assert alone is not None, "return to main is offered after main alone was checked"
        await self.checks.decidable_for_session(ctx, run.skill_id, alone.id)
        measured = await self.checks.read(ctx, run.skill_id, alone.id)
        unknown = measured.hidden_unknown + sum(
            1 for agent in measured.agents if agent.state is AgentState.UNKNOWN
        )
        if unknown and not data.acknowledge_unknown:
            raise refused_field(
                "acknowledge_unknown",
                "Main alone could not be checked on some agents; acknowledge them to return "
                "the fork's agents to main",
            )
        returned = await self.merges.return_to_main(ctx, run.skill_id, run.fork_id, ReturnToMain())
        if returned.remaining and all(item.refused for item in returned.agents):
            raise BadRequestError(
                message=(
                    "No agent could be moved back to main, so the session stays open with its "
                    "checks"
                ),
                details={
                    "agents": [
                        {"id": item.agent.id, "name": item.agent.name, "refused": item.refused}
                        for item in returned.agents
                    ],
                    "hidden": returned.hidden,
                },
            )
        await self._discard_checks(ctx, run)
        await self._decide(ctx, run, SkillImprovementOutcome.RETURNED_TO_MAIN, None)
        return SkillImprovementReturned(session=await self._read(ctx, run, line), returned=returned)

    async def _catch_up(
        self,
        ctx: AuthContext,
        line: SessionLine,
        run: SkillImprovementRun,
        check_id: UUID,
        data: SkillImprovementApply,
    ) -> SkillImprovementApplied:
        """Take a checked merge into the fork: nobody worse, and nobody unknown unasked."""
        await self._refuse_merge_moved(run, line.skill)
        check = await self.checks.decidable_for_session(ctx, run.skill_id, check_id)
        merged = await self.checks.read(ctx, run.skill_id, check_id)
        if merged.verdict is CheckVerdict.BLOCKED:
            raise BadRequestError(
                message="The merge made agents worse, so it is not taken into the fork",
                details={"verdict": merged.verdict},
            )
        unknown = merged.hidden_unknown + sum(
            1 for agent in merged.agents if agent.state is AgentState.UNKNOWN
        )
        if unknown and not data.acknowledge_unknown:
            raise refused_field(
                "acknowledge_unknown",
                "Some agents could not be checked; acknowledge them to take the merge in",
            )
        assert line.fork is not None, "a catch-up runs on its fork"
        version = await self.merges.accept_catch_up(
            ctx, skill=line.skill, fork=line.fork, merge=await self._merge(run)
        )
        await self.checks.record_decision(
            ctx,
            check,
            CheckOutcome.APPLY,
            version.id,
            acknowledged=data.acknowledge_unknown,
        )
        alone = await self._main_alone_check(run)
        if alone is not None and alone.status == CheckStatus.DONE.value:
            await self.checks.discard(ctx, run.skill_id, alone.id, from_session=True)
        await self._decide(ctx, run, SkillImprovementOutcome.CAUGHT_UP, version.id)
        return SkillImprovementApplied(
            session=await self._read(ctx, run, line),
            version_id=version.id,
            version=version.number,
            pinned=[],
        )

    async def fork(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, data: SkillImprovementFork
    ) -> SkillImprovementForked:
        """Make the checked text a fork for the agents the person picked, by default the ones it
        helped; main stays as it is."""
        line, run = await self._editable_row(ctx, skill_id, run_id, lock=True)
        if run.purpose != Purpose.IMPROVE.value:
            raise BadRequestError(
                message="A merge is taken in or moved back, not made a fork",
                details={"purpose": run.purpose},
            )
        check_id = await self._decidable(run)
        forked = await self.checks.fork(
            ctx,
            skill_id,
            check_id,
            SkillCheckFork(
                name=data.name,
                acknowledge_unknown=data.acknowledge_unknown,
                agent_ids=data.agent_ids,
            ),
            from_session=True,
        )
        await self._decide(
            ctx,
            run,
            SkillImprovementOutcome.FORKED,
            None if forked.fork.latest is None else forked.fork.latest.id,
        )
        return SkillImprovementForked(
            session=await self._read(ctx, run, line),
            fork=forked.fork,
            moved=forked.moved,
            draft_only=forked.draft_only,
        )

    async def estimate_recheck(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, data: SkillContinue
    ) -> SkillContinuationEstimate:
        """The price of checking the result's changes again, on the line as it is now."""
        line, run = await self._editable_row(ctx, skill_id, run_id)
        return await self._recheck_quote(
            ctx, line, run, data.mode or await self._mode_of(run), budget=data.budget_usd
        )

    async def recheck(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, consent: SkillContinuationConsent
    ) -> SkillImprovementRead:
        """Check the result's chosen changes again, on the line's current version.

        For a result its line moved past, or whose agents changed since its check - the
        decision then refuses with a conflict. No new proposal is written: the same
        edits are applied to what the line serves now, and measured on its agents.

        Raises:
            BadRequestError: The session has no result, or its changes no longer apply
                to the line as it is now.
            ConcurrentChangeError: The price or the text moved since it was quoted.
            PaymentRequiredError: The spending limit does not cover the check.
        """
        line, run = await self._editable_row(ctx, skill_id, run_id, lock=True)
        mode = consent.mode or await self._mode_of(run)
        quote = await self._recheck_quote(ctx, line, run, mode, budget=consent.budget_usd)
        if consent.candidate_hash != quote.candidate_hash or consent.estimate_usd < quote.total_usd:
            raise ConcurrentChangeError(
                message="The check's price changed since it was quoted; review it again",
                details={"estimate_usd": str(quote.total_usd)},
            )
        spent = await skill_improvement_repo.spent(
            self.db, run.id, organization_id=ctx.organization_id
        )
        budget = max(run.budget_usd, consent.budget_usd)
        if not rules.affordable(spent=spent, step_estimate=quote.total_usd, budget=budget):
            raise PaymentRequiredError(
                message="The spending limit does not cover this check",
                details={"estimate_usd": str(quote.total_usd), "budget_usd": str(budget)},
            )
        previous = await self._check(run)
        assert previous is not None, "a result is the outcome of its check"
        if previous.status == CheckStatus.DONE.value:
            await self.checks.discard(ctx, skill_id, previous.id, from_session=True)
        base = await self._base(line)
        await skill_improvement_repo.update_run(
            self.db,
            run=run,
            values={
                "base_version_id": base.id,
                "budget_usd": budget,
                "actor_user_id": ctx.user_id,
                "actor_api_key_id": ctx.api_key_id,
            },
        )
        iteration = await self._iteration(run)
        await skill_improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={"check_verdict": None, "verdict": None, "ended_at": None},
        )
        await self._remeasure(ctx, run, iteration)
        await self._start_check(ctx, run, line, mode, base=base)
        return await self._read(ctx, run, line)

    async def _recheck_quote(
        self,
        ctx: AuthContext,
        line: SessionLine,
        run: SkillImprovementRun,
        mode: CheckMode | None,
        *,
        budget: Decimal | None,
    ) -> SkillContinuationEstimate:
        if run.purpose != Purpose.IMPROVE.value:
            raise BadRequestError(
                message="A merge is checked once; start a new one to check it again",
                details={"purpose": run.purpose},
            )
        if run.status != Status.READY:
            raise BadRequestError(
                message="Only a result is checked again", details={"status": run.status}
            )
        base = await self._base(line)
        iteration = await self._iteration(run)
        start = await self._check_start(ctx, run, line, iteration, mode, base=base)
        assert start.candidate is not None, "a session checks a text it wrote"
        check = await self.checks.estimate(
            ctx,
            run.skill_id,
            start,
            exclude_conversations=await self._evidence_conversations(iteration),
        )
        spent = await skill_improvement_repo.spent(
            self.db, run.id, organization_id=ctx.organization_id
        )
        limit = _limit(run, budget)
        return SkillContinuationEstimate(
            mode="next_step",
            number=run.iteration,
            total_usd=check.at_most_usd,
            expected_usd=check.expected_usd,
            budget_usd=limit,
            affordable=check.affordable
            and rules.affordable(spent=spent, step_estimate=check.at_most_usd, budget=limit),
            candidate_hash=plan_hash(start.candidate.description, start.candidate.content, check),
            check_estimate=check,
        )

    async def retry(self, ctx: AuthContext, skill_id: UUID, run_id: UUID) -> SkillImprovementRead:
        """Run a failed step again, within the session's spending limit.

        A failed check is checked again on the same edits; no new proposal is paid for.
        """
        line, run = await self._editable_row(ctx, skill_id, run_id, lock=True)
        if run.status != Status.FAILED:
            raise BadRequestError(message="Only a failed step is retried")
        if run.stage == Stage.EVALUATING:
            await self._retry_check(ctx, run, line)
            return await self._read(ctx, run, line)
        stage = Stage.ANALYZING if run.stage in (None, Stage.ANALYZING, Stage.CLASSIFYING) else None
        if stage is not None:
            await skill_improvement_repo.update_run(
                self.db, run=run, values={"analysis_request_id": None}
            )
        else:
            iteration = await self._iteration(run)
            await skill_improvement_repo.update_iteration(
                self.db, iteration=iteration, values={"authoring_request_id": None}
            )
            stage = Stage.PROPOSING
        await skill_improvement_repo.update_run(
            self.db,
            run=run,
            values={"actor_user_id": ctx.user_id, "actor_api_key_id": ctx.api_key_id},
        )
        await self._move(run, rules.Transition(Status.RUNNING, stage), actor_user_id=ctx.subject_id)
        return await self._read(ctx, run, line)

    async def cancel(self, ctx: AuthContext, skill_id: UUID, run_id: UUID) -> SkillImprovementRead:
        """Stop the session where it is: its unfinished analysis or proposal stops, its check
        is stopped or set aside, and what it already checked stays readable.

        Like discarding, only for its creator or an organization admin: stopping sets
        aside a check somebody paid for.
        """
        line, run = await self._editable_row(ctx, skill_id, run_id, lock=True)
        if not self._may_discard(ctx, run):
            raise AuthorizationError(
                message="Only whoever started the session, or an organization admin, stops it",
                details={"permission": Perm.ORG_SETTINGS.value},
            )
        stage = None if run.stage is None else Stage(run.stage)
        await self._move(
            run, rules.Transition(Status.CANCELLED, stage), actor_user_id=ctx.subject_id
        )
        await self._stop_requests(run)
        await self._stop_check(run)
        await self._discard_checks(ctx, run)
        return await self._read(ctx, run, line)

    async def discard(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, data: ImprovementDiscard
    ) -> SkillImprovementRead:
        """End the session without applying anything: its creator or an organization admin."""
        line, run = await self._editable_row(ctx, skill_id, run_id, lock=True)
        if run.status == Status.ACCEPTED or run.outcome is not None:
            raise ConcurrentChangeError(
                message="This session was already decided", details={"outcome": run.outcome}
            )
        if not self._may_discard(ctx, run):
            raise AuthorizationError(
                message="Only whoever started the session, or an organization admin, discards it",
                details={"permission": Perm.ORG_SETTINGS.value},
            )
        stage = None if run.stage is None else Stage(run.stage)
        await self._discard_checks(ctx, run)
        await skill_improvement_repo.update_run(
            self.db, run=run, values={"outcome": SkillImprovementOutcome.DISCARDED.value}
        )
        await self._move(
            run, rules.Transition(Status.REJECTED, stage), actor_user_id=ctx.subject_id
        )
        return await self._read(ctx, run, line)

    async def _retry_check(
        self, ctx: AuthContext, run: SkillImprovementRun, line: SessionLine
    ) -> None:
        if run.purpose != Purpose.IMPROVE.value:
            await self._retry_merge_checks(ctx, run, line)
            return
        self._refuse_moved(run, line)
        iteration = await self._iteration(run)
        failed = await self._check(run)
        assert failed is not None, "a failed check is the attempt's"
        start = await self._check_start(ctx, run, line, iteration, CheckMode(failed.mode))
        quote = await self.checks.estimate(
            ctx,
            run.skill_id,
            start,
            exclude_conversations=await self._evidence_conversations(iteration),
        )
        if not await self._affordable(run, quote.at_most_usd):
            raise PaymentRequiredError(
                message="The spending limit does not cover checking the changes again",
                details={"estimate_usd": str(quote.at_most_usd), "budget_usd": str(run.budget_usd)},
            )
        await skill_improvement_repo.update_run(
            self.db,
            run=run,
            values={"actor_user_id": ctx.user_id, "actor_api_key_id": ctx.api_key_id},
        )
        await skill_improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={"check_verdict": None, "verdict": None, "ended_at": None},
        )
        await self._start_check(ctx, run, line, CheckMode(quote.mode))

    async def _retry_merge_checks(
        self, ctx: AuthContext, run: SkillImprovementRun, line: SessionLine
    ) -> None:
        """Check the merge again as it was checked; main alone again only if it did not
        finish with a verdict, which stands otherwise."""
        await self._refuse_merge_moved(run, line.skill)
        iteration = await self._iteration(run)
        failed = await self._check(run)
        assert failed is not None, "a failed check is the attempt's"
        mode = CheckMode(failed.mode)
        alone = await self._main_alone_check(run)
        main_alone = alone is not None and (
            alone.status != CheckStatus.DONE.value or alone.verdict is None
        )
        price = Decimal(0)
        for start, files in await self._merge_starts(run, line, mode, main_alone=main_alone):
            price += (await self.checks.estimate(ctx, run.skill_id, start, files=files)).at_most_usd
        if not await self._affordable(run, price):
            raise PaymentRequiredError(
                message="The spending limit does not cover checking the merge again",
                details={"estimate_usd": str(price), "budget_usd": str(run.budget_usd)},
            )
        await skill_improvement_repo.update_run(
            self.db,
            run=run,
            values={"actor_user_id": ctx.user_id, "actor_api_key_id": ctx.api_key_id},
        )
        await skill_improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={"check_verdict": None, "verdict": None, "ended_at": None},
        )
        await self._start_merge_checks(
            ctx, run, line, mode, main_alone=main_alone, keep_alone=alone is not None
        )

    async def _stop_requests(self, run: SkillImprovementRun) -> None:
        """Fail the session's unfinished analysis and proposal, so nothing more is paid for."""
        iterations = await skill_improvement_repo.list_iterations(
            self.db, organization_id=run.organization_id, run_id=run.id
        )
        for request_id in [
            run.analysis_request_id,
            *(iteration.authoring_request_id for iteration in iterations),
        ]:
            if request_id is None:
                continue
            request = await authoring_repo.get_request(
                self.db, request_id, organization_id=run.organization_id
            )
            assert request is not None, "a removed request clears the session's reference to it"
            if request.status in (
                AuthoringStatus.QUEUED.value,
                AuthoringStatus.RUNNING.value,
            ):
                await authoring_repo.update_request(
                    self.db,
                    request=request,
                    values={
                        "status": AuthoringStatus.FAILED.value,
                        "error": "The improvement session stopped.",
                        "finished_at": datetime.now(UTC),
                    },
                )

    async def refresh_check_verdict(self, check: SkillCheck, verdict: CheckVerdict) -> None:
        """Copy a judged check's new verdict onto the attempt it measured.

        Only the attempt's record changes: every verdict leaves the session at its
        result, and the Result step reads its outcomes from the check itself.
        """
        iteration = await skill_improvement_repo.iteration_for_check(
            self.db, check.id, organization_id=check.organization_id
        )
        if (
            iteration is None
            or iteration.skill_check_id != check.id
            or iteration.check_verdict is None
        ):
            return
        await skill_improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={
                "check_verdict": verdict.value,
                "verdict": (await self._attempt_verdict(check, verdict)).value,
            },
        )

    async def _attempt_verdict(
        self, check: SkillCheck, verdict: CheckVerdict
    ) -> ImprovementVerdict:
        """A check's verdict as the attempt's result. One that measured no agent - none
        reads the line, or none could be checked - says nothing of the change, though it
        may still be applied once the unknown agents are acknowledged."""
        rows = await skill_check_repo.list_agents(
            self.db, [check.id], organization_id=check.organization_id
        )
        if all(row.state == AgentState.UNKNOWN.value for row in rows):
            return ImprovementVerdict.INCONCLUSIVE
        return _VERDICTS[verdict]

    async def wake_for_check(self, check_id: UUID, *, organization_id: UUID) -> None:
        """Advance the session a finished check belongs to, rather than at the next sweep."""
        iteration = await skill_improvement_repo.iteration_for_check(
            self.db, check_id, organization_id=organization_id
        )
        if iteration is not None:
            await self.wake(iteration.run_id, organization_id=organization_id)

    async def wake(self, run_id: UUID, *, organization_id: UUID) -> None:
        """Advance a session as soon as a step it waits on ended, not at the next sweep."""
        run = await skill_improvement_repo.get_run(self.db, run_id, organization_id=organization_id)
        if run is not None and Status(run.status).active:
            await self._queue(run)

    async def sweep(self) -> int:
        """Queue an advance for every working session, and end those nobody took on in time."""
        count = 0
        after: UUID | None = None
        while rows := await skill_improvement_repo.list_active(self.db, after=after):
            for run_id, organization_id in rows:
                await self.wake(run_id, organization_id=organization_id)
                count += 1
            after = rows[-1][0]
        after = None
        now = datetime.now(UTC)
        while rows := await skill_improvement_repo.list_resting(self.db, after=after):
            for run_id, organization_id in rows:
                run = await skill_improvement_repo.get_run(
                    self.db, run_id, organization_id=organization_id, lock=True
                )
                # Listed resting, but a decision may have taken it while the lock waited.
                if run is None or not Status(run.status).open or Status(run.status).active:
                    continue
                if await self._end_if_left(run, now=now):
                    count += 1
            after = rows[-1][0]
        return count

    async def _end_if_left(self, run: SkillImprovementRun, *, now: datetime) -> bool:
        """End a session nobody took on for a week, or one its line moved past while it
        waited at Understand, stopped or failed - none of those has a step left on the line
        as it is now.

        A stopped or failed session is open too, holding its line, so it expires the same
        way. At Changes or with a result, a moved line leaves the session as it is: it reads
        as stale, and its edits are priced or checked again on the line as it is now. A
        merge whose fork or main moved on is over wherever it stopped: only a new merge
        reads their newest versions.
        """
        stage = None if run.stage is None else Stage(run.stage)
        if rules.expired(run.stage_started_at or run.created_at, now=now):
            await self._move(run, rules.Transition(Status.STALE, stage, StopReason.EXPIRED))
            await self._set_aside_checks(run)
            return True
        if run.purpose != Purpose.IMPROVE.value:
            skill = await skill_repo.get(self.db, run.skill_id, organization_id=run.organization_id)
            assert skill is not None, "a session goes with its skill"
            if await self._merge_moved(run, skill) is None:
                return False
            await self._move(run, rules.Transition(Status.STALE, stage, StopReason.STALE))
            await self._set_aside_checks(run)
            return True
        waiting_at_understand = run.status == Status.WAITING and run.stage != Stage.FILTERING
        if not waiting_at_understand and run.status not in (Status.STOPPED, Status.FAILED):
            return False
        skill = await skill_repo.get(self.db, run.skill_id, organization_id=run.organization_id)
        assert skill is not None, "a session goes with its skill"
        line = await self._line_of(skill, run)
        if line.latest == run.base_version_id and not line.archived:
            return False
        await self._move(run, rules.Transition(Status.STALE, stage, StopReason.STALE))
        await self._set_aside_checks(run)
        return True

    async def advance(self, run_id: UUID, organization_id: UUID) -> None:
        """Take the session one step, as whoever took its latest step."""
        run = await skill_improvement_repo.get_run(
            self.db, run_id, organization_id=organization_id, lock=True
        )
        if run is None or not Status(run.status).active:
            return
        stage = None if run.stage is None else Stage(run.stage)
        try:
            ctx = await job_context(
                self.db,
                organization_id=organization_id,
                user_id=run.actor_user_id or run.created_by_user_id,
                api_key_id=run.actor_api_key_id if run.actor_user_id else run.created_by_api_key_id,
            )
        except AuthenticationError:
            ctx = None
        if ctx is None:
            await self._stop_check(run)
            await self._move(run, rules.Transition(Status.STOPPED, stage, StopReason.PERMISSION))
            return
        skill = await skill_repo.get(self.db, run.skill_id, organization_id=organization_id)
        assert skill is not None, "a session goes with its skill and its fork"
        line = await self._line_of(skill, run)
        standing = SkillStanding(
            edits_skill=await resolve_access(
                self.db, ctx, line.skill, Perm.SKILLS_EDIT, resource_type=SKILL
            ),
            views_runs=ctx.has(Perm.RUNS_VIEW),
        )
        moved = rules.checked(
            stage,
            standing=standing,
            pinned=run.base_version_id,
            current=line.latest,
            archived=line.archived,
        )
        if moved is not None:
            await self._stop_check(run)
            await self._move(run, moved)
            return
        if run.purpose != Purpose.IMPROVE.value:
            await self._advance_merge(ctx, run, line, stage)
            return
        if stage in (None, Stage.ANALYZING):
            await self._analyze(ctx, run, line)
        elif stage == Stage.CLASSIFYING:
            await self._classified(run)
        elif stage == Stage.PROPOSING:
            await self._propose(ctx, run, line)
        elif stage == Stage.FILTERING:
            await self._filter(ctx, run)
        else:
            await self._judge(run)

    async def _analyze(self, ctx: AuthContext, run: SkillImprovementRun, line: SessionLine) -> None:
        pack = await self._evidence(ctx, line, run.window_days)
        if not pack.runs:
            await self._move(
                run, rules.Transition(Status.STOPPED, Stage.ANALYZING, StopReason.NO_DATA)
            )
            return
        price = (
            await self.authoring.estimate_pack(ctx, pack, improver_agent_id=run.improver_agent_id)
        ).estimate_usd
        if not await self._affordable(run, price):
            await self._move(
                run, rules.Transition(Status.STOPPED, Stage.ANALYZING, StopReason.BUDGET)
            )
            return
        request = await self.authoring.start_for_skill_session(
            ctx,
            kind=AuthoringKind.ANALYZE,
            skill_id=line.skill.id,
            session_id=run.id,
            estimate_usd=price,
            window_days=run.window_days,
            improver_agent_id=run.improver_agent_id,
        )
        await skill_improvement_repo.update_run(
            self.db, run=run, values={"analysis_request_id": request.id}
        )
        await self._audit(run, "child_started")
        await self._move(run, rules.Transition(Status.RUNNING, Stage.CLASSIFYING))

    async def _classified(self, run: SkillImprovementRun) -> None:
        if run.analysis_request_id is None:
            # Retention removed the analysis it waited on; it is read again.
            await self._move(run, rules.Transition(Status.RUNNING, Stage.ANALYZING))
            return
        request = await self._request(run, run.analysis_request_id)
        status = AuthoringStatus(request.status)
        if status in (AuthoringStatus.QUEUED, AuthoringStatus.RUNNING):
            return
        if status is AuthoringStatus.FAILED:
            await self._move(
                run, rules.Transition(Status.FAILED, Stage.CLASSIFYING, StopReason.PROPOSAL)
            )
            return
        problems = (request.report or {}).get("problems", [])
        moved = rules.after_classifying(
            "succeeded",
            agent_answers=sum(
                isinstance(item, dict) and item.get("cause") == "skill" for item in problems
            ),
            missing_knowledge=0,
        )
        assert moved is not None, "an ended analysis always moves the session"
        await self._move(run, moved)

    async def _advance_merge(
        self,
        ctx: AuthContext,
        run: SkillImprovementRun,
        line: SessionLine,
        stage: Stage | None,
    ) -> None:
        """A merge's steps: propose the conflicts' texts, stop at Changes, then judge its
        checks. A merge of versions that are no longer the lines' newest is over."""
        if await self._merge_moved(run, line.skill) is not None:
            await self._stop_check(run)
            await self._move(run, rules.Transition(Status.STALE, stage, StopReason.STALE))
        elif stage is None:
            await self._move(run, rules.Transition(Status.RUNNING, Stage.PROPOSING))
        elif stage == Stage.PROPOSING:
            await self._propose_merge(ctx, run, line)
        else:
            await self._judge(run)

    async def _propose_merge(
        self, ctx: AuthContext, run: SkillImprovementRun, line: SessionLine
    ) -> None:
        """Ask for a text for each conflict, once, then stop at Changes. Without the budget
        for it, or once the request failed, the conflicts wait for a person."""
        iteration = await self._iteration(run)
        if iteration.authoring_request_id is None:
            merge = await self._merge(run)
            if merge.conflicts:
                prompt = MERGE_ASK + self.merges.conflicts_prompt(merge)
                price = (
                    await self.authoring.estimate_call(
                        ctx, chars=len(prompt), improver_agent_id=run.improver_agent_id
                    )
                ).estimate_usd
                if await self._affordable(run, price):
                    request = await self.authoring.start_for_skill_session(
                        ctx,
                        kind=AuthoringKind.IMPROVE,
                        skill_id=line.skill.id,
                        session_id=run.id,
                        estimate_usd=price,
                        window_days=run.window_days,
                        improver_agent_id=run.improver_agent_id,
                    )
                    await skill_improvement_repo.update_iteration(
                        self.db, iteration=iteration, values={"authoring_request_id": request.id}
                    )
                    await self._audit(run, "child_started")
                    return
                await self._audit(run, "conflicts_left", reason="budget")
            await self._move(run, rules.Transition(Status.WAITING, Stage.FILTERING))
            return
        request = await self._request(run, iteration.authoring_request_id)
        if request.status in (AuthoringStatus.QUEUED.value, AuthoringStatus.RUNNING.value):
            return
        if request.status != AuthoringStatus.COMPLETED.value:
            await self._audit(run, "conflicts_left", reason="failed")
        await self._move(run, rules.Transition(Status.WAITING, Stage.FILTERING))

    async def _merge(self, run: SkillImprovementRun) -> SkillMerge:
        merge = await self.merges.merge_for_run(run.id, organization_id=run.organization_id)
        assert merge is not None, "a merge session is written with its merge"
        return merge

    async def _merge_moved(
        self, run: SkillImprovementRun, skill: Skill
    ) -> Literal["main", "fork"] | None:
        """Which side of a merge is no longer that line's newest version, if either."""
        merge = await self._merge(run)
        fork = await skill_version_repo.get_fork(
            self.db, merge.fork_id, organization_id=run.organization_id, skill_id=run.skill_id
        )
        if (
            fork is None
            or fork.archived_at is not None
            or SkillVersionService.line_latest(skill, fork) != merge.fork_version_id
        ):
            return "fork"
        if skill.latest_version_id != merge.main_version_id:
            return "main"
        return None

    async def _refuse_merge_moved(self, run: SkillImprovementRun, skill: Skill) -> None:
        """Refuse a step on a merge whose sides moved on: it would bring in versions that are
        no longer the newest, so a new merge has to read them."""
        moved = await self._merge_moved(run, skill)
        if moved is None:
            return
        doing = (
            "catching up" if run.purpose == Purpose.CATCH_UP.value else "moving the fork to main"
        )
        side = "Main" if moved == "main" else "The fork"
        raise ConcurrentChangeError(
            message=f"{side} changed while you were {doing}. Start again to include it.",
            code="LINE_MOVED",
            details={"moved": moved},
        )

    async def _main_alone_check(self, run: SkillImprovementRun) -> SkillCheck | None:
        """A catch-up's second check, of main's newest version alone, once it started."""
        iteration = await self._iteration(run)
        if iteration.main_alone_check_id is None:
            return None
        return await skill_check_repo.get(
            self.db, iteration.main_alone_check_id, organization_id=run.organization_id
        )

    async def _propose(self, ctx: AuthContext, run: SkillImprovementRun, line: SessionLine) -> None:
        iteration = await self._iteration(run)
        if iteration.authoring_request_id is None:
            pack = await self._evidence(ctx, line, run.window_days)
            price = (
                await self.authoring.estimate_pack(
                    ctx, pack, improver_agent_id=run.improver_agent_id
                )
            ).estimate_usd
            if not await self._affordable(run, price):
                await self._move(
                    run, rules.Transition(Status.STOPPED, Stage.PROPOSING, StopReason.BUDGET)
                )
                return
            request = await self.authoring.start_for_skill_session(
                ctx,
                kind=AuthoringKind.IMPROVE,
                skill_id=line.skill.id,
                session_id=run.id,
                estimate_usd=price,
                window_days=run.window_days,
                improver_agent_id=run.improver_agent_id,
            )
            await skill_improvement_repo.update_iteration(
                self.db, iteration=iteration, values={"authoring_request_id": request.id}
            )
            await self._audit(run, "child_started")
            return
        request = await self._request(run, iteration.authoring_request_id)
        batch = await authoring_repo.batch_for_request(
            self.db, request.id, organization_id=run.organization_id
        )
        hunks = (
            []
            if batch is None
            else await authoring_repo.list_hunks(
                self.db, organization_id=run.organization_id, batch_id=batch.id
            )
        )
        moved = rules.after_proposing(AuthoringStatus(request.status), hunks=len(hunks))
        if moved is None:
            return
        if batch is not None:
            await skill_improvement_repo.update_iteration(
                self.db, iteration=iteration, values={"batch_id": batch.id}
            )
        await self._move(run, moved)

    async def _filter(self, ctx: AuthContext, run: SkillImprovementRun) -> None:
        iteration = await self._iteration(run)
        assert iteration.batch_id is not None, "an attempt reaches filtering with its batch"
        hunks = await authoring_repo.list_hunks(
            self.db, organization_id=run.organization_id, batch_id=iteration.batch_id
        )
        kept, dropped = filtered(hunks, await self.base_of(run))
        await skill_improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={
                "included_hunk_ids": [hunk.id for hunk in kept],
                "dropped_hunk_ids": [UUID(item["hunk_id"]) for item in dropped],
                "dropped": dropped,
            },
        )
        await self._remeasure(ctx, run, iteration)
        await self._move(run, rules.after_filtering(kept=len(kept)))

    async def _start_check(
        self,
        ctx: AuthContext,
        run: SkillImprovementRun,
        line: SessionLine,
        mode: CheckMode | None,
        *,
        base: SkillVersion | None = None,
    ) -> None:
        iteration = await self._iteration(run)
        check = await self.checks.start(
            ctx,
            run.skill_id,
            await self._check_start(ctx, run, line, iteration, mode, base=base),
            source=CheckSource.SESSION,
            exclude_conversations=await self._evidence_conversations(iteration),
        )
        await skill_improvement_repo.update_iteration(
            self.db, iteration=iteration, values={"skill_check_id": check.id}
        )
        await self._move(
            run, rules.Transition(Status.RUNNING, Stage.EVALUATING), actor_user_id=ctx.subject_id
        )

    async def _check_start(
        self,
        ctx: AuthContext,
        run: SkillImprovementRun,
        line: SessionLine,
        iteration: SkillImprovementIteration,
        mode: CheckMode | None,
        *,
        base: SkillVersion | None = None,
    ) -> SkillCheckStart:
        text = candidate_text(base or await self.base_of(run), await self._chosen(ctx, iteration))
        if text is None:
            raise refused_field(
                "hunk_ids",
                "The chosen changes no longer apply to the skill as it is now; try again",
            )
        description, content = text
        return SkillCheckStart(
            fork_id=line.fork_id,
            candidate=CandidateText(description=description, content=content),
            mode=mode or CheckMode.QUICK,
        )

    async def _evidence_conversations(self, iteration: SkillImprovementIteration) -> list[UUID]:
        """The conversations the attempt's edits were written from, which its check never asks:
        those its proposal and the session's analysis read, and those of the runs an agent's
        Improve handed over. A change is not measured on the answers it was fitted to."""
        assert iteration.batch_id is not None, "only an attempt with edits is checked"
        org = iteration.organization_id
        batch = await authoring_repo.get_batch(self.db, iteration.batch_id, organization_id=org)
        assert batch is not None, "an attempt's batch goes with the attempt"
        run = await skill_improvement_repo.get_run(self.db, iteration.run_id, organization_id=org)
        assert run is not None, "an attempt goes with its session"
        found = dict.fromkeys(batch.evidence_conversation_ids)
        if run.analysis_request_id is not None:
            analysis = await self._request(run, run.analysis_request_id)
            found.update(
                dict.fromkeys(
                    UUID(value) for value in analysis.evidence.get("conversation_ids", [])
                )
            )
        seeded = [UUID(value) for value in (run.seed or {}).get("run_ids", [])]
        found.update(
            dict.fromkeys(
                await agent_run_repo.conversations_of_runs(self.db, seeded, organization_id=org)
            )
        )
        return list(found)

    async def _judge(self, run: SkillImprovementRun) -> None:
        """Carry the attempt's check into its result once every agent of the line is in.

        Every verdict waits for a person at the result, where the check's outcomes say
        what it allows: a person overturning one of its answers later changes those
        outcomes, never where the session stands. A catch-up waits for main alone too.
        """
        iteration = await self._iteration(run)
        check = await self._check(run)
        assert check is not None, "an attempt is evaluated by its check"
        alone = await self._main_alone_check(run)
        if CheckStatus.RUNNING.value in (
            check.status,
            None if alone is None else alone.status,
        ):
            return
        cost = await skill_improvement_repo.check_cost(
            self.db, check.id, organization_id=run.organization_id
        )
        # A check of main alone kept through a retry was started before the merge's new
        # check, and its cost was counted when the failed attempt was judged.
        if alone is not None and alone.created_at >= check.created_at:
            cost += await skill_improvement_repo.check_cost(
                self.db, alone.id, organization_id=run.organization_id
            )
        if check.verdict is None:
            await skill_improvement_repo.update_iteration(
                self.db,
                iteration=iteration,
                values={
                    "check_verdict": "failed",
                    "verdict": ImprovementVerdict.INCONCLUSIVE.value,
                    "cost_usd": iteration.cost_usd + cost,
                    "ended_at": datetime.now(UTC),
                },
            )
            await self._move(
                run, rules.Transition(Status.FAILED, Stage.EVALUATING, StopReason.EVAL)
            )
            return
        verdict = CheckVerdict(check.verdict)
        await skill_improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={
                "check_verdict": verdict.value,
                "verdict": (await self._attempt_verdict(check, verdict)).value,
                "cost_usd": iteration.cost_usd + cost,
                "ended_at": datetime.now(UTC),
            },
        )
        await skill_improvement_repo.update_run(
            self.db, run=run, values={"best_iteration_id": iteration.id}
        )
        await self._move(run, rules.Transition(Status.READY, Stage.JUDGING))

    async def _stop_check(self, run: SkillImprovementRun) -> None:
        """Stop the checks of a session that stops while they run, and keep what they cost."""
        if run.stage != Stage.EVALUATING:
            return
        for check in (await self._check(run), await self._main_alone_check(run)):
            if check is None or check.status != CheckStatus.RUNNING.value:
                continue
            await self.checks.stop_for_session(check)
            iteration = await self._iteration(run)
            cost = await skill_improvement_repo.check_cost(
                self.db, check.id, organization_id=run.organization_id
            )
            await skill_improvement_repo.update_iteration(
                self.db, iteration=iteration, values={"cost_usd": iteration.cost_usd + cost}
            )

    async def _discard_checks(self, ctx: AuthContext, run: SkillImprovementRun) -> None:
        """Set aside what the attempt's checks found, so nobody decides on them outside it."""
        for check in (await self._check(run), await self._main_alone_check(run)):
            if check is not None and check.status == CheckStatus.DONE.value:
                await self.checks.discard(ctx, run.skill_id, check.id, from_session=True)

    async def _set_aside_checks(self, run: SkillImprovementRun) -> None:
        """Set aside the attempt's finished checks once the session can no longer decide
        them, so none waits forever for a decision only the session could make."""
        for check in (await self._check(run), await self._main_alone_check(run)):
            if check is not None and check.status == CheckStatus.DONE.value:
                await self.checks.set_aside_for_session(check)

    async def _mode_of(self, run: SkillImprovementRun) -> CheckMode | None:
        """How the attempt's last check measured: a check again measures the same way."""
        check = await self._check(run)
        return None if check is None else CheckMode(check.mode)

    @staticmethod
    def _refuse_moved(run: SkillImprovementRun, line: SessionLine) -> None:
        """Refuse a step on a line that moved on since the session read it, or was archived."""
        if line.archived or line.latest != run.base_version_id:
            raise ConcurrentChangeError(
                message="The skill changed since this session read it",
                code="LINE_MOVED",
                details={"base_version_id": run.base_version_id, "latest": line.latest},
            )

    async def _check(self, run: SkillImprovementRun) -> SkillCheck | None:
        """The current attempt's check, once it started."""
        iteration = await self._iteration(run)
        if iteration.skill_check_id is None:
            return None
        return await skill_check_repo.get(
            self.db, iteration.skill_check_id, organization_id=run.organization_id
        )

    async def _decidable(self, run: SkillImprovementRun) -> UUID:
        """The check a person decides on: the result the session waits with."""
        if run.status != Status.READY:
            raise ConcurrentChangeError(
                message="The session has no result to decide on now",
                details={"status": run.status},
            )
        check = await self._check(run)
        assert check is not None, "a session waits with a result only after its check"
        return check.id

    async def _decide(
        self,
        ctx: AuthContext,
        run: SkillImprovementRun,
        outcome: SkillImprovementOutcome,
        version_id: UUID | None,
    ) -> None:
        await skill_improvement_repo.update_run(
            self.db,
            run=run,
            values={"outcome": outcome.value, "applied_version_id": version_id},
        )
        await self._move(
            run, rules.Transition(Status.ACCEPTED, Stage.JUDGING), actor_user_id=ctx.subject_id
        )

    async def _remeasure(
        self, ctx: AuthContext, run: SkillImprovementRun, iteration: SkillImprovementIteration
    ) -> None:
        """Record the hash and the description flag of what the attempt's check will measure."""
        chosen = await self._chosen(ctx, iteration)
        text = candidate_text(await self.base_of(run), chosen)
        await skill_improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={
                "candidate_hash": None if text is None else candidate_hash(*text),
                "description_changed": any(
                    hunk.kind == HunkKind.SKILL_DESCRIPTION.value for hunk in chosen
                ),
            },
        )

    async def _chosen(
        self, ctx: AuthContext, iteration: SkillImprovementIteration
    ) -> list[SpecProposalHunk]:
        assert iteration.batch_id is not None, "only an attempt with edits is measured"
        wanted = set(iteration.included_hunk_ids or [])
        hunks = await authoring_repo.list_hunks(
            self.db, organization_id=ctx.organization_id, batch_id=iteration.batch_id
        )
        return [hunk for hunk in hunks if hunk.id in wanted]

    async def _continue_merge(
        self,
        ctx: AuthContext,
        line: SessionLine,
        run: SkillImprovementRun,
        consent: SkillContinuationConsent,
    ) -> None:
        """Check the merge at the price a person agreed to; a merge has no other step."""
        if consent.note is not None:
            raise refused_field("note", "A note goes with Try again only")
        quote = await self._merge_continuation(
            ctx,
            line,
            run,
            mode=consent.mode,
            main_alone=consent.main_alone,
            budget=consent.budget_usd,
        )
        if consent.candidate_hash != quote.candidate_hash or consent.estimate_usd < quote.total_usd:
            raise ConcurrentChangeError(
                message="The step's price changed since it was quoted; review it again",
                details={"estimate_usd": str(quote.total_usd)},
            )
        spent = await skill_improvement_repo.spent(
            self.db, run.id, organization_id=ctx.organization_id
        )
        budget = max(run.budget_usd, consent.budget_usd)
        if not rules.affordable(spent=spent, step_estimate=quote.total_usd, budget=budget):
            raise PaymentRequiredError(
                message="The spending limit does not cover this step",
                details={"estimate_usd": str(quote.total_usd), "budget_usd": str(budget)},
            )
        await skill_improvement_repo.update_run(
            self.db,
            run=run,
            values={
                "budget_usd": budget,
                "actor_user_id": ctx.user_id,
                "actor_api_key_id": ctx.api_key_id,
            },
        )
        await self._start_merge_checks(ctx, run, line, consent.mode, main_alone=consent.main_alone)

    async def _merge_continuation(
        self,
        ctx: AuthContext,
        line: SessionLine,
        run: SkillImprovementRun,
        *,
        mode: CheckMode | None,
        main_alone: bool,
        budget: Decimal | None,
    ) -> SkillContinuationEstimate:
        """The price of checking the merge at Changes, main alone priced as its own line,
        against `budget` when it raises the session's limit."""
        if not (run.status == Status.WAITING and run.stage == Stage.FILTERING):
            raise BadRequestError(
                message="The session has no step for a person to take now",
                details={"status": run.status, "stage": run.stage},
            )
        await self._refuse_merge_moved(run, line.skill)
        starts = await self._merge_starts(run, line, mode, main_alone=main_alone)
        checks = [
            await self.checks.estimate(ctx, run.skill_id, start, files=files)
            for start, files in starts
        ]
        merged, alone = checks[0], checks[1] if len(checks) > 1 else None
        total = sum((check.at_most_usd for check in checks), Decimal(0))
        spent = await skill_improvement_repo.spent(
            self.db, run.id, organization_id=ctx.organization_id
        )
        limit = _limit(run, budget)
        return SkillContinuationEstimate(
            mode="next_step",
            number=run.iteration,
            total_usd=total,
            expected_usd=sum((check.expected_usd for check in checks), Decimal(0)),
            budget_usd=limit,
            affordable=all(check.affordable for check in checks)
            and rules.affordable(spent=spent, step_estimate=total, budget=limit),
            candidate_hash=merge_hash(starts, checks),
            check_estimate=merged,
            main_alone_usd=None if alone is None else alone.at_most_usd,
            main_alone_estimate=alone,
        )

    async def _merge_starts(
        self,
        run: SkillImprovementRun,
        line: SessionLine,
        mode: CheckMode | None,
        *,
        main_alone: bool,
    ) -> list[tuple[SkillCheckStart, tuple[SkillBodyFile, ...]]]:
        """The merged text with its files, and for a catch-up main's newest alone, unless
        the merge is main itself."""
        merge = await self._merge(run)
        merged = await self.merges.candidate_of(merge)
        if merged is None:
            raise BadRequestError(
                message="Resolve every conflict before checking the merge",
                details={"unresolved": merge.unresolved},
            )
        mode = mode or CheckMode.QUICK
        starts = [
            (
                SkillCheckStart(
                    fork_id=line.fork_id,
                    candidate=CandidateText(description=merged.description, content=merged.content),
                    mode=mode,
                ),
                merged.files,
            )
        ]
        if run.purpose == Purpose.CATCH_UP.value and main_alone:
            main = await self._main_latest(line.skill)
            files = await self._files_of(main)
            if not _same_skill(merged.description, merged.content, merged.files, main, files):
                starts.append(
                    (
                        SkillCheckStart(
                            fork_id=line.fork_id,
                            candidate=CandidateText(
                                description=main.description, content=main.content
                            ),
                            mode=mode,
                        ),
                        files,
                    )
                )
        return starts

    async def _start_merge_checks(
        self,
        ctx: AuthContext,
        run: SkillImprovementRun,
        line: SessionLine,
        mode: CheckMode | None,
        *,
        main_alone: bool,
        keep_alone: bool = False,
    ) -> None:
        """Start the merge's checks; with `keep_alone`, a check of main alone not started
        again keeps the one the attempt has."""
        iteration = await self._iteration(run)
        started = [
            await self.checks.start(
                ctx, run.skill_id, start, source=CheckSource.SESSION, files=files
            )
            for start, files in await self._merge_starts(run, line, mode, main_alone=main_alone)
        ]
        alone = iteration.main_alone_check_id if keep_alone else None
        await skill_improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={
                "skill_check_id": started[0].id,
                "main_alone_check_id": started[1].id if len(started) > 1 else alone,
            },
        )
        await self._move(
            run, rules.Transition(Status.RUNNING, Stage.EVALUATING), actor_user_id=ctx.subject_id
        )

    async def _main_latest(self, skill: Skill) -> SkillVersion:
        assert skill.latest_version_id is not None, "every skill has a main version"
        version = await skill_version_repo.get_version(
            self.db,
            skill.latest_version_id,
            organization_id=skill.organization_id,
            skill_id=skill.id,
        )
        assert version is not None, "a skill's newest version is one of its own"
        return version

    async def _files_of(self, version: SkillVersion) -> tuple[SkillBodyFile, ...]:
        """A version's files in full, as a check serves them."""
        contents = await self.versions.files_of(version)
        return tuple(
            SkillBodyFile(name=name, description=entry["description"], content=contents[name])
            for name, entry in sorted(version.resources.items())
        )

    async def _continuation(
        self,
        ctx: AuthContext,
        line: SessionLine,
        run: SkillImprovementRun,
        *,
        mode: CheckMode | None,
        budget: Decimal | None,
    ) -> tuple[SkillContinuationEstimate, bool]:
        """The next step's quote against `budget` when it raises the session's limit, and
        whether the organization's and the helper's budgets cover it - the session's own
        limit may be raised with consent, those may not.

        Raises:
            BadRequestError: A proposal would have nothing on the line to learn from.
        """
        spent = await skill_improvement_repo.spent(
            self.db, run.id, organization_id=ctx.organization_id
        )
        limit = _limit(run, budget)
        if run.status == Status.WAITING and run.stage == Stage.FILTERING:
            # A line that moved since Changes is priced on its newest version: the same
            # chosen edits, applied to what the line serves now.
            if line.archived:
                self._refuse_moved(run, line)
            iteration = await self._iteration(run)
            start = await self._check_start(
                ctx, run, line, iteration, mode, base=await self._base(line)
            )
            assert start.candidate is not None, "a session checks a text it wrote"
            check = await self.checks.estimate(
                ctx,
                run.skill_id,
                start,
                exclude_conversations=await self._evidence_conversations(iteration),
            )
            return SkillContinuationEstimate(
                mode="next_step",
                number=run.iteration,
                total_usd=check.at_most_usd,
                expected_usd=check.expected_usd,
                budget_usd=limit,
                affordable=check.affordable
                and rules.affordable(spent=spent, step_estimate=check.at_most_usd, budget=limit),
                candidate_hash=plan_hash(
                    start.candidate.description, start.candidate.content, check
                ),
                check_estimate=check,
            ), check.affordable
        self._refuse_moved(run, line)
        step: Literal["next_step", "next_round", "resume"]
        if run.status == Status.WAITING and run.stage == Stage.CLASSIFYING:
            step, number = "next_step", run.iteration
        elif (
            run.status == Status.STOPPED
            and run.stop_reason in _RESUMABLE
            and run.stage in _BEFORE_A_PROPOSAL
        ):
            # Stopped before the attempt wrote anything: the same step again, not a new
            # attempt, so a raised limit or regained access loses nothing paid for.
            step, number = "resume", run.iteration
        elif run.status in (Status.READY, Status.STOPPED) and run.stage not in (
            None,
            Stage.ANALYZING,
            Stage.CLASSIFYING,
        ):
            if run.iteration >= run.max_iterations:
                raise BadRequestError(
                    message="The session has used all its attempts",
                    details={"max_iterations": run.max_iterations},
                )
            step, number = "next_round", run.iteration + 1
        else:
            raise BadRequestError(
                message="The session has no step for a person to take now",
                details={"status": run.status, "stage": run.stage},
            )
        pack = await self._evidence(ctx, line, run.window_days)
        priced = await self.authoring.estimate_pack(
            ctx, pack, improver_agent_id=run.improver_agent_id
        )
        if priced.reason is not None:
            raise BadRequestError(
                message=(
                    "Nothing to learn from on this line now: no answer in the session's window "
                    "that loaded it was rated down or failed"
                ),
                details={"reason": priced.reason},
            )
        price = priced.estimate_usd
        return SkillContinuationEstimate(
            mode=step,
            number=number,
            total_usd=price,
            expected_usd=price,
            budget_usd=limit,
            affordable=priced.affordable
            and rules.affordable(spent=spent, step_estimate=price, budget=limit),
            candidate_hash=hashlib.sha256(f"{run.base_version_id}:{number}".encode()).hexdigest(),
        ), priced.affordable

    async def _read(
        self,
        ctx: AuthContext,
        run: SkillImprovementRun,
        line: SessionLine,
        *,
        people: Mapping[UUID, PersonRef] | None = None,
        line_agents: tuple[int, int] | None = None,
    ) -> SkillImprovementRead:
        """One session as the console reads it. `people` names who started it, and
        `line_agents` counts its line's agents, each read once for a whole page by the
        caller listing many; a single read looks both up."""
        iterations = await skill_improvement_repo.list_iterations(
            self.db, organization_id=ctx.organization_id, run_id=run.id
        )
        base = await skill_version_repo.get_version(
            self.db, run.base_version_id, organization_id=ctx.organization_id, skill_id=run.skill_id
        )
        visible, hidden = line_agents or await self._line_agents(ctx, line)
        result = SkillImprovementRead.model_validate(run)
        result.line_name = line.name
        result.base_version = (
            None if base is None else SkillVersionRef(id=base.id, number=base.number)
        )
        result.agents, result.hidden_agents = visible, hidden
        if people is None:
            people = await self.versions.people(ctx, [run.created_by_user_id])
        result.created_by = _starter(people, run.created_by_user_id)
        result.iterations = [
            SkillImprovementIterationRead.model_validate(item) for item in iterations
        ]
        result.spent_usd = await skill_improvement_repo.spent(
            self.db, run.id, organization_id=ctx.organization_id
        )
        if run.status == Status.WAITING:
            result.next_step = "check" if run.stage == Stage.FILTERING else "propose"
        if run.status in _AWAITING_PERSON:
            result.expires_at = (run.stage_started_at or run.created_at) + rules.WAIT_LIMIT
        result.can_restart = (
            run.purpose == Purpose.IMPROVE.value
            and run.status in (Status.READY, Status.STOPPED)
            and run.stage not in (None, Stage.ANALYZING, Stage.CLASSIFYING)
            and run.iteration < run.max_iterations
            and line.latest == run.base_version_id
            and not line.archived
        )
        result.can_discard = self._may_discard(ctx, run)
        result.timeline = await self._timeline(ctx, run)
        check = await self._check(run)
        if check is not None:
            result.check = await self.checks.read(ctx, run.skill_id, check.id)
            if run.status == Status.READY:
                result.outcomes = [*result.check.outcomes]
        at_changes_or_result = run.status == Status.READY or (
            run.status == Status.WAITING and run.stage == Stage.FILTERING
        )
        result.stale = at_changes_or_result and line.latest != run.base_version_id
        if run.purpose != Purpose.IMPROVE.value:
            result.stale = at_changes_or_result and (
                await self._merge_moved(run, line.skill) is not None
            )
            await self._read_merge(ctx, run, line, result)
        return result

    async def _read_merge(
        self,
        ctx: AuthContext,
        run: SkillImprovementRun,
        line: SessionLine,
        result: SkillImprovementRead,
    ) -> None:
        """A merge session's merge, main alone, and the outcomes its purpose allows."""
        merge = await self._merge(run)
        result.merge_id = merge.id
        alone = await self._main_alone_check(run)
        if alone is not None:
            result.main_alone_check = await self.checks.read(ctx, run.skill_id, alone.id)
        if run.purpose == Purpose.CATCH_UP.value and result.check is not None:
            result.main_alone = (
                "checked" if alone is not None else await self._why_not_main_alone(merge, line)
            )
        if run.status == Status.READY and result.check is not None:
            # A merge of versions that are no longer the newest can only be set aside.
            result.outcomes = (
                [CheckOutcome.DISCARD]
                if result.stale
                else merge_outcomes(Purpose(run.purpose), result.check, result.main_alone_check)
            )

    async def _why_not_main_alone(
        self, merge: SkillMerge, line: SessionLine
    ) -> Literal["off", "same"]:
        merged = await self.merges.candidate_of(merge)
        main = await self._main_latest(line.skill)
        if merged is not None and _same_skill(
            merged.description, merged.content, merged.files, main, await self._files_of(main)
        ):
            return "same"
        return "off"

    async def _timeline(self, ctx: AuthContext, run: SkillImprovementRun) -> list[ImprovementEvent]:
        events = await skill_improvement_repo.timeline(
            self.db, run.id, organization_id=ctx.organization_id
        )
        actors = {
            event.id: UUID(actor)
            for event in events
            if isinstance(actor := (event.details or {}).get("actor"), str)
        }
        people = (
            await user_repo.get_many(self.db, list(set(actors.values())))
            if ctx.has(Perm.MEMBERS_VIEW)
            else {}
        )
        timeline: list[ImprovementEvent] = []
        for event in events:
            details = event.details or {}
            actor = actors.get(event.id)
            person = None if actor is None else people.get(actor)
            timeline.append(
                ImprovementEvent(
                    action=event.action,
                    at=event.created_at,
                    stage=details.get("stage"),
                    status=details.get("status"),
                    reason=details.get("reason"),
                    actor_user_id=actor,
                    actor_name=None if person is None else person.full_name or person.email,
                )
            )
        return timeline

    async def _shown_runs(self, ctx: AuthContext, run_ids: set[UUID]) -> set[UUID]:
        """The runs a reader may see quoted: those of agents they may view."""
        owners = await agent_run_repo.agents_of_runs(
            self.db, list(run_ids), organization_id=ctx.organization_id
        )
        agents = await agent_repo.get_many(
            self.db, list(set(owners.values())), organization_id=ctx.organization_id
        )
        visible = await accessible_ids(
            self.db, ctx, list(agents.values()), Perm.AGENTS_VIEW, resource_type=AGENT
        )
        return {run_id for run_id, agent_id in owners.items() if agent_id in visible}

    @staticmethod
    def _hunk(hunk: SpecProposalHunk, base: SkillVersion, shown: set[UUID]) -> HunkRead:
        description = hunk.kind == HunkKind.SKILL_DESCRIPTION.value
        return HunkRead(
            id=hunk.id,
            kind=hunk.kind,
            origin=hunk.origin,
            status=hunk.status,
            old_text=hunk.old_text,
            new_text=hunk.new_text,
            edited_text=hunk.edited_text,
            accepted_text=hunk.accepted_text,
            context_before=hunk.context_before,
            context_after=hunk.context_after,
            capability_id=None,
            tool_id=None,
            base_name=None,
            base_description=hunk.base_description,
            new_name=None,
            new_description=hunk.new_description,
            rationale=hunk.rationale,
            expected_effect=hunk.expected_effect,
            evidence=[
                EvidenceItemRead(
                    run_id=UUID(item["run_id"]),
                    quote=item.get("quote"),
                    source=item.get("source"),
                    number=item.get("number"),
                )
                for item in hunk.evidence
                if UUID(item["run_id"]) in shown
            ],
            evidence_dropped=hunk.evidence_dropped,
            evidence_hidden=sum(UUID(item["run_id"]) not in shown for item in hunk.evidence),
            applies=description
            or authoring_hunks.apply_text(base.content, hunk, hunk.new_text) is not None,
            decided_at=hunk.decided_at,
        )

    async def _at_changes(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID
    ) -> tuple[SessionLine, SkillImprovementRun, SkillImprovementIteration]:
        line, run = await self._editable_row(ctx, skill_id, run_id, lock=True)
        if run.status != Status.WAITING or run.stage != Stage.FILTERING:
            raise BadRequestError(
                message="Changes are chosen and edited only while the session waits for its check"
            )
        iteration = await self._iteration(run)
        assert iteration.batch_id is not None, "a session waits at Changes with its batch"
        return line, run, iteration

    async def _editable_row(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, *, lock: bool = False
    ) -> tuple[SessionLine, SkillImprovementRun]:
        self._require_runs_view(ctx)
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        if not await resolve_access(self.db, ctx, skill, Perm.SKILLS_EDIT, resource_type=SKILL):
            raise AuthorizationError(
                message="Taking a skill session's steps needs edit access to the skill",
                details={"permission": Perm.SKILLS_EDIT.value},
            )
        if lock:
            # The skill before the session: deleting the skill locks it and then cascades
            # into its sessions, and every decision locks the skill anyway.
            locked = await skill_repo.lock(self.db, skill.id)
            if locked is None:
                raise NotFoundError(message="Skill not found", details={"skill_id": skill_id})
        run = await self._row(ctx, skill, run_id, lock=lock)
        return await self._line_of(skill, run), run

    async def _row(
        self, ctx: AuthContext, skill: Skill, run_id: UUID, *, lock: bool = False
    ) -> SkillImprovementRun:
        run = await skill_improvement_repo.get_run(
            self.db, run_id, organization_id=ctx.organization_id, lock=lock
        )
        if run is None or run.skill_id != skill.id:
            raise NotFoundError(
                message="Improvement session not found", details={"improvement_run_id": run_id}
            )
        return run

    async def _line(
        self, ctx: AuthContext, skill_id: UUID, fork_id: UUID | None, perm: Perm
    ) -> SessionLine:
        skill = await self.versions.skill_for(ctx, skill_id, perm)
        if fork_id is None:
            return SessionLine(skill, None)
        fork = await skill_version_repo.get_fork(
            self.db, fork_id, organization_id=ctx.organization_id, skill_id=skill.id
        )
        if fork is None:
            raise refused_field("fork_id", "No such fork of this skill")
        return SessionLine(skill, fork)

    async def line_for_session(self, ctx: AuthContext, run: SkillImprovementRun) -> SessionLine:
        """The skill and fork a session improves, for whoever runs its steps."""
        skill = await skill_repo.get(self.db, run.skill_id, organization_id=ctx.organization_id)
        if skill is None:
            raise NotFoundError(message="Skill not found", details={"skill_id": run.skill_id})
        return await self._line_of(skill, run)

    async def evidence_of(
        self, ctx: AuthContext, line: SessionLine, run: SkillImprovementRun
    ) -> EvidencePack:
        """What the session's analysis and proposals read."""
        return await self._evidence(ctx, line, run.window_days)

    async def _line_of(self, skill: Skill, run: SkillImprovementRun) -> SessionLine:
        if run.fork_id is None:
            return SessionLine(skill, None)
        fork = await skill_version_repo.get_fork(
            self.db, run.fork_id, organization_id=skill.organization_id, skill_id=skill.id
        )
        return SessionLine(skill, fork)

    async def _line_agents(self, ctx: AuthContext, line: SessionLine) -> tuple[int, int]:
        agents = [
            reached.agent
            for reached in await self.skill_agents.line_agents(line.skill, line.fork_id)
        ]
        visible = await accessible_ids(self.db, ctx, agents, Perm.AGENTS_VIEW, resource_type=AGENT)
        return len(visible), len(agents) - len(visible)

    async def _evidence(
        self, ctx: AuthContext, line: SessionLine, window_days: int
    ) -> EvidencePack:
        """The bad answers of the line's agents that loaded a version of this line.

        A fork with no version of its own serves its base, a main version, and is read
        through it.
        """
        versions, _ = await skill_version_repo.list_versions(
            self.db,
            organization_id=ctx.organization_id,
            skill_id=line.skill.id,
            fork_id=line.fork_id,
            limit=_LINE_VERSIONS,
        )
        ids = [version.id for version in versions]
        if line.fork is not None and not ids:
            ids = [line.fork.base_version_id]
        readers = [
            reached.agent.id
            for reached in await self.skill_agents.line_agents(line.skill, line.fork_id)
        ]
        return await self.authoring.evidence.for_skill(
            ctx, line.skill.id, window_days=window_days, versions=ids, readers=readers
        )

    async def _base(self, line: SessionLine) -> SkillVersion:
        latest = line.latest
        assert latest is not None, "every line serves a version"
        version = await skill_version_repo.get_version(
            self.db, latest, organization_id=line.skill.organization_id, skill_id=line.skill.id
        )
        assert version is not None, "a line's latest version is one of its own"
        return version

    async def base_of(self, run: SkillImprovementRun) -> SkillVersion:
        """The line's version the session's edits are anchored on."""
        version = await skill_version_repo.get_version(
            self.db, run.base_version_id, organization_id=run.organization_id, skill_id=run.skill_id
        )
        assert version is not None, "a session's base is a version its line served"
        return version

    async def _iteration(self, run: SkillImprovementRun) -> SkillImprovementIteration:
        iteration = await skill_improvement_repo.get_iteration(
            self.db, organization_id=run.organization_id, run_id=run.id, number=run.iteration
        )
        assert iteration is not None, "a session holds a row for its current attempt"
        return iteration

    async def _request(self, run: SkillImprovementRun, request_id: UUID) -> AuthoringRequest:
        request = await authoring_repo.get_request(
            self.db, request_id, organization_id=run.organization_id
        )
        assert request is not None, "a removed request clears the session's reference to it"
        # A request whose worker went silent is settled as failed, which fails the step.
        return await self.authoring.settled(request)

    async def _affordable(self, run: SkillImprovementRun, price: Decimal) -> bool:
        spent = await skill_improvement_repo.spent(
            self.db, run.id, organization_id=run.organization_id
        )
        return rules.affordable(spent=spent, step_estimate=price, budget=run.budget_usd)

    async def _move(
        self,
        run: SkillImprovementRun,
        transition: rules.Transition,
        *,
        actor_user_id: UUID | None = None,
    ) -> None:
        if not rules.can_move(Status(run.status), transition.status):
            raise ConcurrentChangeError(
                message=f"This session is {run.status} and cannot become {transition.status.value}",
                details={"status": run.status, "to": transition.status.value},
            )
        now = datetime.now(UTC)
        status = transition.status
        await skill_improvement_repo.update_run(
            self.db,
            run=run,
            values={
                "status": status.value,
                "stage": None if transition.stage is None else transition.stage.value,
                "stop_reason": None
                if transition.stop_reason is None
                else transition.stop_reason.value,
                "heartbeat_at": now,
                "stage_started_at": now,
                "finished_at": None if status.active or status is Status.WAITING else now,
            },
        )
        await self._audit(
            run,
            "stage_changed" if status.active else status.value,
            actor_user_id=actor_user_id,
        )
        if status.active:
            await self._queue(run)

    async def _queue(self, run: SkillImprovementRun) -> None:
        iteration = await skill_improvement_repo.get_iteration(
            self.db, organization_id=run.organization_id, run_id=run.id, number=run.iteration
        )
        marker = (
            f"{run.analysis_request_id}"
            if iteration is None
            else f"{run.analysis_request_id}:{iteration.authoring_request_id}"
        )
        await enqueue(
            self.db,
            ADVANCE_SKILL_IMPROVEMENT,
            AdvanceSkillImprovement(run_id=run.id, organization_id=run.organization_id),
            organization_id=run.organization_id,
            concurrency_key=f"skill-improvement:{run.skill_id}",
            dedupe_key=f"{run.id}:{run.status}:{run.stage}:{run.iteration}:{marker}",
            dedupe_active=True,
        )

    async def _audit(
        self,
        run: SkillImprovementRun,
        action: str,
        *,
        actor_user_id: UUID | None = None,
        reason: str | None = None,
    ) -> None:
        """Record a step on the session's timeline; the session's own steps name no actor."""
        details: dict[str, str | None] = {
            "stage": run.stage,
            "status": run.status,
            "reason": reason or run.stop_reason,
            "skill_id": str(run.skill_id),
            "fork_id": None if run.fork_id is None else str(run.fork_id),
        }
        if actor_user_id is not None:
            details["actor"] = str(actor_user_id)
        await record_audit(
            self.db,
            actor_user_id=actor_user_id or run.created_by_user_id,
            organization_id=run.organization_id,
            action=f"skill.improvement_{action}",
            target_type=skill_improvement_repo.TIMELINE_TARGET,
            target_id=str(run.id),
            details=details,
        )

    @staticmethod
    def _may_discard(ctx: AuthContext, run: SkillImprovementRun) -> bool:
        return ctx.user_id == run.created_by_user_id or ctx.has(Perm.ORG_SETTINGS)

    @staticmethod
    def _require_runs_view(ctx: AuthContext) -> None:
        if not ctx.has(Perm.RUNS_VIEW):
            raise AuthorizationError(
                message="A skill session reads runs, which needs runs:view",
                details={"permission": Perm.RUNS_VIEW.value},
            )


def _limit(run: SkillImprovementRun, budget: Decimal | None) -> Decimal:
    """The spending limit a step is priced against: a person may raise it, never lower it."""
    return run.budget_usd if budget is None else max(run.budget_usd, budget)


def _starter(people: Mapping[UUID, PersonRef], user_id: UUID | None) -> PersonRef | None:
    """Who started a session, as far as the reader may know; nobody for one with no starter."""
    return people.get(user_id) if user_id is not None else None

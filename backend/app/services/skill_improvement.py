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

Nothing here writes a skill: a session ends at a person's decision at the latest.
"""

import hashlib
import json
import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.db.models.improvement import DroppedHunk, StopReason
from app.db.models.improvement import ImprovementStage as Stage
from app.db.models.improvement import ImprovementStatus as Status
from app.db.models.skill import Skill
from app.db.models.skill_improvement import (
    SkillImprovementIteration,
    SkillImprovementOutcome,
    SkillImprovementRun,
)
from app.db.models.skill_version import SkillFork, SkillVersion
from app.repositories import (
    agent_repo,
    agent_run_repo,
    authoring_repo,
    organization_repo,
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
from app.schemas.skill_improvement import (
    ProblemAgent,
    SkillContinuationConsent,
    SkillContinuationEstimate,
    SkillImprovementAwaiting,
    SkillImprovementEstimate,
    SkillImprovementIterationRead,
    SkillImprovementProblems,
    SkillImprovementRead,
    SkillImprovementStart,
    SkillImprovementTarget,
    SkillLine,
    SkillProblemExample,
    SkillProblemRead,
    SkillVersionRef,
)
from app.services import authoring_hunks
from app.services import improvement_states as rules
from app.services.access import AGENT, SKILL, accessible_ids, resolve_access
from app.services.api_key import job_context
from app.services.authoring import AuthoringService
from app.services.authoring_evidence import EvidencePack
from app.services.background_jobs import enqueue
from app.services.skill_agents import SkillAgentService
from app.services.skill_versions import SkillVersionService
from app.worker.jobs import ADVANCE_SKILL_IMPROVEMENT, AdvanceSkillImprovement

logger = logging.getLogger(__name__)

_AWAITING_PERSON = (Status.WAITING.value, Status.READY.value)
_LINE_VERSIONS = 500
"""Versions of one line the evidence is read for; a line holds far fewer."""


@dataclass(frozen=True)
class SkillStanding:
    """Whether the person a skill session acts for may still do what it does."""

    edits_skill: bool
    views_runs: bool
    ai_assistance: bool

    @property
    def allowed(self) -> bool:
        return self.edits_skill and self.views_runs and self.ai_assistance


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

    async def estimate(
        self, ctx: AuthContext, skill_id: UUID, target: SkillImprovementTarget
    ) -> SkillImprovementEstimate:
        """What a session on the line would read and cost before it first waits for a person."""
        self._require_runs_view(ctx)
        line = await self._line(ctx, skill_id, target.fork_id, Perm.SKILLS_EDIT)
        pack = await self._evidence(ctx, line, target.window_days)
        priced = await self.authoring.estimate_pack(ctx, pack)
        visible, hidden = await self._line_agents(ctx, line)
        base = await self._base(line)
        return SkillImprovementEstimate(
            line=SkillLine(fork_id=line.fork_id, name=line.name),
            base_version=SkillVersionRef(id=base.id, number=base.number),
            proposal_usd=priced.estimate_usd * 2,
            per_round_usd=priced.estimate_usd,
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
        estimate = await self.estimate(ctx, skill_id, data)
        line = await self._line(ctx, skill_id, data.fork_id, Perm.SKILLS_EDIT)
        if line.archived:
            raise refused_field("fork_id", "An archived fork cannot be improved")
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
                    seed_run_ids=[],
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
        return [await self._read(ctx, row, await self._line_of(skill, row)) for row in rows]

    async def read(self, ctx: AuthContext, skill_id: UUID, run_id: UUID) -> SkillImprovementRead:
        self._require_runs_view(ctx)
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        run = await self._row(ctx, skill, run_id)
        return await self._read(ctx, run, await self._line_of(skill, run))

    async def awaiting(self, ctx: AuthContext) -> list[SkillImprovementAwaiting]:
        """Sessions waiting for a person - at a stop, or with a result - on skills the caller
        may read."""
        self._require_runs_view(ctx)
        rows = await skill_improvement_repo.list_for_person(
            self.db, organization_id=ctx.organization_id, statuses=_AWAITING_PERSON
        )
        skills = {
            skill.id: skill
            for skill in [
                await skill_repo.get(self.db, skill_id, organization_id=ctx.organization_id)
                for skill_id in dict.fromkeys(row.skill_id for row in rows)
            ]
            if skill is not None
            and await resolve_access(self.db, ctx, skill, Perm.SKILLS_VIEW, resource_type=SKILL)
        }
        awaiting: list[SkillImprovementAwaiting] = []
        for row in rows:
            skill = skills.get(row.skill_id)
            if skill is None:
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
        owners = await agent_run_repo.agents_of_runs(
            self.db, list(run_ids), organization_id=ctx.organization_id
        )
        agents = await agent_repo.get_many(
            self.db, list(set(owners.values())), organization_id=ctx.organization_id
        )
        visible = await accessible_ids(
            self.db, ctx, list(agents.values()), Perm.AGENTS_VIEW, resource_type=AGENT
        )
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
                    ],
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
        return [self._hunk(hunk, base) for hunk in hunks]

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
        return self._hunk(hunk, await self.base_of(run))

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
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID
    ) -> SkillContinuationEstimate:
        """The price of the step a person may take now: a proposal after Understand, or Try
        again after a stop or a result."""
        line, run = await self._editable_row(ctx, skill_id, run_id)
        return await self._continuation(ctx, line, run)

    async def continue_run(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, consent: SkillContinuationConsent
    ) -> SkillImprovementRead:
        """Take the next step, or try again with a note, at the price a person agreed to.

        Raises:
            ConcurrentChangeError: The price or what it measures moved since it was quoted.
            PaymentRequiredError: The spending limit does not cover the step.
        """
        line, run = await self._editable_row(ctx, skill_id, run_id, lock=True)
        quote = await self._continuation(ctx, line, run)
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
        values: dict[str, object] = {
            "budget_usd": budget,
            "actor_user_id": ctx.user_id,
            "actor_api_key_id": ctx.api_key_id,
        }
        if quote.mode == "next_round":
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
        await self._move(
            run, rules.Transition(Status.RUNNING, Stage.PROPOSING), actor_user_id=ctx.subject_id
        )
        return await self._read(ctx, run, line)

    async def retry(self, ctx: AuthContext, skill_id: UUID, run_id: UUID) -> SkillImprovementRead:
        """Run a failed step again, within the session's spending limit."""
        line, run = await self._editable_row(ctx, skill_id, run_id, lock=True)
        if run.status != Status.FAILED:
            raise BadRequestError(message="Only a failed step is retried")
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
        """Stop the session where it is; what it already checked stays readable."""
        line, run = await self._editable_row(ctx, skill_id, run_id, lock=True)
        stage = None if run.stage is None else Stage(run.stage)
        await self._move(
            run, rules.Transition(Status.CANCELLED, stage), actor_user_id=ctx.subject_id
        )
        return await self._read(ctx, run, line)

    async def discard(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, data: ImprovementDiscard
    ) -> SkillImprovementRead:
        """End the session without applying anything: its creator or an organization admin."""
        line, run = await self._editable_row(ctx, skill_id, run_id, lock=True)
        if not self._may_discard(ctx, run):
            raise AuthorizationError(
                message="Only whoever started the session, or an organization admin, discards it"
            )
        stage = None if run.stage is None else Stage(run.stage)
        await skill_improvement_repo.update_run(
            self.db, run=run, values={"outcome": SkillImprovementOutcome.DISCARDED.value}
        )
        await self._move(
            run, rules.Transition(Status.REJECTED, stage), actor_user_id=ctx.subject_id
        )
        return await self._read(ctx, run, line)

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
                if run is not None and rules.expired(
                    run.stage_started_at or run.created_at, now=now
                ):
                    stage = None if run.stage is None else Stage(run.stage)
                    await self._move(run, rules.Transition(Status.STALE, stage, StopReason.EXPIRED))
                    count += 1
            after = rows[-1][0]
        return count

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
            await self._move(run, rules.Transition(Status.STOPPED, stage, StopReason.PERMISSION))
            return
        skill = await skill_repo.get(self.db, run.skill_id, organization_id=organization_id)
        assert skill is not None, "a session goes with its skill and its fork"
        line = await self._line_of(skill, run)
        organization = await organization_repo.get_by_id(self.db, organization_id)
        standing = SkillStanding(
            edits_skill=await resolve_access(
                self.db, ctx, line.skill, Perm.SKILLS_EDIT, resource_type=SKILL
            ),
            views_runs=ctx.has(Perm.RUNS_VIEW),
            ai_assistance=organization is not None and organization.ai_assistance_enabled,
        )
        moved = rules.checked(
            stage,
            standing=standing,
            pinned=run.base_version_id,
            current=line.latest,
            archived=line.archived,
        )
        if moved is not None:
            await self._move(run, moved)
            return
        if stage in (None, Stage.ANALYZING):
            await self._analyze(ctx, run, line)
        elif stage == Stage.CLASSIFYING:
            await self._classified(run)
        elif stage == Stage.PROPOSING:
            await self._propose(ctx, run, line)
        elif stage == Stage.FILTERING:
            await self._filter(ctx, run)

    async def _analyze(self, ctx: AuthContext, run: SkillImprovementRun, line: SessionLine) -> None:
        pack = await self._evidence(ctx, line, run.window_days)
        if not pack.runs:
            await self._move(
                run, rules.Transition(Status.STOPPED, Stage.ANALYZING, StopReason.NO_DATA)
            )
            return
        price = (await self.authoring.estimate_pack(ctx, pack)).estimate_usd
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

    async def _propose(self, ctx: AuthContext, run: SkillImprovementRun, line: SessionLine) -> None:
        iteration = await self._iteration(run)
        if iteration.authoring_request_id is None:
            pack = await self._evidence(ctx, line, run.window_days)
            price = (await self.authoring.estimate_pack(ctx, pack)).estimate_usd
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

    async def _continuation(
        self, ctx: AuthContext, line: SessionLine, run: SkillImprovementRun
    ) -> SkillContinuationEstimate:
        if run.status == Status.WAITING and run.stage == Stage.CLASSIFYING:
            mode, number = "next_step", run.iteration
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
            mode, number = "next_round", run.iteration + 1
        else:
            raise BadRequestError(
                message="The session has no step for a person to take now",
                details={"status": run.status, "stage": run.stage},
            )
        pack = await self._evidence(ctx, line, run.window_days)
        price = (await self.authoring.estimate_pack(ctx, pack)).estimate_usd
        spent = await skill_improvement_repo.spent(
            self.db, run.id, organization_id=ctx.organization_id
        )
        return SkillContinuationEstimate(
            mode=mode,
            number=number,
            total_usd=price,
            expected_usd=price,
            budget_usd=run.budget_usd,
            affordable=rules.affordable(spent=spent, step_estimate=price, budget=run.budget_usd),
            candidate_hash=hashlib.sha256(f"{run.base_version_id}:{number}".encode()).hexdigest(),
        )

    async def _read(
        self, ctx: AuthContext, run: SkillImprovementRun, line: SessionLine
    ) -> SkillImprovementRead:
        iterations = await skill_improvement_repo.list_iterations(
            self.db, organization_id=ctx.organization_id, run_id=run.id
        )
        base = await skill_version_repo.get_version(
            self.db, run.base_version_id, organization_id=ctx.organization_id, skill_id=run.skill_id
        )
        visible, hidden = await self._line_agents(ctx, line)
        result = SkillImprovementRead.model_validate(run)
        result.line_name = line.name
        result.base_version = (
            None if base is None else SkillVersionRef(id=base.id, number=base.number)
        )
        result.agents, result.hidden_agents = visible, hidden
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
            run.status in (Status.READY, Status.STOPPED)
            and run.stage not in (None, Stage.ANALYZING, Stage.CLASSIFYING)
            and run.iteration < run.max_iterations
        )
        result.can_discard = self._may_discard(ctx, run)
        result.timeline = await self._timeline(ctx, run)
        return result

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

    @staticmethod
    def _hunk(hunk: SpecProposalHunk, base: SkillVersion) -> HunkRead:
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
            ],
            evidence_dropped=hunk.evidence_dropped,
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
        """The bad answers that loaded a version of this line.

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
        return await self.authoring.evidence.for_skill(
            ctx, line.skill.id, window_days=window_days, versions=ids
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
        self, run: SkillImprovementRun, action: str, *, actor_user_id: UUID | None = None
    ) -> None:
        """Record a step on the session's timeline; the session's own steps name no actor."""
        details: dict[str, str | None] = {
            "stage": run.stage,
            "status": run.status,
            "reason": run.stop_reason,
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

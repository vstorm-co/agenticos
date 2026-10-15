"""Eval runs: an agent answering every case of a dataset version, and how it compares.

A person starts a run from an agent: a dataset version, a candidate (a published
version or the draft), the environment whose test connections the cases use, and
optionally several models and a baseline in the same run. Nothing runs until the
estimate has been shown and the run is started; starting refuses before anything
is written when the estimate would take the agent or the organization past what
it has left this month.

Every case is then an ordinary agent run - stamped `eval`, budget-checked before
each model call, recorded in Activity - executed in the background by
:mod:`app.services.eval_run_worker` and scored by the scoring service.

The comparison follows the rules a decision can rest on:

* a run that backs a decision (`purpose=gate`) runs its baseline in the same run,
  because providers drift between days; a recent matching baseline may stand in;
* a case that flipped is rerun, so regressions are reported confirmed or not;
* the verdict rests on confirmed flips alone, and a pass rate on each case's
  settled outcome - the majority of its attempts;
* two sides scored by different scoring or a different judge do not compare;
* quality and efficiency are separate axes.

Callers beyond the HTTP API - suites, the promotion gate, the authoring
assistant - start runs through :meth:`EvalRunService.start` with their own
`purpose`, scoring override or candidate spec, and read the verdict through
:meth:`EvalRunService.compare`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import price_request
from app.agents.spec import AgentSpec
from app.agents.system_agents import JUDGE
from app.core.background import spawn_after_commit
from app.core.config import settings
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    PaymentRequiredError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.case_score import CaseScore
from app.db.models.dataset import Dataset, DatasetCase, DatasetVersion
from app.db.models.eval_run import (
    ArmRole,
    ArmSource,
    CaseAttemptStatus,
    EvalRun,
    EvalRunArm,
    EvalRunCase,
    EvalRunPurpose,
    EvalRunStatus,
)
from app.repositories import (
    agent_repo,
    agent_run_repo,
    dataset_repo,
    eval_run_repo,
    organization_repo,
)
from app.schemas.dataset import StoredCaseContent
from app.schemas.eval_run import (
    ArmEstimate,
    ArmSummaryRead,
    CaseFlipRead,
    ComparisonSide,
    EfficiencyRead,
    EvalAttemptRead,
    EvalCallRead,
    EvalCaseLinkRead,
    EvalCaseList,
    EvalCaseRead,
    EvalComparisonRead,
    EvalOutcomeRead,
    EvalRunArmRead,
    EvalRunEstimate,
    EvalRunList,
    EvalRunRead,
    EvalRunRequest,
)
from app.schemas.scoring import CaseScoreRead, DatasetScoring
from app.services.access import AGENT, DATASET, accessible_ids, resolve_access
from app.services.agent_registry import (
    AgentRegistryService,
    PublishedCandidate,
    UnpublishedCandidate,
)
from app.services.ai_assistance import AiAssistanceService
from app.services.dataset import DatasetService
from app.services.eval_comparison import (
    ArmSummary,
    Attempt,
    Flip,
    Outcome,
    PairedCase,
    efficiency,
    flips_by_tag,
    quality_verdict,
    summarize,
)
from app.services.model_profile import ModelProfileService
from app.services.spend import month_start, organization_monthly_spend

logger = logging.getLogger(__name__)

_CENT = Decimal("0.000001")


def scoring_hash(scoring: DatasetScoring) -> str:
    """A fingerprint of the scoring a run used: equal only when every setting is."""
    canonical = json.dumps(scoring.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def spec_hash(spec: AgentSpec) -> str:
    """A fingerprint of a spec, equal for equal specs whatever order their keys were written in."""
    canonical = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def attempt_outcome(attempt: EvalRunCase, score: CaseScore | None) -> Outcome:
    """Pass, fail, or undecided - a person's verdict before the scorers'."""
    if attempt.status != CaseAttemptStatus.DONE.value or score is None:
        return None
    return score.human_passed if score.human_passed is not None else score.passed


def _check_type(check: object) -> str | None:
    return check.get("type") if isinstance(check, dict) else None


def scoring_refusal(
    scoring: DatasetScoring, cases: Sequence[DatasetCase], *, ai_enabled: bool
) -> BadRequestError | None:
    """Why no case of this version could be decided, or `None` when one can.

    A run whose every case ends undecided spends money to say nothing. Each
    required scorer is checked against what the cases hold: a check needs a
    check to apply, the trajectory an expected call, and the judge - for a
    rubric, a reference answer or a judge check - needs AI assistance on.
    """
    checks, trajectory = scoring.checks, scoring.trajectory
    judge, reference = scoring.judge, scoring.reference
    rubric = judge.enabled and any(criterion.required for criterion in judge.criteria)
    judged = False
    for case in cases:
        own = [_check_type(check) for check in case.checks]
        if checks.enabled and checks.required:
            if scoring.checks.defaults or any(kind != "judge" for kind in own):
                return None
            judged = judged or "judge" in own
        if trajectory.enabled and trajectory.required and case.expected_tool_calls:
            return None
        if reference.enabled and reference.required and case.reference_answer:
            judged = True
        judged = judged or rubric
    if judged and ai_enabled:
        return None
    if judged:
        return BadRequestError(
            message=(
                "The judge needs AI assistance, which is off for this organization, and "
                "nothing else in this dataset's scoring can decide a case. Turn AI "
                "assistance on in the organization's settings, or add a check."
            ),
            details={"reason": "ai_assistance_off"},
        )
    return BadRequestError(
        message=(
            "Nothing in this dataset's scoring can decide a case. Add a check, an "
            "expected tool call, or enable the judge."
        ),
        details={"reason": "no_scorer"},
    )


@dataclass(frozen=True)
class ArmPlan:
    """One arm as it will run: what, on which model, and whether it is reused."""

    role: ArmRole
    source: ArmSource
    version: AgentVersion | None
    spec: AgentSpec
    model_profile_id: UUID | None
    model_label: str
    cached: tuple[EvalRunArm, EvalRun] | None = None


@dataclass(frozen=True)
class RunPlan:
    """Everything a run is, decided before it is estimated or written."""

    agent: Agent
    dataset: Dataset
    dataset_version: DatasetVersion
    cases: list[DatasetCase]
    scoring: DatasetScoring
    scoring_hash: str
    arms: list[ArmPlan]
    environment_id: UUID | None
    purpose: EvalRunPurpose
    paired: bool
    reruns: int
    from_recordings: bool
    live_reads: bool
    judged: bool


@dataclass(frozen=True)
class Baseline:
    """What a candidate arm is compared with, and whether it ran beside it.

    `here` is this run's own arm standing in for a reused one: its first answers
    are the earlier run's, and the cases that flipped are asked of it again in
    this run, so both sides confirm a flip the same day.
    """

    arm: EvalRunArm
    run: EvalRun
    paired: bool
    here: EvalRunArm | None = None


def _summary_read(summary: ArmSummary) -> ArmSummaryRead:
    return ArmSummaryRead(
        cases=summary.cases,
        passed=summary.passed,
        failed=summary.failed,
        incomplete=summary.incomplete,
        pass_rate=summary.pass_rate,
        first_pass_rate=summary.first_pass_rate,
        cost_usd=summary.cost_usd,
        cost_per_pass_usd=summary.cost_per_pass,
        avg_tokens=summary.avg_tokens,
        p50_ms=summary.p50_ms,
        p95_ms=summary.p95_ms,
    )


def _attempt(
    attempt: EvalRunCase,
    score: CaseScore | None,
    tags: Sequence[str],
    reruns: Sequence[Outcome] = (),
) -> Attempt:
    tokens = (
        None
        if attempt.input_tokens is None and attempt.output_tokens is None
        else (attempt.input_tokens or 0) + (attempt.output_tokens or 0)
    )
    return Attempt(
        outcome=attempt_outcome(attempt, score),
        cost_usd=attempt.cost_usd,
        tokens=tokens,
        latency_ms=attempt.latency_ms,
        tags=tuple(tags),
        reruns=tuple(reruns),
        by_person=score is not None and score.human_passed is not None,
    )


class EvalRunService:
    """Estimating, starting, cancelling, reading and comparing eval runs."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)
        self.datasets = DatasetService(db)
        self.models = ModelProfileService(db)

    async def plan(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        request: EvalRunRequest,
        *,
        purpose: EvalRunPurpose = EvalRunPurpose.MANUAL,
        scoring: DatasetScoring | None = None,
        candidate_spec: AgentSpec | None = None,
    ) -> RunPlan:
        """Decide what a run is, refusing anything that could not or should not run.

        `scoring` is a suite's override of the dataset's own. `candidate_spec`
        runs a spec the caller built - the authoring assistant's projection -
        and the caller has already decided they may: it is validated against
        the caller's access like a draft, and attributed to no version.

        Raises:
            NotFoundError: The agent, dataset or environment cannot be reached.
            AuthorizationError: Running the draft without edit access to it.
            BadRequestError: An empty dataset version, scoring that decides
                nothing, an unpublished agent asked for a version, or a
                baseline with no earlier version to be.
        """
        dataset = await self.datasets.get(ctx, request.dataset_id, perm=Perm.DATASETS_RUN)
        dataset_version = await self._dataset_version(ctx, dataset, request.dataset_version)
        cases = await dataset_repo.list_cases(
            self.db, dataset_version.id, organization_id=ctx.organization_id, limit=None
        )
        if not cases:
            raise BadRequestError(
                message=f"Version {dataset_version.number} of '{dataset.name}' holds no cases",
                details={"dataset_id": dataset.id, "version": dataset_version.number},
            )
        config = scoring or DatasetScoring.model_validate(dataset.scoring)
        ai_enabled = await AiAssistanceService(self.db).is_enabled(
            organization_id=ctx.organization_id
        )
        refusal = scoring_refusal(config, cases, ai_enabled=ai_enabled)
        if refusal is not None:
            raise refusal

        agent = await self.registry.get(ctx, agent_id, perm=Perm.AGENTS_RUN)
        if agent.status == AgentStatus.ARCHIVED.value:
            raise BadRequestError(
                message=f"Agent '{agent.name}' is archived", details={"agent_id": agent.id}
            )
        source, version, spec = await self._candidate(ctx, agent, request, candidate_spec)
        candidates = [
            await self._arm(
                ctx,
                agent,
                role=ArmRole.CANDIDATE,
                source=source,
                version=version,
                spec=spec,
                model_profile_id=profile_id,
                environment_id=request.environment_id,
            )
            for profile_id in (request.model_profile_ids or [spec.model_profile_id])
        ]
        paired = request.paired_baseline or purpose is EvalRunPurpose.GATE
        hashed = scoring_hash(config)
        arms = list(candidates)
        if paired:
            baseline_version = await self._baseline_version(ctx, agent, request, source, version)
            baseline_spec = AgentSpec.model_validate(baseline_version.spec)
            profile_id = (
                request.model_profile_ids[0]
                if request.model_profile_ids
                else baseline_spec.model_profile_id
            )
            baseline = await self._arm(
                ctx,
                agent,
                role=ArmRole.BASELINE,
                source=ArmSource.VERSION,
                version=baseline_version,
                spec=baseline_spec,
                model_profile_id=profile_id,
                environment_id=request.environment_id,
            )
            cached = await self._cached(
                ctx,
                agent=agent,
                dataset=dataset,
                dataset_version=dataset_version,
                arm=baseline,
                scoring_hash=hashed,
                judged=ai_enabled and (config.judge.enabled or config.reference.enabled),
                judge_id=config.judge.agent_id,
            )
            arms.append(baseline if cached is None else replace(baseline, cached=cached))
        return RunPlan(
            agent=agent,
            dataset=dataset,
            dataset_version=dataset_version,
            cases=cases,
            scoring=config,
            scoring_hash=hashed,
            arms=arms,
            environment_id=request.environment_id,
            purpose=purpose,
            paired=paired,
            reruns=settings.EVAL_RERUNS if request.reruns is None else request.reruns,
            from_recordings=request.from_recordings,
            live_reads=request.live_reads,
            judged=ai_enabled and (config.judge.enabled or config.reference.enabled),
        )

    async def _dataset_version(
        self, ctx: AuthContext, dataset: Dataset, number: int | None
    ) -> DatasetVersion:
        wanted = number or dataset.latest_version
        version = (
            await dataset_repo.get_version(
                self.db, dataset.id, wanted, organization_id=ctx.organization_id
            )
            if wanted
            else None
        )
        if version is None:
            raise BadRequestError(
                message=(
                    f"'{dataset.name}' has no cases yet"
                    if not wanted
                    else f"'{dataset.name}' has no version {wanted}"
                ),
                details={"dataset_id": dataset.id, "version": number},
            )
        return version

    async def _candidate(
        self,
        ctx: AuthContext,
        agent: Agent,
        request: EvalRunRequest,
        candidate_spec: AgentSpec | None,
    ) -> tuple[ArmSource, AgentVersion | None, AgentSpec]:
        if candidate_spec is not None:
            return ArmSource.EXPLICIT, None, candidate_spec
        if request.candidate == "draft":
            # The draft is the editors' work in progress; running it is reading it.
            if not await resolve_access(self.db, ctx, agent, Perm.AGENTS_EDIT, resource_type=AGENT):
                raise AuthorizationError(
                    message="Running the draft needs edit access to the agent",
                    details={"agent_id": agent.id},
                )
            return ArmSource.DRAFT, None, AgentSpec.model_validate(agent.draft_spec)
        version = await self._version(ctx, agent, request.version)
        return ArmSource.VERSION, version, AgentSpec.model_validate(version.spec)

    async def _version(self, ctx: AuthContext, agent: Agent, number: int | None) -> AgentVersion:
        if number is not None:
            version = await agent_repo.get_version_by_number(
                self.db, agent_id=agent.id, number=number, organization_id=ctx.organization_id
            )
        elif agent.current_version_id is not None:
            version = await agent_repo.get_version(
                self.db, agent.current_version_id, organization_id=ctx.organization_id
            )
        else:
            raise BadRequestError(
                message=f"Agent '{agent.name}' has not been published yet; run its draft instead",
                details={"agent_id": agent.id},
            )
        if version is None:
            raise BadRequestError(
                message=f"Agent '{agent.name}' has no version {number}",
                details={"agent_id": agent.id, "version": number},
            )
        return version

    async def _baseline_version(
        self,
        ctx: AuthContext,
        agent: Agent,
        request: EvalRunRequest,
        source: ArmSource,
        version: AgentVersion | None,
    ) -> AgentVersion:
        """The version a candidate is measured against: named, or the obvious one.

        A draft or a projection is measured against what is published now; a
        version against the one before it.
        """
        if request.baseline_version is not None:
            return await self._version(ctx, agent, request.baseline_version)
        if source is not ArmSource.VERSION:
            return await self._version(ctx, agent, None)
        assert version is not None
        previous = await agent_repo.version_before(
            self.db, agent_id=agent.id, number=version.version, organization_id=ctx.organization_id
        )
        if previous is None:
            raise BadRequestError(
                message=(
                    f"Version {version.version} of '{agent.name}' is its first; there is no "
                    "earlier version to run as a baseline"
                ),
                details={"agent_id": agent.id, "version": version.version},
            )
        return previous

    async def _arm(
        self,
        ctx: AuthContext,
        agent: Agent,
        *,
        role: ArmRole,
        source: ArmSource,
        version: AgentVersion | None,
        spec: AgentSpec,
        model_profile_id: UUID | None,
        environment_id: UUID | None,
    ) -> ArmPlan:
        """One arm, checked now rather than at its first case.

        The same resolution a case's run will make: the environment must be the
        agent's, an unpublished spec must validate for the caller, and the model
        must resolve - so a run that cannot start is refused before it is
        written, not after it has been estimated and consented to.
        """
        candidate = (
            PublishedCandidate(version.id) if version is not None else UnpublishedCandidate(spec)
        )
        await self.registry.get_candidate_spec(
            ctx, agent.id, candidate, environment_id=environment_id
        )
        model = await self.models.resolve(ctx, profile_id=model_profile_id or spec.model_profile_id)
        return ArmPlan(
            role=role,
            source=source,
            version=version,
            spec=spec,
            model_profile_id=model_profile_id or spec.model_profile_id,
            model_label=model.label,
        )

    async def _judge_model(
        self, ctx: AuthContext, judge: Agent, scoring: DatasetScoring
    ) -> UUID | None:
        """The model the judge grades on: the dataset's choice, else its published spec's."""
        if scoring.judge.model_profile_id is not None:
            return scoring.judge.model_profile_id
        version = (
            await agent_repo.get_version(
                self.db, judge.current_version_id, organization_id=ctx.organization_id
            )
            if judge.current_version_id is not None
            else None
        )
        return AgentSpec.model_validate(version.spec).model_profile_id if version else None

    async def _judge_agent(self, ctx: AuthContext, judge_id: UUID | None) -> Agent | None:
        """The agent that grades a dataset: the judge it names, or the default one."""
        if judge_id is not None:
            return await agent_repo.get(self.db, judge_id, organization_id=ctx.organization_id)
        return await agent_repo.get_system(
            self.db, organization_id=ctx.organization_id, key=JUDGE.key
        )

    async def _cached(
        self,
        ctx: AuthContext,
        *,
        agent: Agent,
        dataset: Dataset,
        dataset_version: DatasetVersion,
        arm: ArmPlan,
        scoring_hash: str,
        judged: bool,
        judge_id: UUID | None,
    ) -> tuple[EvalRunArm, EvalRun] | None:
        """A completed baseline arm that may stand in for running this one.

        Only one that matches on everything the comparison holds constant: the
        version, the dataset version, the model, the scoring - and the judge,
        whose published version must be the one that graded every case, or no
        judge at all when none would grade now.
        """
        assert arm.version is not None
        since = datetime.now(UTC) - timedelta(hours=settings.EVAL_BASELINE_CACHE_HOURS)
        found = await eval_run_repo.latest_arm(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            dataset_id=dataset.id,
            agent_version_id=arm.version.id,
            dataset_version_id=dataset_version.id,
            model_profile_id=arm.model_profile_id,
            scoring_hash=scoring_hash,
            since=since,
        )
        if found is None:
            return None
        judge = await self._judge_agent(ctx, judge_id)
        attempts = await eval_run_repo.list_arm_cases(
            self.db, found[0].id, organization_id=ctx.organization_id
        )
        scores = await eval_run_repo.scores(
            self.db,
            [a.case_score_id for a in attempts if a.case_score_id is not None],
            organization_id=ctx.organization_id,
        )
        pinned = {
            (score.judge or {}).get("agent_version_id")
            for score in scores.values()
            if score.judge is not None
        }
        current = str(judge.current_version_id) if judge and judge.current_version_id else None
        # Graded by the judge that would grade now, or by none when none would.
        return found if pinned == ({current} if judged else set()) else None

    async def estimate(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        request: EvalRunRequest,
        *,
        purpose: EvalRunPurpose = EvalRunPurpose.MANUAL,
        scoring: DatasetScoring | None = None,
        candidate_spec: AgentSpec | None = None,
    ) -> EvalRunEstimate:
        """What a run would cost, against what the agent and organization have left."""
        plan = await self.plan(
            ctx, agent_id, request, purpose=purpose, scoring=scoring, candidate_spec=candidate_spec
        )
        return await self._estimate(ctx, plan)

    async def _per_case(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        model_label: str | None,
        profile_id: UUID | None = None,
    ) -> tuple[Decimal, bool]:
        """What one case costs: this agent's recent runs on the model, or - with
        no history - a typical case at the model's own price, or a flat guess
        for a model nothing prices. The flag says whether it was history."""
        average = await agent_run_repo.average_cost(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            model_label=model_label,
            sample=settings.EVAL_ESTIMATE_SAMPLE,
        )
        if average is not None:
            return average.quantize(_CENT), True
        if profile_id is not None:
            model = await self.models.resolve(ctx, profile_id=profile_id)
            typical = RunUsage(
                input_tokens=settings.EVAL_FALLBACK_INPUT_TOKENS,
                output_tokens=settings.EVAL_FALLBACK_OUTPUT_TOKENS,
            )
            priced = price_request(typical, model.model, model.provider)
            if priced is not None:
                return Decimal(priced).quantize(_CENT), False
        return settings.EVAL_FALLBACK_CASE_COST_USD, False

    async def _estimate(self, ctx: AuthContext, plan: RunPlan) -> EvalRunEstimate:
        cases = len(plan.cases)
        arms: list[ArmEstimate] = []
        arms_usd = Decimal(0)
        rerun_per_case = Decimal(0)
        for arm in plan.arms:
            if arm.cached is not None:
                arms.append(
                    ArmEstimate(
                        role=arm.role,
                        source=arm.source,
                        version_number=arm.version.version if arm.version else None,
                        model_profile_id=arm.model_profile_id,
                        model_label=arm.model_label,
                        cost_per_case_usd=Decimal(0),
                        cost_usd=Decimal(0),
                        basis="cached",
                        cached_from_run_id=arm.cached[1].id,
                        cached_at=arm.cached[1].ended_at,
                    )
                )
                continue
            per_case, known = await self._per_case(
                ctx, plan.agent.id, arm.model_label, arm.model_profile_id
            )
            cost = per_case * cases
            arms_usd += cost
            rerun_per_case += per_case
            arms.append(
                ArmEstimate(
                    role=arm.role,
                    source=arm.source,
                    version_number=arm.version.version if arm.version else None,
                    model_profile_id=arm.model_profile_id,
                    model_label=arm.model_label,
                    cost_per_case_usd=per_case,
                    cost_usd=cost,
                    basis="history" if known else "fallback",
                )
            )
        judge_per_case = Decimal(0)
        if plan.judged:
            judge = await self._judge_agent(ctx, plan.scoring.judge.agent_id)
            judge_per_case = (
                (
                    await self._per_case(
                        ctx, judge.id, None, await self._judge_model(ctx, judge, plan.scoring)
                    )
                )[0]
                if judge is not None
                else settings.EVAL_FALLBACK_CASE_COST_USD
            )
        fresh_arms = sum(1 for arm in plan.arms if arm.cached is None)
        judge_usd = judge_per_case * cases * fresh_arms
        total = arms_usd + judge_usd
        rerun_ceiling = (rerun_per_case + judge_per_case * fresh_arms) * cases * plan.reruns

        agent_left = await self._agent_left(ctx, plan)
        org_left = await self._org_left(ctx)
        return EvalRunEstimate(
            cases=cases,
            arms=arms,
            judge_usd=judge_usd,
            total_usd=total,
            rerun_ceiling_usd=rerun_ceiling,
            agent_remaining_usd=agent_left,
            org_remaining_usd=org_left,
            # The judge bills to its own agent; only the organization pays both.
            agent_after_usd=None if agent_left is None else agent_left - arms_usd,
            org_after_usd=None if org_left is None else org_left - total,
            affordable=(agent_left is None or arms_usd <= agent_left)
            and (org_left is None or total <= org_left),
        )

    async def _agent_left(self, ctx: AuthContext, plan: RunPlan) -> Decimal | None:
        cap = plan.arms[0].spec.budget.monthly_usd if plan.arms[0].spec.budget else None
        if cap is None:
            return None
        spent = await agent_run_repo.sum_cost_since(
            self.db,
            organization_id=ctx.organization_id,
            since=month_start(),
            agent_id=plan.agent.id,
            include_delegations=True,
        )
        return Decimal(str(cap)) - spent

    async def _org_left(self, ctx: AuthContext) -> Decimal | None:
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        if organization is None or organization.monthly_budget_usd is None:
            return None
        spent = await organization_monthly_spend(self.db, ctx.organization_id)
        return organization.monthly_budget_usd - spent

    async def start(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        request: EvalRunRequest,
        *,
        purpose: EvalRunPurpose = EvalRunPurpose.MANUAL,
        scoring: DatasetScoring | None = None,
        candidate_spec: AgentSpec | None = None,
    ) -> EvalRunRead:
        """Write a run and hand it to the worker - or refuse it before anything is spent.

        Raises:
            PaymentRequiredError: The estimate is more than the agent or the
                organization has left this month. Nothing is written.
        """
        plan = await self.plan(
            ctx, agent_id, request, purpose=purpose, scoring=scoring, candidate_spec=candidate_spec
        )
        estimate = await self._estimate(ctx, plan)
        if not estimate.affordable:
            raise PaymentRequiredError(
                message=(
                    "This eval would cost more than is left in the budget this month. "
                    "Run fewer cases or models, or raise the budget."
                ),
                details={
                    # Money is stringified deliberately: a Decimal encodes to a float.
                    "estimate_usd": str(estimate.total_usd),
                    "agent_remaining_usd": _money(estimate.agent_remaining_usd),
                    "org_remaining_usd": _money(estimate.org_remaining_usd),
                },
            )
        run = EvalRun(
            agent_id=plan.agent.id,
            dataset_id=plan.dataset.id,
            dataset_version_id=plan.dataset_version.id,
            environment_id=plan.environment_id,
            created_by_user_id=ctx.user_id,
            status=EvalRunStatus.QUEUED.value,
            purpose=plan.purpose.value,
            paired=plan.paired,
            from_recordings=plan.from_recordings,
            live_reads=plan.live_reads,
            reruns=plan.reruns,
            scoring=plan.scoring.model_dump(mode="json", by_alias=True),
            scoring_hash=plan.scoring_hash,
            estimate_usd=estimate.total_usd,
            rerun_ceiling_usd=estimate.rerun_ceiling_usd,
        )
        arms = [
            EvalRunArm(
                role=arm.role.value,
                position=position,
                source=arm.source.value,
                agent_version_id=arm.version.id if arm.version else None,
                version_number=arm.version.version if arm.version else None,
                spec=None if arm.version else arm.spec.model_dump(mode="json"),
                spec_hash=spec_hash(arm.spec),
                model_profile_id=arm.model_profile_id,
                model_label=arm.model_label,
                reused_from_arm_id=arm.cached[0].id if arm.cached else None,
            )
            for position, arm in enumerate(plan.arms)
        ]
        run = await eval_run_repo.create(
            self.db, organization_id=ctx.organization_id, run=run, arms=arms
        )
        await eval_run_repo.add_cases(
            self.db,
            organization_id=ctx.organization_id,
            cases=[
                EvalRunCase(
                    eval_run_id=run.id,
                    arm_id=arm.id,
                    case_id=case.case_id,
                    case_revision_id=case.id,
                    position=position,
                )
                for arm in arms
                if arm.reused_from_arm_id is None
                for position, case in enumerate(plan.cases)
            ],
        )
        from app.worker.tasks.eval_tasks import dispatch_eval_run

        spawn_after_commit(
            self.db,
            dispatch_eval_run(str(run.id), str(ctx.organization_id)),
            name=f"eval-run:{run.id}",
        )
        logger.info("Eval run %s queued: %d case(s), %d arm(s)", run.id, len(plan.cases), len(arms))
        return (await self._reads(ctx, [run]))[0]

    async def cancel(self, ctx: AuthContext, run_id: UUID) -> EvalRunRead:
        """Stop a run: what has started finishes, nothing else starts.

        Its creator may cancel it, and so may anyone who may edit the agent.
        """
        run = await self._readable(ctx, run_id)
        if run.created_by_user_id != ctx.user_id:
            agent = await self.registry.get(ctx, run.agent_id)
            if not await resolve_access(self.db, ctx, agent, Perm.AGENTS_EDIT, resource_type=AGENT):
                raise AuthorizationError(
                    message="Only whoever started this eval, or an editor of the agent, can stop it",
                    details={"eval_run_id": run.id},
                )
        locked = await eval_run_repo.lock(self.db, run.id, organization_id=ctx.organization_id)
        assert locked is not None
        if EvalRunStatus(locked.status).terminal:
            return (await self._reads(ctx, [locked]))[0]
        await eval_run_repo.update_run(
            self.db,
            run=locked,
            values={"status": EvalRunStatus.CANCELLED.value, "ended_at": datetime.now(UTC)},
        )
        await eval_run_repo.skip_pending(self.db, run.id, organization_id=ctx.organization_id)
        return (await self._reads(ctx, [locked]))[0]

    async def _readable(self, ctx: AuthContext, run_id: UUID) -> EvalRun:
        """A run the caller may read: their organization's, its agent and dataset visible."""
        self._require_runs_view(ctx)
        run = await eval_run_repo.get(self.db, run_id, organization_id=ctx.organization_id)
        if run is None:
            raise NotFoundError(message="Eval run not found", details={"eval_run_id": run_id})
        try:
            await self.registry.get(ctx, run.agent_id)
            await self.datasets.get(ctx, run.dataset_id)
        except NotFoundError:
            raise NotFoundError(
                message="Eval run not found", details={"eval_run_id": run_id}
            ) from None
        return run

    async def get(self, ctx: AuthContext, run_id: UUID) -> EvalRunRead:
        """One run, and - for a run of the draft - whether the draft changed since."""
        run = await self._readable(ctx, run_id)
        read = (await self._reads(ctx, [run]))[0]
        tested = next(
            (
                arm
                for arm in read.arms
                if arm.role == ArmRole.CANDIDATE and arm.source == ArmSource.DRAFT
            ),
            None,
        )
        if tested is None:
            return read
        agent = await self.registry.get(ctx, run.agent_id)
        current = spec_hash(AgentSpec.model_validate(agent.draft_spec))
        return read.model_copy(update={"draft_changed": current != tested.spec_hash})

    async def arm_spec(self, ctx: AuthContext, run_id: UUID, arm_id: UUID) -> AgentSpec:
        """The spec one side of a run answered with - what History compares a version with.

        A draft is the editors' work in progress, so reading it takes edit access
        to the agent, as running it did.
        """
        run = await self._readable(ctx, run_id)
        org = ctx.organization_id
        arm = next(
            (
                item
                for item in await eval_run_repo.list_arms(self.db, [run.id], organization_id=org)
                if item.id == arm_id
            ),
            None,
        )
        if arm is None:
            raise NotFoundError(message="Arm not found", details={"arm_id": arm_id})
        agent = await self.registry.get(ctx, run.agent_id)
        if not await resolve_access(self.db, ctx, agent, Perm.AGENTS_EDIT, resource_type=AGENT):
            raise AuthorizationError(
                message="Reading what a run tested needs edit access to the agent",
                details={"agent_id": agent.id},
            )
        if arm.spec is not None:
            return AgentSpec.model_validate(arm.spec)
        version = (
            await agent_repo.get_version(self.db, arm.agent_version_id, organization_id=org)
            if arm.agent_version_id is not None
            else None
        )
        if version is None:
            raise NotFoundError(
                message="The version this side ran is gone", details={"arm_id": arm_id}
            )
        return AgentSpec.model_validate(version.spec)

    @staticmethod
    def _require_runs_view(ctx: AuthContext) -> None:
        if not ctx.has(Perm.RUNS_VIEW):
            raise AuthorizationError(
                message="Reading eval runs needs runs:view", details={"permission": "runs:view"}
            )

    async def list_for_agent(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        *,
        draft: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> EvalRunList:
        """An agent's runs over the datasets the caller may read, newest first.

        `draft` keeps only the runs that tested the draft as it stands now - the
        same spec hash, whatever order its keys were stored in.
        """
        self._require_runs_view(ctx)
        agent = await self.registry.get(ctx, agent_id)
        org = ctx.organization_id
        _, dataset_ids = await eval_run_repo.referenced_ids(
            self.db, organization_id=org, agent_id=agent.id
        )
        readable = sorted(await self._readable_datasets(ctx, dataset_ids))
        if draft:
            tested = await eval_run_repo.draft_runs(
                self.db,
                agent.id,
                organization_id=org,
                dataset_ids=readable,
                spec_hash=spec_hash(AgentSpec.model_validate(agent.draft_spec)),
            )
            return EvalRunList(
                items=await self._reads(ctx, tested[skip : skip + limit]), total=len(tested)
            )
        runs, total = await eval_run_repo.list_for_agent(
            self.db, agent.id, organization_id=org, dataset_ids=readable, skip=skip, limit=limit
        )
        return EvalRunList(items=await self._reads(ctx, runs), total=total)

    async def list_for_dataset(
        self, ctx: AuthContext, dataset_id: UUID, *, skip: int = 0, limit: int = 50
    ) -> EvalRunList:
        """A dataset's runs over the agents the caller may see, newest first."""
        self._require_runs_view(ctx)
        dataset = await self.datasets.get(ctx, dataset_id)
        org = ctx.organization_id
        agent_ids, _ = await eval_run_repo.referenced_ids(
            self.db, organization_id=org, dataset_id=dataset.id
        )
        agents = await agent_repo.get_many(self.db, sorted(agent_ids), organization_id=org)
        visible = await accessible_ids(
            self.db, ctx, list(agents.values()), Perm.AGENTS_VIEW, resource_type=AGENT
        )
        runs, total = await eval_run_repo.list_for_dataset(
            self.db,
            dataset.id,
            organization_id=org,
            agent_ids=sorted(visible),
            skip=skip,
            limit=limit,
        )
        return EvalRunList(items=await self._reads(ctx, runs), total=total)

    async def recent(self, ctx: AuthContext, *, limit: int = 10) -> EvalRunList:
        """The organization's latest runs the caller may read - the dashboard's view."""
        if not ctx.has(Perm.RUNS_VIEW):
            return EvalRunList(items=[], total=0)
        agent_ids, dataset_ids = await eval_run_repo.referenced_ids(
            self.db, organization_id=ctx.organization_id
        )
        agents = await agent_repo.get_many(
            self.db, sorted(agent_ids), organization_id=ctx.organization_id
        )
        visible_agents = await accessible_ids(
            self.db, ctx, list(agents.values()), Perm.AGENTS_VIEW, resource_type=AGENT
        )
        readable = await self._readable_datasets(ctx, dataset_ids)
        runs = await eval_run_repo.list_recent(
            self.db,
            organization_id=ctx.organization_id,
            agent_ids=sorted(visible_agents),
            dataset_ids=sorted(readable),
            limit=limit,
        )
        return EvalRunList(items=await self._reads(ctx, runs), total=len(runs))

    async def case_link(self, ctx: AuthContext, agent_run_id: UUID) -> EvalCaseLinkRead | None:
        """The eval run and case an agent run answered - or, for the judge's run,
        graded - for a caller who may see its dataset.

        None for a run no eval started, and for one over a dataset the caller
        cannot read, whose name and question are not theirs to learn from a run
        history.
        """
        org = ctx.organization_id
        attempt = await eval_run_repo.case_of_agent_run(self.db, agent_run_id, organization_id=org)
        if attempt is not None:
            return await self._link(
                ctx, attempt.eval_run_id, attempt.case_id, attempt.case_revision_id, graded=False
            )
        score = await eval_run_repo.score_graded_by(self.db, agent_run_id, organization_id=org)
        if score is None or score.eval_run_id is None:
            return None
        return await self._link(
            ctx, score.eval_run_id, score.case_id, score.case_revision_id, graded=True
        )

    async def case_links(
        self, ctx: AuthContext, agent_run_ids: Sequence[UUID]
    ) -> dict[UUID, EvalCaseLinkRead]:
        """The eval case each of these agent runs answered, read for a page of run
        history at once - only over datasets the caller may see."""
        if not agent_run_ids:
            return {}
        org = ctx.organization_id
        attempts = await eval_run_repo.cases_of_agent_runs(
            self.db, agent_run_ids, organization_id=org
        )
        runs = await eval_run_repo.get_many(
            self.db, sorted({a.eval_run_id for a in attempts}), organization_id=org
        )
        readable = await self._readable_datasets(ctx, {run.dataset_id for run in runs.values()})
        names = await eval_run_repo.datasets(self.db, sorted(readable), organization_id=org)
        revisions = await eval_run_repo.revisions(
            self.db, sorted({a.case_revision_id for a in attempts}), organization_id=org
        )
        links: dict[UUID, EvalCaseLinkRead] = {}
        for attempt in attempts:
            run = runs[attempt.eval_run_id]
            dataset = names.get(run.dataset_id)
            # Read by the agent runs they name, so each attempt names one.
            if dataset is None or attempt.agent_run_id is None:
                continue
            revision = revisions[attempt.case_revision_id]
            links[attempt.agent_run_id] = EvalCaseLinkRead(
                eval_run_id=run.id,
                agent_id=run.agent_id,
                case_id=attempt.case_id,
                dataset_name=dataset.name,
                case_input=revision.input,
            )
        return links

    async def _link(
        self,
        ctx: AuthContext,
        eval_run_id: UUID,
        case_id: UUID,
        revision_id: UUID,
        *,
        graded: bool,
    ) -> EvalCaseLinkRead | None:
        org = ctx.organization_id
        run = await eval_run_repo.get(self.db, eval_run_id, organization_id=org)
        # An attempt never outlives its run, and a score goes with the run it belongs to.
        assert run is not None
        try:
            dataset = await self.datasets.get(ctx, run.dataset_id)
        except NotFoundError:
            return None
        revision = (await eval_run_repo.revisions(self.db, [revision_id], organization_id=org)).get(
            revision_id
        )
        return EvalCaseLinkRead(
            eval_run_id=run.id,
            agent_id=run.agent_id,
            case_id=case_id,
            dataset_name=dataset.name,
            case_input=revision.input if revision else "",
            graded=graded,
        )

    async def _readable_datasets(self, ctx: AuthContext, dataset_ids: set[UUID]) -> set[UUID]:
        rows = await eval_run_repo.datasets(
            self.db, sorted(dataset_ids), organization_id=ctx.organization_id
        )
        return await accessible_ids(
            self.db, ctx, list(rows.values()), Perm.DATASETS_VIEW, resource_type=DATASET
        )

    async def _reads(self, ctx: AuthContext, runs: Sequence[EvalRun]) -> list[EvalRunRead]:
        org = ctx.organization_id
        arms_by_run: dict[UUID, list[EvalRunArm]] = defaultdict(list)
        for arm in await eval_run_repo.list_arms(
            self.db, [run.id for run in runs], organization_id=org
        ):
            arms_by_run[arm.eval_run_id].append(arm)
        datasets = await eval_run_repo.datasets(
            self.db, sorted({run.dataset_id for run in runs}), organization_id=org
        )
        numbers = await eval_run_repo.dataset_version_numbers(
            self.db, sorted({run.dataset_version_id for run in runs}), organization_id=org
        )
        reads = []
        for run in runs:
            attempts = await eval_run_repo.list_cases(self.db, run.id, organization_id=org)
            arm_reads = []
            for arm in arms_by_run[run.id]:
                summary = summarize(
                    [c.attempt for c in await self._first_attempts(ctx, arm, attempts)]
                )
                arm_reads.append(
                    EvalRunArmRead(
                        id=arm.id,
                        role=ArmRole(arm.role),
                        position=arm.position,
                        source=ArmSource(arm.source),
                        agent_version_id=arm.agent_version_id,
                        version_number=arm.version_number,
                        model_profile_id=arm.model_profile_id,
                        model_label=arm.model_label,
                        reused_from_arm_id=arm.reused_from_arm_id,
                        spec_hash=arm.spec_hash,
                        summary=_summary_read(summary),
                        by_tag={tag: _summary_read(s) for tag, s in summary.by_tag.items()},
                    )
                )
            scores = await self._scores(ctx, attempts)
            judge_runs = {
                UUID(str(result["judge_run_id"]))
                for score in scores.values()
                for result in score.results
                if result.get("judge_run_id")
            }
            judge_cost, judge_partial = await agent_run_repo.cost_of_runs(
                self.db, sorted(judge_runs), organization_id=org
            )
            attempt_cost = sum((a.cost_usd for a in attempts if a.cost_usd is not None), Decimal(0))
            finished = (CaseAttemptStatus.DONE.value, CaseAttemptStatus.FAILED.value)
            first = [a for a in attempts if a.attempt == 0]
            dataset = datasets.get(run.dataset_id)
            reads.append(
                EvalRunRead(
                    id=run.id,
                    agent_id=run.agent_id,
                    dataset_id=run.dataset_id,
                    dataset_name=dataset.name if dataset else "",
                    dataset_version=numbers.get(run.dataset_version_id, 0),
                    environment_id=run.environment_id,
                    status=EvalRunStatus(run.status),
                    purpose=EvalRunPurpose(run.purpose),
                    paired=run.paired,
                    from_recordings=run.from_recordings,
                    live_reads=run.live_reads,
                    reruns=run.reruns,
                    estimate_usd=run.estimate_usd,
                    rerun_ceiling_usd=run.rerun_ceiling_usd,
                    cost_usd=attempt_cost + judge_cost,
                    cost_is_partial=judge_partial or any(a.cost_is_partial for a in attempts),
                    attempts_done=sum(1 for a in attempts if a.status in finished),
                    attempts_total=len(attempts),
                    cases=len({a.case_id for a in attempts}),
                    first_done=sum(1 for a in first if a.status in finished),
                    first_total=len(first),
                    outcome=await self._outcome(ctx, run),
                    error=run.error,
                    created_by_user_id=run.created_by_user_id,
                    created_at=run.created_at,
                    started_at=run.started_at,
                    ended_at=run.ended_at,
                    arms=arm_reads,
                )
            )
        return reads

    async def _arm_attempts(
        self, ctx: AuthContext, arm: EvalRunArm, attempts: Sequence[EvalRunCase]
    ) -> list[EvalRunCase]:
        """An arm's attempts. A reused arm answered first in the run it was reused
        from, and its confirming reruns are this run's own."""
        own = [a for a in attempts if a.arm_id == arm.id]
        if arm.reused_from_arm_id is None:
            return own
        original = await eval_run_repo.list_arm_cases(
            self.db, arm.reused_from_arm_id, organization_id=ctx.organization_id
        )
        return [a for a in original if a.attempt == 0] + own

    async def _scores(
        self, ctx: AuthContext, attempts: Sequence[EvalRunCase]
    ) -> dict[UUID, CaseScore]:
        return await eval_run_repo.scores(
            self.db,
            [a.case_score_id for a in attempts if a.case_score_id is not None],
            organization_id=ctx.organization_id,
        )

    async def _tags(
        self, ctx: AuthContext, attempts: Sequence[EvalRunCase]
    ) -> dict[UUID, tuple[str, ...]]:
        revisions = await eval_run_repo.revisions(
            self.db,
            sorted({a.case_revision_id for a in attempts}),
            organization_id=ctx.organization_id,
        )
        return {revision.id: tuple(revision.tags or ()) for revision in revisions.values()}

    async def _inputs(self, ctx: AuthContext, attempts: Sequence[EvalRunCase]) -> dict[UUID, str]:
        revisions = await eval_run_repo.revisions(
            self.db,
            sorted({a.case_revision_id for a in attempts}),
            organization_id=ctx.organization_id,
        )
        return {
            a.case_id: revisions[a.case_revision_id].input
            for a in attempts
            if a.case_revision_id in revisions
        }

    async def cases(
        self,
        ctx: AuthContext,
        run_id: UUID,
        *,
        arm_id: UUID | None = None,
        outcome: str | None = None,
        tag: str | None = None,
        case_ids: Sequence[UUID] | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> EvalCaseList:
        """The run's cases, each with every attempt every arm made at it.

        `outcome` narrows to cases whose first attempt on `arm_id` (the first
        candidate when omitted) passed, failed or is undecided, and `case_ids`
        to those cases - the ones a comparison says broke, say. A reused
        baseline's attempts are shown under this run's baseline arm.
        """
        run = await self._readable(ctx, run_id)
        org = ctx.organization_id
        arms = await eval_run_repo.list_arms(self.db, [run.id], organization_id=org)
        attempts = await eval_run_repo.list_cases(self.db, run.id, organization_id=org)
        shown: list[tuple[UUID, EvalRunCase]] = []
        for arm in arms:
            shown += [(arm.id, a) for a in await self._arm_attempts(ctx, arm, attempts)]
        scores = await self._scores(ctx, [a for _, a in shown])
        revisions = await eval_run_repo.revisions(
            self.db, sorted({a.case_revision_id for _, a in shown}), organization_id=org
        )
        focus = arm_id or next(arm.id for arm in arms if arm.role == ArmRole.CANDIDATE.value)
        by_case: dict[UUID, list[tuple[UUID, EvalRunCase]]] = defaultdict(list)
        for pair in shown:
            by_case[pair[1].case_id].append(pair)
        wanted: dict[str, Outcome] = {"passed": True, "failed": False, "undecided": None}
        items: list[EvalCaseRead] = []
        for case_id, pairs in sorted(by_case.items(), key=lambda item: item[1][0][1].position):
            if case_ids is not None and case_id not in case_ids:
                continue
            first = next(
                (a for shown_arm, a in pairs if shown_arm == focus and a.attempt == 0), None
            )
            decided = attempt_outcome(first, scores.get(first.case_score_id)) if first else None
            if outcome in wanted and decided is not wanted[outcome]:
                continue
            revision = revisions.get(pairs[0][1].case_revision_id)
            tags = list(revision.tags or []) if revision else []
            if tag is not None and tag not in tags:
                continue
            items.append(
                EvalCaseRead(
                    case_id=case_id,
                    case_revision_id=pairs[0][1].case_revision_id,
                    position=pairs[0][1].position,
                    input=revision.input if revision else "",
                    tags=tags,
                    expectation=(StoredCaseContent.model_validate(revision) if revision else None),
                    attempts=[
                        self._attempt_read(shown_arm, a, scores.get(a.case_score_id))
                        for shown_arm, a in pairs
                    ],
                )
            )
        return EvalCaseList(items=items[skip : skip + limit], total=len(items))

    @staticmethod
    def _attempt_read(
        arm_id: UUID, attempt: EvalRunCase, score: CaseScore | None
    ) -> EvalAttemptRead:
        return EvalAttemptRead(
            id=attempt.id,
            arm_id=arm_id,
            attempt=attempt.attempt,
            status=CaseAttemptStatus(attempt.status),
            agent_run_id=attempt.agent_run_id,
            answer=attempt.answer,
            calls=[EvalCallRead.model_validate(call) for call in attempt.calls or []],
            cost_usd=attempt.cost_usd,
            cost_is_partial=attempt.cost_is_partial,
            input_tokens=attempt.input_tokens,
            output_tokens=attempt.output_tokens,
            latency_ms=attempt.latency_ms,
            error=attempt.error,
            outcome=attempt_outcome(attempt, score),
            score=CaseScoreRead.model_validate(score) if score is not None else None,
        )

    async def baseline_for(
        self, ctx: AuthContext, run: EvalRun, arm: EvalRunArm
    ) -> Baseline | None:
        """What a candidate arm is compared with when nobody names a baseline.

        The baseline that ran in this run, if one did. One reused from an
        earlier run is that run's arm, so the comparison names where it came
        from and when it finished. Otherwise the cheap default: the last completed run of this dataset on
        the version before the candidate's (the published one, for a draft),
        whatever its model and dataset version - the comparison says both.
        """
        arms = await eval_run_repo.list_arms(self.db, [run.id], organization_id=ctx.organization_id)
        paired = next((a for a in arms if a.role == ArmRole.BASELINE.value), None)
        if paired is not None and paired.reused_from_arm_id is None:
            return Baseline(arm=paired, run=run, paired=True)
        if paired is not None:
            return await self._reused(ctx, paired)
        if arm.version_number is not None:
            previous = await agent_repo.version_before(
                self.db,
                agent_id=run.agent_id,
                number=arm.version_number,
                organization_id=ctx.organization_id,
            )
            previous_id = previous.id if previous else None
        else:
            agent = await agent_repo.get(self.db, run.agent_id, organization_id=ctx.organization_id)
            previous_id = agent.current_version_id if agent else None
        if previous_id is None:
            return None
        found = await eval_run_repo.latest_arm(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=run.agent_id,
            dataset_id=run.dataset_id,
            agent_version_id=previous_id,
            exclude_run_id=run.id,
        )
        return Baseline(arm=found[0], run=found[1], paired=False) if found else None

    async def _reused(self, ctx: AuthContext, arm: EvalRunArm) -> Baseline:
        assert arm.reused_from_arm_id is not None
        org = ctx.organization_id
        # The reference is set null when the original arm goes, and an arm
        # never outlives its run.
        original = await eval_run_repo.get_arm(self.db, arm.reused_from_arm_id, organization_id=org)
        assert original is not None
        source = await eval_run_repo.get(self.db, original.eval_run_id, organization_id=org)
        assert source is not None
        return Baseline(arm=original, run=source, paired=False, here=arm)

    async def outcomes(
        self, ctx: AuthContext, arm: EvalRunArm, attempts: Sequence[EvalRunCase]
    ) -> dict[UUID, tuple[Outcome, tuple[Outcome, ...], tuple[str, ...]]]:
        """Each case's first outcome on an arm, its rerun outcomes and its tags.

        `attempts` are the attempts of the run the arm belongs to.
        """
        own = await self._arm_attempts(ctx, arm, attempts)
        scores = await self._scores(ctx, own)
        tags = await self._tags(ctx, own)
        firsts: dict[UUID, Outcome] = {}
        reruns: dict[UUID, list[Outcome]] = defaultdict(list)
        case_tags: dict[UUID, tuple[str, ...]] = {}
        for attempt in sorted(own, key=lambda a: a.attempt):
            decided = attempt_outcome(attempt, scores.get(attempt.case_score_id))
            case_tags[attempt.case_id] = tags.get(attempt.case_revision_id, ())
            # A rerun not yet answered, or skipped, decides nothing - so it leaves
            # the flip unconfirmed rather than being left out of the count.
            if attempt.attempt == 0:
                firsts[attempt.case_id] = decided
            else:
                reruns[attempt.case_id].append(decided)
        return {
            case_id: (first, tuple(reruns[case_id]), case_tags[case_id])
            for case_id, first in firsts.items()
        }

    async def compare(
        self,
        ctx: AuthContext,
        run_id: UUID,
        *,
        arm_id: UUID | None = None,
        baseline_run_id: UUID | None = None,
    ) -> EvalComparisonRead:
        """One candidate arm against its baseline.

        `arm_id` picks the candidate arm (the first when omitted).
        `baseline_run_id` compares with that run's first candidate arm instead
        of the default; it must be a run of the same agent and dataset.
        """
        run = await self._readable(ctx, run_id)
        return await self._comparison(ctx, run, arm_id=arm_id, baseline_run_id=baseline_run_id)

    @staticmethod
    def _kept_outcome(run: EvalRun) -> EvalOutcomeRead | None:
        """The verdict as kept, or None when there is none or its shape is an older
        one - a cache that no longer reads is compared afresh, not a 500."""
        if run.outcome is None:
            return None
        try:
            return EvalOutcomeRead.model_validate(run.outcome)
        except ValidationError:
            logger.warning("Eval run %s kept an outcome that no longer reads", run.id)
            return None

    async def _outcome(self, ctx: AuthContext, run: EvalRun) -> EvalOutcomeRead | None:
        """A finished run's verdict, as kept - or compared again once a person has
        decided one of the scores it rests on since it was kept."""
        if run.status in (EvalRunStatus.QUEUED.value, EvalRunStatus.RUNNING.value):
            return None
        kept = self._kept_outcome(run)
        if kept is not None and run.outcome_at is not None:
            sides = {run.id} | ({kept.baseline.run_id} if kept.baseline else set())
            if not await eval_run_repo.reviewed_since(
                self.db, sorted(sides), since=run.outcome_at, organization_id=ctx.organization_id
            ):
                return kept
        comparison = await self._comparison(ctx, run)
        theirs = comparison.baseline_summary
        outcome = EvalOutcomeRead(
            candidate_arm_id=comparison.candidate.arm_id,
            verdict=comparison.verdict,
            overall=comparison.overall,
            baseline=comparison.baseline,
            regressions_confirmed=comparison.regressions_confirmed,
            fixed_confirmed=comparison.fixed_confirmed,
            candidate_pass_rate=comparison.candidate_summary.pass_rate,
            baseline_pass_rate=theirs.pass_rate if theirs else None,
            candidate_first_pass_rate=comparison.candidate_summary.first_pass_rate,
            baseline_first_pass_rate=theirs.first_pass_rate if theirs else None,
        )
        await eval_run_repo.update_run(
            self.db,
            run=run,
            values={"outcome": outcome.model_dump(mode="json"), "outcome_at": datetime.now(UTC)},
        )
        return outcome

    async def _comparison(
        self,
        ctx: AuthContext,
        run: EvalRun,
        *,
        arm_id: UUID | None = None,
        baseline_run_id: UUID | None = None,
    ) -> EvalComparisonRead:
        arms = await eval_run_repo.list_arms(self.db, [run.id], organization_id=ctx.organization_id)
        candidates = [a for a in arms if a.role == ArmRole.CANDIDATE.value]
        candidate = (
            next((a for a in candidates if a.id == arm_id), None) if arm_id else candidates[0]
        )
        if candidate is None:
            raise NotFoundError(message="Arm not found", details={"arm_id": arm_id})
        baseline = (
            await self._named_baseline(ctx, run, baseline_run_id)
            if baseline_run_id is not None
            else await self.baseline_for(ctx, run, candidate)
        )
        attempts = await eval_run_repo.list_cases(
            self.db, run.id, organization_id=ctx.organization_id
        )
        mine = await self.outcomes(ctx, candidate, attempts)
        candidate_side = await self._side(ctx, run, candidate)
        candidate_attempts = await self._first_attempts(ctx, candidate, attempts)
        if baseline is None:
            return EvalComparisonRead(
                candidate=candidate_side,
                baseline=None,
                paired=False,
                verdict=None,
                overall=None,
                p_value=None,
                invalid_reason=None,
                regressions_confirmed=0,
                regressions_unconfirmed=0,
                fixed_confirmed=0,
                fixed_unconfirmed=0,
                compared=0,
                not_compared=len(mine),
                candidate_summary=_summary_read(
                    summarize([c.attempt for c in candidate_attempts], with_tags=False)
                ),
                baseline_summary=None,
                efficiency=None,
                cases=[],
                flips_by_tag={},
            )
        theirs = (
            await self.outcomes(ctx, baseline.here, attempts)
            if baseline.here is not None
            else await self.outcomes(
                ctx,
                baseline.arm,
                attempts
                if baseline.run.id == run.id
                else await eval_run_repo.list_cases(
                    self.db, baseline.run.id, organization_id=ctx.organization_id
                ),
            )
        )
        confirmed_here = baseline.paired or baseline.here is not None
        common = [case_id for case_id in mine if case_id in theirs]
        paired_cases = [
            PairedCase(
                case_id=case_id,
                baseline=theirs[case_id][0],
                candidate=mine[case_id][0],
                baseline_reruns=theirs[case_id][1] if confirmed_here else (),
                candidate_reruns=mine[case_id][1],
                tags=mine[case_id][2],
            )
            for case_id in common
        ]
        invalid_reason = await self._incomparable(ctx, run, candidate, baseline, attempts)
        quality = quality_verdict(
            paired_cases, alpha=settings.EVAL_SIGNIFICANCE, invalid=invalid_reason is not None
        )
        shared = set(common)
        mine_summary = summarize(
            [c.attempt for c in candidate_attempts if c.case_id in shared], with_tags=False
        )
        theirs_summary = summarize(
            [
                c.attempt
                for c in (
                    await self._first_attempts(ctx, baseline.here, attempts)
                    if baseline.here is not None
                    else await self._first_attempts(ctx, baseline.arm, None)
                )
                if c.case_id in shared
            ],
            with_tags=False,
        )
        inputs = await self._inputs(ctx, [a for a in attempts if a.arm_id == candidate.id])

        def count(flip: Flip, confirmed: bool) -> int:
            return sum(1 for c in paired_cases if c.flip is flip and c.confirmed is confirmed)

        trends = efficiency(
            theirs_summary, mine_summary, tolerance=settings.EVAL_EFFICIENCY_TOLERANCE
        )
        return EvalComparisonRead(
            candidate=candidate_side,
            baseline=await self._side(ctx, baseline.run, baseline.arm),
            paired=baseline.paired,
            verdict=quality.verdict.value,
            overall=quality.overall,
            p_value=quality.p_value,
            invalid_reason=invalid_reason,
            regressions_confirmed=count(Flip.REGRESSION, True),
            regressions_unconfirmed=count(Flip.REGRESSION, False),
            fixed_confirmed=count(Flip.FIXED, True),
            fixed_unconfirmed=count(Flip.FIXED, False),
            compared=len(common),
            not_compared=len(set(mine) ^ set(theirs)),
            candidate_summary=_summary_read(mine_summary),
            baseline_summary=_summary_read(theirs_summary),
            efficiency=EfficiencyRead(
                cost_per_pass=trends.cost_per_pass.value,
                avg_tokens=trends.avg_tokens.value,
                p50_ms=trends.p50_ms.value,
                p95_ms=trends.p95_ms.value,
            ),
            cases=[
                CaseFlipRead(
                    case_id=c.case_id,
                    input=inputs.get(c.case_id, ""),
                    flip=c.flip.value,
                    confirmed=c.confirmed,
                    baseline=c.baseline,
                    candidate=c.candidate,
                    baseline_reruns=list(c.baseline_reruns),
                    candidate_reruns=list(c.candidate_reruns),
                    tags=list(c.tags),
                )
                for c in paired_cases
            ],
            flips_by_tag={
                tag: {flip.value: n for flip, n in counts.items()}
                for tag, counts in flips_by_tag(paired_cases).items()
            },
        )

    async def _first_attempts(
        self, ctx: AuthContext, arm: EvalRunArm, attempts: Sequence[EvalRunCase] | None
    ) -> list[_CaseAttempt]:
        if attempts is None:
            attempts = await eval_run_repo.list_cases(
                self.db, arm.eval_run_id, organization_id=ctx.organization_id
            )
        every = await self._arm_attempts(ctx, arm, attempts)
        scores = await self._scores(ctx, every)
        reruns: dict[UUID, list[Outcome]] = defaultdict(list)
        for a in sorted(every, key=lambda a: a.attempt):
            if a.attempt > 0:
                reruns[a.case_id].append(attempt_outcome(a, scores.get(a.case_score_id)))
        own = [a for a in every if a.attempt == 0]
        tags = await self._tags(ctx, own)
        return [
            _CaseAttempt(
                case_id=a.case_id,
                attempt=_attempt(
                    a,
                    scores.get(a.case_score_id),
                    tags.get(a.case_revision_id, ()),
                    reruns[a.case_id],
                ),
            )
            for a in own
        ]

    async def _named_baseline(
        self, ctx: AuthContext, run: EvalRun, baseline_run_id: UUID
    ) -> Baseline:
        other = await self._readable(ctx, baseline_run_id)
        if other.agent_id != run.agent_id or other.dataset_id != run.dataset_id:
            raise BadRequestError(
                message="A baseline must be a run of the same agent on the same dataset",
                details={"eval_run_id": run.id, "baseline_run_id": baseline_run_id},
            )
        arms = await eval_run_repo.list_arms(
            self.db, [other.id], organization_id=ctx.organization_id
        )
        first = next(a for a in arms if a.role == ArmRole.CANDIDATE.value)
        return Baseline(arm=first, run=other, paired=other.id == run.id)

    async def _side(self, ctx: AuthContext, run: EvalRun, arm: EvalRunArm) -> ComparisonSide:
        return ComparisonSide(
            run_id=run.id,
            arm_id=arm.id,
            role=ArmRole(arm.role),
            source=ArmSource(arm.source),
            version_number=arm.version_number,
            model_label=arm.model_label,
            dataset_version=(
                await eval_run_repo.dataset_version_numbers(
                    self.db, [run.dataset_version_id], organization_id=ctx.organization_id
                )
            ).get(run.dataset_version_id, 0),
            finished_at=run.ended_at,
        )

    async def _incomparable(
        self,
        ctx: AuthContext,
        run: EvalRun,
        candidate: EvalRunArm,
        baseline: Baseline,
        attempts: Sequence[EvalRunCase],
    ) -> str | None:
        """Why the two sides cannot be compared at all, or `None` when they can.

        Different scoring decides cases by different rules; a different judge
        grades by a different hand. Either way a flip says nothing about the
        agent, so the comparison is refused rather than read.

        The judge is compared case by case: a rubric fingerprint covers the
        judge checks a case carries of its own, so two cases of one side are
        rightly pinned differently. A case only one side's judge graded is left
        to its outcome, which is already undecided on the other side.
        """
        if baseline.run.scoring_hash != run.scoring_hash:
            return "The two runs were scored with different scoring settings."
        other_attempts = (
            attempts
            if baseline.run.id == run.id
            else await eval_run_repo.list_cases(
                self.db, baseline.run.id, organization_id=ctx.organization_id
            )
        )
        mine = await self._pins(ctx, await self._arm_attempts(ctx, candidate, attempts))
        theirs = await self._pins(ctx, await self._arm_attempts(ctx, baseline.arm, other_attempts))
        if any(mine[case_id] != theirs[case_id] for case_id in mine.keys() & theirs.keys()):
            return "The two sides were graded by a different judge, model or rubric."
        return None

    async def _pins(
        self, ctx: AuthContext, attempts: Sequence[EvalRunCase]
    ) -> dict[UUID, set[str]]:
        """Each case's judge pins across its attempts, for the cases a judge graded."""
        scores = await self._scores(ctx, attempts)
        pins: dict[UUID, set[str]] = defaultdict(set)
        for attempt in attempts:
            score = scores.get(attempt.case_score_id)
            if score is not None and score.judge is not None:
                pins[attempt.case_id].add(json.dumps(score.judge, sort_keys=True))
        return pins


@dataclass(frozen=True)
class _CaseAttempt:
    case_id: UUID
    attempt: Attempt


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)

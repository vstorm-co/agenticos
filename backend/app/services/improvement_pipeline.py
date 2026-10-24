"""Durable, transactionally advanced improvement sessions.

A transition only coordinates stored children. Paid calls belong to authoring
and eval jobs, each of which has one attempt. The minute sweep recovers a lost
transition without repeating a model call. Nothing here accepts or publishes.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.audit import record_audit
from app.core.exceptions import (
    AppException,
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
    PaymentRequiredError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentStatus
from app.db.models.authoring import AuthoringStatus, BatchStatus, HunkKind, HunkStatus
from app.db.models.improvement import (
    DroppedHunk,
    ImprovementIteration,
    ImprovementRun,
    ImprovementVerdict,
    StopReason,
)
from app.db.models.improvement import (
    ImprovementStage as Stage,
)
from app.db.models.improvement import (
    ImprovementStatus as Status,
)
from app.repositories import (
    agent_repo,
    authoring_repo,
    dataset_repo,
    improvement_repo,
    organization_repo,
)
from app.schemas.authoring import AuthoringStart, ProposalCheck
from app.schemas.eval_run import EvalRunRequest, ProposalCheckRecord
from app.schemas.eval_suite import EvalSuiteRead
from app.schemas.eval_threshold import EvalSuiteCheck
from app.schemas.improvement import (
    ImprovementEstimate,
    ImprovementEvent,
    ImprovementIterationRead,
    ImprovementRead,
    ImprovementStart,
    ImprovementTarget,
)
from app.schemas.scoring import DatasetScoring
from app.services import authoring_fields, authoring_hunks
from app.services import improvement_states as rules
from app.services.agent_registry import AgentRegistryService
from app.services.api_key import job_context
from app.services.authoring import AuthoringService
from app.services.background_jobs import enqueue
from app.services.dataset import DatasetService
from app.services.eval_run import EvalRunService, scoring_hash, spec_hash
from app.services.eval_suite import EvalSuiteService
from app.services.notifications import NotificationService
from app.worker.jobs import ADVANCE_IMPROVEMENT, AdvanceImprovement


@dataclass(frozen=True)
class Inputs:
    agent: Agent
    request: EvalRunRequest
    scoring: DatasetScoring
    current_scoring_hash: str
    suite: EvalSuiteRead | None
    judge_version_id: UUID | None
    base_version_id: UUID | None

    @property
    def suite_hash(self) -> str | None:
        if self.suite is None:
            return None
        # Every setting the paired check uses, including a guard's grading pin.
        payload = self.suite.model_dump(
            mode="json",
            include={
                "id",
                "dataset_id",
                "environment_id",
                "threshold",
                "pin",
            },
        )
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    @property
    def pins(self) -> rules.Pins:
        return rules.Pins(
            spec_hash(AgentSpec.model_validate(self.agent.draft_spec)),
            self.base_version_id,
            self.current_scoring_hash,
            self.request.dataset_id,
            None if self.suite is None else self.suite.id,
            self.suite_hash,
        )


class ImprovementPipelineService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)
        self.authoring = AuthoringService(db)
        self.evals = EvalRunService(db)

    async def _inputs(self, ctx: AuthContext, agent_id: UUID, target: ImprovementTarget) -> Inputs:
        agent = await self.registry.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)
        if not ctx.has(Perm.RUNS_VIEW):
            raise AuthorizationError(
                message="Improving an agent needs runs:view",
                details={"permission": Perm.RUNS_VIEW.value},
            )
        if agent.status == AgentStatus.ARCHIVED.value:
            raise BadRequestError(message="An archived agent cannot be improved")
        checked = await self.authoring._check_request(
            ctx,
            agent.id,
            ProposalCheck(
                dataset_id=target.dataset_id,
                suite_id=target.suite_id,
            ),
        )
        dataset = await DatasetService(self.db).get(
            ctx, checked.request.dataset_id, perm=Perm.DATASETS_RUN
        )
        version = await agent_repo.newest_version(
            self.db, agent_id=agent.id, organization_id=ctx.organization_id
        )
        draft = AgentSpec.model_validate(agent.draft_spec)
        plan = await self.evals.plan(
            ctx,
            agent.id,
            checked.request,
            scoring=checked.scoring,
            candidate_spec=draft,
            baseline_spec=draft,
            judge_version_id=checked.judge_version_id,
            judge_pinned=checked.judge_pinned,
        )
        judge = (
            (await self.evals._judge_agent(ctx, plan.scoring.judge.agent_id))
            if plan.judged
            else None
        )
        suite = (
            None
            if target.suite_id is None
            else await EvalSuiteService(self.db).get(ctx, agent.id, target.suite_id)
        )
        return Inputs(
            agent,
            checked.request.model_copy(update={"dataset_version": plan.dataset_version.number}),
            plan.scoring,
            scoring_hash(DatasetScoring.model_validate(dataset.scoring)),
            suite,
            checked.judge_version_id
            if checked.judge_pinned
            else (judge.current_version_id if judge else None),
            None if version is None else version.id,
        )

    async def _estimate(
        self, ctx: AuthContext, inputs: Inputs, target: ImprovementTarget
    ) -> ImprovementEstimate:
        proposal = await self.authoring.estimate_agent(
            ctx,
            inputs.agent.id,
            AuthoringStart(
                window_days=target.window_days, improver_agent_id=target.improver_agent_id
            ),
        )
        draft = AgentSpec.model_validate(inputs.agent.draft_spec)
        check = await self.evals.estimate(
            ctx,
            inputs.agent.id,
            inputs.request,
            scoring=inputs.scoring,
            candidate_spec=draft,
            baseline_spec=draft,
            judge_version_id=inputs.judge_version_id,
            judge_pinned=True,
        )
        full_eval = check.total_usd + check.rerun_ceiling_usd
        # Each round may need one repeat of an inconclusive comparison.
        per_round = proposal.estimate_usd + full_eval * (1 + rules.INCONCLUSIVE_RERUNS)
        org_left = await self.evals._org_left(ctx)
        return ImprovementEstimate(
            proposal_usd=proposal.estimate_usd,
            eval_usd=full_eval,
            per_round_usd=per_round,
            total_usd=per_round * target.max_iterations,
            max_iterations=target.max_iterations,
            cases=check.cases,
            evidence_runs=proposal.runs,
            affordable=proposal.affordable
            and check.affordable
            and (org_left is None or per_round * target.max_iterations <= org_left),
            reason=proposal.reason,
        )

    async def estimate(
        self, ctx: AuthContext, agent_id: UUID, target: ImprovementTarget
    ) -> ImprovementEstimate:
        return await self._estimate(ctx, await self._inputs(ctx, agent_id, target), target)

    async def start(
        self, ctx: AuthContext, agent_id: UUID, data: ImprovementStart
    ) -> ImprovementRead:
        inputs = await self._inputs(ctx, agent_id, data)
        estimate = await self._estimate(ctx, inputs, data)
        active = await improvement_repo.get_active(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id
        )
        if active is not None:
            raise self._already_running(active)
        if not estimate.affordable or estimate.total_usd > data.budget_usd:
            raise PaymentRequiredError(
                message="The full improvement estimate exceeds the available budget",
                details={
                    "estimate_usd": str(estimate.total_usd),
                    "budget_usd": str(data.budget_usd),
                },
            )
        try:
            async with self.db.begin_nested():
                run = await improvement_repo.create_run(
                    self.db,
                    organization_id=ctx.organization_id,
                    agent_id=agent_id,
                    created_by_user_id=ctx.subject_id,
                    created_by_api_key_id=ctx.api_key_id,
                    base_version_id=inputs.base_version_id,
                    base_draft_hash=inputs.pins.draft_hash,
                    dataset_id=inputs.request.dataset_id,
                    dataset_version=inputs.request.dataset_version or 1,
                    suite_id=data.suite_id,
                    suite_hash=inputs.suite_hash,
                    scoring_hash=inputs.current_scoring_hash,
                    window_days=data.window_days,
                    estimate_usd=estimate.total_usd,
                    budget_usd=data.budget_usd,
                    max_iterations=data.max_iterations,
                )
                await improvement_repo.update_run(
                    self.db,
                    run=run,
                    values={
                        "pinned_scoring": inputs.scoring.model_dump(mode="json"),
                        "improver_agent_id": data.improver_agent_id,
                        "judge_version_id": inputs.judge_version_id,
                    },
                )
        except IntegrityError as exc:
            if (
                getattr(exc.orig, "constraint_name", None) != "uq_improvement_runs_active"
                and getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
                != "uq_improvement_runs_active"
            ):
                raise
            active = await improvement_repo.get_active(
                self.db, organization_id=ctx.organization_id, agent_id=agent_id
            )
            if active is None:
                raise
            raise self._already_running(active) from exc
        await improvement_repo.create_iteration(
            self.db, organization_id=ctx.organization_id, run_id=run.id, number=1
        )
        await self._audit(run, "started")
        await self._queue(run)
        return await self._read(ctx, run)

    @staticmethod
    def _already_running(run: ImprovementRun) -> ConcurrentChangeError:
        return ConcurrentChangeError(
            message="An improvement is already running for this agent",
            details={"improvement_run_id": str(run.id)},
        )

    async def _row(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, *, lock: bool = False
    ) -> ImprovementRun:
        row = await improvement_repo.get_run(
            self.db, run_id, organization_id=ctx.organization_id, lock=lock
        )
        if row is None or row.agent_id != agent_id:
            raise NotFoundError(message="Improvement session not found")
        return row

    async def read(self, ctx: AuthContext, agent_id: UUID, run_id: UUID) -> ImprovementRead:
        await self.registry.get(ctx, agent_id)
        return await self._read(ctx, await self._row(ctx, agent_id, run_id))

    async def list_for_agent(self, ctx: AuthContext, agent_id: UUID) -> list[ImprovementRead]:
        await self.registry.get(ctx, agent_id)
        rows = await improvement_repo.list_for_agent(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id
        )
        return [await self._read(ctx, row) for row in rows]

    async def _read(self, ctx: AuthContext, run: ImprovementRun) -> ImprovementRead:
        iterations = await improvement_repo.list_iterations(
            self.db, organization_id=ctx.organization_id, run_id=run.id
        )
        events = await improvement_repo.timeline(
            self.db, run.id, organization_id=ctx.organization_id
        )
        result = ImprovementRead.model_validate(run)
        result.spent_usd = await improvement_repo.spent(
            self.db, run.id, organization_id=run.organization_id
        )
        result.iterations = [ImprovementIterationRead.model_validate(item) for item in iterations]
        result.timeline = [
            ImprovementEvent(
                action=event.action,
                at=event.created_at,
                stage=self._event_detail(event.details, "stage"),
                status=self._event_detail(event.details, "status"),
                reason=self._event_detail(event.details, "reason"),
            )
            for event in events
        ]
        if not ctx.has(Perm.RUNS_VIEW):
            result.error = None
        return result

    @staticmethod
    def _event_detail(details: object, key: str) -> str | None:
        if not isinstance(details, dict):
            return None
        value = details.get(key)
        return value if isinstance(value, str) else None

    async def cancel(self, ctx: AuthContext, agent_id: UUID, run_id: UUID) -> ImprovementRead:
        run = await self._row(ctx, agent_id, run_id, lock=True)
        if ctx.subject_id != run.created_by_user_id and not ctx.has(Perm.ORG_SETTINGS):
            raise AuthorizationError(
                message="Only the creator or an organization administrator can stop this session"
            )
        if Status(run.status).active:
            # Cancellation must still work after the creator loses resource access.
            await self._stop_children(run)
            await self._move(
                run, rules.Transition(Status.CANCELLED, Stage(run.stage) if run.stage else None)
            )
        return await self._read(ctx, run)

    async def _stop_children(self, run: ImprovementRun) -> None:
        from app.db.models.eval_run import EvalRunStatus
        from app.repositories import eval_run_repo

        iteration = await improvement_repo.get_iteration(
            self.db, organization_id=run.organization_id, run_id=run.id, number=run.iteration
        )
        if iteration is None:
            return
        if iteration.authoring_request_id is not None:
            request = await authoring_repo.get_request(
                self.db, iteration.authoring_request_id, organization_id=run.organization_id
            )
            if request is not None and request.status in {"queued", "running"}:
                await authoring_repo.update_request(
                    self.db,
                    request=request,
                    values={
                        "status": AuthoringStatus.FAILED.value,
                        "error": "The improvement session stopped.",
                        "finished_at": datetime.now(UTC),
                    },
                )
        for run_id in iteration.eval_run_ids:
            child = await eval_run_repo.get(self.db, run_id, organization_id=run.organization_id)
            if child is not None and not EvalRunStatus(child.status).terminal:
                await eval_run_repo.cancel_live(
                    self.db, child.id, organization_id=run.organization_id, now=datetime.now(UTC)
                )

    async def _queue(self, run: ImprovementRun) -> None:
        # State is part of dedupe: the current job may enqueue its successor.
        children = await improvement_repo.get_iteration(
            self.db, organization_id=run.organization_id, run_id=run.id, number=run.iteration
        )
        marker = (
            "" if children is None else f"{children.authoring_request_id}:{children.eval_run_ids}"
        )
        await enqueue(
            self.db,
            ADVANCE_IMPROVEMENT,
            AdvanceImprovement(run_id=run.id, organization_id=run.organization_id),
            organization_id=run.organization_id,
            concurrency_key=f"improvement:{run.agent_id}",
            dedupe_key=f"{run.id}:{run.status}:{run.stage}:{run.iteration}:{marker}",
            dedupe_active=True,
        )

    async def sweep(self) -> int:
        after = None
        count = 0
        while rows := await improvement_repo.list_active(self.db, after=after):
            for run_id, org_id in rows:
                run = await improvement_repo.get_run(self.db, run_id, organization_id=org_id)
                if run is not None:
                    await self._queue(run)
                    count += 1
            after = rows[-1][0]
        return count

    async def _audit(self, run: ImprovementRun, action: str) -> None:
        await record_audit(
            self.db,
            actor_user_id=run.created_by_user_id,
            organization_id=run.organization_id,
            action=f"improvement.{action}",
            target_type="improvement",
            target_id=str(run.id),
            details={
                "stage": run.stage,
                "status": run.status,
                "reason": run.stop_reason,
                "iteration": run.iteration,
                "spent_usd": str(run.spent_usd),
                "budget_usd": str(run.budget_usd),
                "estimate_usd": str(run.estimate_usd),
                "dataset_id": str(run.dataset_id),
                "dataset_version": run.dataset_version,
                "max_iterations": run.max_iterations,
            },
        )

    async def _move(self, run: ImprovementRun, transition: rules.Transition) -> None:
        now = datetime.now(UTC)
        await improvement_repo.update_run(
            self.db,
            run=run,
            values={
                "status": transition.status.value,
                "stage": None if transition.stage is None else transition.stage.value,
                "stop_reason": None
                if transition.stop_reason is None
                else transition.stop_reason.value,
                "heartbeat_at": now,
                "stage_started_at": now,
                "finished_at": None if transition.status.active else now,
                "spent_usd": await improvement_repo.spent(
                    self.db, run.id, organization_id=run.organization_id
                ),
            },
        )
        await self._audit(
            run, "stage_changed" if transition.status.active else transition.status.value
        )
        if transition.status.active:
            await self._queue(run)
        else:
            agent = await agent_repo.get(self.db, run.agent_id, organization_id=run.organization_id)
            if agent is not None and run.created_by_user_id is not None:
                await NotificationService(self.db).improvement_finished(
                    agent=agent,
                    run_id=run.id,
                    user_id=run.created_by_user_id,
                    status=run.status,
                    reason=run.stop_reason,
                )

    async def advance(self, run_id: UUID, organization_id: UUID) -> None:
        run = await improvement_repo.get_run(
            self.db, run_id, organization_id=organization_id, lock=True
        )
        if run is None or not Status(run.status).active:
            return
        try:
            ctx = await job_context(
                self.db,
                organization_id=organization_id,
                user_id=run.created_by_user_id,
                api_key_id=run.created_by_api_key_id,
            )
        except AuthenticationError:
            ctx = None
        if ctx is None:
            await self._move(
                run,
                rules.Transition(
                    Status.STOPPED, Stage(run.stage) if run.stage else None, StopReason.PERMISSION
                ),
            )
            return
        try:
            inputs = await self._inputs(
                ctx,
                run.agent_id,
                ImprovementTarget(
                    dataset_id=run.dataset_id if run.suite_id is None else None,
                    suite_id=run.suite_id,
                ),
            )
        except AuthorizationError:
            await self._move(
                run,
                rules.Transition(
                    Status.STOPPED, Stage(run.stage) if run.stage else None, StopReason.PERMISSION
                ),
            )
            return
        except NotFoundError:
            agent = await agent_repo.get(self.db, run.agent_id, organization_id=organization_id)
            dataset = await dataset_repo.get(
                self.db, run.dataset_id, organization_id=organization_id
            )
            gone = agent is None or dataset is None
            await self._move(
                run,
                rules.Transition(
                    Status.STALE if gone else Status.STOPPED,
                    Stage(run.stage) if run.stage else None,
                    StopReason.STALE if gone else StopReason.PERMISSION,
                ),
            )
            return
        except BadRequestError:
            await self._move(
                run,
                rules.Transition(
                    Status.STALE, Stage(run.stage) if run.stage else None, StopReason.STALE
                ),
            )
            return
        organization = await organization_repo.get_by_id(self.db, organization_id)
        if organization is None or not organization.ai_assistance_enabled:
            await self._move(
                run,
                rules.Transition(
                    Status.STOPPED, Stage(run.stage) if run.stage else None, StopReason.PERMISSION
                ),
            )
            return
        pins = rules.Pins(
            run.base_draft_hash,
            run.base_version_id,
            run.scoring_hash,
            run.dataset_id,
            run.suite_id,
            run.suite_hash,
        )
        if run.pinned_scoring is None or rules.stale(pins, inputs.pins, archived=False):
            await self._move(
                run,
                rules.Transition(
                    Status.STALE, Stage(run.stage) if run.stage else None, StopReason.STALE
                ),
            )
            return
        iteration = await improvement_repo.get_iteration(
            self.db, organization_id=organization_id, run_id=run.id, number=run.iteration
        )
        assert iteration is not None, "a session and its first iteration are created atomically"
        try:
            await self._step(ctx, inputs, run, iteration)
        except PaymentRequiredError:
            await self._move(
                run,
                rules.Transition(
                    Status.STOPPED, Stage(run.stage) if run.stage else None, StopReason.BUDGET
                ),
            )
        except AppException as exc:
            await improvement_repo.update_run(self.db, run=run, values={"error": exc.message})
            await self._move(
                run,
                rules.Transition(
                    Status.FAILED,
                    Stage(run.stage) if run.stage else None,
                    StopReason.PROPOSAL if run.stage == Stage.PROPOSING else StopReason.EVAL,
                ),
            )

    async def _step(
        self, ctx: AuthContext, inputs: Inputs, run: ImprovementRun, iteration: ImprovementIteration
    ) -> None:
        if run.stage is None:
            await self._move(run, rules.Transition(Status.RUNNING, Stage.ANALYZING))
        elif run.stage == Stage.ANALYZING:
            pack = await self.authoring.evidence.for_agent(
                ctx, run.agent_id, window_days=run.window_days
            )
            plan = await self.evals.plan(
                ctx,
                run.agent_id,
                inputs.request,
                scoring=inputs.scoring,
                candidate_spec=AgentSpec.model_validate(inputs.agent.draft_spec),
                exclude_conversations=pack.conversation_ids,
            )
            transition = rules.after_analyzing(
                has_evidence=bool(pack.runs), gradable_cases=len(plan.cases) - plan.ungraded
            )
            # Knowledge classification is a separate branch; no paid classification
            # is necessary for a session proposing agent changes only.
            if transition.status.active:
                transition = rules.Transition(Status.RUNNING, Stage.PROPOSING)
            await self._move(run, transition)
        elif run.stage == Stage.PROPOSING:
            if iteration.authoring_request_id is None:
                estimate = await self.authoring.estimate_agent(
                    ctx,
                    run.agent_id,
                    AuthoringStart(
                        window_days=run.window_days, improver_agent_id=run.improver_agent_id
                    ),
                )
                spent = await improvement_repo.spent(
                    self.db, run.id, organization_id=run.organization_id
                )
                if not rules.affordable(
                    spent=spent, step_estimate=estimate.estimate_usd, budget=run.budget_usd
                ):
                    await self._move(
                        run, rules.Transition(Status.STOPPED, Stage.PROPOSING, StopReason.BUDGET)
                    )
                    return
                request = await self.authoring.start_agent(
                    ctx,
                    run.agent_id,
                    AuthoringStart(
                        window_days=run.window_days, improver_agent_id=run.improver_agent_id
                    ),
                    improvement_run_id=run.id,
                )
                await improvement_repo.update_iteration(
                    self.db, iteration=iteration, values={"authoring_request_id": request.id}
                )
                await self._audit(run, "child_started")
                return
            request = await authoring_repo.get_request(
                self.db, iteration.authoring_request_id, organization_id=run.organization_id
            )
            if request is None:
                await self._move(
                    run, rules.Transition(Status.FAILED, Stage.PROPOSING, StopReason.PROPOSAL)
                )
                return
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
            transition = rules.after_proposing(AuthoringStatus(request.status), hunks=len(hunks))
            if transition is not None:
                await improvement_repo.update_iteration(
                    self.db,
                    iteration=iteration,
                    values={"batch_id": None if batch is None else batch.id},
                )
                await self._move(run, transition)
            elif rules.stalled(
                Stage.PROPOSING,
                waiting=request.status == "queued",
                last_progress=max(
                    value
                    for value in (
                        request.heartbeat_at,
                        request.started_at,
                        run.stage_started_at,
                        run.created_at,
                    )
                    if value is not None
                ),
                now=datetime.now(UTC),
            ):
                await self._stop_children(run)
                await self._move(run, rules.stall(Stage.PROPOSING))
        elif run.stage == Stage.FILTERING:
            projected, kept = await self._candidate(
                inputs.agent, run, iteration, filter_policy=True
            )
            await improvement_repo.update_iteration(
                self.db, iteration=iteration, values={"candidate_spec_hash": spec_hash(projected)}
            )
            await self._move(run, rules.after_filtering(kept=kept))
        elif run.stage == Stage.EVALUATING:
            await self._evaluate(ctx, inputs, run, iteration)
        elif run.stage == Stage.JUDGING:
            await self._judge(ctx, inputs, run, iteration)

    async def _candidate(
        self,
        agent: Agent,
        run: ImprovementRun,
        iteration: ImprovementIteration,
        *,
        filter_policy: bool = False,
    ) -> tuple[AgentSpec, int]:
        assert iteration.batch_id is not None
        hunks = await authoring_repo.list_hunks(
            self.db, organization_id=run.organization_id, batch_id=iteration.batch_id
        )
        pending = [h for h in hunks if h.status == HunkStatus.PENDING.value]
        draft = AgentSpec.model_validate(agent.draft_spec)
        dropped: list[UUID] = []
        reasons: list[DroppedHunk] = []
        if filter_policy:
            # The same policy as interactive authoring runs again at this boundary,
            # including historical or manually inserted proposal rows.
            for hunk in pending:
                if hunk.kind != HunkKind.SPEC_FIELD.value:
                    continue
                staged = authoring_fields.stage(
                    draft, hunk.path or "", hunk.op or "", hunk.new_value
                )
                if isinstance(staged, str):
                    dropped.append(hunk.id)
                    reasons.append({"hunk_id": str(hunk.id), "reason": staged})
                else:
                    hunk.new_value = staged.new
            await self.db.flush()
        remaining = [h for h in pending if h.id not in dropped]
        model_changes = [
            h
            for h in remaining
            if h.kind == HunkKind.SPEC_FIELD.value and h.path == "model_profile_id"
        ]
        other_changes = [h for h in remaining if h not in model_changes]
        if filter_policy and model_changes and other_changes:
            batch = await authoring_repo.get_batch(
                self.db, iteration.batch_id, organization_id=run.organization_id
            )
            assert batch is not None
            separate = await authoring_repo.split_candidate(
                self.db, batch=batch, hunks=other_changes
            )
            rounds = await improvement_repo.list_iterations(
                self.db, organization_id=run.organization_id, run_id=run.id
            )
            deferred = await improvement_repo.create_iteration(
                self.db,
                organization_id=run.organization_id,
                run_id=run.id,
                number=max(item.number for item in rounds) + 1,
            )
            await improvement_repo.update_iteration(
                self.db, iteration=deferred, values={"batch_id": separate.id}
            )
            remaining = model_changes
            await self._audit(run, "candidate_split")
        projected, skipped = authoring_hunks.projection(draft, remaining)
        dropped.extend(h.id for h in skipped)
        reasons.extend({"hunk_id": str(h.id), "reason": "does_not_apply"} for h in skipped)
        if dropped:
            if not filter_policy:
                raise ConcurrentChangeError(message="The candidate no longer applies to the draft")
            for hunk in pending:
                if hunk.id in dropped:
                    hunk.status = HunkStatus.DISMISSED.value
            await improvement_repo.update_iteration(
                self.db,
                iteration=iteration,
                values={"dropped_hunk_ids": dropped, "dropped": reasons},
            )
            await self._audit(run, "policy_dropped")
        return projected, len(remaining) - len(skipped)

    @staticmethod
    def _eval_request(inputs: Inputs, run: ImprovementRun) -> EvalRunRequest:
        # Keep the stored dataset version even after new cases are added.
        return inputs.request.model_copy(update={"dataset_version": run.dataset_version})

    async def _evaluate(
        self, ctx: AuthContext, inputs: Inputs, run: ImprovementRun, iteration: ImprovementIteration
    ) -> None:
        if iteration.eval_run_ids:
            child = await self.evals.get(ctx, iteration.eval_run_ids[-1])
            if not child.status.terminal:
                from app.repositories import eval_run_repo

                stored = await eval_run_repo.get(
                    self.db, child.id, organization_id=run.organization_id
                )
                assert stored is not None
                progress = max(
                    value
                    for value in (
                        stored.heartbeat_at,
                        stored.started_at,
                        run.stage_started_at,
                        run.created_at,
                    )
                    if value is not None
                )
                if rules.stalled(
                    Stage.EVALUATING,
                    waiting=child.status == "queued",
                    last_progress=progress,
                    now=datetime.now(UTC),
                ):
                    await self._stop_children(run)
                    await self._move(run, rules.stall(Stage.EVALUATING))
                return
            # A return from judging means an explicitly authorized inconclusive repeat.
            if iteration.verdict != ImprovementVerdict.INCONCLUSIVE.value:
                transition = rules.after_evaluating(child.status)
                if transition is not None:
                    await self._move(run, transition)
                return
        projected, count = await self._candidate(inputs.agent, run, iteration)
        batch = (
            await authoring_repo.get_batch(
                self.db, iteration.batch_id, organization_id=run.organization_id
            )
            if iteration.batch_id
            else None
        )
        assert batch is not None
        request = self._eval_request(inputs, run)
        scoring = DatasetScoring.model_validate(run.pinned_scoring)
        baseline = AgentSpec.model_validate(inputs.agent.draft_spec)
        estimate = await self.evals.estimate(
            ctx,
            run.agent_id,
            request,
            candidate_spec=projected,
            baseline_spec=baseline,
            scoring=scoring,
            exclude_conversations=batch.evidence_conversation_ids,
            judge_version_id=run.judge_version_id,
            judge_pinned=True,
        )
        spent = await improvement_repo.spent(self.db, run.id, organization_id=run.organization_id)
        transition = rules.before_evaluating(
            spent=spent,
            step_estimate=estimate.total_usd + estimate.rerun_ceiling_usd,
            budget=run.budget_usd,
        )
        if not transition.status.active:
            await self._move(run, transition)
            return
        child = await self.evals.start(
            ctx,
            run.agent_id,
            request,
            candidate_spec=projected,
            baseline_spec=baseline,
            scoring=scoring,
            exclude_conversations=batch.evidence_conversation_ids,
            judge_version_id=run.judge_version_id,
            judge_pinned=True,
            suite=None
            if inputs.suite is None
            else EvalSuiteCheck(
                suite_id=inputs.suite.id, name=inputs.suite.name, threshold=inputs.suite.threshold
            ),
            proposal_check=ProposalCheckRecord(
                kind="agent",
                base_version=None,
                on_draft=True,
                suggestions=count,
                improvement_run_id=run.id,
            ),
        )
        await improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={"eval_run_ids": [*iteration.eval_run_ids, child.id], "verdict": None},
        )
        await self._audit(run, "child_started")

    async def _judge(
        self, ctx: AuthContext, inputs: Inputs, run: ImprovementRun, iteration: ImprovementIteration
    ) -> None:
        child = await self.evals.get(ctx, iteration.eval_run_ids[-1])
        comparison = await self.evals.compare(ctx, child.id)
        mine, theirs = comparison.candidate_summary, comparison.baseline_summary
        suite = child.suite_check
        outcome = (
            None
            if suite is None
            else (
                rules.SuiteOutcome(suite.status)
                if suite.status in {"passed", "failed", "inconclusive"}
                else rules.SuiteOutcome.INCONCLUSIVE
            )
        )
        result = rules.CheckResult(
            comparable=comparison.baseline is not None and comparison.verdict != "invalid",
            incomplete=mine.incomplete + (theirs.incomplete if theirs else 0),
            ungraded=mine.ungraded + (theirs.ungraded if theirs else 0),
            crashed=mine.crashed + (theirs.crashed if theirs else 0),
            regressions_confirmed=comparison.regressions_confirmed,
            fixed_confirmed=comparison.fixed_confirmed,
            candidate_pass_rate=mine.pass_rate,
            baseline_pass_rate=None if theirs is None else theirs.pass_rate,
            suite=outcome,
        )
        verdict = rules.judge(result)
        await improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={
                "verdict": verdict.value,
                "verdict_detail": {
                    "broken": result.regressions_confirmed,
                    "fixed": result.fixed_confirmed,
                    "ungraded": result.ungraded,
                    "incomplete": result.incomplete,
                    "crashed": result.crashed,
                },
                "cost_usd": await improvement_repo.spent(
                    self.db, run.id, organization_id=run.organization_id
                ),
                "ended_at": datetime.now(UTC),
            },
        )
        await self._audit(run, "verdict")
        transition = rules.after_judging(
            verdict,
            reruns_used=len(iteration.eval_run_ids) - 1,
            spent=await improvement_repo.spent(
                self.db, run.id, organization_id=run.organization_id
            ),
            rerun_estimate=Decimal(0),
            budget=run.budget_usd,
        )
        # The evaluating transition checks the actual fresh full estimate before paying.
        if transition.status == Status.READY:
            assert iteration.batch_id is not None
            batch = await authoring_repo.get_batch(
                self.db, iteration.batch_id, organization_id=run.organization_id
            )
            assert batch is not None
            current = await authoring_repo.get_open_batch(
                self.db, organization_id=run.organization_id, agent_id=run.agent_id, lock=True
            )
            if current is not None and current.source_started_at > run.created_at:
                transition = rules.Transition(Status.STALE, Stage.JUDGING, StopReason.SUPERSEDED)
            else:
                if current is not None:
                    await authoring_repo.close_batch(
                        self.db, batch=current, status=BatchStatus.SUPERSEDED
                    )
                batch.status = BatchStatus.OPEN.value
                await improvement_repo.update_run(
                    self.db, run=run, values={"best_iteration_id": iteration.id}
                )
        await self._move(run, transition)

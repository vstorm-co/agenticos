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

from pydantic_ai.usage import RunUsage
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import price_request
from app.agents.capabilities.context import ContextBody
from app.agents.capabilities.knowledge._capability import KnowledgeConfig
from app.agents.capabilities.skills import SkillBody
from app.agents.factory import DEFAULT_MAX_STEPS
from app.agents.spec import AgentSpec
from app.core.audit import record_audit
from app.core.config import settings
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
    knowledge_gap_repo,
    organization_repo,
)
from app.schemas.authoring import AuthoringStart, HunkDecision, ProposalCheck
from app.schemas.eval_run import (
    EvalRunRead,
    EvalRunRequest,
    KnowledgeCheckRecord,
    ProposalCheckRecord,
)
from app.schemas.eval_suite import EvalSuiteCreate, EvalSuiteRead
from app.schemas.eval_threshold import EvalSuiteCheck
from app.schemas.improvement import (
    AttributionConsent,
    AttributionEstimate,
    ImprovementEstimate,
    ImprovementEvent,
    ImprovementFinish,
    ImprovementFinished,
    ImprovementIterationRead,
    ImprovementRead,
    ImprovementStart,
    ImprovementTarget,
    KnowledgeCheckConsent,
    KnowledgeCheckEstimate,
    KnowledgeCheckTarget,
)
from app.schemas.scoring import DatasetScoring
from app.services import authoring_fields, authoring_hunks
from app.services import improvement_states as rules
from app.services.agent_registry import AgentRegistryService
from app.services.api_key import job_context
from app.services.authoring import AuthoringService
from app.services.background_jobs import enqueue
from app.services.dataset import DatasetService
from app.services.embedding_resolution import embeddings_for_collection
from app.services.eval_run import EvalRunService, scoring_hash, spec_hash
from app.services.eval_suite import EvalSuiteService
from app.services.improvement_data import input_hash
from app.services.knowledge_gaps import KnowledgeGapService, draft_fingerprint
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


@dataclass(frozen=True)
class KnowledgePlan:
    session: ImprovementRun
    request: EvalRunRequest
    base: AgentSpec
    candidate: AgentSpec
    skills: dict[UUID, SkillBody]
    contexts: dict[UUID, ContextBody]
    record: ProposalCheckRecord
    quote: KnowledgeCheckEstimate


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
            evidence_dataset_id=inputs.request.dataset_id,
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
        pack = await self.authoring.evidence.for_agent(
            ctx, agent_id, window_days=data.window_days, dataset_id=inputs.request.dataset_id
        )
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
                        "chat_evidence_run_ids": [
                            item.run_id for item in pack.runs if item.evidence_kind == "chat"
                        ],
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
        if ctx.has(Perm.RUNS_VIEW):
            result.knowledge_eval_run_ids = await improvement_repo.knowledge_checks(
                self.db, run.id, organization_id=ctx.organization_id
            )
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
        if Status(run.status).active or run.status in {Status.READY, Status.STOPPED}:
            # Cancellation must still work after the creator loses resource access.
            await self._stop_children(run)
            await self._move(
                run, rules.Transition(Status.CANCELLED, Stage(run.stage) if run.stage else None)
            )
        return await self._read(ctx, run)

    async def finish(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, data: ImprovementFinish
    ) -> ImprovementFinished:
        """Accept the selected round and optionally publish, in one human-confirmed transaction.

        Normal authoring and publish validation apply to the confirming person.
        Guarded environments remain on their old version until their checks pass.
        """
        await self.authoring._editable(ctx, agent_id)
        self.authoring._require_runs_view(ctx)
        run = await self._row(ctx, agent_id, run_id, lock=True)
        if run.status == Status.PUBLISHED:
            raise ConcurrentChangeError(message="This session was already published")
        if run.status != Status.READY:
            raise BadRequestError(message="Select a checked round before accepting it")
        await self.ensure_current(ctx, run.id, allow_finished=True)
        if await improvement_repo.has_active_check(
            self.db, run.id, organization_id=ctx.organization_id
        ):
            raise ConcurrentChangeError(
                message="Wait for this session's checks to finish, or stop the session"
            )
        rounds = await improvement_repo.list_iterations(
            self.db, organization_id=run.organization_id, run_id=run.id
        )
        selected = next((item for item in rounds if item.id == run.best_iteration_id), None)
        if selected is None or selected.batch_id is None:
            raise BadRequestError(message="No checked round is selected")
        batch = await authoring_repo.get_open_batch(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id
        )
        if batch is None or batch.id != selected.batch_id:
            raise ConcurrentChangeError(message="The selected suggestions were replaced")
        hunks = await authoring_repo.list_hunks(
            self.db, organization_id=ctx.organization_id, batch_id=batch.id
        )
        agent = await self.authoring._editable(ctx, agent_id)
        projected, skipped = authoring_hunks.projection(
            AgentSpec.model_validate(agent.draft_spec), hunks
        )
        if (
            skipped
            or spec_hash(projected, authoring_hunks.projected_skills(hunks))
            != selected.candidate_spec_hash
        ):
            raise ConcurrentChangeError(
                message="The selected changes differ from the checked candidate; check them again"
            )
        for hunk in hunks:
            if hunk.status == HunkStatus.PENDING:
                await self.authoring.decide(ctx, agent_id, hunk.id, HunkDecision(action="accept"))
        if data.automatic_check:
            suites = await EvalSuiteService(self.db).list_for_agent(ctx, agent_id)
            if not suites.items:
                await EvalSuiteService(self.db).create(
                    ctx,
                    agent_id,
                    EvalSuiteCreate(
                        name="Improvement checks",
                        dataset_id=run.dataset_id,
                        on_publish=True,
                        max_run_usd=run.budget_usd,
                    ),
                )
        version = await self.registry.publish(ctx, agent_id) if data.publish else None
        await improvement_repo.update_run(
            self.db,
            run=run,
            values={"status": Status.PUBLISHED.value if version else Status.ACCEPTED.value},
        )
        await self._audit(run, "published" if version else "accepted", actor_user_id=ctx.subject_id)
        return ImprovementFinished(
            session=await self._read(ctx, run),
            version_id=None if version is None else version.id,
            version=None if version is None else version.version,
        )

    async def retry(self, ctx: AuthContext, agent_id: UUID, run_id: UUID) -> ImprovementRead:
        """Retry a failed paid step only after a person's explicit request.

        The parent lock makes a repeated click idempotent. The old child remains
        in Activity; its cost counts toward the same budget and the new child
        is created in this transaction. No job retries a paid call implicitly.
        """
        await self.authoring._editable(ctx, agent_id)
        self.authoring._require_runs_view(ctx)
        run = await self._row(ctx, agent_id, run_id, lock=True)
        if Status(run.status).active:
            return await self._read(ctx, run)
        if run.status != Status.FAILED or run.stage not in {Stage.PROPOSING, Stage.EVALUATING}:
            raise BadRequestError(message="Only a failed proposal or test step can be retried")
        other = await improvement_repo.get_active(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id
        )
        if other is not None:
            raise ConcurrentChangeError(message="Another improvement session is running")
        iteration = await improvement_repo.get_iteration(
            self.db, organization_id=ctx.organization_id, run_id=run.id, number=run.iteration
        )
        assert iteration is not None
        # A refusal rolls this transaction back, including this temporary status.
        await improvement_repo.update_run(
            self.db,
            run=run,
            values={
                "status": Status.RUNNING.value,
                "error": None,
                "stop_reason": None,
                "finished_at": None,
            },
        )
        await self.ensure_current(ctx, run.id)
        if run.stage == Stage.PROPOSING:
            await improvement_repo.update_iteration(
                self.db, iteration=iteration, values={"authoring_request_id": None}
            )
            await self._step(
                ctx,
                await self._inputs(
                    ctx,
                    agent_id,
                    ImprovementTarget(
                        dataset_id=run.dataset_id if run.suite_id is None else None,
                        suite_id=run.suite_id,
                    ),
                ),
                run,
                iteration,
            )
        else:
            inputs = await self._inputs(
                ctx,
                agent_id,
                ImprovementTarget(
                    dataset_id=run.dataset_id if run.suite_id is None else None,
                    suite_id=run.suite_id,
                ),
            )
            await self._evaluate(ctx, inputs, run, iteration, force_new=True)
        await self._audit(run, "retried", actor_user_id=ctx.subject_id)
        if Status(run.status).active:
            await self._move(run, rules.Transition(Status.RUNNING, Stage(run.stage)))
        return await self._read(ctx, run)

    async def _stop_children(self, run: ImprovementRun) -> None:
        from app.db.models.eval_run import EvalRunStatus
        from app.repositories import eval_run_repo

        for child_id in await improvement_repo.knowledge_checks(
            self.db, run.id, organization_id=run.organization_id
        ):
            await eval_run_repo.cancel_live(
                self.db, child_id, organization_id=run.organization_id, now=datetime.now(UTC)
            )
        iterations = await improvement_repo.list_iterations(
            self.db, organization_id=run.organization_id, run_id=run.id
        )
        for iteration in iterations:
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
            for child_id in [
                *iteration.eval_run_ids,
                *(UUID(value) for value in iteration.attribution_eval_run_ids.values()),
            ]:
                child = await eval_run_repo.get(
                    self.db, child_id, organization_id=run.organization_id
                )
                if child is not None and not EvalRunStatus(child.status).terminal:
                    await eval_run_repo.cancel_live(
                        self.db,
                        child.id,
                        organization_id=run.organization_id,
                        now=datetime.now(UTC),
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
        after = None
        while rows := await improvement_repo.list_waiting(self.db, after=after):
            for run_id, org_id in rows:
                run = await improvement_repo.get_run(self.db, run_id, organization_id=org_id)
                if run is not None:
                    await self._queue(run)
                    count += 1
            after = rows[-1][0]
        return count

    async def _settle_decisions(self, run: ImprovementRun) -> None:
        """Observe human decisions without acquiring an agent lock after the parent lock."""
        rounds = await improvement_repo.list_iterations(
            self.db, organization_id=run.organization_id, run_id=run.id
        )
        selected = next((item for item in rounds if item.id == run.best_iteration_id), None)
        if selected is None or selected.batch_id is None:
            return
        batch = await authoring_repo.get_batch(
            self.db, selected.batch_id, organization_id=run.organization_id
        )
        if batch is None or batch.status == BatchStatus.SUPERSEDED:
            status = Status.REJECTED
        else:
            hunks = await authoring_repo.list_hunks(
                self.db, organization_id=run.organization_id, batch_id=batch.id
            )
            accepted = any(h.status == HunkStatus.ACCEPTED for h in hunks)
            pending = any(h.status == HunkStatus.PENDING for h in hunks)
            if batch.status == BatchStatus.PUBLISHED:
                status = Status.PUBLISHED if accepted else Status.REJECTED
            elif pending:
                status = Status.READY
            else:
                status = Status.ACCEPTED if accepted else Status.REJECTED
        if run.status != status:
            await improvement_repo.update_run(self.db, run=run, values={"status": status.value})
            await self._audit(run, status.value)

    async def _audit(
        self, run: ImprovementRun, action: str, *, actor_user_id: UUID | None = None
    ) -> None:
        await record_audit(
            self.db,
            actor_user_id=actor_user_id or run.created_by_user_id,
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
        elif transition.status in {Status.READY, Status.STOPPED, Status.FAILED}:
            agent = await agent_repo.get(self.db, run.agent_id, organization_id=run.organization_id)
            if agent is not None and run.created_by_user_id is not None:
                await NotificationService(self.db).improvement_finished(
                    agent=agent,
                    run_id=run.id,
                    user_id=run.created_by_user_id,
                    status=run.status,
                    reason=run.stop_reason,
                )

    async def ensure_current(
        self, ctx: AuthContext, run_id: UUID, *, allow_finished: bool = False
    ) -> None:
        """Recheck a queued paid child's authority and pins just before it starts."""
        run = await improvement_repo.get_run(self.db, run_id, organization_id=ctx.organization_id)
        if run is None or not (
            Status(run.status).active
            or (allow_finished and run.status in {Status.READY, Status.STOPPED})
        ):
            raise BadRequestError(
                message="The improvement session stopped", details={"reason": "stopped"}
            )
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        if organization is None or not organization.ai_assistance_enabled:
            raise AuthorizationError(message="AI assistance is disabled")
        inputs = await self._inputs(
            ctx,
            run.agent_id,
            ImprovementTarget(
                dataset_id=run.dataset_id if run.suite_id is None else None, suite_id=run.suite_id
            ),
        )
        pinned = rules.Pins(
            run.base_draft_hash,
            run.base_version_id,
            run.scoring_hash,
            run.dataset_id,
            run.suite_id,
            run.suite_hash,
        )
        if run.chat_evidence_run_ids is None or rules.stale(pinned, inputs.pins, archived=False):
            raise ConcurrentChangeError(
                message="The improvement session is stale", details={"reason": "stale"}
            )

    async def advance(self, run_id: UUID, organization_id: UUID) -> None:
        run = await improvement_repo.get_run(
            self.db, run_id, organization_id=organization_id, lock=True
        )
        if run is None:
            return
        if Status(run.status).waiting:
            await self._settle_decisions(run)
            return
        if not Status(run.status).active:
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
        if (
            run.pinned_scoring is None
            or run.chat_evidence_run_ids is None
            or rules.stale(pins, inputs.pins, archived=False)
        ):
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
            pack = await self.authoring.evidence.for_improvement(ctx, run.id)
            plan = await self.evals.plan(
                ctx,
                run.agent_id,
                self._eval_request(inputs, run),
                scoring=inputs.scoring,
                candidate_spec=AgentSpec.model_validate(inputs.agent.draft_spec),
                exclude_conversations=pack.conversation_ids,
            )
            measured = await self.evals.improvement_measurement(
                ctx,
                plan,
                evidence_run_ids=list(
                    {*(run.chat_evidence_run_ids or []), *(item.run_id for item in pack.runs)}
                ),
                evidence_conversations=pack.conversation_ids,
            )
            await improvement_repo.update_iteration(
                self.db,
                iteration=iteration,
                values={
                    "verdict_detail": {
                        "gradable_holdout": measured.gradable_holdout,
                        "minimum_holdout": measured.minimum_holdout,
                        "missing_holdout": max(
                            0, measured.minimum_holdout - measured.gradable_holdout
                        ),
                    },
                },
            )
            transition = rules.after_analyzing(
                has_evidence=bool(pack.runs), gradable_cases=measured.gradable_holdout
            )
            if transition.stop_reason == StopReason.NO_DATA:
                needed = max(0, measured.minimum_holdout - measured.gradable_holdout)
                await improvement_repo.update_run(
                    self.db,
                    run=run,
                    values={
                        "error": f"Add {needed} more held-out test questions to measure a change"
                        if needed
                        else "No rated chat runs or training failures are available yet",
                    },
                )
            # Knowledge classification is a separate branch; no paid classification
            # is necessary for a session proposing agent changes only.
            if transition.status.active:
                transition = rules.Transition(Status.RUNNING, Stage.PROPOSING)
            await self._move(run, transition)
        elif run.stage == Stage.PROPOSING:
            if iteration.batch_id is not None and iteration.authoring_request_id is None:
                await self._move(run, rules.Transition(Status.RUNNING, Stage.FILTERING))
                return
            if iteration.authoring_request_id is None:
                estimate = await self.authoring.estimate_agent(
                    ctx,
                    run.agent_id,
                    AuthoringStart(
                        window_days=run.window_days, improver_agent_id=run.improver_agent_id
                    ),
                    improvement_run_id=run.id,
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
            assert iteration.batch_id is not None
            candidate_hash = spec_hash(
                projected, await self.authoring.projected_skills(ctx, iteration.batch_id)
            )
            await improvement_repo.update_iteration(
                self.db, iteration=iteration, values={"candidate_spec_hash": candidate_hash}
            )
            previous = await improvement_repo.list_iterations(
                self.db, organization_id=run.organization_id, run_id=run.id
            )
            repeated = any(
                item.number < iteration.number
                and item.eval_run_ids
                and item.candidate_spec_hash == candidate_hash
                for item in previous
            )
            await self._move(
                run,
                rules.Transition(Status.STOPPED, Stage.FILTERING, StopReason.REPEAT_CANDIDATE)
                if repeated
                else rules.after_filtering(kept=kept),
            )
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
        self,
        ctx: AuthContext,
        inputs: Inputs,
        run: ImprovementRun,
        iteration: ImprovementIteration,
        *,
        force_new: bool = False,
    ) -> None:
        if iteration.eval_run_ids and not force_new:
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
            candidate_skills=await self.authoring.projected_skills(ctx, batch.id),
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
            candidate_skills=await self.authoring.projected_skills(ctx, batch.id),
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
                evidence_run_ids=list(
                    {
                        *(run.chat_evidence_run_ids or []),
                        *await self.authoring.evidence_run_ids(ctx, batch),
                    }
                ),
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
        rounds = await improvement_repo.list_iterations(
            self.db, organization_id=run.organization_id, run_id=run.id
        )
        spent = await improvement_repo.spent(self.db, run.id, organization_id=run.organization_id)
        previous_cost = sum(
            (item.cost_usd for item in rounds if item.number < iteration.number), Decimal(0)
        )
        await improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={
                "verdict": verdict.value,
                "verdict_detail": {
                    **(iteration.verdict_detail or {}),
                    "broken": result.regressions_confirmed,
                    "fixed": result.fixed_confirmed,
                    "ungraded": result.ungraded,
                    "incomplete": result.incomplete,
                    "crashed": result.crashed,
                    "candidate_pass_rate": result.candidate_pass_rate,
                    "baseline_pass_rate": result.baseline_pass_rate,
                },
                "cost_usd": max(Decimal(0), spent - previous_cost),
                "ended_at": datetime.now(UTC),
            },
        )
        await self._audit(run, "verdict")
        transition = rules.after_judging(
            verdict,
            reruns_used=max(
                0,
                await improvement_repo.completed_checks(
                    self.db, iteration.eval_run_ids, organization_id=run.organization_id
                )
                - 1,
            ),
            spent=await improvement_repo.spent(
                self.db, run.id, organization_id=run.organization_id
            ),
            rerun_estimate=Decimal(0),
            budget=run.budget_usd,
        )
        results = [
            rules.RoundResult(
                item.number,
                ImprovementVerdict(item.verdict),
                (item.verdict_detail or {}).get("broken", 0),
                (item.verdict_detail or {}).get("candidate_pass_rate"),
            )
            for item in rounds
            if item.verdict is not None and item.number <= iteration.number
        ]
        best_number = rules.best_round(results)
        best = next((item for item in rounds if item.number == best_number), None)
        await improvement_repo.update_run(
            self.db, run=run, values={"best_iteration_id": None if best is None else best.id}
        )
        # A confirming rerun belongs to this round, before considering a new proposal.
        if transition.status.active:
            await self._move(run, transition)
            return
        if verdict != ImprovementVerdict.BETTER:
            reason = rules.round_stop(results, maximum=run.max_iterations)
            if reason is None:
                target = ImprovementTarget(
                    dataset_id=run.dataset_id if run.suite_id is None else None,
                    suite_id=run.suite_id,
                    window_days=run.window_days,
                    improver_agent_id=run.improver_agent_id,
                    max_iterations=1,
                )
                estimate = await self._estimate(ctx, inputs, target)
                if not estimate.affordable or not rules.affordable(
                    spent=spent, step_estimate=estimate.total_usd, budget=run.budget_usd
                ):
                    reason = StopReason.BUDGET
            if reason is None:
                following = next(
                    (item for item in rounds if item.number == run.iteration + 1), None
                )
                if following is None:
                    await improvement_repo.create_iteration(
                        self.db,
                        organization_id=run.organization_id,
                        run_id=run.id,
                        number=run.iteration + 1,
                    )
                await improvement_repo.update_run(
                    self.db, run=run, values={"iteration": run.iteration + 1}
                )
                await self._move(run, rules.Transition(Status.RUNNING, Stage.PROPOSING))
                return
            transition = rules.Transition(Status.STOPPED, Stage.JUDGING, reason)
        if transition.status == Status.READY:
            transition = await self._expose(run, iteration)
        await self._move(run, transition)

    async def _expose(
        self, run: ImprovementRun, iteration: ImprovementIteration
    ) -> rules.Transition:
        assert iteration.batch_id is not None
        batch = await authoring_repo.get_batch(
            self.db, iteration.batch_id, organization_id=run.organization_id
        )
        if batch is None:
            raise NotFoundError(message="The round's candidate is no longer available")
        current = await authoring_repo.get_open_batch(
            self.db, organization_id=run.organization_id, agent_id=run.agent_id, lock=True
        )
        if current is not None and current.id != batch.id:
            if current.improvement_run_id != run.id and current.source_started_at > run.created_at:
                return rules.Transition(Status.STALE, Stage.JUDGING, StopReason.SUPERSEDED)
            await authoring_repo.close_batch(self.db, batch=current, status=BatchStatus.SUPERSEDED)
        batch.status = BatchStatus.OPEN.value
        batch.closed_at = None
        batch.check_eval_run_ids = list(iteration.eval_run_ids)
        await self.db.flush()
        return rules.Transition(Status.READY, Stage.JUDGING)

    async def select_round(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, number: int
    ) -> ImprovementRead:
        await self.authoring._editable(ctx, agent_id)
        self.authoring._require_runs_view(ctx)
        run = await self._row(ctx, agent_id, run_id, lock=True)
        if run.status not in {Status.READY, Status.STOPPED}:
            raise BadRequestError(message="Choose a round after the session finishes")
        await self.ensure_current(ctx, run.id, allow_finished=True)
        iteration = await improvement_repo.get_iteration(
            self.db, organization_id=run.organization_id, run_id=run.id, number=number
        )
        if iteration is None or iteration.verdict is None or iteration.batch_id is None:
            raise NotFoundError(message="A measured round is not available")
        transition = await self._expose(run, iteration)
        if transition.status == Status.READY:
            await improvement_repo.update_run(
                self.db, run=run, values={"best_iteration_id": iteration.id}
            )
        await self._audit(run, "round_selected")
        await self._move(run, transition)
        return await self._read(ctx, run)

    async def _knowledge_plan(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, data: KnowledgeCheckTarget
    ) -> KnowledgePlan | KnowledgeCheckEstimate:
        run, iteration, inputs = await self._attribution_target(ctx, agent_id, run_id, data.round)
        gaps = KnowledgeGapService(self.db)
        topic = await gaps._topic(ctx, data.topic_id, edit=True)
        if (await gaps._row(ctx, topic)).status != "open":
            raise BadRequestError(message="Reopen the knowledge topic before checking a draft")
        kb = await gaps._knowledge_base(ctx, topic.knowledge_base_id, edit=True)
        if not topic.draft_content:
            raise BadRequestError(message="This topic has no draft to check")
        base, _ = await self._candidate(inputs.agent, run, iteration)
        if topic.knowledge_base_id not in base.collection_ids:
            raise BadRequestError(message="The selected round does not search this knowledge base")
        assert iteration.batch_id is not None
        skills = await self.authoring.projected_skills(ctx, iteration.batch_id)
        if spec_hash(base, skills) != iteration.candidate_spec_hash:
            raise ConcurrentChangeError(
                message="The selected changes no longer match the measured round"
            )
        evidence = await knowledge_gap_repo.topic_evidence(
            self.db, topic.id, organization_id=ctx.organization_id
        )
        if len(evidence) > 1000:
            raise BadRequestError(
                message="The topic has too much source material to isolate a test safely"
            )
        source_runs = (
            {row.run_id for row in evidence}
            | set(topic.draft_evidence_run_ids or [])
            | set(run.chat_evidence_run_ids or [])
        )
        conversations = {row.conversation_id for row in evidence if row.conversation_id is not None}
        sources = await authoring_repo.evidence_inputs(
            self.db,
            organization_id=ctx.organization_id,
            run_ids=list(source_runs),
            conversation_ids=list(conversations),
        )
        if sources.truncated:
            raise BadRequestError(
                message="The source material is too large to isolate a test safely"
            )
        source_hashes = {
            input_hash(text) for text in [*sources.inputs, *(row.query for row in evidence)]
        }
        source_hashes.update(topic.draft_evidence_input_hashes or [])
        version = await dataset_repo.get_version(
            self.db, run.dataset_id, run.dataset_version, organization_id=ctx.organization_id
        )
        if version is None:
            raise NotFoundError(message="The session's test questions no longer exist")
        cases = await dataset_repo.list_cases(
            self.db, version.id, organization_id=ctx.organization_id, limit=None
        )
        selected = set(data.case_ids)
        if len(selected) != len(data.case_ids) or selected - {case.case_id for case in cases}:
            raise BadRequestError(message="Choose distinct questions from this session's test set")
        # Every topic member is excluded, not only the subset the drafter cited.
        eligible = [
            case.case_id
            for case in cases
            if case.case_id in selected
            and case.improvement_partition == "holdout"
            and case.anonymised_at is None
            and case.source_run_id not in source_runs
            and case.source_conversation_id not in conversations
            and input_hash(case.input) not in source_hashes
        ]
        document_ids = [
            UUID(source["id"]) for source in topic.draft_sources if source.get("kind") == "document"
        ]
        supported = bool(
            await knowledge_gap_repo.documents_in(
                self.db, topic.knowledge_base_id, document_ids, organization_id=ctx.organization_id
            )
        )
        hashed = draft_fingerprint(topic)
        if topic.draft_evidence_run_ids is None or topic.draft_evidence_input_hashes is None:
            return KnowledgeCheckEstimate(
                total_usd=Decimal(0),
                affordable=False,
                can_measure=False,
                cases=0,
                excluded=len(selected),
                supported=supported,
                draft_hash=hashed,
                reason="untracked_draft_sources",
            )
        if not eligible:
            return KnowledgeCheckEstimate(
                total_usd=Decimal(0),
                affordable=False,
                can_measure=False,
                cases=0,
                excluded=len(selected),
                supported=supported,
                draft_hash=hashed,
                reason="no_independent_questions",
            )
        request = self._eval_request(inputs, run).model_copy(update={"case_ids": eligible})
        contexts = {
            topic.id: ContextBody(
                name=f"draft-{topic.id}", description=topic.draft_title, content=topic.draft_content
            )
        }
        binding = next((binding for binding in base.capabilities if binding.id == "context"), None)
        capabilities = list(base.capabilities)
        context_ids = list(base.context_ids)
        if binding is None or not binding.enabled:
            from app.agents.spec import CapabilityBindingSpec

            capabilities = [item for item in capabilities if item.id != "context"] + [
                CapabilityBindingSpec(id="context")
            ]
            context_ids = []
        candidate = base.model_copy(
            update={"context_ids": [*context_ids, topic.id], "capabilities": capabilities}
        )
        record = ProposalCheckRecord(
            kind="context",
            base_version=None,
            on_draft=True,
            suggestions=1,
            improvement_run_id=run.id,
            evidence_run_ids=list(source_runs),
            knowledge=KnowledgeCheckRecord(
                topic_id=topic.id, draft_hash=hashed, supported=supported, mode=data.mode
            ),
        )
        if data.mode == "retrieval":
            knowledge_binding = next(
                (item for item in base.capabilities if item.id == "knowledge" and item.enabled),
                None,
            )
            if knowledge_binding is None:
                return KnowledgeCheckEstimate(
                    total_usd=Decimal(0),
                    affordable=False,
                    can_measure=False,
                    cases=len(eligible),
                    excluded=len(selected) - len(eligible),
                    supported=supported,
                    draft_hash=hashed,
                    reason="knowledge_search_disabled",
                )
            resolved = await embeddings_for_collection(kb.collection_name, ctx.organization_id)
            if (
                resolved is None
                or resolved.key_source.is_degraded
                or resolved.vector_tenant != ctx.organization_id
            ):
                return KnowledgeCheckEstimate(
                    total_usd=Decimal(0),
                    affordable=False,
                    can_measure=False,
                    cases=len(eligible),
                    excluded=len(selected) - len(eligible),
                    supported=supported,
                    draft_hash=hashed,
                    reason="embedding_unavailable",
                )
            config = KnowledgeConfig.model_validate(knowledge_binding.config)
            variants = (
                1 + config.query_analysis_max_variants
                if config.query_analysis_mode == "multi_query"
                else 1
            )
            searches = (
                (base.max_steps or DEFAULT_MAX_STEPS)
                * variants
                * (2 if settings.rag.enable_hybrid_search else 1)
            )
            tokens = (
                len(topic.draft_content.encode("utf-8")) + 3
            ) // 4 + settings.EVAL_FALLBACK_INPUT_TOKENS
            priced = price_request(
                RunUsage(input_tokens=tokens * searches), resolved.model, resolved.provider
            )
            if priced is None:
                return KnowledgeCheckEstimate(
                    total_usd=Decimal(0),
                    affordable=False,
                    can_measure=False,
                    cases=len(eligible),
                    excluded=len(selected) - len(eligible),
                    supported=supported,
                    draft_hash=hashed,
                    reason="embedding_price_unavailable",
                )
            embedding_usd = (priced * len(eligible)).quantize(Decimal("0.000001"))
            assert record.knowledge is not None
            record.knowledge.collection_name = kb.collection_name
            record.knowledge.embedding_model = resolved.model
            record.knowledge.embedding_dim = resolved.dim
            record.knowledge.embedding_estimate_usd = embedding_usd
            record.knowledge.embedding_rerun_ceiling_usd = embedding_usd * (
                request.reruns if request.reruns is not None else settings.EVAL_RERUNS
            )
            candidate = base
        estimate = await self.evals.estimate(
            ctx,
            agent_id,
            request,
            scoring=DatasetScoring.model_validate(run.pinned_scoring),
            judge_version_id=run.judge_version_id,
            judge_pinned=True,
            candidate_spec=candidate,
            candidate_skills=skills,
            candidate_contexts=contexts,
            baseline_spec=base,
            baseline_skills=skills,
            exclude_conversations=list(conversations),
            proposal_check=record,
        )
        measured = estimate.proposal_check.measurement if estimate.proposal_check else None
        can_measure = measured is not None and measured.gradable_holdout >= measured.minimum_holdout
        total = estimate.total_usd + estimate.rerun_ceiling_usd
        quote = KnowledgeCheckEstimate(
            total_usd=total,
            affordable=can_measure
            and estimate.affordable
            and rules.affordable(
                spent=await improvement_repo.spent(
                    self.db, run.id, organization_id=ctx.organization_id
                ),
                step_estimate=total,
                budget=run.budget_usd,
            ),
            can_measure=can_measure,
            cases=len(eligible),
            excluded=len(selected) - len(eligible),
            supported=supported,
            draft_hash=hashed,
            reason=None if can_measure else "too_few_independent_questions",
        )
        return KnowledgePlan(run, request, base, candidate, skills, contexts, record, quote)

    async def estimate_knowledge(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, data: KnowledgeCheckTarget
    ) -> KnowledgeCheckEstimate:
        planned = await self._knowledge_plan(ctx, agent_id, run_id, data)
        return planned.quote if isinstance(planned, KnowledgePlan) else planned

    async def start_knowledge(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, data: KnowledgeCheckConsent
    ) -> EvalRunRead:
        planned = await self._knowledge_plan(ctx, agent_id, run_id, data)
        quote = planned.quote if isinstance(planned, KnowledgePlan) else planned
        if quote.draft_hash != data.draft_hash or quote.total_usd != data.estimate_usd:
            raise ConcurrentChangeError(
                message="The draft or its estimate changed; review the new estimate"
            )
        if not isinstance(planned, KnowledgePlan) or not quote.can_measure:
            raise BadRequestError(message="This draft cannot be measured on the selected questions")
        # The parent row is locked before the quote. No two clicks can reserve
        # additional work against the same available session budget.
        if await improvement_repo.has_active_check(
            self.db, run_id, organization_id=ctx.organization_id
        ):
            raise ConcurrentChangeError(message="A check is already running in this session")
        if not quote.affordable:
            raise PaymentRequiredError(
                message="The complete knowledge check exceeds the remaining budget"
            )
        child = await self.evals.start(
            ctx,
            agent_id,
            planned.request,
            scoring=DatasetScoring.model_validate(planned.session.pinned_scoring),
            judge_version_id=planned.session.judge_version_id,
            judge_pinned=True,
            candidate_spec=planned.candidate,
            candidate_skills=planned.skills,
            candidate_contexts=planned.contexts,
            baseline_spec=planned.base,
            baseline_skills=planned.skills,
            proposal_check=planned.record,
        )
        await self._audit(planned.session, "knowledge_check_started", actor_user_id=ctx.user_id)
        return child

    async def _attribution_target(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, number: int
    ) -> tuple[ImprovementRun, ImprovementIteration, Inputs]:
        await self.authoring._editable(ctx, agent_id)
        self.authoring._require_runs_view(ctx)
        run = await self._row(ctx, agent_id, run_id, lock=True)
        if run.status not in {Status.READY, Status.STOPPED}:
            raise BadRequestError(message="Attribution is available after the session finishes")
        await self.ensure_current(ctx, run_id, allow_finished=True)
        iteration = await improvement_repo.get_iteration(
            self.db, organization_id=run.organization_id, run_id=run.id, number=number
        )
        if iteration is None or iteration.batch_id is None or iteration.verdict is None:
            raise NotFoundError(message="A measured round is not available")
        inputs = await self._inputs(
            ctx,
            agent_id,
            ImprovementTarget(
                dataset_id=run.dataset_id if run.suite_id is None else None, suite_id=run.suite_id
            ),
        )
        return run, iteration, inputs

    async def _attribution_changes(
        self, ctx: AuthContext, run: ImprovementRun, iteration: ImprovementIteration, inputs: Inputs
    ) -> list[tuple[UUID, AgentSpec, Decimal]]:
        assert iteration.batch_id is not None
        baseline = AgentSpec.model_validate(inputs.agent.draft_spec)
        hunks = await authoring_repo.list_hunks(
            self.db, organization_id=run.organization_id, batch_id=iteration.batch_id
        )
        changes: list[tuple[UUID, AgentSpec, Decimal]] = []
        for hunk in hunks:
            if hunk.status != HunkStatus.PENDING.value:
                continue
            candidate, skipped = authoring_hunks.projection(baseline, [hunk])
            if skipped:
                raise ConcurrentChangeError(message="A change no longer applies to the base")
            estimate = await self.evals.estimate(
                ctx,
                run.agent_id,
                self._eval_request(inputs, run),
                candidate_spec=candidate,
                candidate_skills=authoring_hunks.projected_skills([hunk]),
                baseline_spec=baseline,
                scoring=DatasetScoring.model_validate(run.pinned_scoring),
                judge_version_id=run.judge_version_id,
                judge_pinned=True,
            )
            changes.append((hunk.id, candidate, estimate.total_usd + estimate.rerun_ceiling_usd))
        if not changes:
            raise BadRequestError(message="No pending changes can be attributed")
        return changes

    async def estimate_attribution(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, number: int
    ) -> AttributionEstimate:
        run, iteration, inputs = await self._attribution_target(ctx, agent_id, run_id, number)
        if iteration.attribution_eval_run_ids:
            return AttributionEstimate(
                changes=len(iteration.attribution_eval_run_ids),
                total_usd=Decimal(0),
                affordable=True,
                already_started=True,
            )
        changes = await self._attribution_changes(ctx, run, iteration, inputs)
        total = sum((price for _, _, price in changes), Decimal(0))
        spent = await improvement_repo.spent(self.db, run_id, organization_id=run.organization_id)
        org_left = await self.evals._org_left(ctx)
        return AttributionEstimate(
            changes=len(changes),
            total_usd=total,
            affordable=rules.affordable(spent=spent, step_estimate=total, budget=run.budget_usd)
            and (org_left is None or total <= org_left),
            already_started=False,
        )

    async def start_attribution(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        run_id: UUID,
        number: int,
        consent: AttributionConsent,
    ) -> ImprovementRead:
        run, iteration, inputs = await self._attribution_target(ctx, agent_id, run_id, number)
        if iteration.attribution_eval_run_ids:
            return await self._read(ctx, run)
        if await improvement_repo.has_active_check(
            self.db, run_id, organization_id=ctx.organization_id
        ):
            raise ConcurrentChangeError(message="Another check is still running")
        changes = await self._attribution_changes(ctx, run, iteration, inputs)
        total = sum((price for _, _, price in changes), Decimal(0))
        if total > consent.estimate_usd:
            raise ConcurrentChangeError(
                message="The attribution estimate changed; review it again",
                details={"estimate_usd": str(total)},
            )
        spent = await improvement_repo.spent(self.db, run_id, organization_id=run.organization_id)
        org_left = await self.evals._org_left(ctx)
        if not rules.affordable(spent=spent, step_estimate=total, budget=run.budget_usd) or (
            org_left is not None and total > org_left
        ):
            raise PaymentRequiredError(message="Attribution exceeds the remaining budget")
        assert iteration.batch_id is not None
        batch = await authoring_repo.get_batch(
            self.db, iteration.batch_id, organization_id=run.organization_id
        )
        assert batch is not None
        evidence_ids = list(
            {*(run.chat_evidence_run_ids or []), *await self.authoring.evidence_run_ids(ctx, batch)}
        )
        ids: dict[str, str] = {}
        for hunk_id, candidate, _ in changes:
            hunk = await authoring_repo.get_hunk(
                self.db, hunk_id, organization_id=run.organization_id
            )
            assert hunk is not None
            child = await self.evals.start(
                ctx,
                run.agent_id,
                self._eval_request(inputs, run),
                candidate_spec=candidate,
                candidate_skills=authoring_hunks.projected_skills([hunk]),
                baseline_spec=AgentSpec.model_validate(inputs.agent.draft_spec),
                scoring=DatasetScoring.model_validate(run.pinned_scoring),
                exclude_conversations=batch.evidence_conversation_ids,
                judge_version_id=run.judge_version_id,
                judge_pinned=True,
                proposal_check=ProposalCheckRecord(
                    kind="agent",
                    base_version=None,
                    on_draft=True,
                    suggestions=1,
                    improvement_run_id=run.id,
                    evidence_run_ids=evidence_ids,
                ),
            )
            ids[str(hunk_id)] = str(child.id)
        await improvement_repo.update_iteration(
            self.db, iteration=iteration, values={"attribution_eval_run_ids": ids}
        )
        await self._audit(run, "attribution_started")
        return await self._read(ctx, run)

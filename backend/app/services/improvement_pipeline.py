"""Durable, transactionally advanced improvement sessions.

A transition only coordinates stored children. Paid calls belong to authoring
and eval jobs, each of which has one attempt. The minute sweep recovers a lost
transition without repeating a model call. Only an explicit human finish accepts or publishes.
"""

import hashlib
import json
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
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
from app.agents.system_agents import refuse_system_agent
from app.core.audit import record_audit
from app.core.background import spawn_after_commit
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
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm, Scope
from app.db.models.agent import Agent, AgentStatus
from app.db.models.authoring import (
    AuthoringStatus,
    BatchStatus,
    HunkKind,
    HunkStatus,
    SpecProposalBatch,
    SpecProposalHunk,
)
from app.db.models.eval_run import ArmRole, EvalRun
from app.db.models.improvement import (
    DroppedHunk,
    ImprovementIteration,
    ImprovementRun,
    ImprovementVerdict,
    StopReason,
    VerdictDetail,
)
from app.db.models.improvement import (
    ImprovementStage as Stage,
)
from app.db.models.improvement import (
    ImprovementStatus as Status,
)
from app.db.models.user import User
from app.repositories import (
    agent_repo,
    agent_run_repo,
    authoring_repo,
    dataset_repo,
    eval_run_repo,
    improvement_repo,
    knowledge_base_repo,
    knowledge_gap_repo,
    organization_repo,
    user_repo,
)
from app.repositories import (
    background_job as background_job_repo,
)
from app.repositories.agent_run import RunFilter
from app.schemas.authoring import AuthoringStart, HunkDecision, HunkRead, ProposalCheck
from app.schemas.change_event import ChangeEvent
from app.schemas.eval_run import (
    EvalComparisonRead,
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
    ChangeEdit,
    CheckAnswers,
    ContinuationConsent,
    ContinuationEstimate,
    ImprovementAwaiting,
    ImprovementContinue,
    ImprovementDiscard,
    ImprovementEstimate,
    ImprovementEvent,
    ImprovementEvidence,
    ImprovementEvidenceItem,
    ImprovementFinish,
    ImprovementFinished,
    ImprovementIterationRead,
    ImprovementRead,
    ImprovementSelection,
    ImprovementStart,
    ImprovementTarget,
    KnowledgeAdded,
    KnowledgeCheckConsent,
    KnowledgeCheckEstimate,
    KnowledgeCheckTarget,
    SelectionConsent,
    SelectionEstimate,
    TopicDeferral,
)
from app.schemas.scoring import DatasetScoring
from app.services import authoring_fields, authoring_hunks, change_feed
from app.services import improvement_states as rules
from app.services.agent_registry import AgentRegistryService
from app.services.ai_assistance import AiAssistanceService
from app.services.api_key import job_context
from app.services.authoring import AuthoringService
from app.services.authoring_evidence import MAX_EVIDENCE_RUNS
from app.services.background_jobs import enqueue
from app.services.collection_access import readable_kb, writable_kb
from app.services.dataset import DatasetService, redact_credentials
from app.services.embedding_resolution import embeddings_for_collection
from app.services.eval_run import EvalRunService, scoring_hash, spec_hash
from app.services.eval_suite import EvalSuiteService
from app.services.improvement_data import drawn_holdout, input_hash
from app.services.knowledge_gaps import KnowledgeGapService, draft_fingerprint
from app.services.notifications import NotificationService
from app.worker.jobs import (
    ADVANCE_IMPROVEMENT,
    CLASSIFY_GAPS,
    AdvanceImprovement,
    ClassifyGaps,
)

ANSWER_TIME_WINDOW = timedelta(days=30)
"""How far back the agent's answers are read to time a session's checks."""

_AWAITING_PERSON = (Status.WAITING.value, Status.READY.value)
"""Statuses a session waits in for a person to take the next step or decide."""


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


@dataclass(frozen=True)
class SelectionPlan:
    session: ImprovementRun
    iteration: ImprovementIteration
    quote: SelectionEstimate


@dataclass(frozen=True)
class ContinuationPlan:
    session: ImprovementRun
    iteration: ImprovementIteration
    inputs: Inputs
    quote: ContinuationEstimate


class ImprovementPipelineService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)
        self.authoring = AuthoringService(db)
        self.evals = EvalRunService(db)

    async def _inputs(self, ctx: AuthContext, agent_id: UUID, target: ImprovementTarget) -> Inputs:
        agent = await self.registry.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)
        refuse_system_agent(agent, action="an improvement session")
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

    async def knowledge_sources(
        self, ctx: AuthContext, run: ImprovementRun
    ) -> tuple[list[UUID], list[UUID], list[UUID]]:
        """Writable bound bases and bad chat answers from the frozen, unerased evidence only."""
        await self.ensure_current(ctx, run.id, allow_finished=True)
        agent = await self.registry.get(ctx, run.agent_id, perm=Perm.AGENTS_EDIT)
        return await self._knowledge_sources(ctx, agent, run_id=run.id, dataset_id=run.dataset_id)

    async def _knowledge_sources(
        self,
        ctx: AuthContext,
        agent: Agent,
        *,
        run_id: UUID | None = None,
        dataset_id: UUID,
        window_days: int = 30,
    ) -> tuple[list[UUID], list[UUID], list[UUID]]:
        if ctx.scope_for(Perm.RUNS_VIEW) < Scope.ALL:
            return [], [], []
        pack = (
            await self.authoring.evidence.for_improvement(ctx, run_id)
            if run_id
            else await self.authoring.evidence.for_agent(
                ctx, agent.id, window_days=window_days, dataset_id=dataset_id
            )
        )
        pack = await self.authoring.evidence.forget_erased(pack)
        run_ids = [
            item.run_id
            for item in pack.runs
            if item.evidence_kind == "chat" and (item.rating < 0 or item.status != "completed")
        ]
        if not run_ids:
            return [], [], []
        spec = AgentSpec.model_validate(agent.draft_spec)
        bases = await knowledge_base_repo.get_by_ids(self.db, spec.collection_ids)
        ids = [
            kb.id
            for kb in bases.values()
            if kb.organization_id == ctx.organization_id and await writable_kb(self.db, ctx, kb)
        ]
        messages = await knowledge_gap_repo.answers_for_runs(
            self.db, organization_id=ctx.organization_id, run_ids=run_ids
        )
        return ids, list(messages.values()), run_ids

    async def _knowledge_branches(
        self, ctx: AuthContext, run: ImprovementRun
    ) -> tuple[int, int, list[UUID]]:
        ids, messages, source_runs = await self.knowledge_sources(ctx, run)
        causes = await KnowledgeGapService(self.db).causes(ctx, ids, messages)
        pack = await self.authoring.evidence.for_improvement(ctx, run.id)
        training = sum(item.evidence_kind == "train_eval" for item in pack.runs)
        branches = {c.message_id: c.branch for c in causes.values()}
        # An answer whose knowledge was added since has nothing left to draft.
        answers = await knowledge_gap_repo.answers_for_runs(
            self.db, organization_id=run.organization_id, run_ids=source_runs
        )
        run_of = {message_id: run_id for run_id, message_id in answers.items()}
        topics = await knowledge_gap_repo.topic_of_runs(
            self.db, ids, source_runs, organization_id=run.organization_id
        )
        added = await knowledge_gap_repo.covering_documents(
            self.db, list(set(topics.values())), organization_id=run.organization_id
        )
        agent = (
            training
            + len(source_runs)
            - len(messages)
            + sum(branch in {"agent", "unknown"} for branch in branches.values())
        )
        missing = sum(
            branch == "missing_knowledge"
            and not ((source := run_of.get(message_id)) is not None and topics.get(source) in added)
            for message_id, branch in branches.items()
        )
        excluded = [
            message_id
            for message_id, branch in branches.items()
            if branch in {"missing_knowledge", "not_a_problem"}
        ]
        return agent, missing, excluded

    async def _knowledge_exclusions(self, ctx: AuthContext, run: ImprovementRun) -> list[UUID]:
        first = await improvement_repo.get_iteration(
            self.db, organization_id=run.organization_id, run_id=run.id, number=1
        )
        job = (
            await background_job_repo.get(self.db, first.classify_job_id)
            if first and first.classify_job_id
            else None
        )
        if job is not None and job.status == "succeeded":
            _, _, excluded = await self._knowledge_branches(ctx, run)
            return excluded
        return []

    async def _knowledge_step(
        self, ctx: AuthContext, run: ImprovementRun, iteration: ImprovementIteration
    ) -> None:
        if run.stage == Stage.DRAFTING:
            # Sessions draft nothing; a row stored in this stage moves on as if its sort just ended.
            agent, missing, _ = await self._knowledge_branches(ctx, run)
            moved = rules.after_classifying(None, agent_answers=agent, missing_knowledge=missing)
            assert moved is not None, "a sort with no job is over"
            await self._move(run, moved)
            return
        ids, messages, sources = await self.knowledge_sources(ctx, run)
        job_id = iteration.classify_job_id
        if job_id is None:
            price = await KnowledgeGapService(self.db).improvement_estimate(
                ctx, ids, messages, source_run_ids=sources
            )
            spent = await improvement_repo.spent(
                self.db, run.id, organization_id=run.organization_id
            )
            if not rules.affordable(spent=spent, step_estimate=price, budget=run.budget_usd):
                await self._move(
                    run, rules.Transition(Status.STOPPED, Stage(run.stage), StopReason.BUDGET)
                )
                return
            assert ctx.user_id is not None, "job_context resolved a key issuer or active member"
            child = await enqueue(
                self.db,
                CLASSIFY_GAPS,
                ClassifyGaps(
                    organization_id=run.organization_id,
                    knowledge_base_ids=ids,
                    message_ids=messages,
                    user_id=ctx.user_id,
                    improvement_run_id=run.id,
                ),
                organization_id=run.organization_id,
                concurrency_key=f"improvement-knowledge:{run.id}",
                dedupe_key=f"{run.id}:classify",
            )
            assert child is not None, "a fresh step has no queued child"
            await improvement_repo.update_iteration(
                self.db, iteration=iteration, values={"classify_job_id": child}
            )
            await self._audit(run, "child_started")
            return
        job = await background_job_repo.get(self.db, job_id)
        if job is not None and job.organization_id != run.organization_id:
            raise NotFoundError(message="Knowledge step not found")
        agent, missing, _ = await self._knowledge_branches(ctx, run)
        status = job.status if job else None
        transition = rules.after_classifying(status, agent_answers=agent, missing_knowledge=missing)
        if transition is None and rules.stalled(
            Stage(run.stage),
            waiting=status == "queued",
            last_progress=max(
                value
                for value in (job.started_at if job else None, run.stage_started_at, run.created_at)
                if value is not None
            ),
            now=datetime.now(UTC),
        ):
            await self._stop_children(run)
            await self._move(run, rules.stall(Stage(run.stage)))
            return
        if transition is not None:
            if status != "succeeded":
                await self._audit(run, "classification_failed")
                # The conversations remain available to the improver; a failed
                # classifier is never presented as a successful grouping.
                transition = rules.Transition(Status.WAITING, Stage.CLASSIFYING)
            await self._move(run, transition)

    async def _estimate(
        self,
        ctx: AuthContext,
        inputs: Inputs,
        target: ImprovementTarget,
    ) -> ImprovementEstimate:
        """What a session spends before it first waits for a person, with what one attempt
        costs beside it: every step after that stop is priced when somebody takes it."""
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
        ids, messages, sources = await self._knowledge_sources(
            ctx,
            inputs.agent,
            dataset_id=inputs.request.dataset_id,
            window_days=target.window_days,
        )
        total = await KnowledgeGapService(self.db).improvement_estimate(
            ctx, ids, messages, source_run_ids=sources
        )
        org_left = await self.evals._org_left(ctx)
        now = datetime.now(UTC)
        answer_ms, _ = await agent_run_repo.latency_percentiles_ms(
            self.db,
            organization_id=ctx.organization_id,
            start=now - ANSWER_TIME_WINDOW,
            end=now,
            where=RunFilter(agent_id=inputs.agent.id),
        )
        return ImprovementEstimate(
            proposal_usd=proposal.estimate_usd,
            knowledge_usd=total,
            eval_usd=full_eval,
            per_round_usd=per_round,
            total_usd=total,
            max_iterations=target.max_iterations,
            cases=check.cases,
            evidence_runs=proposal.runs,
            estimated_minutes=rules.estimated_minutes(
                rounds=target.max_iterations,
                answers=check.cases * len(check.arms),
                answer_seconds=None if answer_ms is None else answer_ms / 1000,
                concurrency=settings.EVAL_RUN_CONCURRENCY,
            ),
            affordable=proposal.affordable
            and check.affordable
            and (org_left is None or total <= org_left),
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
        existing = await improvement_repo.get_open(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id
        )
        if existing is not None:
            raise self._already_open(existing)
        if not estimate.affordable or estimate.total_usd > data.budget_usd:
            raise PaymentRequiredError(
                message="The full improvement estimate exceeds the available budget",
                details={
                    "estimate_usd": str(estimate.total_usd),
                    "budget_usd": str(data.budget_usd),
                },
            )
        async with self._sole_open(organization_id=ctx.organization_id, agent_id=agent_id):
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
        await improvement_repo.create_iteration(
            self.db, organization_id=ctx.organization_id, run_id=run.id, number=1
        )
        await self._audit(run, "started")
        await self._queue(run)
        return await self._read(ctx, run)

    @asynccontextmanager
    async def _sole_open(self, *, organization_id: UUID, agent_id: UUID) -> AsyncGenerator[None]:
        """Open a session, refusing as a conflict when another took the agent first.

        One open session per agent is a unique index; two requests that both
        found none still race to it, and the loser is told who won rather than
        answered with a database error.
        """
        try:
            async with self.db.begin_nested():
                yield
        except IntegrityError as exc:
            if "uq_improvement_runs_open" not in {
                getattr(exc.orig, "constraint_name", None),
                getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None),
            }:
                raise
            winner = await improvement_repo.get_open(
                self.db, organization_id=organization_id, agent_id=agent_id
            )
            if winner is None:
                raise
            raise self._already_open(winner) from exc

    @staticmethod
    def _already_open(run: ImprovementRun) -> ConcurrentChangeError:
        return ConcurrentChangeError(
            message="An improvement session is already open for this agent",
            details={"improvement_run_id": str(run.id)},
        )

    async def _row(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        run_id: UUID,
        *,
        lock: bool = False,
        settled: Status | None = None,
    ) -> ImprovementRun:
        """The session; locked, it is about to change, which a closed session refuses.

        `settled` is the status repeating this same action finds, answered as before.
        """
        row = await improvement_repo.get_run(
            self.db, run_id, organization_id=ctx.organization_id, lock=lock
        )
        if row is None or row.agent_id != agent_id:
            raise NotFoundError(message="Improvement session not found")
        if lock and Status(row.status).closed and row.status != settled:
            raise ConcurrentChangeError(
                message="This improvement is finished", details={"status": row.status}
            )
        return row

    async def evidence(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        *,
        run_id: UUID | None = None,
        dataset_id: UUID | None = None,
    ) -> ImprovementEvidence:
        """The bounded, current-readable source examples, never paid classification.

        Sessions use their frozen chat identities and dataset version. Deleted
        or erased sources disappear; a knowledge-base verdict is shown only
        while that base remains readable. Unknown means no usable recorded
        classification, rather than an inferred knowledge gap.
        """
        agent = await self.registry.get(ctx, agent_id)
        if not ctx.has(Perm.RUNS_VIEW):
            raise AuthorizationError(message="Reading improvement evidence needs runs:view")
        if run_id is not None:
            await self._row(ctx, agent_id, run_id)
            pack = await self.authoring.evidence.for_improvement(ctx, run_id)
        else:
            if dataset_id is not None:
                await DatasetService(self.db).get(ctx, dataset_id, perm=Perm.DATASETS_RUN)
            pack = await self.authoring.evidence.for_agent(
                ctx, agent_id, window_days=30, dataset_id=dataset_id
            )
        pack = await self.authoring.evidence.forget_erased(pack)
        bases = await knowledge_base_repo.get_by_ids(
            self.db, AgentSpec.model_validate(agent.draft_spec).collection_ids
        )
        readable = [
            kb.id
            for kb in bases.values()
            if kb.organization_id == ctx.organization_id and await readable_kb(self.db, ctx, kb)
        ]
        messages = await knowledge_gap_repo.answers_for_runs(
            self.db,
            organization_id=ctx.organization_id,
            run_ids=[item.run_id for item in pack.runs if item.evidence_kind == "chat"],
        )
        causes = await KnowledgeGapService(self.db).causes(ctx, readable, list(messages.values()))
        topics = await knowledge_gap_repo.topic_of_runs(
            self.db, readable, list(messages), organization_id=ctx.organization_id
        )
        covering = await knowledge_gap_repo.covering_documents(
            self.db, list(set(topics.values())), organization_id=ctx.organization_id
        )
        items: list[ImprovementEvidenceItem] = []
        for item in pack.runs:
            cause = causes.get(messages[item.run_id]) if item.run_id in messages else None
            added = covering.get(topic) if (topic := topics.get(item.run_id)) else None
            items.append(
                ImprovementEvidenceItem(
                    run_id=item.run_id,
                    conversation_id=item.conversation_id,
                    kind=item.evidence_kind,
                    status=item.status,
                    rating=item.rating,
                    question=redact_credentials(item.prompt)[0],
                    answer=redact_credentials(item.answer)[0],
                    comments=[
                        text
                        for comment in item.comments
                        if (text := redact_credentials(comment)[0]) is not None
                    ],
                    branch=(
                        "agent"
                        if item.evidence_kind == "train_eval"
                        else "not_a_problem"
                        if item.rating > 0
                        else cause.branch
                        if cause
                        else "unknown"
                    ),
                    reason=redact_credentials(cause.reason)[0] if cause else None,
                    topic_id=topics.get(item.run_id),
                    knowledge_added=KnowledgeAdded(
                        document_id=added.document.id,
                        filename=added.document.filename,
                        knowledge_base_id=added.document.knowledge_base_id,
                        added_at=added.covered_at,
                    )
                    if added is not None
                    and cause is not None
                    and cause.branch == "missing_knowledge"
                    and added.document.knowledge_base_id is not None
                    else None,
                )
            )
        return ImprovementEvidence(
            items=items,
            sample_limit=MAX_EVIDENCE_RUNS,
            training_failures=sum(item.status == "train_eval_failure" for item in pack.runs),
        )

    async def defer_topic(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, topic_id: UUID, data: TopicDeferral
    ) -> ImprovementRead:
        """Set a knowledge document aside for this session with Not now, or bring it back.

        The topic and its draft are untouched; the session only stops offering it.
        """
        await self.authoring._editable(ctx, agent_id)
        self.authoring._require_runs_view(ctx)
        run = await self._row(ctx, agent_id, run_id, lock=True)
        if (
            await knowledge_gap_repo.get_topic(
                self.db, topic_id, organization_id=ctx.organization_id
            )
            is None
        ):
            raise NotFoundError(
                message="Knowledge gap topic not found", details={"topic_id": topic_id}
            )
        kept = [item for item in run.deferred_topic_ids if item != topic_id]
        await improvement_repo.update_run(
            self.db,
            run=run,
            values={"deferred_topic_ids": [*kept, topic_id] if data.later else kept},
        )
        return await self._read(ctx, run)

    async def read(self, ctx: AuthContext, agent_id: UUID, run_id: UUID) -> ImprovementRead:
        await self.registry.get(ctx, agent_id)
        return await self._read(ctx, await self._row(ctx, agent_id, run_id))

    async def awaiting(self, ctx: AuthContext) -> list[ImprovementAwaiting]:
        """Sessions waiting for a person, on the agents this caller may read.

        A session stopped at a step, or with a result ready, waits for whoever may
        take it on; one on an agent the caller cannot see is left out.
        """
        if not ctx.has(Perm.RUNS_VIEW):
            raise AuthorizationError(message="Reading improvement sessions needs runs:view")
        rows = await improvement_repo.list_for_person(
            self.db, organization_id=ctx.organization_id, statuses=_AWAITING_PERSON
        )
        names: dict[UUID, str | None] = {}
        for agent_id in dict.fromkeys(row.agent_id for row in rows):
            try:
                names[agent_id] = (await self.registry.get(ctx, agent_id)).name
            except NotFoundError, AuthorizationError:
                names[agent_id] = None
        return [
            ImprovementAwaiting(
                id=row.id,
                agent_id=row.agent_id,
                agent_name=name,
                status=row.status,
                stage=row.stage,
                iteration=row.iteration,
                max_iterations=row.max_iterations,
                created_at=row.created_at,
            )
            for row in rows
            if (name := names[row.agent_id]) is not None
        ]

    async def read_session(self, ctx: AuthContext, run_id: UUID) -> ImprovementRead:
        """A session by its id alone, read with the same access to its agent as `read`.

        For a caller that kept the session and not its agent - the Architect, a
        few turns into a conversation.
        """
        run = await improvement_repo.get_run(self.db, run_id, organization_id=ctx.organization_id)
        if run is None:
            raise NotFoundError(
                message="Improvement session not found", details={"improvement_run_id": run_id}
            )
        return await self.read(ctx, run.agent_id, run_id)

    async def changes(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, *, attempt: int | None = None
    ) -> list[HunkRead]:
        """The changes the session's chosen round measured, wherever their batch is now; with
        `attempt`, every change that attempt proposed, tested or not."""
        agent = await self.registry.get(ctx, agent_id)
        self.authoring._require_runs_view(ctx)
        run = await self._row(ctx, agent_id, run_id)
        rounds = await improvement_repo.list_iterations(
            self.db, organization_id=ctx.organization_id, run_id=run.id
        )
        if attempt is not None:
            proposed = next((item for item in rounds if item.number == attempt), None)
            if proposed is None or proposed.batch_id is None:
                return []
            return await self.authoring.changes_of(ctx, agent, proposed.batch_id, None)
        if run.status == Status.WAITING and run.stage == Stage.FILTERING:
            # Waiting at Changes, the attempt's own changes are the ones to choose and edit.
            chosen = next((item for item in rounds if item.number == run.iteration), None)
        else:
            chosen = next((item for item in rounds if item.id == run.best_iteration_id), None)
        if chosen is None or chosen.batch_id is None:
            return []
        return await self.authoring.changes_of(
            ctx, agent, chosen.batch_id, chosen.included_hunk_ids
        )

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
        if run.status == Status.READY and ctx.has(Perm.RUNS_VIEW):
            latest = await agent_repo.newest_version(
                self.db, agent_id=run.agent_id, organization_id=run.organization_id
            )
            result.next_version = 1 if latest is None else latest.version + 1
            suites = await EvalSuiteService(self.db).list_for_agent(ctx, run.agent_id)
            result.offer_automatic_check = not suites.items
        result.can_restart = await self._may_continue(ctx, run)
        if run.status == Status.WAITING:
            result.next_step = "check" if run.stage == Stage.FILTERING else "propose"
        measured = [self._round_result(item) for item in iterations if item.verdict is not None]
        hint = rules.no_progress(measured)
        if hint is not None:
            result.round_hint = "no_change" if hint == StopReason.NO_CHANGE else "inconclusive"
        result.can_discard = ctx.user_id == run.created_by_user_id or ctx.has(Perm.ORG_SETTINGS)
        result.spent_usd = await improvement_repo.spent(
            self.db, run.id, organization_id=run.organization_id
        )
        result.iterations = [ImprovementIterationRead.model_validate(item) for item in iterations]
        first = next((item for item in iterations if item.number == 1), None)
        current = next(
            (item for item in iterations if item.number == run.iteration),
            iterations[-1] if iterations else None,
        )
        result.baseline_answers = await self._answers(run, first, ArmRole.BASELINE)
        result.candidate_answers = await self._answers(run, current, ArmRole.CANDIDATE)
        if ctx.has(Perm.RUNS_VIEW):
            result.knowledge_eval_run_ids = await improvement_repo.knowledge_checks(
                self.db, run.id, organization_id=ctx.organization_id
            )
            if not Status(run.status).active:
                result.measurement_noise = rules.measurement_noise(
                    await self._checked(ctx, run, iterations)
                )
        actors = {
            event.id: UUID(actor)
            for event in events
            if (actor := self._event_detail(event.details, "actor")) is not None
        }
        people = (
            await user_repo.get_many(self.db, list(actors.values()))
            if ctx.has(Perm.MEMBERS_VIEW)
            else {}
        )
        result.timeline = [
            ImprovementEvent(
                action=event.action,
                at=event.created_at,
                stage=self._event_detail(event.details, "stage"),
                status=self._event_detail(event.details, "status"),
                reason=self._event_detail(event.details, "reason"),
                actor_user_id=actors.get(event.id),
                actor_name=self._name(people, actors.get(event.id)),
            )
            for event in events
        ]
        if not ctx.has(Perm.RUNS_VIEW):
            result.error = None
        return result

    async def _answers(
        self, run: ImprovementRun, round_: ImprovementIteration | None, role: ArmRole
    ) -> CheckAnswers | None:
        """How far one side of a round's latest check has answered."""
        if round_ is None or not round_.eval_run_ids:
            return None
        counted = await eval_run_repo.arm_answers(
            self.db, round_.eval_run_ids[-1], role=role, organization_id=run.organization_id
        )
        return None if counted is None else CheckAnswers(**counted._asdict())

    async def _checked(
        self, ctx: AuthContext, run: ImprovementRun, iterations: list[ImprovementIteration]
    ) -> list[rules.CheckedAttempt]:
        """Each measured attempt's latest check, as the held-out grades it stored.

        A check the caller can no longer read - its agent or dataset hidden from
        them since - is left out rather than failing the whole session read.
        """
        attempts = []
        for iteration in iterations:
            if (
                iteration.verdict is None
                or not iteration.eval_run_ids
                or iteration.number > run.max_iterations
            ):
                continue
            try:
                comparison = await self.evals.compare(ctx, iteration.eval_run_ids[-1])
            except NotFoundError:
                continue
            attempts.append(
                rules.CheckedAttempt(
                    number=iteration.number,
                    cases=tuple(
                        rules.CheckedCase(
                            case_id=case.case_id,
                            input=case.input,
                            baseline=(case.baseline, *case.baseline_reruns),
                            candidate=(case.candidate, *case.candidate_reruns),
                        )
                        for case in comparison.cases
                    ),
                )
            )
        return attempts

    @staticmethod
    def _name(people: dict[UUID, User], user_id: UUID | None) -> str | None:
        person = None if user_id is None else people.get(user_id)
        return None if person is None else person.full_name or person.email

    @staticmethod
    def _event_detail(details: object, key: str) -> str | None:
        if not isinstance(details, dict):
            return None
        value = details.get(key)
        return value if isinstance(value, str) else None

    async def cancel(self, ctx: AuthContext, agent_id: UUID, run_id: UUID) -> ImprovementRead:
        run = await self._row(ctx, agent_id, run_id, lock=True, settled=Status.CANCELLED)
        if ctx.subject_id != run.created_by_user_id and not ctx.has(Perm.ORG_SETTINGS):
            raise AuthorizationError(
                message="Only the creator or an organization administrator can stop this session"
            )
        if Status(run.status).open:
            # Cancellation must still work after the creator loses resource access.
            await self._stop_children(run)
            await self._move(
                run,
                rules.Transition(Status.CANCELLED, Stage(run.stage) if run.stage else None),
                actor_user_id=ctx.subject_id,
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
        if await agent_repo.lock(self.db, agent_id, organization_id=ctx.organization_id) is None:
            raise NotFoundError(message="Agent not found")
        run = await self._row(ctx, agent_id, run_id, lock=True)
        if run.status != Status.READY:
            raise BadRequestError(message="Select a checked round before accepting it")
        await self.ensure_current(ctx, run.id, allow_finished=True)
        if await improvement_repo.has_active_check(
            self.db, run.id, organization_id=ctx.organization_id
        ):
            raise ConcurrentChangeError(
                message="Wait for this session's checks to finish, or stop the session"
            )
        selected, hunks = await self._measured_selection(run)
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
        return await self._conclude(ctx, agent_id, run, data)

    async def _measured_selection(
        self, run: ImprovementRun
    ) -> tuple[ImprovementIteration, list[SpecProposalHunk]]:
        """The selected round and its measured suggestions, while its batch is the open one."""
        rounds = await improvement_repo.list_iterations(
            self.db, organization_id=run.organization_id, run_id=run.id
        )
        selected = next((item for item in rounds if item.id == run.best_iteration_id), None)
        if selected is None or selected.batch_id is None:
            raise BadRequestError(message="No checked round is selected")
        batch = await authoring_repo.get_open_batch(
            self.db, organization_id=run.organization_id, agent_id=run.agent_id
        )
        if batch is None or batch.id != selected.batch_id:
            raise ConcurrentChangeError(message="The selected suggestions were replaced")
        hunks = await authoring_repo.list_hunks(
            self.db, organization_id=run.organization_id, batch_id=batch.id
        )
        return selected, [
            h
            for h in hunks
            if selected.included_hunk_ids is None or h.id in selected.included_hunk_ids
        ]

    async def _conclude(
        self, ctx: AuthContext, agent_id: UUID, run: ImprovementRun, data: ImprovementFinish
    ) -> ImprovementFinished:
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
        self._allow(run, Status.PUBLISHED if version else Status.ACCEPTED)
        await improvement_repo.update_run(
            self.db,
            run=run,
            values={
                "status": Status.PUBLISHED.value if version else Status.ACCEPTED.value,
                "published_version_id": None if version is None else version.id,
                "published_version": None if version is None else version.version,
            },
        )
        await self._audit(run, "published" if version else "accepted", actor_user_id=ctx.subject_id)
        self._announce(run)
        return ImprovementFinished(
            session=await self._read(ctx, run),
            version_id=None if version is None else version.id,
            version=None if version is None else version.version,
        )

    @staticmethod
    def _allow(run: ImprovementRun, to: Status) -> None:
        """Refuse a move the session's state table does not hold; every status write passes here."""
        if not rules.can_move(Status(run.status), to):
            raise ConcurrentChangeError(
                message=f"This session is {run.status} and cannot become {to.value}",
                details={"status": run.status, "to": to.value},
            )

    @staticmethod
    def _acting_as(run: ImprovementRun) -> tuple[UUID | None, UUID | None]:
        """Who the session's own steps run as: whoever took its latest step, else its creator,
        with the credential they acted with."""
        if run.actor_user_id is not None:
            return run.actor_user_id, run.actor_api_key_id
        return run.created_by_user_id, run.created_by_api_key_id

    async def _require_may_continue(self, ctx: AuthContext, agent_id: UUID) -> None:
        """Refuse unless the caller may start a session on this agent, which is all that taking
        a session's next step, trying again, resuming or retrying asks of them."""
        await self.authoring._editable(ctx, agent_id)
        self.authoring._require_runs_view(ctx)
        await AiAssistanceService(self.db).require_enabled(organization_id=ctx.organization_id)

    async def _may_continue(self, ctx: AuthContext, run: ImprovementRun) -> bool:
        agent = await agent_repo.get(self.db, run.agent_id, organization_id=run.organization_id)
        return (
            agent is not None
            and agent.status != AgentStatus.ARCHIVED.value
            and ctx.has(Perm.RUNS_VIEW)
            and await self.registry.may_edit(ctx, agent)
            and await AiAssistanceService(self.db).is_enabled(organization_id=ctx.organization_id)
        )

    @staticmethod
    def _require_requester(ctx: AuthContext, run: ImprovementRun) -> None:
        if ctx.user_id != run.created_by_user_id or ctx.api_key_id != run.created_by_api_key_id:
            raise AuthorizationError(
                message="Use the session requester's original account and credentials for paid restarts, or start a new session"
            )

    async def retry(self, ctx: AuthContext, agent_id: UUID, run_id: UUID) -> ImprovementRead:
        """Retry a failed paid step only after a person's explicit request.

        The parent lock makes a repeated click idempotent. The old child remains
        in Activity; its cost counts toward the same budget and the new child
        is created in this transaction. No job retries a paid call implicitly.
        """
        await self._require_may_continue(ctx, agent_id)
        if await agent_repo.lock(self.db, agent_id, organization_id=ctx.organization_id) is None:
            raise NotFoundError(message="Agent not found")
        run = await self._row(ctx, agent_id, run_id, lock=True)
        if Status(run.status).active:
            return await self._read(ctx, run)
        if run.status != Status.FAILED or run.stage not in {Stage.PROPOSING, Stage.EVALUATING}:
            raise BadRequestError(message="Only a failed proposal or test step can be retried")
        iteration = await improvement_repo.get_iteration(
            self.db, organization_id=ctx.organization_id, run_id=run.id, number=run.iteration
        )
        assert iteration is not None
        # A refusal rolls this transaction back, including this temporary status.
        self._allow(run, Status.RUNNING)
        await improvement_repo.update_run(
            self.db,
            run=run,
            values={
                "status": Status.RUNNING.value,
                "error": None,
                "stop_reason": None,
                "finished_at": None,
                "actor_user_id": ctx.subject_id,
                "actor_api_key_id": ctx.api_key_id,
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

    async def _assert_idle(self, run: ImprovementRun, rounds: list[ImprovementIteration]) -> None:
        if await improvement_repo.has_active_check(
            self.db, run.id, organization_id=run.organization_id
        ):
            raise ConcurrentChangeError(message="Wait for the current checks to finish")
        for iteration in rounds:
            if iteration.authoring_request_id:
                request = await authoring_repo.get_request(
                    self.db, iteration.authoring_request_id, organization_id=run.organization_id
                )
                if request is not None and request.status in {"queued", "running"}:
                    raise ConcurrentChangeError(message="Wait for the current proposal to finish")
            for job_id in (iteration.classify_job_id, iteration.draft_job_id):
                job = await background_job_repo.get(self.db, job_id) if job_id else None
                if job and job.organization_id != run.organization_id:
                    raise NotFoundError(message="Knowledge step not found")
                if job and job.status in {"queued", "running"}:
                    raise ConcurrentChangeError(
                        message="Wait for the current knowledge step to finish"
                    )

    async def _continuation_plan(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, data: ImprovementContinue
    ) -> ContinuationPlan:
        await self._require_may_continue(ctx, agent_id)
        run = await self._row(ctx, agent_id, run_id, lock=True)
        if run.status not in {Status.WAITING, Status.READY, Status.STOPPED, Status.FAILED}:
            raise BadRequestError(message="This session cannot be continued")
        inputs = await self._current_inputs(ctx, run)
        rounds = await improvement_repo.list_iterations(
            self.db, organization_id=ctx.organization_id, run_id=run.id
        )
        current = next((item for item in rounds if item.number == run.iteration), None)
        if current is None:
            raise NotFoundError(message="The current improvement round is no longer available")
        await self._assert_idle(run, rounds)
        mode: Literal["next_step", "next_round", "resume", "retry"]
        number = current.number
        if run.status == Status.WAITING:
            mode = "next_step"
        elif run.status == Status.STOPPED and (
            run.stop_reason == StopReason.PERMISSION
            or (
                run.stop_reason == StopReason.BUDGET
                and run.stage
                in {Stage.CLASSIFYING, Stage.DRAFTING, Stage.PROPOSING, Stage.EVALUATING}
            )
        ):
            mode = "resume"
        elif run.status == Status.FAILED and run.stage in {Stage.PROPOSING, Stage.EVALUATING}:
            mode = "retry"
        elif current.verdict is not None and run.status in {Status.READY, Status.STOPPED}:
            deferred = next(
                (
                    item
                    for item in rounds
                    if item.number > current.number
                    and item.batch_id is not None
                    and item.authoring_request_id is None
                    and not item.eval_run_ids
                ),
                None,
            )
            number = deferred.number if deferred else max(item.number for item in rounds) + 1
            if number > run.max_iterations:
                raise BadRequestError(message="The session reached its attempt limit")
            mode = "next_round"
        else:
            raise BadRequestError(
                message="This step needs a new session or a review decision before it can continue"
            )
        stage = self._continued_stage(run, mode)
        if (
            mode == "next_step"
            and stage == Stage.EVALUATING
            and any(
                item.number != current.number
                and item.eval_run_ids
                and item.candidate_spec_hash == current.candidate_spec_hash
                for item in rounds
            )
        ):
            raise BadRequestError(
                message="An earlier attempt already checked exactly these changes; choose others"
            )
        total, step_affordable = await self._step_price(ctx, inputs, run, current, stage)
        spent = await improvement_repo.spent(self.db, run.id, organization_id=ctx.organization_id)
        org_left = await self.evals._org_left(ctx)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "run": str(run.id),
                    "base": run.base_draft_hash,
                    "dataset_version": run.dataset_version,
                    "number": number,
                    "mode": mode,
                    "stage": run.stage,
                    "budget": str(data.budget_usd.quantize(Decimal("0.000001"))),
                    "rounds": [
                        (
                            item.number,
                            item.candidate_spec_hash,
                            item.verdict,
                            item.verdict_detail,
                            [str(check_id) for check_id in item.eval_run_ids],
                        )
                        for item in rounds
                    ],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return ContinuationPlan(
            run,
            current,
            inputs,
            ContinuationEstimate(
                mode=mode,
                number=number,
                total_usd=total,
                budget_usd=data.budget_usd,
                candidate_hash=fingerprint,
                affordable=step_affordable
                and spent + total <= data.budget_usd
                and (org_left is None or total <= org_left),
            ),
        )

    @staticmethod
    def _continued_stage(run: ImprovementRun, mode: str) -> Stage | None:
        """The step a continuation starts: what follows a stop, a new attempt's proposal,
        or the step that stopped or failed again."""
        if mode == "next_round":
            return Stage.PROPOSING
        if mode == "next_step":
            return Stage.EVALUATING if run.stage == Stage.FILTERING else Stage.PROPOSING
        return None if run.stage is None else Stage(run.stage)

    async def _step_price(
        self,
        ctx: AuthContext,
        inputs: Inputs,
        run: ImprovementRun,
        iteration: ImprovementIteration,
        stage: Stage | None,
    ) -> tuple[Decimal, bool]:
        """What the paid step a continuation starts costs, and whether its own budgets allow it.

        Only that step: every later paid step waits for a person again. A check includes
        the one repeat an inconclusive result gets, as the check itself would start it.
        """
        if stage == Stage.PROPOSING:
            proposal = await self.authoring.estimate_agent(
                ctx,
                run.agent_id,
                AuthoringStart(
                    window_days=run.window_days, improver_agent_id=run.improver_agent_id
                ),
                improvement_run_id=run.id,
                excluded_message_ids=await self._knowledge_exclusions(ctx, run),
            )
            return proposal.estimate_usd, proposal.affordable and proposal.reason is None
        if stage == Stage.EVALUATING:
            if iteration.batch_id is None:
                raise NotFoundError(message="The candidate is no longer available")
            projected, _ = await self._candidate(inputs.agent, run, iteration)
            batch = await authoring_repo.get_batch(
                self.db, iteration.batch_id, organization_id=run.organization_id
            )
            if batch is None:
                raise NotFoundError(message="The candidate is no longer available")
            skills = await self.authoring.projected_skills(
                ctx, batch.id, hunk_ids=iteration.included_hunk_ids
            )
            if spec_hash(projected, skills) != iteration.candidate_spec_hash:
                raise ConcurrentChangeError(
                    message="The pending suggestions changed; restore them or start a new session before continuing"
                )
            check = await self.evals.estimate(
                ctx,
                run.agent_id,
                self._eval_request(inputs, run),
                candidate_spec=projected,
                candidate_skills=skills,
                baseline_spec=AgentSpec.model_validate(inputs.agent.draft_spec),
                scoring=DatasetScoring.model_validate(run.pinned_scoring),
                exclude_conversations=batch.evidence_conversation_ids,
                judge_version_id=run.judge_version_id,
                judge_pinned=True,
                proposal_check=await self._check_record(
                    ctx, run, iteration, batch, max(1, len(iteration.included_hunk_ids or []))
                ),
            )
            measured = check.proposal_check.measurement if check.proposal_check else None
            assert measured is not None, "an attempt's check is always measured"
            if measured.gradable_holdout < measured.minimum_holdout:
                missing = measured.minimum_holdout - measured.gradable_holdout
                raise BadRequestError(
                    message=f"Add {missing} more test questions to measure this attempt",
                    details={"missing_holdout": missing},
                )
            completed = await improvement_repo.completed_checks(
                self.db, iteration.eval_run_ids, organization_id=ctx.organization_id
            )
            repeats = max(0, rules.INCONCLUSIVE_RERUNS - completed)
            return (check.total_usd + check.rerun_ceiling_usd) * (1 + repeats), check.affordable
        if stage == Stage.CLASSIFYING:
            ids, messages, sources = await self._knowledge_sources(
                ctx, inputs.agent, run_id=run.id, dataset_id=run.dataset_id
            )
            price = await KnowledgeGapService(self.db).improvement_estimate(
                ctx, ids, messages, source_run_ids=sources
            )
            return price, True
        return Decimal(0), True

    async def estimate_continuation(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, data: ImprovementContinue
    ) -> ContinuationEstimate:
        """Quote a complete next round or a resumed step without changing the session."""
        return (await self._continuation_plan(ctx, agent_id, run_id, data)).quote

    async def continue_run(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, data: ContinuationConsent
    ) -> ImprovementRead:
        """Continue only on fresh consent, preserving source pins, history and hard limits.

        Whoever continues takes the session over: its following steps run as them.
        """
        await self._require_may_continue(ctx, agent_id)
        if await agent_repo.lock(self.db, agent_id, organization_id=ctx.organization_id) is None:
            raise NotFoundError(message="Agent not found")
        existing = await self._row(ctx, agent_id, run_id, lock=True)
        if Status(existing.status).active:
            return await self._read(ctx, existing)
        plan = await self._continuation_plan(ctx, agent_id, run_id, data)
        run, iteration, quote = plan.session, plan.iteration, plan.quote
        if data.candidate_hash != quote.candidate_hash or data.estimate_usd != quote.total_usd:
            raise ConcurrentChangeError(
                message="The continuation estimate or inputs changed; review them again"
            )
        if not quote.affordable:
            raise PaymentRequiredError(
                message="The full continuation estimate exceeds the spending limit or available budget"
            )
        if data.note is not None and quote.mode != "next_round":
            raise refused_field("note", "A note goes only with Try again")
        stage = self._continued_stage(run, quote.mode)
        if quote.mode == "next_round":
            following = await improvement_repo.get_iteration(
                self.db, organization_id=ctx.organization_id, run_id=run.id, number=quote.number
            )
            if following is None:
                following = await improvement_repo.create_iteration(
                    self.db, organization_id=ctx.organization_id, run_id=run.id, number=quote.number
                )
                await self._draw_split(run, following)
            await improvement_repo.update_iteration(
                self.db, iteration=following, values={"note": data.note}
            )
        elif stage == Stage.PROPOSING:
            await improvement_repo.update_iteration(
                self.db, iteration=iteration, values={"authoring_request_id": None}
            )
        elif stage in {Stage.CLASSIFYING, Stage.DRAFTING}:
            await improvement_repo.update_iteration(
                self.db,
                iteration=iteration,
                values={"classify_job_id" if stage == Stage.CLASSIFYING else "draft_job_id": None},
            )
        await improvement_repo.update_run(
            self.db,
            run=run,
            values={
                "iteration": quote.number,
                "budget_usd": data.budget_usd,
                "error": None,
                "actor_user_id": ctx.subject_id,
                "actor_api_key_id": ctx.api_key_id,
            },
        )
        await self._audit(
            run,
            "next_step_taken" if quote.mode == "next_step" else "continuation_confirmed",
            actor_user_id=ctx.subject_id,
            step_estimate_usd=quote.total_usd,
            quote_hash=quote.candidate_hash,
        )
        await self._move(run, rules.Transition(Status.RUNNING, stage))
        if stage == Stage.EVALUATING:
            await self._evaluate(ctx, plan.inputs, run, iteration, force_new=True)
        return await self._read(ctx, run)

    async def choose_changes(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, data: ImprovementSelection
    ) -> ImprovementRead:
        """Choose which of the attempt's changes its check measures, while the session waits
        at Changes. Free: the check is priced and started by the next step."""
        await self._require_may_continue(ctx, agent_id)
        run = await self._row(ctx, agent_id, run_id, lock=True)
        if run.status != Status.WAITING or run.stage != Stage.FILTERING:
            raise BadRequestError(
                message="Changes are chosen only while the session waits for its check"
            )
        inputs = await self._current_inputs(ctx, run)
        iteration = await improvement_repo.get_iteration(
            self.db, organization_id=ctx.organization_id, run_id=run.id, number=run.iteration
        )
        assert iteration is not None and iteration.batch_id is not None
        hunks = await authoring_repo.list_hunks(
            self.db, organization_id=ctx.organization_id, batch_id=iteration.batch_id
        )
        pending = {h.id for h in hunks if h.status == HunkStatus.PENDING.value}
        if not set(data.hunk_ids) <= pending:
            raise refused_field("hunk_ids", "Choose among this attempt's pending changes")
        projected, _ = await self._candidate(inputs.agent, run, iteration, hunk_ids=data.hunk_ids)
        skills = await self.authoring.projected_skills(
            ctx, iteration.batch_id, hunk_ids=data.hunk_ids
        )
        await improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={
                "included_hunk_ids": data.hunk_ids,
                "candidate_spec_hash": spec_hash(projected, skills),
            },
        )
        await self._audit(run, "changes_chosen", actor_user_id=ctx.subject_id)
        self._announce(run)
        return await self._read(ctx, run)

    async def edit_change(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, hunk_id: UUID, data: ChangeEdit
    ) -> HunkRead:
        """Reword one of the attempt's proposed instructions while the session waits at
        Changes. The check measures the edit, and Accept writes it."""
        await self._require_may_continue(ctx, agent_id)
        run = await self._row(ctx, agent_id, run_id, lock=True)
        if run.status != Status.WAITING or run.stage != Stage.FILTERING:
            raise BadRequestError(
                message="Changes are edited only while the session waits for its check"
            )
        inputs = await self._current_inputs(ctx, run)
        iteration = await improvement_repo.get_iteration(
            self.db, organization_id=ctx.organization_id, run_id=run.id, number=run.iteration
        )
        assert iteration is not None and iteration.batch_id is not None
        hunk = await authoring_repo.get_hunk(self.db, hunk_id, organization_id=ctx.organization_id)
        if (
            hunk is None
            or hunk.batch_id != iteration.batch_id
            or hunk.status != HunkStatus.PENDING.value
        ):
            raise NotFoundError(message="Change not found", details={"hunk_id": hunk_id})
        if hunk.kind != HunkKind.INSTRUCTIONS.value:
            raise refused_field("edited_text", "Only a change to the instructions has text to edit")
        hunk.edited_text = None if data.edited_text == hunk.new_text else data.edited_text
        await self.db.flush()
        projected, _ = await self._candidate(inputs.agent, run, iteration)
        skills = await self.authoring.projected_skills(
            ctx, iteration.batch_id, hunk_ids=iteration.included_hunk_ids
        )
        await improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={"candidate_spec_hash": spec_hash(projected, skills)},
        )
        await self._audit(run, "change_edited", actor_user_id=ctx.subject_id)
        self._announce(run)
        [read] = await self.authoring.changes_of(ctx, inputs.agent, iteration.batch_id, [hunk.id])
        return read

    async def discard(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, data: ImprovementDiscard
    ) -> ImprovementRead:
        """Dismiss only this session's pending suggestions; never undo an applied change."""
        await self.authoring._editable(ctx, agent_id)
        self.authoring._require_runs_view(ctx)
        if await agent_repo.lock(self.db, agent_id, organization_id=ctx.organization_id) is None:
            raise NotFoundError(message="Agent not found")
        run = await self._row(ctx, agent_id, run_id, lock=True, settled=Status.REJECTED)
        if ctx.user_id != run.created_by_user_id and not ctx.has(Perm.ORG_SETTINGS):
            raise AuthorizationError(
                message="Only the creator or an organization administrator can discard this session"
            )
        if run.status == Status.REJECTED:
            return await self._read(ctx, run)
        if Status(run.status).active:
            raise BadRequestError(message="Stop running work first")
        rounds = await improvement_repo.list_iterations(
            self.db, organization_id=ctx.organization_id, run_id=run.id
        )
        await self._assert_idle(run, rounds)
        if await authoring_repo.improvement_has_applied_changes(
            self.db, organization_id=ctx.organization_id, run_id=run.id
        ):
            raise BadRequestError(
                message="Some suggestions were already applied; use the agent's undo or version history"
            )
        await authoring_repo.dismiss_improvement_batches(
            self.db, organization_id=ctx.organization_id, run_id=run.id
        )
        await self._audit(run, "discarded", actor_user_id=ctx.subject_id)
        await self._move(
            run,
            rules.Transition(Status.REJECTED, Stage(run.stage) if run.stage else None),
            actor_user_id=ctx.subject_id,
        )
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
            for job_id in (iteration.classify_job_id, iteration.draft_job_id):
                if job_id is not None:
                    await background_job_repo.cancel_queued(self.db, job_id)
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

    async def wake(
        self, run_id: UUID, *, organization_id: UUID, after: timedelta | None = None
    ) -> None:
        """Advance a session as soon as a step it waits on has ended, not at the next sweep.

        Called in the transaction that ends the step, so the advance runs on what it
        wrote. A step whose end the queue records only after it returns - a knowledge
        job's - passes `after`, so the advance reads that end rather than racing it.
        """
        run = await improvement_repo.get_run(self.db, run_id, organization_id=organization_id)
        if run is not None and Status(run.status).active:
            await self._queue(run, run_after=None if after is None else datetime.now(UTC) + after)

    async def _queue(self, run: ImprovementRun, *, run_after: datetime | None = None) -> None:
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
            run_after=run_after,
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
        while rows := await improvement_repo.list_deciding(self.db, after=after):
            for run_id, org_id in rows:
                run = await improvement_repo.get_run(self.db, run_id, organization_id=org_id)
                if run is not None:
                    await self._queue(run)
                    count += 1
            after = rows[-1][0]
        after = None
        while rows := await improvement_repo.list_resting(self.db, after=after):
            for run_id, org_id in rows:
                await self._end_if_left(run_id, org_id)
            after = rows[-1][0]
        return count

    async def _end_if_left(self, run_id: UUID, organization_id: UUID) -> None:
        """End a session waiting for a person once nobody took it further for a week, or at
        once when its agent or test set changed under it.

        A ready session's draft moves while its candidate is decided in the Builder, so
        only the week ends one; and a session whose person lost access is left for
        whoever acts next to be told.
        """
        run = await improvement_repo.get_run(
            self.db, run_id, organization_id=organization_id, lock=True
        )
        if run is None or Status(run.status).active or not Status(run.status).open:
            return
        stage = Stage(run.stage) if run.stage else None
        if rules.expired(run.stage_started_at or run.created_at, now=datetime.now(UTC)):
            await self._move(run, rules.Transition(Status.STALE, stage, StopReason.EXPIRED))
            return
        if run.status == Status.READY:
            return
        user_id, api_key_id = self._acting_as(run)
        try:
            ctx = await job_context(
                self.db, organization_id=organization_id, user_id=user_id, api_key_id=api_key_id
            )
            if ctx is None:
                return
            current = await self._inputs(
                ctx,
                run.agent_id,
                ImprovementTarget(
                    dataset_id=run.dataset_id if run.suite_id is None else None,
                    suite_id=run.suite_id,
                ),
            )
        except AuthenticationError, AuthorizationError:
            return
        except NotFoundError:
            # Hidden from whoever it runs as is not gone: they are told when they act.
            agent = await agent_repo.get(self.db, run.agent_id, organization_id=organization_id)
            dataset = await dataset_repo.get(
                self.db, run.dataset_id, organization_id=organization_id
            )
            if agent is not None and dataset is not None:
                return
            current = None
        except BadRequestError:
            current = None
        pins = rules.Pins(
            run.base_draft_hash,
            run.base_version_id,
            run.scoring_hash,
            run.dataset_id,
            run.suite_id,
            run.suite_hash,
        )
        if current is None or rules.stale(pins, current.pins, archived=False):
            await self._move(run, rules.Transition(Status.STALE, stage, StopReason.STALE))

    async def _settle_decisions(self, run: ImprovementRun) -> None:
        """Observe human decisions without acquiring an agent lock after the parent lock."""
        rounds = await improvement_repo.list_iterations(
            self.db, organization_id=run.organization_id, run_id=run.id
        )
        selected = next((item for item in rounds if item.id == run.best_iteration_id), None)
        if selected is None or selected.batch_id is None:
            return
        published: dict[str, UUID | int] = {}
        batch = await authoring_repo.get_batch(
            self.db, selected.batch_id, organization_id=run.organization_id
        )
        if batch is not None and batch.status == BatchStatus.SUPERSEDED:
            current = await authoring_repo.get_open_batch(
                self.db, organization_id=run.organization_id, agent_id=run.agent_id
            )
            # Exposing another of its own rounds is not a person's decision.
            if current is not None and current.improvement_run_id == run.id:
                return
        if batch is None or batch.status == BatchStatus.SUPERSEDED:
            status = Status.REJECTED
        else:
            hunks = await authoring_repo.list_hunks(
                self.db, organization_id=run.organization_id, batch_id=batch.id
            )
            hunks = [
                h
                for h in hunks
                if selected.included_hunk_ids is None or h.id in selected.included_hunk_ids
            ]
            accepted = any(h.status == HunkStatus.ACCEPTED for h in hunks)
            pending = any(h.status == HunkStatus.PENDING for h in hunks)
            if batch.status == BatchStatus.PUBLISHED:
                status = Status.PUBLISHED if accepted else Status.REJECTED
                if accepted:
                    published = await self._measured_version(run, selected, hunks)
            elif pending:
                status = Status.READY
            else:
                status = Status.ACCEPTED if accepted else Status.REJECTED
        if run.status != status:
            self._allow(run, status)
            await improvement_repo.update_run(
                self.db, run=run, values={"status": status.value, **published}
            )
            await self._audit(run, status.value)
            self._announce(run)
            await self._notify_end(run, end=datetime.now(UTC).isoformat())

    async def _measured_version(
        self,
        run: ImprovementRun,
        selected: ImprovementIteration,
        hunks: list[SpecProposalHunk],
    ) -> dict[str, UUID | int]:
        """The agent's newest version, when it is the candidate this session measured."""
        version = await agent_repo.newest_version(
            self.db, agent_id=run.agent_id, organization_id=run.organization_id
        )
        assert version is not None, "a batch is closed as published by a publish"
        spec, skills = authoring_hunks.as_measured(AgentSpec.model_validate(version.spec), hunks)
        if spec_hash(spec, skills) != selected.candidate_spec_hash:
            return {}
        return {"published_version_id": version.id, "published_version": version.version}

    async def _audit(
        self,
        run: ImprovementRun,
        action: str,
        *,
        actor_user_id: UUID | None = None,
        step_estimate_usd: Decimal | None = None,
        quote_hash: str | None = None,
        decided: dict[str, str] | None = None,
    ) -> None:
        """Record a step on the session's timeline.

        `actor_user_id` names a person who acted; the session's own steps name
        none and are recorded under its requester. `decided` is what they decided.
        """
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
                **(
                    {"step_estimate_usd": str(step_estimate_usd)}
                    if step_estimate_usd is not None
                    else {}
                ),
                **({"quote_hash": quote_hash} if quote_hash is not None else {}),
                **({"actor": str(actor_user_id)} if actor_user_id is not None else {}),
                **(decided or {}),
            },
        )

    async def _move(
        self,
        run: ImprovementRun,
        transition: rules.Transition,
        *,
        actor_user_id: UUID | None = None,
    ) -> None:
        self._allow(run, transition.status)
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
            run,
            "stage_changed" if transition.status.active else transition.status.value,
            actor_user_id=actor_user_id,
        )
        self._announce(run)
        if transition.status.active:
            await self._queue(run)
        elif actor_user_id is None or actor_user_id != self._acting_as(run)[0]:
            await self._notify_end(run, end=now.isoformat())

    def _announce(self, run: ImprovementRun) -> None:
        """Tell open pages of the agent that this session changed, once the change commits."""
        spawn_after_commit(
            self.db,
            change_feed.publish(
                ChangeEvent(
                    organization_id=run.organization_id,
                    resource="improvement",
                    id=run.agent_id,
                    action="updated",
                    surface="system",
                    actor_user_id=None,
                    actor_name=None,
                )
            ),
            name=f"improvement-moved:{run.id}",
        )

    async def _notify_end(
        self, run: ImprovementRun, *, end: str, reason: str | None = None
    ) -> None:
        agent = await agent_repo.get(self.db, run.agent_id, organization_id=run.organization_id)
        user_id, _ = self._acting_as(run)
        if agent is None or user_id is None:
            return
        await NotificationService(self.db).improvement_finished(
            agent=agent,
            run_id=run.id,
            user_id=user_id,
            status=run.status,
            reason=reason or (run.stage if run.status == Status.WAITING else run.stop_reason),
            end=end,
        )

    async def check_finished(self, check: EvalRun) -> None:
        """One of a session's eval runs ended: advance the session at once, and tell its
        requester when it was a knowledge or attribution check of a finished session."""
        session_id = (check.proposal_check or {}).get("improvement_run_id")
        assert session_id is not None, "only a session's own check reports here"
        run = await improvement_repo.get_run(
            self.db, UUID(session_id), organization_id=check.organization_id
        )
        if run is None:
            return
        if Status(run.status).active:
            await self._queue(run)
            return
        if (check.proposal_check or {}).get("knowledge") is not None:
            kind = "knowledge_check"
        elif any(
            str(check.id) in map(str, item.attribution_eval_run_ids.values())
            for item in await improvement_repo.list_iterations(
                self.db, organization_id=run.organization_id, run_id=run.id
            )
        ):
            kind = "attribution_check"
        else:
            return
        await self._notify_end(run, end=f"{kind}:{check.id}", reason=kind)

    async def ensure_current(
        self, ctx: AuthContext, run_id: UUID, *, allow_finished: bool = False
    ) -> None:
        """Recheck a queued paid child's authority and pins just before it starts.

        `allow_finished` also admits a session between steps or after them, a
        failed one included: retrying its step reads the same sources again.
        """
        run = await improvement_repo.get_run(self.db, run_id, organization_id=ctx.organization_id)
        if run is None or not (
            Status(run.status).active
            or (
                allow_finished
                and run.status in {Status.WAITING, Status.READY, Status.STOPPED, Status.FAILED}
            )
        ):
            raise BadRequestError(
                message="The improvement session stopped", details={"reason": "stopped"}
            )
        await self._current_inputs(ctx, run)

    async def _current_inputs(self, ctx: AuthContext, run: ImprovementRun) -> Inputs:
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
        return inputs

    async def advance(self, run_id: UUID, organization_id: UUID) -> None:
        run = await improvement_repo.get_run(
            self.db, run_id, organization_id=organization_id, lock=True
        )
        if run is None:
            return
        if Status(run.status).deciding:
            await self._settle_decisions(run)
            return
        if not Status(run.status).active:
            return
        user_id, api_key_id = self._acting_as(run)
        try:
            ctx = await job_context(
                self.db, organization_id=organization_id, user_id=user_id, api_key_id=api_key_id
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
            if transition.status.active:
                ids, messages, _ = await self.knowledge_sources(ctx, run)
                if not ids or not messages:
                    transition = rules.Transition(Status.WAITING, Stage.ANALYZING)
            await self._move(run, transition)
        elif run.stage in {Stage.CLASSIFYING, Stage.DRAFTING}:
            await self._knowledge_step(ctx, run, iteration)
        elif run.stage == Stage.PROPOSING:
            if iteration.batch_id is not None and iteration.authoring_request_id is None:
                await self._move(run, rules.Transition(Status.RUNNING, Stage.FILTERING))
                return
            if iteration.authoring_request_id is None:
                excluded = await self._knowledge_exclusions(ctx, run)
                estimate = await self.authoring.estimate_agent(
                    ctx,
                    run.agent_id,
                    AuthoringStart(
                        window_days=run.window_days, improver_agent_id=run.improver_agent_id
                    ),
                    improvement_run_id=run.id,
                    excluded_message_ids=excluded,
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
                    excluded_message_ids=excluded,
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
            measured = await authoring_repo.list_hunks(
                self.db, organization_id=run.organization_id, batch_id=iteration.batch_id
            )
            await improvement_repo.update_iteration(
                self.db,
                iteration=iteration,
                values={
                    "included_hunk_ids": [
                        h.id for h in measured if h.status == HunkStatus.PENDING.value
                    ]
                },
            )
            candidate_hash = spec_hash(
                projected,
                await self.authoring.projected_skills(
                    ctx, iteration.batch_id, hunk_ids=iteration.included_hunk_ids
                ),
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
        elif run.stage == Stage.JUDGING:  # pragma: no branch - the stages above are exhaustive
            await self._judge(ctx, run, iteration)

    async def _candidate(
        self,
        agent: Agent,
        run: ImprovementRun,
        iteration: ImprovementIteration,
        *,
        filter_policy: bool = False,
        hunk_ids: list[UUID] | None = None,
    ) -> tuple[AgentSpec, int]:
        assert iteration.batch_id is not None
        hunks = await authoring_repo.list_hunks(
            self.db, organization_id=run.organization_id, batch_id=iteration.batch_id
        )
        included = iteration.included_hunk_ids if hunk_ids is None else hunk_ids
        pending = [
            h
            for h in hunks
            if h.status == HunkStatus.PENDING.value and (included is None or h.id in included)
        ]
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
        # Only while another attempt can measure the rest: on the last one the split
        # left a round no attempt would ever run.
        if (
            filter_policy
            and model_changes
            and other_changes
            and iteration.number < run.max_iterations
        ):
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
            # Proposed from this attempt's evidence, so measured on this attempt's split.
            await improvement_repo.update_iteration(
                self.db,
                iteration=deferred,
                values={
                    "batch_id": separate.id,
                    "split_seed": iteration.split_seed,
                    "train_case_ids": iteration.train_case_ids,
                    "holdout_case_ids": iteration.holdout_case_ids,
                },
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
                if transition is not None:  # pragma: no branch - a terminal check always moves
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
            candidate_skills=await self.authoring.projected_skills(
                ctx, batch.id, hunk_ids=iteration.included_hunk_ids
            ),
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
            candidate_skills=await self.authoring.projected_skills(
                ctx, batch.id, hunk_ids=iteration.included_hunk_ids
            ),
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
            proposal_check=await self._check_record(ctx, run, iteration, batch, count),
        )
        await improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={"eval_run_ids": [*iteration.eval_run_ids, child.id], "verdict": None},
        )
        await self._audit(run, "child_started")

    async def _check_record(
        self,
        ctx: AuthContext,
        run: ImprovementRun,
        iteration: ImprovementIteration,
        batch: SpecProposalBatch,
        suggestions: int,
    ) -> ProposalCheckRecord:
        """What an attempt's check records: its evidence, kept out of the measured questions,
        and the attempt's own draw of those questions."""
        return ProposalCheckRecord(
            kind="agent",
            base_version=None,
            on_draft=True,
            suggestions=suggestions,
            improvement_run_id=run.id,
            evidence_run_ids=list(
                {
                    *(run.chat_evidence_run_ids or []),
                    *await self.authoring.evidence_run_ids(ctx, batch),
                }
            ),
            attempt_holdout=iteration.holdout_case_ids,
        )

    async def _draw_split(self, run: ImprovementRun, iteration: ImprovementIteration) -> None:
        """Give a new attempt its own draw of the questions it learns from and is measured on."""
        dataset = await dataset_repo.get(
            self.db, run.dataset_id, organization_id=run.organization_id
        )
        version = await dataset_repo.get_version(
            self.db, run.dataset_id, run.dataset_version, organization_id=run.organization_id
        )
        assert dataset is not None and version is not None, "the quote checked the pinned set"
        cases = [
            case.case_id
            for case in await dataset_repo.list_cases(
                self.db, version.id, organization_id=run.organization_id, limit=None
            )
            if case.anonymised_at is None
        ]
        seed = secrets.randbelow(2**31 - 1)
        holdout = drawn_holdout(cases, share=dataset.improvement_holdout_share, seed=seed)
        held = set(holdout)
        await improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={
                "split_seed": seed,
                "train_case_ids": [case_id for case_id in cases if case_id not in held],
                "holdout_case_ids": holdout,
            },
        )

    @staticmethod
    def _check_result(child: EvalRunRead, comparison: EvalComparisonRead) -> rules.CheckResult:
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
        return rules.CheckResult(
            comparable=comparison.baseline is not None and comparison.verdict != "invalid",
            incomplete=mine.incomplete + (theirs.incomplete if theirs else 0),
            ungraded=mine.ungraded + (theirs.ungraded if theirs else 0),
            crashed=mine.crashed + (theirs.crashed if theirs else 0),
            regressions_confirmed=comparison.regressions_confirmed,
            fixed_confirmed=comparison.fixed_confirmed,
            candidate_pass_rate=mine.pass_rate,
            baseline_pass_rate=None if theirs is None else theirs.pass_rate,
            suite=outcome,
            held_out=None
            if child.proposal_check is None or child.proposal_check.measurement is None
            else len(child.proposal_check.measurement.holdout_case_ids),
        )

    @staticmethod
    def _round_result(item: ImprovementIteration) -> rules.RoundResult:
        assert item.verdict is not None
        detail = item.verdict_detail or {}
        return rules.RoundResult(
            item.number,
            ImprovementVerdict(item.verdict),
            detail.get("fixed") or 0,
            detail.get("broken") or 0,
            detail.get("held_out") or 0,
        )

    @staticmethod
    def _result_detail(result: rules.CheckResult) -> VerdictDetail:
        return {
            "reason": None,
            "broken": result.regressions_confirmed,
            "fixed": result.fixed_confirmed,
            "ungraded": result.ungraded,
            "incomplete": result.incomplete,
            "crashed": result.crashed,
            "candidate_pass_rate": result.candidate_pass_rate,
            "baseline_pass_rate": result.baseline_pass_rate,
            "held_out": result.held_out,
        }

    async def recompute_after_review(self, ctx: AuthContext, check_ids: list[UUID]) -> None:
        """Refresh measured verdicts in the review transaction without new work or publication.

        Preserve the person's selected round. Archived checks and attribution
        cannot replace its current measurement. Read as the original requester,
        never grant the reviewer additional access to an agent's answers.
        """
        for run_id in await improvement_repo.runs_for_checks(
            self.db, organization_id=ctx.organization_id, check_ids=check_ids
        ):
            run = await improvement_repo.get_run(
                self.db, run_id, organization_id=ctx.organization_id, lock=True
            )
            if run is None:
                continue
            rounds = await improvement_repo.list_iterations(
                self.db, organization_id=ctx.organization_id, run_id=run.id
            )
            for iteration in rounds:
                if (
                    not iteration.verdict
                    or not iteration.eval_run_ids
                    or iteration.eval_run_ids[-1] not in check_ids
                ):
                    continue
                result: rules.CheckResult | None = None
                try:
                    user_id, api_key_id = self._acting_as(run)
                    reader = await job_context(
                        self.db,
                        organization_id=ctx.organization_id,
                        user_id=user_id,
                        api_key_id=api_key_id,
                    )
                    if reader is not None:
                        child = await self.evals.get(reader, iteration.eval_run_ids[-1])
                        comparison = await self.evals.compare(reader, child.id)
                        result = self._check_result(child, comparison)
                except AuthenticationError, AuthorizationError, NotFoundError:
                    result = None
                if result is None:
                    verdict = ImprovementVerdict.INCONCLUSIVE
                    detail: VerdictDetail = {
                        "fixed": None,
                        "broken": None,
                        "candidate_pass_rate": None,
                        "baseline_pass_rate": None,
                        "reason": "review_access_unavailable",
                    }
                    if run.status == Status.READY:
                        await self._move(
                            run,
                            rules.Transition(Status.STOPPED, Stage.JUDGING, StopReason.PERMISSION),
                        )
                else:
                    verdict = rules.judge(result)
                    detail = self._result_detail(result)
                await improvement_repo.update_iteration(
                    self.db,
                    iteration=iteration,
                    values={
                        "verdict": verdict.value,
                        "verdict_detail": {**(iteration.verdict_detail or {}), **detail},
                    },
                )
                await self._audit(run, "review_recomputed", actor_user_id=ctx.subject_id)

    async def _judge(
        self, ctx: AuthContext, run: ImprovementRun, iteration: ImprovementIteration
    ) -> None:
        child = await self.evals.get(ctx, iteration.eval_run_ids[-1])
        comparison = await self.evals.compare(ctx, child.id)
        result = self._check_result(child, comparison)
        verdict = rules.judge(result)
        rounds = await improvement_repo.list_iterations(
            self.db, organization_id=run.organization_id, run_id=run.id
        )
        spent = await improvement_repo.spent(self.db, run.id, organization_id=run.organization_id)
        previous_cost = sum(
            (item.cost_usd for item in rounds if item.id != iteration.id), Decimal(0)
        )
        await improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={
                "verdict": verdict.value,
                "verdict_detail": {
                    **(iteration.verdict_detail or {}),
                    **self._result_detail(result),
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
            self._round_result(item)
            for item in rounds
            if item.verdict is not None
            and (bool(iteration.previous_eval_run_ids) or item.number <= iteration.number)
        ]
        best_number = rules.best_round(results)
        best = next((item for item in rounds if item.number == best_number), None)
        await improvement_repo.update_run(
            self.db, run=run, values={"best_iteration_id": None if best is None else best.id}
        )
        # A confirming rerun belongs to this round; any other verdict waits for a person.
        if transition.status.active:
            await self._move(run, transition)
            return
        if transition.status == Status.READY:
            # The waiting candidate is the best round, which an equal later round does not displace.
            assert best is not None, "a round judged ready was measured"
            transition = await self._expose(run, best)
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
        run, iteration, _ = await self._attribution_target(ctx, agent_id, run_id, number)
        transition = await self._expose(run, iteration)
        if transition.status == Status.READY:
            await improvement_repo.update_run(
                self.db, run=run, values={"best_iteration_id": iteration.id}
            )
        await self._audit(run, "round_selected")
        await self._move(run, transition, actor_user_id=ctx.subject_id)
        return await self._read(ctx, run)

    async def _knowledge_plan(
        self, ctx: AuthContext, agent_id: UUID, run_id: UUID, data: KnowledgeCheckTarget
    ) -> KnowledgePlan | KnowledgeCheckEstimate:
        run, iteration, inputs = await self._finished_round(
            ctx, agent_id, run_id, data.round, allow_knowledge_only=True
        )
        gaps = KnowledgeGapService(self.db)
        topic = await gaps._topic(ctx, data.topic_id, edit=True)
        if (await gaps._row(ctx, topic)).status != "open":
            raise BadRequestError(message="Reopen the knowledge topic before checking a draft")
        kb = await gaps._knowledge_base(ctx, topic.knowledge_base_id, edit=True)
        if not topic.draft_content:
            raise BadRequestError(message="This topic has no draft to check")
        base = AgentSpec.model_validate(inputs.agent.draft_spec)
        skills: dict[UUID, SkillBody] = {}
        if iteration.batch_id is not None:
            base, _ = await self._candidate(inputs.agent, run, iteration)
            skills = await self.authoring.projected_skills(
                ctx, iteration.batch_id, hunk_ids=iteration.included_hunk_ids
            )
            if spec_hash(base, skills) != iteration.candidate_spec_hash:
                raise ConcurrentChangeError(
                    message="The selected changes no longer match the measured round"
                )
        if topic.knowledge_base_id not in base.collection_ids:
            raise BadRequestError(message="The selected round does not search this knowledge base")
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
            and (
                case.improvement_partition == "holdout"
                if iteration.holdout_case_ids is None
                else case.case_id in iteration.holdout_case_ids
            )
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
            attempt_holdout=iteration.holdout_case_ids,
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
        self._require_requester(ctx, await self._row(ctx, agent_id, run_id))
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
        run, iteration, inputs = await self._finished_round(ctx, agent_id, run_id, number)
        projected, _ = await self._candidate(inputs.agent, run, iteration)
        assert iteration.batch_id is not None
        skills = await self.authoring.projected_skills(
            ctx, iteration.batch_id, hunk_ids=iteration.included_hunk_ids
        )
        if spec_hash(projected, skills) != iteration.candidate_spec_hash:
            raise ConcurrentChangeError(
                message="The changes differ from the measured round; check them again"
            )
        return run, iteration, inputs

    async def _selection_plan(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        run_id: UUID,
        number: int,
        data: ImprovementSelection,
    ) -> SelectionPlan:
        run, iteration, inputs = await self._finished_round(ctx, agent_id, run_id, number)
        assert iteration.batch_id is not None
        batch = await authoring_repo.get_batch(
            self.db, iteration.batch_id, organization_id=ctx.organization_id
        )
        if batch is None:
            raise NotFoundError(message="The suggestions are no longer available")
        hunks = await authoring_repo.list_hunks(
            self.db, organization_id=ctx.organization_id, batch_id=batch.id
        )
        pending = {h.id for h in hunks if h.status == HunkStatus.PENDING.value}
        if not set(data.hunk_ids) <= pending:
            raise BadRequestError(message="Select pending changes from this round only")
        projected, count = await self._candidate(
            inputs.agent, run, iteration, hunk_ids=data.hunk_ids
        )
        skills = await self.authoring.projected_skills(ctx, batch.id, hunk_ids=data.hunk_ids)
        quote = await self.evals.estimate(
            ctx,
            agent_id,
            self._eval_request(inputs, run),
            candidate_spec=projected,
            candidate_skills=skills,
            baseline_spec=AgentSpec.model_validate(inputs.agent.draft_spec),
            scoring=DatasetScoring.model_validate(run.pinned_scoring),
            exclude_conversations=batch.evidence_conversation_ids,
            judge_version_id=run.judge_version_id,
            judge_pinned=True,
        )
        total = (quote.total_usd + quote.rerun_ceiling_usd) * (1 + rules.INCONCLUSIVE_RERUNS)
        spent = await improvement_repo.spent(self.db, run.id, organization_id=ctx.organization_id)
        org_left = await self.evals._org_left(ctx)
        return SelectionPlan(
            run,
            iteration,
            SelectionEstimate(
                suggestions=count,
                total_usd=total,
                candidate_hash=spec_hash(projected, skills),
                affordable=rules.affordable(spent=spent, step_estimate=total, budget=run.budget_usd)
                and (org_left is None or total <= org_left),
            ),
        )

    async def estimate_selection(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        run_id: UUID,
        number: int,
        data: ImprovementSelection,
    ) -> SelectionEstimate:
        return (await self._selection_plan(ctx, agent_id, run_id, number, data)).quote

    async def check_selection(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        run_id: UUID,
        number: int,
        data: SelectionConsent,
    ) -> ImprovementRead:
        """Queue the chosen changes only after consent to their hash and full price.

        Prior combined and attribution checks remain in the round's history.
        Excluded suggestions stay undecided; accepting the session applies only
        its measured selection through normal authoring decisions.
        """
        await self.authoring._editable(ctx, agent_id)
        self.authoring._require_runs_view(ctx)
        if await agent_repo.lock(self.db, agent_id, organization_id=ctx.organization_id) is None:
            raise NotFoundError(message="Agent not found")
        existing = await self._row(ctx, agent_id, run_id, lock=True)
        self._require_requester(ctx, existing)
        if Status(existing.status).active:
            current = await improvement_repo.get_iteration(
                self.db, organization_id=ctx.organization_id, run_id=run_id, number=number
            )
            if (
                current is not None
                and current.included_hunk_ids is not None
                and set(current.included_hunk_ids) == set(data.hunk_ids)
                and current.candidate_spec_hash == data.candidate_hash
            ):
                return await self._read(ctx, existing)
            raise ConcurrentChangeError(
                message="This session is already running a step",
                details={"improvement_run_id": str(existing.id)},
            )
        plan = await self._selection_plan(ctx, agent_id, run_id, number, data)
        run, iteration, quote = plan.session, plan.iteration, plan.quote
        if quote.candidate_hash != data.candidate_hash or quote.total_usd != data.estimate_usd:
            raise ConcurrentChangeError(
                message="The selected changes or their estimate changed; review them again"
            )
        if not quote.affordable:
            raise PaymentRequiredError(
                message="The complete selected check exceeds the remaining budget"
            )
        if await improvement_repo.has_active_check(
            self.db, run.id, organization_id=ctx.organization_id
        ):
            raise ConcurrentChangeError(message="Wait for the current checks to finish")
        await improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={
                "included_hunk_ids": list(data.hunk_ids),
                "candidate_spec_hash": quote.candidate_hash,
                "previous_eval_run_ids": list(
                    dict.fromkeys(
                        [
                            *iteration.previous_eval_run_ids,
                            *iteration.eval_run_ids,
                            *(UUID(value) for value in iteration.attribution_eval_run_ids.values()),
                        ]
                    )
                ),
                "eval_run_ids": [],
                "attribution_eval_run_ids": {},
                "verdict": None,
                "verdict_detail": None,
                "ended_at": None,
            },
        )
        await improvement_repo.update_run(
            self.db,
            run=run,
            values={
                "iteration": number,
                "error": None,
            },
        )
        await self._audit(
            run,
            "selection_confirmed",
            actor_user_id=ctx.subject_id,
            step_estimate_usd=quote.total_usd,
            quote_hash=quote.candidate_hash,
        )
        await self._move(run, rules.Transition(Status.RUNNING, Stage.EVALUATING))
        return await self._read(ctx, run)

    async def _finished_round(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        run_id: UUID,
        number: int,
        *,
        allow_knowledge_only: bool = False,
    ) -> tuple[ImprovementRun, ImprovementIteration, Inputs]:
        await self.authoring._editable(ctx, agent_id)
        self.authoring._require_runs_view(ctx)
        run = await self._row(ctx, agent_id, run_id, lock=True)
        if run.status not in {Status.READY, Status.STOPPED}:
            raise BadRequestError(message="Checks are available after the session finishes")
        await self.ensure_current(ctx, run_id, allow_finished=True)
        iteration = await improvement_repo.get_iteration(
            self.db, organization_id=run.organization_id, run_id=run.id, number=number
        )
        knowledge_only = (
            allow_knowledge_only
            and run.status == Status.STOPPED
            and run.stop_reason == StopReason.KNOWLEDGE_ONLY
        )
        if iteration is None or (
            not knowledge_only and (iteration.batch_id is None or iteration.verdict is None)
        ):
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
            if hunk.status != HunkStatus.PENDING.value or (
                iteration.included_hunk_ids is not None
                and hunk.id not in iteration.included_hunk_ids
            ):
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
        self._require_requester(ctx, run)
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
                    attempt_holdout=iteration.holdout_case_ids,
                ),
            )
            ids[str(hunk_id)] = str(child.id)
        await improvement_repo.update_iteration(
            self.db, iteration=iteration, values={"attribution_eval_run_ids": ids}
        )
        await self._audit(run, "attribution_started")
        return await self._read(ctx, run)

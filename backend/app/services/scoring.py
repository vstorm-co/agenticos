"""Score answers against dataset cases, and keep what each scorer found.

A dataset says how its cases are scored (`DatasetScoring`): rule-based checks,
the tool calls the agent made against the ones expected, and the eval judge on a
rubric and on the reference answer. Scoring one answer runs every configured
scorer and writes a `CaseScore` - the results, whether the case passed, and a
copy of the configuration used. A person's verdict is written beside it later
and never replaces what the scorers said.

The judge is the platform's seeded system agent, run as the person asking for the
score: budget-checked, recorded, visible in Activity. When it cannot run - AI
assistance switched off, the judge unpublished, the budget spent - its criteria
are recorded as skipped with the reason, the rule-based scorers still score, and
a case whose required judge was skipped is left unscored rather than passed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic_ai_harness.guardrails.detectors import redact_secrets
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.system_agents import JUDGE
from app.core.audit import record_audit
from app.core.exceptions import (
    AiAssistanceDisabledError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    NothingToScoreError,
    SystemAgentOutputError,
    SystemAgentRunError,
    SystemAgentUnavailableError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import AgentKind
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.case_score import CaseScore
from app.db.models.dataset import Dataset, DatasetCase
from app.db.models.intercepted_tool_call import InterceptionOutcome
from app.repositories import (
    agent_repo,
    case_score_repo,
    conversation_repo,
    credential_repo,
    dataset_repo,
    intercepted_tool_call_repo,
)
from app.schemas.dataset import DatasetRead
from app.schemas.scoring import (
    CaseScoreCreate,
    CaseScoreList,
    CaseScoreRead,
    CaseVerdict,
    DatasetScoring,
    JudgeCreate,
    JudgePin,
    PendingDataset,
    PendingScore,
    ReviewQueue,
    ReviewRequest,
    ReviewRequested,
    ReviewWithdrawn,
    ScoreOutcome,
    ScorerResult,
)
from app.services.access import DATASET, visible_resource_ids
from app.services.agent_runner import AgentRunnerService
from app.services.ai_assistance import AiAssistanceService
from app.services.dataset import DatasetService
from app.services.scorers import (
    CaseView,
    JudgeCriterion,
    JudgeVerdict,
    ScoredAnswer,
    ScoredCall,
    case_passed,
    graded,
    judge_criteria,
    judge_prompt,
    not_graded,
    rubric_hash,
    run_checks,
    score_trajectory,
)
from app.services.system_agent_runner import SystemAgentRunner
from app.services.system_agents import SystemAgentService

_MAX_TURNS = 100
# Enough of an answer to review it; a longer one is read in full from its run.
_MAX_ANSWER = 8_000


def _redact(text: str | None) -> str | None:
    if not text:
        return text
    verdict = redact_secrets(text)
    if verdict.action == "replace" and isinstance(verdict.replacement, str):
        return verdict.replacement
    return text


@dataclass(frozen=True)
class Evaluation:
    """Every scorer's result for one answer, and which judge graded it, if one did."""

    results: list[ScorerResult]
    judge: JudgePin | None = None


def _kept_answer(text: str) -> str | None:
    clipped = text if len(text) <= _MAX_ANSWER else f"{text[:_MAX_ANSWER]}…"
    return _redact(clipped)


def _by_dataset(counts: list[tuple[UUID, str, bool | None, int]]) -> list[PendingDataset]:
    """Each dataset's waiting scores by outcome, the dataset with the most first."""
    tallies: dict[UUID, dict[str, int]] = {}
    names: dict[UUID, str] = {}
    for dataset_id, name, passed, count in counts:
        names[dataset_id] = name
        outcome = "unscored" if passed is None else "passed" if passed else "failed"
        tallies.setdefault(dataset_id, {})[outcome] = count
    datasets = [
        PendingDataset(dataset_id=dataset_id, name=names[dataset_id], **tally)
        for dataset_id, tally in tallies.items()
    ]
    return sorted(datasets, key=lambda d: (-(d.failed + d.unscored + d.passed), d.name))


def _case_view(case: DatasetCase) -> CaseView:
    return CaseView(
        input=case.input,
        history=case.history,
        reference_answer=case.reference_answer,
        counter_example=case.counter_example,
        expected_tool_calls=case.expected_tool_calls,
        order_mode=case.order_mode,
        checks=case.checks,
    )


class ScoringService:
    """Configure a dataset's scoring, score answers, and record people's verdicts."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.datasets = DatasetService(db)
        self.judge = SystemAgentRunner(db)

    async def set_scoring(
        self, ctx: AuthContext, dataset_id: UUID, data: DatasetScoring
    ) -> DatasetRead:
        """Replace how a dataset's cases are scored. Needs `datasets:edit` on it.

        Scores already written keep the configuration they were computed with.

        Raises:
            NotFoundError: The dataset is not one the caller may edit.
            BadRequestError: Every scorer is off, the judge is on with nothing to
                grade, the judge picked is not one of the organization's judges,
                the judge's model is not one of the organization's, or the
                judge or the reference comparison is turned on while AI
                assistance is off. One already on stays on, and is skipped.
        """
        dataset = await self.datasets.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        stored = DatasetScoring.model_validate(dataset.scoring)
        turned_on = [
            field
            for field, now, before in (
                ("judge.enabled", data.judge.enabled, stored.judge.enabled),
                ("reference.enabled", data.reference.enabled, stored.reference.enabled),
            )
            if now and not before
        ]
        if turned_on and not await AiAssistanceService(self.db).is_enabled(
            organization_id=ctx.organization_id
        ):
            raise refused_field(
                turned_on[0],
                "AI assistance is off in this organization, so the judge cannot be "
                "turned on. Ask an admin to enable AI assistance.",
            )
        scorers = (data.checks, data.trajectory, data.judge, data.reference)
        if not any(scorer.enabled for scorer in scorers):
            raise refused_field("checks.enabled", "Turn on at least one scorer")
        if data.judge.enabled and not data.judge.criteria:
            raise refused_field("judge.criteria", "Give the judge at least one criterion")
        judge_id = data.judge.agent_id
        if judge_id is not None and judge_id != stored.judge.agent_id:
            judge = await agent_repo.get(self.db, judge_id, organization_id=ctx.organization_id)
            if judge is None or judge.kind != AgentKind.JUDGE.value:
                raise refused_field("judge.agent_id", "This organization has no such judge")
        profile_id = data.judge.model_profile_id
        if profile_id is not None and (
            await credential_repo.get_profile(
                self.db, profile_id, organization_id=ctx.organization_id
            )
            is None
        ):
            raise refused_field("judge.model_profile_id", "This organization has no such model")
        await dataset_repo.update(
            self.db,
            dataset=dataset,
            update_data={"scoring": data.model_dump(mode="json", by_alias=True)},
        )
        return await self.datasets.read(ctx, dataset_id)

    async def create_judge(
        self, ctx: AuthContext, dataset_id: UUID, data: JudgeCreate
    ) -> DatasetRead:
        """Create a judge of the dataset's own and make it the one grading the dataset.

        Needs `datasets:edit` on the dataset and `agents:edit`, since a judge is
        an agent. The rubric stays the dataset's; only which judge grades changes,
        so scores graded before keep the judge they were graded by.

        Raises:
            NotFoundError: The dataset is not one the caller may edit, or the
                model is not one of the organization's.
            AuthorizationError: The caller's role may not create agents.
            AlreadyExistsError: An agent of the organization holds the name.
        """
        dataset = await self.datasets.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        if not ctx.has(Perm.AGENTS_EDIT):
            raise AuthorizationError(
                message="Creating a judge creates an agent, which your role does not allow"
            )
        judge = await SystemAgentService(self.db).create_judge(
            ctx,
            name=data.name,
            description=f"Grades the cases of the dataset '{dataset.name}'.",
            instructions=data.instructions,
            model_profile_id=data.model_profile_id,
        )
        scoring = DatasetScoring.model_validate(dataset.scoring)
        scoring.judge.agent_id = judge.id
        await dataset_repo.update(
            self.db,
            dataset=dataset,
            update_data={"scoring": scoring.model_dump(mode="json", by_alias=True)},
        )
        return await self.datasets.read(ctx, dataset_id)

    async def score_run(
        self, ctx: AuthContext, dataset_id: UUID, case_id: UUID, data: CaseScoreCreate
    ) -> CaseScoreRead:
        """Score a recorded run's answer against one case, and keep the score.

        Needs `datasets:run` on the dataset - scoring may spend on the judge - and
        `runs:view`, since the answer is read from the run's transcript.

        Raises:
            NotFoundError: The dataset, the case or the run is not one the caller
                may reach.
            AuthorizationError: The caller may not read runs.
            BadRequestError: The run kept no transcript to score, or the
                dataset's scorers have nothing to check on the case.
        """
        dataset = await self.datasets.get(ctx, dataset_id, perm=Perm.DATASETS_RUN)
        case = await self.datasets.case_at(ctx, dataset, case_id, version=data.version)
        answer = await self.answer_of(ctx, data.run_id)
        score = await self.score_case(
            ctx, dataset=dataset, case=case, answer=answer, enqueue_review=True
        )
        return (await self._reads(ctx, [score]))[0]

    async def answer_of(self, ctx: AuthContext, run_id: UUID) -> ScoredAnswer:
        """What a recorded run answered and called, read from its transcript.

        Raises:
            NotFoundError: The run is not in the caller's organization.
            AuthorizationError: The caller does not hold `runs:view`.
            BadRequestError: The run has no answer to score - it kept no
                transcript, or never answered.
        """
        runs = AgentRunnerService(self.db)
        run, messages, total = await runs.get_run_transcript(ctx, run_id, limit=_MAX_TURNS)
        if total > len(messages):
            run, messages, _ = await runs.get_run_transcript(
                ctx, run_id, skip=total - _MAX_TURNS, limit=_MAX_TURNS
            )
        answers = [message for message in messages if message.role == "assistant"]
        if not answers:
            raise BadRequestError(
                message="This run kept no answer to score",
                details={"run_id": run_id, "status": run.status},
            )
        started, ended = run.started_at, run.ended_at
        latency = (
            None
            if started is None or ended is None
            else int((ended - started).total_seconds() * 1000)
        )
        return ScoredAnswer(
            text=answers[-1].content,
            calls=await self._calls_of(ctx, run.id),
            cost_usd=run.cost_usd,
            latency_ms=latency,
            run_id=run.id,
        )

    async def _calls_of(self, ctx: AuthContext, run_id: UUID) -> tuple[ScoredCall, ...]:
        """A run's tool calls in the order it made them, with the writes it was kept from.

        A call an isolated run held back still has its row in the transcript, so
        it is joined by its call id. Only the run's own calls are read: a
        delegate's calls belong to the delegate's run.
        """
        calls = await conversation_repo.list_tool_calls_for_run(
            self.db, run_id=run_id, organization_id=ctx.organization_id
        )
        held = await intercepted_tool_call_repo.list_for_run(
            self.db, run_id=run_id, organization_id=ctx.organization_id
        )
        blocked = {
            call.tool_call_id for call in held if call.outcome == InterceptionOutcome.BLOCKED
        }
        return tuple(
            ScoredCall(
                tool=call.tool_name,
                args=call.args or {},
                blocked=call.tool_call_id in blocked,
            )
            for call, _ in calls
        )

    async def score_case(
        self,
        ctx: AuthContext,
        *,
        dataset: Dataset,
        case: DatasetCase,
        answer: ScoredAnswer,
        enqueue_review: bool,
        scoring: DatasetScoring | None = None,
        eval_run_id: UUID | None = None,
    ) -> CaseScore:
        """Run every configured scorer on one answer to one case, and keep the score.

        The entry point for an eval run as much as for a single score: `scoring`
        overrides the dataset's configuration, as a suite may. The caller has
        already decided the caller may score this dataset.

        Args:
            enqueue_review: Whether the dataset's review setting may put the
                score in the review queue. A score asked for by hand passes
                `True`; an eval run passes `False` and sends what a person
                chooses with :meth:`request_reviews`.
            eval_run_id: The eval run scoring the answer, if one is.

        Raises:
            NothingToScoreError: No configured scorer has anything to check on
                this case - nothing is kept, and the judge is not called.
        """
        config = scoring or DatasetScoring.model_validate(dataset.scoring)
        evaluation = await self.evaluate(ctx, _case_view(case), answer, config)
        results = evaluation.results
        if not results:
            raise NothingToScoreError(case_id=case.case_id)
        passed = case_passed(results)
        select = config.review.select
        waits = enqueue_review and (select == "all" or (select == "failed" and passed is not True))
        return await case_score_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            dataset_id=dataset.id,
            case_revision_id=case.id,
            case_id=case.case_id,
            run_id=answer.run_id,
            eval_run_id=eval_run_id,
            answer=_kept_answer(answer.text),
            scoring=config.model_dump(mode="json", by_alias=True),
            results=[
                result.model_copy(
                    update={
                        "reason": _redact(result.reason),
                        "unverified_quotes": [
                            _redact(quote) or quote for quote in result.unverified_quotes
                        ],
                    }
                ).model_dump(mode="json")
                for result in results
            ],
            judge=None if evaluation.judge is None else evaluation.judge.model_dump(mode="json"),
            passed=passed,
            review_state="pending" if waits else "none",
            created_by_user_id=ctx.user_id,
        )

    async def evaluate(
        self, ctx: AuthContext, case: CaseView, answer: ScoredAnswer, scoring: DatasetScoring
    ) -> Evaluation:
        """Every configured scorer's result for one answer, without keeping them."""
        results: list[ScorerResult] = []
        judged = []
        if scoring.checks.enabled:
            defaults = [check.model_dump(by_alias=True) for check in scoring.checks.defaults]
            checked, judged = run_checks(
                [*defaults, *case.checks], answer, required=scoring.checks.required
            )
            results.extend(checked)
        if scoring.trajectory.enabled:
            trajectory = score_trajectory(
                case.expected_tool_calls,
                answer.calls,
                order_mode=case.order_mode,
                required=scoring.trajectory.required,
            )
            if trajectory is not None:
                results.append(trajectory)
        criteria = judge_criteria(case, scoring, judged)
        if not criteria:
            return Evaluation(results)
        judging = await self._judge(ctx, case, answer, criteria, scoring)
        return Evaluation([*results, *judging.results], judging.judge)

    async def _judge(
        self,
        ctx: AuthContext,
        case: CaseView,
        answer: ScoredAnswer,
        criteria: list[JudgeCriterion],
        scoring: DatasetScoring,
    ) -> Evaluation:
        try:
            result = await self.judge.run(
                ctx,
                key=JUDGE.key,
                prompt=judge_prompt(case, answer, criteria, scale_max=scoring.judge.scale_max),
                output_type=JudgeVerdict,
                agent_id=scoring.judge.agent_id,
                model_profile_id=scoring.judge.model_profile_id,
            )
        except AiAssistanceDisabledError as exc:
            skipped = not_graded(
                criteria, skipped=True, code="ai_assistance_off", reason=exc.message
            )
            return Evaluation(skipped)
        except SystemAgentUnavailableError as exc:
            skipped = not_graded(
                criteria, skipped=True, code=f"judge_{exc.reason}", reason=exc.message
            )
            return Evaluation(skipped)
        except SystemAgentRunError as exc:
            budget = exc.status == RunStatus.BUDGET_EXCEEDED.value
            failed = not_graded(
                criteria,
                skipped=budget,
                code="judge_budget" if budget else "judge_run_failed",
                reason=exc.message,
                run_id=exc.run_id,
            )
            return Evaluation(failed)
        except SystemAgentOutputError as exc:
            failed = not_graded(
                criteria,
                skipped=False,
                code="judge_output_invalid",
                reason=exc.message,
                run_id=exc.run_id,
            )
            return Evaluation(failed)
        grades = graded(
            criteria,
            result.output,
            answer=answer.text,
            scale_max=scoring.judge.scale_max,
            pass_at=scoring.judge.pass_at,
            run_id=result.run.id,
        )
        return Evaluation(grades, await self._pin(ctx, result.run, criteria, scoring))

    async def _pin(
        self,
        ctx: AuthContext,
        run: AgentRun,
        criteria: list[JudgeCriterion],
        scoring: DatasetScoring,
    ) -> JudgePin:
        """The judge that graded: its version, the model it ran on, and what it was asked."""
        version = (
            None
            if run.agent_version_id is None
            else await agent_repo.get_version(
                self.db, run.agent_version_id, organization_id=ctx.organization_id
            )
        )
        published = None if version is None else version.spec.get("model_profile_id")
        return JudgePin(
            agent_id=run.agent_id,
            model_profile_id=scoring.judge.model_profile_id or published,
            agent_version_id=run.agent_version_id,
            spec_version=None if version is None else version.version,
            rubric_hash=rubric_hash(criteria, scale_max=scoring.judge.scale_max),
        )

    async def list_scores(
        self,
        ctx: AuthContext,
        dataset_id: UUID,
        *,
        case_id: UUID | None = None,
        pending: bool = False,
        outcome: ScoreOutcome | None = None,
        agent_id: UUID | None = None,
        eval_run_id: UUID | None = None,
        tag: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> CaseScoreList:
        """A dataset's scores, newest first, narrowed as the filters say. Needs
        `datasets:view` on it."""
        await self.datasets.get(ctx, dataset_id)
        items, total = await case_score_repo.list_for_dataset(
            self.db,
            organization_id=ctx.organization_id,
            dataset_id=dataset_id,
            case_id=case_id,
            review_state="pending" if pending else None,
            outcome=outcome,
            agent_id=agent_id,
            eval_run_id=eval_run_id,
            tag=tag,
            skip=skip,
            limit=limit,
        )
        return CaseScoreList(items=await self._reads(ctx, items), total=total)

    async def review_queue(
        self, ctx: AuthContext, *, skip: int = 0, limit: int = 50
    ) -> ReviewQueue:
        """Scores waiting for a person, across every dataset the caller may see."""
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=DATASET, perm=Perm.DATASETS_VIEW
        )
        see_all, shared_ids = shared is None, [] if shared is None else shared
        items, total = await case_score_repo.list_pending(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=see_all,
            shared_ids=shared_ids,
            skip=skip,
            limit=limit,
        )
        counts = await case_score_repo.pending_counts(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=see_all,
            shared_ids=shared_ids,
        )
        reads = await self._reads(ctx, [score for score, _ in items])
        return ReviewQueue(
            items=[
                PendingScore(**read.model_dump(), dataset_name=name)
                for read, (_, name) in zip(reads, items, strict=True)
            ],
            total=total,
            datasets=_by_dataset(counts),
        )

    async def _reads(self, ctx: AuthContext, scores: list[CaseScore]) -> list[CaseScoreRead]:
        """Scores as read, each with the name and version number of the agent that answered."""
        reads = [CaseScoreRead.model_validate(score) for score in scores]
        agents = await agent_repo.get_many(
            self.db,
            list({read.agent_id for read in reads if read.agent_id is not None}),
            organization_id=ctx.organization_id,
        )
        versions = await agent_repo.get_versions_by_ids(
            self.db,
            list({read.agent_version_id for read in reads if read.agent_version_id is not None}),
            organization_id=ctx.organization_id,
        )
        named = []
        for read in reads:
            agent = None if read.agent_id is None else agents.get(read.agent_id)
            version = None if read.agent_version_id is None else versions.get(read.agent_version_id)
            named.append(
                read.model_copy(
                    update={
                        "agent_name": None if agent is None else agent.name,
                        "agent_version": None if version is None else version.version,
                    }
                )
            )
        return named

    async def _score(self, ctx: AuthContext, dataset_id: UUID, score_id: UUID) -> CaseScore:
        await self.datasets.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        score = await case_score_repo.get(
            self.db, score_id, organization_id=ctx.organization_id, dataset_id=dataset_id
        )
        if score is None:
            raise NotFoundError(
                message="This dataset has no such score",
                details={"dataset_id": dataset_id, "score_id": score_id},
            )
        return score

    async def set_verdict(
        self, ctx: AuthContext, dataset_id: UUID, score_id: UUID, data: CaseVerdict
    ) -> CaseScoreRead:
        """Record a person's verdict on a score, or withdraw it. Needs `datasets:edit`.

        Only the verdict's own columns change: the scorers' results, the judge's
        grades among them, stay as they were written.
        """
        score = await self._score(ctx, dataset_id, score_id)
        decided = data.passed is not None
        score = await case_score_repo.update(
            self.db,
            score=score,
            update_data={
                "human_passed": data.passed,
                "human_note": _redact(data.note) if decided else None,
                "reviewed_by_user_id": ctx.user_id if decided else None,
                "reviewed_at": datetime.now(UTC) if decided else None,
                "review_state": "done" if decided else "pending",
            },
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="case_score.verdict",
            target_type="case_score",
            target_id=str(score.id),
            details={"dataset_id": str(dataset_id), "passed": data.passed},
        )
        return (await self._reads(ctx, [score]))[0]

    async def request_review(
        self, ctx: AuthContext, dataset_id: UUID, score_id: UUID
    ) -> CaseScoreRead:
        """Put a score in the review queue. Needs `datasets:edit`; a decided one stays decided."""
        score = await self._score(ctx, dataset_id, score_id)
        if score.review_state == "none":
            score = await case_score_repo.update(
                self.db, score=score, update_data={"review_state": "pending"}
            )
        return (await self._reads(ctx, [score]))[0]

    async def request_reviews(
        self, ctx: AuthContext, dataset_id: UUID, data: ReviewRequest
    ) -> ReviewRequested:
        """Put several of a dataset's scores in the review queue. Needs `datasets:edit`.

        All of them or none: one that is not a score of this dataset refuses the
        request. A score already waiting, or already decided, is left as it is.

        Raises:
            NotFoundError: The dataset is not one the caller may edit, or it has
                no score with one of the ids.
        """
        wanted = await self._scores_of(ctx, dataset_id, data)
        queued = await case_score_repo.queue_for_review(
            self.db, wanted, organization_id=ctx.organization_id, dataset_id=dataset_id
        )
        return ReviewRequested(queued=queued, already=len(wanted) - queued)

    async def withdraw_reviews(
        self, ctx: AuthContext, dataset_id: UUID, data: ReviewRequest
    ) -> ReviewWithdrawn:
        """Take several of a dataset's scores out of the review queue, undecided.

        Needs `datasets:edit`. All of them or none, as when sending them; a score
        somebody already decided keeps its decision, and one not waiting is left
        as it is.

        Raises:
            NotFoundError: The dataset is not one the caller may edit, or it has
                no score with one of the ids.
        """
        wanted = await self._scores_of(ctx, dataset_id, data)
        removed = await case_score_repo.dequeue(
            self.db, wanted, organization_id=ctx.organization_id, dataset_id=dataset_id
        )
        return ReviewWithdrawn(removed=removed, kept=len(wanted) - removed)

    async def _scores_of(
        self, ctx: AuthContext, dataset_id: UUID, data: ReviewRequest
    ) -> list[UUID]:
        await self.datasets.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        wanted = list(dict.fromkeys(data.score_ids))
        found = await case_score_repo.existing_ids(
            self.db, wanted, organization_id=ctx.organization_id, dataset_id=dataset_id
        )
        missing = [score_id for score_id in wanted if score_id not in found]
        if missing:
            raise NotFoundError(
                message="This dataset has no score with some of these ids",
                details={"dataset_id": dataset_id, "missing": missing},
            )
        return wanted

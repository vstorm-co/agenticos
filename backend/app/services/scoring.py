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

from datetime import UTC, datetime
from uuid import UUID

from pydantic_ai_harness.guardrails.detectors import redact_secrets
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.system_agents import JUDGE
from app.core.audit import record_audit
from app.core.exceptions import (
    AiAssistanceDisabledError,
    BadRequestError,
    NotFoundError,
    SystemAgentOutputError,
    SystemAgentRunError,
    SystemAgentUnavailableError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_run import RunStatus
from app.db.models.case_score import CaseScore
from app.db.models.dataset import Dataset, DatasetCase
from app.db.models.intercepted_tool_call import InterceptionOutcome
from app.repositories import (
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
    ScorerResult,
)
from app.services.access import DATASET, visible_resource_ids
from app.services.agent_runner import AgentRunnerService
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
    run_checks,
    score_trajectory,
)
from app.services.system_agent_runner import SystemAgentRunner

_MAX_TURNS = 100


def _redact(text: str | None) -> str | None:
    if not text:
        return text
    verdict = redact_secrets(text)
    if verdict.action == "replace" and isinstance(verdict.replacement, str):
        return verdict.replacement
    return text


def _score_read(score: CaseScore) -> CaseScoreRead:
    return CaseScoreRead.model_validate(score)


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
            BadRequestError: The judge's model is not one of the organization's.
        """
        dataset = await self.datasets.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
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
            BadRequestError: The run kept no transcript to score.
        """
        dataset = await self.datasets.get(ctx, dataset_id, perm=Perm.DATASETS_RUN)
        case = await self.datasets.case_at(ctx, dataset, case_id, version=data.version)
        answer = await self.answer_of(ctx, data.run_id)
        return _score_read(await self.score_case(ctx, dataset=dataset, case=case, answer=answer))

    async def answer_of(self, ctx: AuthContext, run_id: UUID) -> ScoredAnswer:
        """What a recorded run answered and called, read from its transcript.

        Raises:
            NotFoundError: The run is not in the caller's organization.
            AuthorizationError: The caller does not hold `runs:view`.
            BadRequestError: The run has no answer to score - it kept no
                transcript, or never answered.
        """
        run, messages, _ = await AgentRunnerService(self.db).get_run_transcript(
            ctx, run_id, limit=_MAX_TURNS
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
        scoring: DatasetScoring | None = None,
    ) -> CaseScore:
        """Run every configured scorer on one answer to one case, and keep the score.

        The entry point for an eval run as much as for a single score: `scoring`
        overrides the dataset's configuration, as a suite may. The caller has
        already decided the caller may score this dataset.
        """
        config = scoring or DatasetScoring.model_validate(dataset.scoring)
        results = await self.evaluate(ctx, _case_view(case), answer, config)
        passed = case_passed(results)
        select = config.review.select
        waits = select == "all" or (select == "failed" and passed is not True)
        return await case_score_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            dataset_id=dataset.id,
            case_revision_id=case.id,
            case_id=case.case_id,
            run_id=answer.run_id,
            scoring=config.model_dump(mode="json", by_alias=True),
            results=[
                result.model_copy(update={"reason": _redact(result.reason)}).model_dump(mode="json")
                for result in results
            ],
            passed=passed,
            review_state="pending" if waits else "none",
            created_by_user_id=ctx.user_id,
        )

    async def evaluate(
        self, ctx: AuthContext, case: CaseView, answer: ScoredAnswer, scoring: DatasetScoring
    ) -> list[ScorerResult]:
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
        if criteria:
            results.extend(await self._judge(ctx, case, answer, criteria, scoring))
        return results

    async def _judge(
        self,
        ctx: AuthContext,
        case: CaseView,
        answer: ScoredAnswer,
        criteria: list[JudgeCriterion],
        scoring: DatasetScoring,
    ) -> list[ScorerResult]:
        try:
            result = await self.judge.run(
                ctx,
                key=JUDGE.key,
                prompt=judge_prompt(case, answer, criteria, scale_max=scoring.judge.scale_max),
                output_type=JudgeVerdict,
                model_profile_id=scoring.judge.model_profile_id,
            )
        except AiAssistanceDisabledError as exc:
            return not_graded(criteria, skipped=True, code="ai_assistance_off", reason=exc.message)
        except SystemAgentUnavailableError as exc:
            return not_graded(
                criteria, skipped=True, code=f"judge_{exc.reason}", reason=exc.message
            )
        except SystemAgentRunError as exc:
            budget = exc.status == RunStatus.BUDGET_EXCEEDED.value
            return not_graded(
                criteria,
                skipped=budget,
                code="judge_budget" if budget else "judge_run_failed",
                reason=exc.message,
                run_id=exc.run_id,
            )
        except SystemAgentOutputError as exc:
            return not_graded(
                criteria,
                skipped=False,
                code="judge_output_invalid",
                reason=exc.message,
                run_id=exc.run_id,
            )
        return graded(
            criteria,
            result.output,
            answer=answer.text,
            scale_max=scoring.judge.scale_max,
            pass_at=scoring.judge.pass_at,
            run_id=result.run.id,
        )

    async def list_scores(
        self,
        ctx: AuthContext,
        dataset_id: UUID,
        *,
        case_id: UUID | None = None,
        pending: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> CaseScoreList:
        """A dataset's scores, newest first. Needs `datasets:view` on it."""
        await self.datasets.get(ctx, dataset_id)
        items, total = await case_score_repo.list_for_dataset(
            self.db,
            organization_id=ctx.organization_id,
            dataset_id=dataset_id,
            case_id=case_id,
            review_state="pending" if pending else None,
            skip=skip,
            limit=limit,
        )
        return CaseScoreList(items=[_score_read(item) for item in items], total=total)

    async def review_queue(
        self, ctx: AuthContext, *, skip: int = 0, limit: int = 50
    ) -> CaseScoreList:
        """Scores waiting for a person, across every dataset the caller may see."""
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=DATASET, perm=Perm.DATASETS_VIEW
        )
        items, total = await case_score_repo.list_pending(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=[] if shared is None else shared,
            skip=skip,
            limit=limit,
        )
        return CaseScoreList(items=[_score_read(item) for item in items], total=total)

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
        return _score_read(score)

    async def request_review(
        self, ctx: AuthContext, dataset_id: UUID, score_id: UUID
    ) -> CaseScoreRead:
        """Put a score in the review queue. Needs `datasets:edit`; a decided one stays decided."""
        score = await self._score(ctx, dataset_id, score_id)
        if score.review_state == "none":
            score = await case_score_repo.update(
                self.db, score=score, update_data={"review_state": "pending"}
            )
        return _score_read(score)

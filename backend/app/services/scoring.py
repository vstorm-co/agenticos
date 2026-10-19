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
a case whose required judge was skipped or errored is left unscored rather than
passed or failed - and can be graded again, on the same answer, once the cause is
fixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
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
from app.core.permissions import AuthContext, Perm, Scope
from app.db.locks import LockScope, hold_subject
from app.db.models.agent import AgentKind
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.case_score import CaseScore
from app.db.models.dataset import Dataset, DatasetCase
from app.db.models.intercepted_tool_call import InterceptionOutcome
from app.db.models.resource_grant import Visibility
from app.repositories import (
    agent_repo,
    agent_run_repo,
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
    JudgeAgreement,
    JudgeCreate,
    JudgePin,
    JudgeTemplate,
    PendingDataset,
    PendingScore,
    Rescored,
    RescoreRequest,
    ReviewQueue,
    ReviewRequest,
    ReviewRequested,
    ReviewWithdrawn,
    RubricCriterion,
    ScoreOutcome,
    ScorerResult,
)
from app.services.access import AGENT, DATASET, resolve_access, visible_resource_ids
from app.services.agent_runner import AgentRunnerService
from app.services.ai_assistance import AiAssistanceService
from app.services.dataset import DatasetService
from app.services.scorers import (
    JUDGE_PROMPT_VERSION,
    CaseView,
    JudgeCriterion,
    JudgeVerdict,
    ScoredAnswer,
    ScoredCall,
    case_passed,
    graded,
    judge_criteria,
    judge_prompt,
    judge_verdict,
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
# Enough of an unreadable judge answer to see what went wrong. Kept on the score, behind
# the dataset's access - never on the run, which every reader of runs can open.
_SAID = 2_000


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


def _rank(score: CaseScore) -> tuple[bool, datetime]:
    """Which of a case's scores the review queue keeps: a graded one, then the newest."""
    return score.passed is not None, score.created_at


def _ungraded(score: CaseScore) -> bool:
    """Whether some scorer on a score reached no verdict, and could be asked again."""
    return any(result.get("status") in ("skipped", "error") for result in score.results)


def _kept_answer(text: str) -> str | None:
    clipped = text if len(text) <= _MAX_ANSWER else f"{text[:_MAX_ANSWER]}…"
    return _redact(clipped)


# What a new judge grades until the dataset says otherwise - general enough to
# fit any dataset, so a person replaces it rather than keeps it.
STARTING_CRITERION = RubricCriterion(
    name="answers the question",
    description=(
        "Quote what in the answer settles the question, then say whether it is right by "
        "the reference answer or what you were told, and what the question asked that "
        "the answer leaves out."
    ),
)


def _judge_instructions(dataset: Dataset) -> str:
    """The default judge's prompt, which holds the rules of grading, and what the dataset is."""
    about = f" It is about: {dataset.description}" if dataset.description else ""
    return (
        f"{JUDGE.instructions}\n\nThe answers you grade are to the test questions of the "
        f'dataset "{dataset.name}".{about}'
    )


def _with_knowledge(instructions: str, knowledge: str | None) -> str:
    if knowledge is None or not knowledge.strip():
        return instructions
    return f"{instructions}\n\nWhat you must know to grade:\n{knowledge.strip()}"


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
        note=case.note,
    )


def _kept_results(results: list[ScorerResult]) -> list[dict[str, Any]]:
    """Results as a score keeps them: the judge's words with any secret redacted."""
    return [
        result.model_copy(
            update={
                "reason": _redact(result.reason),
                "rule": _redact(result.rule),
                "judge_said": _redact(result.judge_said),
                "unverified_quotes": [
                    _redact(quote) or quote for quote in result.unverified_quotes
                ],
            }
        ).model_dump(mode="json")
        for result in results
    ]


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
                or the judge or the reference comparison is turned on while AI
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
        an agent; it is as widely visible as the dataset, and stays a draft for a
        caller who may not publish it. Its prompt is the one edited from :meth:`judge_template`, or
        that template when none is sent. The rubric stays the dataset's; only
        which judge grades changes, so scores graded before keep the judge they
        were graded by. What the judge must know is added to its instructions
        under its own heading.

        Where AI assistance is on, the judge is switched on in the same write, so
        the dataset grades from the next score: on its rubric, or on one starting
        criterion when it has none, and on the reference answer as well once a
        case has one. Where it is off, only the judge picked changes.

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
        instructions = data.instructions or _judge_instructions(dataset)
        judge = await SystemAgentService(self.db).create_judge(
            ctx,
            name=data.name,
            description=f"Grades the cases of the dataset '{dataset.name}'.",
            instructions=_with_knowledge(instructions, data.knowledge),
            visibility=Visibility(dataset.visibility),
            model_profile_id=data.model_profile_id,
        )
        scoring = DatasetScoring.model_validate(dataset.scoring)
        scoring.judge.agent_id = judge.id
        if await AiAssistanceService(self.db).is_enabled(organization_id=ctx.organization_id):
            scoring.judge.enabled = True
            if not scoring.judge.criteria:
                scoring.judge.criteria = [STARTING_CRITERION]
            stats = await dataset_repo.case_stats(
                self.db, [dataset.id], organization_id=ctx.organization_id
            )
            if dataset.id in stats and stats[dataset.id].with_reference > 0:
                scoring.reference.enabled = True
        await dataset_repo.update(
            self.db,
            dataset=dataset,
            update_data={"scoring": scoring.model_dump(mode="json", by_alias=True)},
        )
        return await self.datasets.read(ctx, dataset_id)

    async def judge_template(self, ctx: AuthContext, dataset_id: UUID) -> JudgeTemplate:
        """The prompt a judge made for this dataset starts from. Needs `datasets:edit` on it.

        Raises:
            NotFoundError: The dataset is not one the caller may edit.
        """
        dataset = await self.datasets.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        return JudgeTemplate(instructions=_judge_instructions(dataset))

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
            results=_kept_results(results),
            judge=None if evaluation.judge is None else evaluation.judge.model_dump(mode="json"),
            passed=passed,
            review_state="pending" if waits else "none",
            created_by_user_id=ctx.user_id,
        )

    async def rescore(self, ctx: AuthContext, dataset_id: UUID, data: RescoreRequest) -> Rescored:
        """Grade again the scores that reached no verdict, on the answers they graded.

        Needs `datasets:run` on the dataset, as scoring does. The agent is not
        run again: each score is graded anew on the same answer, the same case
        revision and the configuration it was graded with, and keeps its id, its
        eval run and any person's verdict. A score every scorer reached a verdict
        on is kept as it is. Every answer is read, and the judge checked, before
        any is graded, so a refusal leaves every score as it was.

        Raises:
            NotFoundError: The dataset is not one the caller may run, or it has
                no score with one of the ids.
            AuthorizationError: An answer is read from its run, and the caller
                may not read runs.
            AiAssistanceDisabledError: AI assistance is still off.
            SystemAgentUnavailableError: The judge still cannot run, and why.
            BadRequestError: A score's answer can no longer be read, or an eval
                run's judge has been published anew since it failed.
        """
        dataset = await self.datasets.get(ctx, dataset_id, perm=Perm.DATASETS_RUN)
        wanted = list(dict.fromkeys(data.score_ids))
        scores = await case_score_repo.get_many(
            self.db, wanted, organization_id=ctx.organization_id, dataset_id=dataset.id
        )
        missing = [score_id for score_id in wanted if score_id not in scores]
        if missing:
            raise NotFoundError(
                message="This dataset has no score with some of these ids",
                details={"dataset_id": dataset_id, "missing": missing},
            )
        stale = [scores[score_id] for score_id in wanted if _ungraded(scores[score_id])]
        kept = [score_id for score_id in wanted if not _ungraded(scores[score_id])]
        for score in stale:
            await self._judge_unchanged(ctx, score)
        answers = [await self.answer_for(ctx, score) for score in stale]
        rescored = [
            await self._rescore(ctx, score, answer)
            for score, answer in zip(stale, answers, strict=True)
        ]
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="case_score.rescored",
            target_type="dataset",
            target_id=str(dataset_id),
            details={"score_ids": [str(score.id) for score in rescored]},
        )
        return Rescored(rescored=await self._reads(ctx, rescored), kept=kept)

    async def _judge_unchanged(self, ctx: AuthContext, score: CaseScore) -> None:
        """Refuse to grade a score again when its judge cannot run, or an eval run's has changed.

        The cause a judge was skipped for - AI assistance off, the judge gone or
        unpublished - is refused as it stands rather than recorded again. A judge
        published anew since its run failed, or a judge prompt changed since the
        score was pinned, would grade with other instructions, so a score of an
        eval run would no longer compare with the rest of it. A judge that ran
        and left no pin was asked from a prompt nothing recorded, and is refused
        the same way. A score graded on its own has no run to compare with, and
        is graded by the version published now, which its pin then names.

        Raises:
            AiAssistanceDisabledError: AI assistance is off.
            SystemAgentUnavailableError: The judge cannot run, and why.
            BadRequestError: An eval run's judge has a newer version, or a newer
                prompt, than the one that graded it.
        """
        judged = [r for r in score.results if r.get("scorer") in ("judge", "reference")]
        if not judged:
            return
        config = DatasetScoring.model_validate(score.scoring)
        judge = await self.judge.require_runnable(
            ctx, key=JUDGE.key, agent_id=config.judge.agent_id
        )
        if score.eval_run_id is None:
            return
        asked = (score.judge or {}).get("prompt_version")
        ran = any(r.get("judge_run_id") for r in judged)
        if (score.judge is not None or ran) and asked != JUDGE_PROMPT_VERSION:
            raise BadRequestError(
                message=(
                    "The judge has been asked differently since it graded this answer, so a new "
                    "grade would not compare with the rest. Run the eval again."
                ),
                details={"score_id": score.id, "prompt_version": asked},
            )
        for run_id in {r["judge_run_id"] for r in judged if r.get("judge_run_id")}:
            run = await agent_run_repo.get_run(
                self.db, UUID(run_id), organization_id=ctx.organization_id
            )
            if run is not None and run.agent_version_id not in (None, judge.current_version_id):
                raise BadRequestError(
                    message=(
                        f"'{judge.name}' has been published anew since it failed on this answer, "
                        "so a new grade would not compare with the rest. Run the eval again."
                    ),
                    details={"score_id": score.id, "judge_version_id": run.agent_version_id},
                )

    async def answer_for(self, ctx: AuthContext, score: CaseScore) -> ScoredAnswer:
        """The answer a score graded, read again in full from where it is kept.

        Raises:
            BadRequestError: The score names no run, or its run kept no answer.
        """
        if score.run_id is None:
            raise BadRequestError(
                message="This score names no run, so its answer cannot be graded again",
                details={"score_id": score.id},
            )
        return await self.answer_of(ctx, score.run_id)

    async def _rescore(self, ctx: AuthContext, score: CaseScore, answer: ScoredAnswer) -> CaseScore:
        config = DatasetScoring.model_validate(score.scoring)
        evaluation = await self.evaluate(ctx, _case_view(score.case_revision), answer, config)
        passed = case_passed(evaluation.results)
        # A score waiting because nothing graded it, now graded a pass, has
        # nothing left for a person to decide; one somebody decided stays decided.
        settled = passed is True and score.review_state == "pending" and score.human_passed is None
        return await case_score_repo.update(
            self.db,
            score=score,
            update_data={
                "results": _kept_results(evaluation.results),
                "passed": passed,
                "judge": (
                    None if evaluation.judge is None else evaluation.judge.model_dump(mode="json")
                ),
                "review_state": "none" if settled else score.review_state,
            },
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
            return Evaluation(failed, await self._failed_pin(ctx, exc.run_id, criteria, scoring))
        except SystemAgentOutputError as exc:
            said = " ".join(exc.answer.split())
            failed = not_graded(
                criteria,
                skipped=False,
                code="judge_output_invalid",
                reason=exc.message,
                run_id=exc.run_id,
                said=said if len(said) <= _SAID else f"{said[:_SAID]}…",
            )
            return Evaluation(failed, await self._failed_pin(ctx, exc.run_id, criteria, scoring))
        grades = graded(
            criteria,
            result.output,
            answer=answer.text,
            scale_max=scoring.judge.scale_max,
            pass_at=scoring.judge.pass_at,
            run_id=result.run.id,
            counter_example=case.counter_example,
        )
        return Evaluation(grades, await self._pin(ctx, result.run, criteria, scoring))

    async def _failed_pin(
        self,
        ctx: AuthContext,
        run_id: UUID,
        criteria: list[JudgeCriterion],
        scoring: DatasetScoring,
    ) -> JudgePin | None:
        """The judge that ran and failed, pinned as one that graded is.

        A judge that failed still answered to a version and a prompt; grading
        the answer again from other ones would leave its eval run graded two ways.
        """
        run = await agent_run_repo.get_run(self.db, run_id, organization_id=ctx.organization_id)
        return None if run is None else await self._pin(ctx, run, criteria, scoring)

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
            model_profile_id=published,
            agent_version_id=run.agent_version_id,
            spec_version=None if version is None else version.version,
            rubric_hash=rubric_hash(criteria, scale_max=scoring.judge.scale_max),
            prompt_version=JUDGE_PROMPT_VERSION,
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
        judge_id: UUID | None = None,
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
            judge_id=judge_id,
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

    async def judge_agreement(self, ctx: AuthContext, judge_id: UUID) -> JudgeAgreement:
        """How often a person's decision agreed with the judge's own verdict.

        The judge's verdict is read from its results alone - the rubric and the
        reference answer - so a check failing beside it is not counted against
        it. Only scores the judge graded to a verdict count, once somebody
        decided them, and only in the datasets the caller may see.
        """
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=DATASET, perm=Perm.DATASETS_VIEW
        )
        rows = await case_score_repo.decided_for_judge(
            self.db,
            organization_id=ctx.organization_id,
            judge_id=judge_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=[] if shared is None else shared,
        )
        pairs = [
            (judge_verdict([ScorerResult.model_validate(r) for r in results]), human)
            for results, human in rows
        ]
        judged = [(verdict, human) for verdict, human in pairs if verdict is not None]
        return JudgeAgreement(
            agreed=sum(verdict == human for verdict, human in judged), decided=len(judged)
        )

    async def _reads(self, ctx: AuthContext, scores: list[CaseScore]) -> list[CaseScoreRead]:
        """Scores as read, each with the name and version number of the agent that
        answered, and the name of the model the judge graded on.

        A reader who may not view the agent that answered reads the outcome and
        the case, not the answer: it, and every result's reason, quotes and what
        the judge said, are left out, and `answer_hidden` says so. An answer
        whose run or agent is gone is read only by somebody who may view every
        agent, since nothing is left to check the reader against.
        """
        reads = [CaseScoreRead.model_validate(score) for score in scores]
        models = await credential_repo.get_profiles_by_ids(
            self.db,
            list(
                {
                    read.judge.model_profile_id
                    for read in reads
                    if read.judge is not None and read.judge.model_profile_id is not None
                }
            ),
            organization_id=ctx.organization_id,
        )
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
        hidden = {
            agent.id
            for agent in agents.values()
            if not await resolve_access(self.db, ctx, agent, Perm.AGENTS_VIEW, resource_type=AGENT)
        }
        sees_every_agent = ctx.scope_for(Perm.AGENTS_VIEW) >= Scope.ALL
        named = []
        for read in reads:
            agent = None if read.agent_id is None else agents.get(read.agent_id)
            unchecked = agent is None and read.answer is not None and not sees_every_agent
            if unchecked or (agent is not None and agent.id in hidden):
                read = _without_answer(read)
            version = None if read.agent_version_id is None else versions.get(read.agent_version_id)
            judged_on = (
                None
                if read.judge is None or read.judge.model_profile_id is None
                else models.get(read.judge.model_profile_id)
            )
            named.append(
                read.model_copy(
                    update={
                        "agent_name": None if agent is None else agent.name,
                        "agent_version": None if version is None else version.version,
                        "judge_model": None if judged_on is None else judged_on.label,
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
        """Put a score in the review queue. Needs `datasets:edit`.

        It replaces an older score of its case waiting there, as
        `route_to_review` says; a decided one stays decided.
        """
        score = await self._score(ctx, dataset_id, score_id)
        await self.route_to_review(ctx, dataset_id=dataset_id, score_ids=[score.id])
        return (await self._reads(ctx, [score]))[0]

    async def request_reviews(
        self, ctx: AuthContext, dataset_id: UUID, data: ReviewRequest
    ) -> ReviewRequested:
        """Put several of a dataset's scores in the review queue. Needs `datasets:edit`.

        All of them or none: one that is not a score of this dataset refuses the
        request. Each case gets one score in the queue, as `route_to_review` says.

        Raises:
            NotFoundError: The dataset is not one the caller may edit, or it has
                no score with one of the ids.
        """
        wanted = await self._scores_of(ctx, dataset_id, data)
        return await self.route_to_review(ctx, dataset_id=dataset_id, score_ids=wanted)

    async def route_to_review(
        self, ctx: AuthContext, *, dataset_id: UUID, score_ids: list[UUID]
    ) -> ReviewRequested:
        """Send scores to the review queue, one per case, the newest replacing an older one.

        For the eval run's own worker, which has already decided what deserves a
        person - its confirmed regressions and the scores its judge failed on -
        and for the routes, which check `datasets:edit` first; no permission is
        checked here. A graded score - a regression, or a fail sent by hand -
        outranks one no scorer reached a verdict on, such as a judge's error, so
        a judge failing on a case never pushes its regression out of the queue.
        Of the scores sent for one case the highest ranked is queued, the newest
        of those, and the first given among those scored at the same moment. A
        waiting score of the case ranked no higher and scored earlier leaves the
        queue undecided and stays a score; one ranked higher, or scored as late
        or later, keeps its place, and the one sent is not queued. A decided
        score is never touched, and one already waiting or decided is not queued
        again. Ids of another dataset are ignored.
        """
        scores = await case_score_repo.get_many(
            self.db, score_ids, organization_id=ctx.organization_id, dataset_id=dataset_id
        )
        newest: dict[UUID, CaseScore] = {}
        for score_id in dict.fromkeys(score_ids):
            score = scores.get(score_id)
            if score is None or score.review_state != "none":
                continue
            held = newest.get(score.case_id)
            if held is None or _rank(score) > _rank(held):
                newest[score.case_id] = score
        for case_id in sorted(newest):
            await hold_subject(self.db, LockScope.REVIEW_PER_CASE, case_id)
        waiting = await case_score_repo.waiting_for_cases(
            self.db, list(newest), organization_id=ctx.organization_id, dataset_id=dataset_id
        )
        chosen, older = [], []
        for case_id, score in newest.items():
            others = [other for other in waiting if other.case_id == case_id]
            if any(_rank(other) >= _rank(score) for other in others):
                continue
            chosen.append(score.id)
            older.extend(other.id for other in others)
        replaced = await case_score_repo.dequeue(
            self.db, older, organization_id=ctx.organization_id, dataset_id=dataset_id
        )
        queued = await case_score_repo.queue_for_review(
            self.db, chosen, organization_id=ctx.organization_id, dataset_id=dataset_id
        )
        return ReviewRequested(
            queued=queued, replaced=replaced, already=len(set(score_ids)) - queued
        )

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


def _without_answer(read: CaseScoreRead) -> CaseScoreRead:
    """A score with the answer, and everything that can repeat it, left out."""
    return read.model_copy(
        update={
            "answer": None,
            "answer_hidden": True,
            "results": [
                result.model_copy(
                    update={"reason": "", "unverified_quotes": [], "judge_said": None}
                )
                for result in read.results
            ],
        }
    )

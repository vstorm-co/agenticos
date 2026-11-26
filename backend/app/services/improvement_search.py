"""Search many variants of an agent's instructions within one Improve attempt.

A search attempt does not ask the improver for one change. It asks for a few
complete rewrites of the instructions at a time, answers the same handful of the
attempt's training questions with each, grades the answers, and asks for the
next rewrites from the best so far and the questions they still fail. Only
training questions are read: the questions the attempt is measured on stay
unseen until its check. When the search ends, the best variant that beat the
starting instructions goes through Changes, the check and Result like any other
attempt's candidate, and a person still decides every step after it.

The work runs as `SEARCH_IMPROVEMENT` jobs of one unit each - a round of
proposals or one variant's scoring - so no job holds an eval worker for long and
a lost job is picked up where it left off. The session's own step starts the
search, keeps a job queued, and hands the winner on once the search says it
ended; nothing here moves the session.

A session's search runs one unit at a time - one queued job per session, one
running per organization - and each unit is priced against what the search has
spent so far before it starts. A unit starts only while its estimate fits what is
left of the search's budget and of the session's, and each answer is capped at
twice its share of that estimate, so a search goes over its budget by at most the
one variant it was scoring.
"""

import asyncio
import difflib
import hashlib
import logging
import re
from collections.abc import Callable, Collection, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import price_request
from app.agents.isolation import RunIsolation
from app.agents.spec import AgentSpec
from app.agents.system_agents import IMPROVER
from app.core.config import settings
from app.core.exceptions import AppException, AuthenticationError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentStatus
from app.db.models.agent_run import RunStatus, RunSurface
from app.db.models.authoring import HunkKind, HunkOrigin
from app.db.models.dataset import DatasetCase
from app.db.models.improvement import (
    ImprovementIteration,
    ImprovementMode,
    ImprovementRun,
    ImprovementSearchVariant,
    ImprovementStage,
    ImprovementStatus,
    SearchProgress,
    SearchSettings,
    SearchVariantStatus,
    VariantFailure,
)
from app.db.models.intercepted_tool_call import InterceptionOutcome
from app.db.session import get_worker_db_context
from app.repositories import (
    agent_repo,
    authoring_repo,
    dataset_repo,
    improvement_repo,
    intercepted_tool_call_repo,
)
from app.schemas.dataset_helpers import DatasetHelper
from app.schemas.eval_run import EvalRunRequest
from app.schemas.improvement import SearchOptions, SearchVariantRead, VariantSearchRead
from app.schemas.scoring import DatasetScoring, ScorerResult
from app.services.agent_registry import UnpublishedCandidate
from app.services.agent_runner import AgentRunnerService
from app.services.api_key import job_context
from app.services.background_jobs import enqueue
from app.services.eval_run import EvalRunService, scoring_hash, spec_hash
from app.services.eval_run_worker import trajectory
from app.services.improvement_data import split_seed
from app.services.improvement_states import SEARCH_CHOICES
from app.services.message_history import HistoryMessage, build_message_history
from app.services.model_profile import ModelProfileService
from app.services.scorers import CaseView, ScoredAnswer, ScoredCall
from app.services.scoring import ScoringService
from app.services.system_agent_runner import SystemAgentRunner
from app.services.transcript import RecordedToolCall
from app.worker.jobs import (
    ADVANCE_IMPROVEMENT,
    SEARCH_IMPROVEMENT,
    AdvanceImprovement,
    SearchImprovement,
)

logger = logging.getLogger(__name__)

MIN_TRAIN_QUESTIONS = 10
"""Training questions a search needs: fewer and a variant's score is mostly noise."""

CASE_PARALLELISM = 3
"""Answers one variant's scoring asks at once - beside, never inside, the eval slots."""

ANSWER_CAP_FACTOR = 2
"""How far over its share of the estimate one answer may run before it is stopped."""

MAX_SCORING_ATTEMPTS = 2
"""Times a variant's scoring may begin before a variant whose job keeps dying is given up."""

PARENTS = 2
"""Best variants each round of proposals starts from."""

FAILURES_SHOWN = 8
"""Failed training questions shown to the improver per variant it starts from."""

MAX_VARIANT_CHARS = 60_000

_UNANSWERED = "not answered"
_UNGRADED = "not graded"

_PLACEHOLDER = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")

type SearchEnd = Literal[
    "budget", "max_variants", "patience", "proposal", "questions", "no_variant"
]


class InstructionVariant(BaseModel):
    """One complete rewrite of the instructions."""

    instructions: str = Field(min_length=1, max_length=MAX_VARIANT_CHARS)
    rationale: str = Field(default="", max_length=1000)


class InstructionVariants(BaseModel):
    """What one round of proposals answers with."""

    variants: list[InstructionVariant] = Field(min_length=1, max_length=8)


def variant_hash(instructions: str) -> str:
    """The identity of a variant's text, so the same text is never scored twice."""
    return hashlib.sha256(instructions.strip().encode()).hexdigest()


def draw_questions(case_ids: Sequence[UUID], *, size: int, seed: int) -> list[UUID]:
    """The training questions every variant of an attempt is scored on, the same for each.

    Ranked by a hash of the seed and the question, as an attempt's split is, so
    the same attempt always draws the same questions.
    """
    ranked = sorted(
        case_ids, key=lambda case_id: hashlib.sha256(f"{seed}:{case_id}".encode()).hexdigest()
    )
    return sorted(ranked[:size], key=str)


def case_share(results: Sequence[ScorerResult]) -> float | None:
    """The share of a case's required checks its answer passed; `None` when none was graded."""
    graded = [r for r in results if r.required and r.status in ("pass", "fail")]
    if not graded:
        return None
    return sum(1 for r in graded if r.status == "pass") / len(graded)


def keeps_placeholders(seed: str, variant: str) -> bool:
    """Whether a variant names no template variable the instructions it came from did not."""
    return set(_PLACEHOLDER.findall(variant)) <= set(_PLACEHOLDER.findall(seed))


def variant_hunks(base: str, variant: str, *, rationale: str) -> list[dict[str, object]]:
    """The instruction hunks that turn `base` into `variant`, one per changed run of lines.

    Built from a line diff, so each hunk replaces whole lines and a person can
    leave any of them out at Changes like any proposed change. A hunk's context
    stops where its neighbour's change begins, so it anchors whether or not the
    neighbour is applied first.
    """
    old = base.splitlines(keepends=True)
    new = variant.splitlines(keepends=True)
    offsets = [0]
    for line in old:
        offsets.append(offsets[-1] + len(line))
    changed = [
        op
        for op in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes()
        if op[0] != "equal"
    ]
    hunks: list[dict[str, object]] = []
    for index, (_, i1, i2, j1, j2) in enumerate(changed):
        start, end = offsets[i1], offsets[i2]
        floor = offsets[changed[index - 1][2]] if index else 0
        ceiling = offsets[changed[index + 1][1]] if index + 1 < len(changed) else len(base)
        hunks.append(
            {
                "base_start": start,
                "base_end": end,
                "context_before": base[max(floor, start - _CONTEXT_CHARS) : start],
                "context_after": base[end : min(ceiling, end + _CONTEXT_CHARS)],
                "old_text": base[start:end],
                "new_text": "".join(new[j1:j2]),
                "kind": HunkKind.INSTRUCTIONS.value,
                "origin": HunkOrigin.IMPROVE.value,
                "rationale": rationale,
                "evidence": [],
                "evidence_dropped": 0,
            }
        )
    return hunks


def search_left(progress: SearchProgress, *, spent: Decimal, budget: Decimal) -> Decimal:
    """What the search may still start: the least of its own budget's and the session's rest."""
    own = Decimal(progress["settings"]["budget_usd"]) - search_cost(progress, spent=spent)
    return min(own, budget - spent)


def search_cost(progress: SearchProgress, *, spent: Decimal) -> Decimal:
    """What the search itself has spent: the session's spend since it began."""
    return max(Decimal(0), spent - Decimal(progress["spent_before_usd"]))


def winner(
    variants: Sequence[ImprovementSearchVariant], seed_score: float | None
) -> list[ImprovementSearchVariant]:
    """The scored variants that beat the starting instructions, best first.

    Ties go to the shorter text. With no score for the starting instructions
    nothing can be shown to beat them, so there is none.
    """
    if seed_score is None:
        return []
    better = [
        v
        for v in variants
        if v.generation > 0
        and v.status == SearchVariantStatus.SCORED.value
        and v.train_score is not None
        and v.train_score > seed_score
    ]
    return sorted(better, key=lambda v: (-(v.train_score or 0), len(v.instructions), v.created_at))


_CONTEXT_CHARS = 80


@dataclass(frozen=True)
class _Question:
    case_id: UUID
    input: str
    history: list[HistoryMessage]
    view: CaseView


@dataclass(frozen=True)
class _Score:
    ctx: AuthContext
    run_id: UUID
    agent_id: UUID
    iteration_id: UUID
    variant_id: UUID
    spec: AgentSpec
    questions: list[_Question]
    scoring: DatasetScoring
    judge_version_id: UUID | None
    answer_cap: Decimal
    spent_at_claim: Decimal


@dataclass(frozen=True)
class _Propose:
    ctx: AuthContext
    run_id: UUID
    iteration_id: UUID
    generation: int
    count: int
    parent_ids: list[UUID]
    seed: str
    prompt: str
    improver_agent_id: UUID | None
    helper: DatasetHelper


@dataclass
class _Answered:
    """One question's result. A question that could not be answered or graded counts as
    failed, so every variant's score has the same questions behind it; only one that
    requires nothing to pass, or was never asked, is left out (`counted`)."""

    share: float = 0.0
    failed: list[str] = field(default_factory=list)
    budget: bool = False
    counted: bool = True


class ImprovementSearchService:
    """Starts a search attempt, reads its progress and hands on its winner."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def train_questions(
        self,
        *,
        organization_id: UUID,
        dataset_id: UUID,
        dataset_version: int,
        drawn: Collection[UUID] | None,
    ) -> list[DatasetCase]:
        """The pinned questions an attempt learns from, never those it is measured on.

        An attempt that drew its own split learns from its draw (`drawn`); the
        first one learns from the dataset's stored training partition.
        """
        version = await dataset_repo.get_version(
            self.db, dataset_id, dataset_version, organization_id=organization_id
        )
        if version is None:
            return []
        cases = await dataset_repo.list_cases(
            self.db, version.id, organization_id=organization_id, limit=None
        )
        return [
            case
            for case in cases
            if case.anonymised_at is None
            and (case.improvement_partition == "train" if drawn is None else case.case_id in drawn)
        ]

    async def begin(
        self,
        run: ImprovementRun,
        iteration: ImprovementIteration,
        *,
        instructions: str,
    ) -> bool:
        """Draw the questions every variant is scored on and queue the starting instructions.

        False when the attempt has too few training questions to search on.
        """
        progress = iteration.search
        assert progress is not None, "a search attempt is given its settings when it is made"
        train = await self.train_questions(
            organization_id=run.organization_id,
            dataset_id=run.dataset_id,
            dataset_version=run.dataset_version,
            drawn=iteration.train_case_ids,
        )
        if len(train) < MIN_TRAIN_QUESTIONS:
            return False
        chosen = draw_questions(
            [case.case_id for case in train],
            size=progress["settings"]["minibatch"],
            seed=iteration.split_seed or split_seed(run.id, iteration.number),
        )
        spent = await improvement_repo.spent(self.db, run.id, organization_id=run.organization_id)
        await improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={
                "search": SearchProgress(
                    settings=progress["settings"],
                    case_ids=[str(case_id) for case_id in chosen],
                    spent_before_usd=str(spent),
                    generation=0,
                    closed_generation=-1,
                    stale_generations=0,
                    seed_score=None,
                    best_before=None,
                    cost_usd="0",
                    stop_reason=None,
                    chosen_variant_id=None,
                )
            },
        )
        await improvement_repo.add_variants(
            self.db,
            organization_id=run.organization_id,
            iteration_id=iteration.id,
            generation=0,
            variants=[(None, instructions, variant_hash(instructions), "")],
        )
        await self.queue(run)
        return True

    async def queue(self, run: ImprovementRun) -> None:
        """Keep one unit of the search queued; a running one may queue its successor."""
        await enqueue(
            self.db,
            SEARCH_IMPROVEMENT,
            SearchImprovement(run_id=run.id, organization_id=run.organization_id),
            organization_id=run.organization_id,
            dedupe_key=f"improvement-search:{run.id}",
            concurrency_key=f"improvement-search:{run.organization_id}",
        )

    async def winners(
        self, run: ImprovementRun, iteration: ImprovementIteration
    ) -> list[ImprovementSearchVariant]:
        progress = iteration.search
        assert progress is not None, "only a search attempt has winners"
        variants = await improvement_repo.list_variants(
            self.db, organization_id=run.organization_id, iteration_id=iteration.id
        )
        return winner(variants, progress.get("seed_score"))

    async def adopt(
        self,
        run: ImprovementRun,
        iteration: ImprovementIteration,
        *,
        base: str,
        variant: ImprovementSearchVariant,
    ) -> UUID:
        """Make a variant the attempt's candidate: a batch of its changes to the instructions."""
        progress = iteration.search
        assert progress is not None, "only a search attempt adopts a variant"
        seed = progress.get("seed_score")
        batch = await authoring_repo.create_batch(
            self.db,
            organization_id=run.organization_id,
            agent_id=run.agent_id,
            request_id=None,
            source_started_at=iteration.started_at,
            expected_effect=(
                f"Passed {variant.train_score or 0:.0%} of required checks on "
                f"{variant.cases_scored} training questions, against {seed or 0:.0%} for the "
                "current instructions. Not yet checked on the held-out questions."
            ),
            evidence_conversation_ids=[],
            improvement_run_id=run.id,
        )
        await authoring_repo.add_hunks(
            self.db,
            organization_id=run.organization_id,
            batch_id=batch.id,
            hunks=variant_hunks(
                base,
                variant.instructions,
                rationale=variant.rationale or "The best variant the search found",
            ),
        )
        await improvement_repo.update_iteration(
            self.db,
            iteration=iteration,
            values={
                "batch_id": batch.id,
                "included_hunk_ids": None,
                "candidate_spec_hash": None,
                "search": {**progress, "chosen_variant_id": str(variant.id)},
            },
        )
        return batch.id

    async def read(
        self, run: ImprovementRun, iteration: ImprovementIteration, *, variants_text: bool
    ) -> VariantSearchRead:
        """The search's progress; its best variants only with `variants_text`.

        A variant is written from the attempt's training questions and reference
        answers, so its text and rationale go only to a caller who could start the
        session; anyone else reads the counts.
        """
        progress = iteration.search
        assert progress is not None, "only a search attempt has a search to read"
        options = progress["settings"]
        variants = await improvement_repo.list_variants(
            self.db, organization_id=run.organization_id, iteration_id=iteration.id
        )
        spent = await improvement_repo.spent(self.db, run.id, organization_id=run.organization_id)
        scored = [v for v in variants if v.train_score is not None]
        chosen = progress.get("chosen_variant_id")
        return VariantSearchRead(
            budget_usd=Decimal(options["budget_usd"]),
            cost_usd=search_cost(progress, spent=spent)
            if "spent_before_usd" in progress
            else Decimal(0),
            grading_model_profile_id=_uuid(options["grading_model_profile_id"]),
            max_variants=options["max_variants"],
            per_generation=options["per_generation"],
            patience=options["patience"],
            questions=len(progress.get("case_ids", [])),
            generation=progress.get("generation", 0),
            tried=sum(1 for v in variants if v.status != SearchVariantStatus.PENDING.value),
            pending=sum(1 for v in variants if v.status == SearchVariantStatus.PENDING.value),
            seed_score=progress.get("seed_score"),
            best_score=max((v.train_score or 0 for v in scored), default=None),
            stop_reason=cast(SearchEnd | None, progress.get("stop_reason")),
            chosen_variant_id=_uuid(chosen),
            top=[
                SearchVariantRead.model_validate(v)
                for v in winner(variants, progress.get("seed_score"))[:SEARCH_CHOICES]
            ]
            if variants_text
            else [],
        )


def search_settings(options: SearchOptions) -> SearchSettings:
    """What a search attempt keeps of the options it was started with."""
    return SearchSettings(
        budget_usd=str(options.budget_usd),
        grading_model_profile_id=None
        if options.grading_model_profile_id is None
        else str(options.grading_model_profile_id),
        max_variants=options.max_variants,
        per_generation=options.per_generation,
        minibatch=options.minibatch,
        patience=options.patience,
    )


def _uuid(value: str | None) -> UUID | None:
    return None if value is None else UUID(value)


class SearchWorker:
    """Does one unit of a search attempt, then queues the next or says the search ended.

    The session row is locked only to claim a unit and to record it, never while
    a model answers, so the session's own advance is never kept waiting.
    """

    def __init__(
        self,
        run_id: UUID,
        organization_id: UUID,
        *,
        sessions: Callable[[], AbstractAsyncContextManager[AsyncSession]] = get_worker_db_context,
    ) -> None:
        self.run_id = run_id
        self.organization_id = organization_id
        self.sessions = sessions

    async def run(self) -> None:
        unit = await self._claim()
        if isinstance(unit, _Score):
            answered = await self._answer_all(unit)
            await self._record_score(unit, answered)
        elif isinstance(unit, _Propose):
            proposed = await self._propose(unit)
            await self._record_proposal(unit, proposed)

    async def _claim(self) -> _Score | _Propose | None:
        """Pick the next unit and hold its estimate against the budget, or end the search."""
        async with self.sessions() as db:
            found = await self._searching(db)
            if found is None:
                return None
            run, iteration, progress = found
            try:
                ctx = await job_context(
                    db,
                    organization_id=self.organization_id,
                    user_id=run.actor_user_id or run.created_by_user_id,
                    api_key_id=run.actor_api_key_id
                    if run.actor_user_id is not None
                    else run.created_by_api_key_id,
                )
            except AuthenticationError:
                ctx = None
            agent = await agent_repo.get(db, run.agent_id, organization_id=self.organization_id)
            if ctx is None or agent is None or not await _pinned(db, run, agent):
                # The session's own advance reads why and stops it, before more is spent.
                await _advance(db, run)
                return None
            spec = AgentSpec.model_validate(agent.draft_spec)
            spent = await improvement_repo.spent(db, run.id, organization_id=self.organization_id)
            left = search_left(progress, spent=spent, budget=run.budget_usd)
            variant = await improvement_repo.next_pending_variant(
                db, organization_id=self.organization_id, iteration_id=iteration.id
            )
            if variant is not None:
                return await self._claim_score(
                    db, ctx, run, iteration, progress, variant, spec=spec, spent=spent, left=left
                )
            return await self._claim_proposal(
                db, ctx, run, iteration, progress, spec=spec, left=left
            )

    async def _searching(
        self, db: AsyncSession
    ) -> tuple[ImprovementRun, ImprovementIteration, SearchProgress] | None:
        """The session, its attempt and the search, while the search may still go on."""
        run = await improvement_repo.get_run(
            db, self.run_id, organization_id=self.organization_id, lock=True
        )
        if (
            run is None
            or run.status != ImprovementStatus.RUNNING.value
            or run.stage != ImprovementStage.SEARCHING.value
            or run.mode != ImprovementMode.SEARCH.value
        ):
            return None
        iteration = await improvement_repo.get_iteration(
            db, organization_id=self.organization_id, run_id=run.id, number=run.iteration
        )
        progress = None if iteration is None else iteration.search
        if (
            iteration is None
            or progress is None
            or "case_ids" not in progress
            or progress.get("stop_reason") is not None
        ):
            return None
        return run, iteration, progress

    async def _claim_score(
        self,
        db: AsyncSession,
        ctx: AuthContext,
        run: ImprovementRun,
        iteration: ImprovementIteration,
        progress: SearchProgress,
        variant: ImprovementSearchVariant,
        *,
        spec: AgentSpec,
        spent: Decimal,
        left: Decimal,
    ) -> _Score | None:
        if variant.attempts >= MAX_SCORING_ATTEMPTS:
            await improvement_repo.update_variant(
                db,
                variant=variant,
                values={
                    "status": SearchVariantStatus.FAILED.value,
                    "scored_at": datetime.now(UTC),
                },
            )
            await ImprovementSearchService(db).queue(run)
            return None
        scoring = _grading(run, progress["settings"])
        variant_spec = spec.model_copy(update={"instructions": variant.instructions})
        questions = await self._questions(db, run, progress)
        try:
            priced = await EvalRunService(db).estimate(
                ctx,
                run.agent_id,
                EvalRunRequest(
                    dataset_id=run.dataset_id,
                    dataset_version=run.dataset_version,
                    candidate="draft",
                ),
                scoring=scoring,
                judge_version_id=run.judge_version_id,
                judge_pinned=run.judge_version_id is not None,
                candidate_spec=variant_spec,
            )
        except AppException:
            # The pinned questions can no longer be answered - erased, say - and would
            # refuse every later unit the same way.
            logger.info("A search of session %s could not price its questions", run.id)
            priced = None
        if priced is None or not questions:
            await _end(db, run, iteration, progress, "questions")
            return None
        estimate = priced.total_usd / max(1, priced.cases) * len(questions)
        if estimate > left:
            await _end(db, run, iteration, progress, "budget")
            return None
        answer_usd = priced.arms[0].cost_per_case_usd
        await improvement_repo.update_variant(
            db, variant=variant, values={"attempts": variant.attempts + 1, "estimate_usd": estimate}
        )
        await self._claimed(db, run, iteration, progress)
        return _Score(
            ctx=ctx,
            run_id=run.id,
            agent_id=run.agent_id,
            iteration_id=iteration.id,
            variant_id=variant.id,
            spec=variant_spec,
            questions=questions,
            scoring=scoring,
            judge_version_id=run.judge_version_id,
            answer_cap=answer_usd * ANSWER_CAP_FACTOR,
            spent_at_claim=spent,
        )

    async def _claim_proposal(
        self,
        db: AsyncSession,
        ctx: AuthContext,
        run: ImprovementRun,
        iteration: ImprovementIteration,
        progress: SearchProgress,
        *,
        spec: AgentSpec,
        left: Decimal,
    ) -> _Propose | None:
        variants = await improvement_repo.list_variants(
            db, organization_id=self.organization_id, iteration_id=iteration.id
        )
        progress = _close_generation(progress, variants)
        options = progress["settings"]
        tried = len(variants)
        end: SearchEnd | None = None
        if tried >= options["max_variants"]:
            end = "max_variants"
        elif progress["generation"] > 0 and progress["stale_generations"] >= options["patience"]:
            end = "patience"
        elif progress.get("seed_score") is None:
            # The starting instructions could not be graded: nothing can be shown better.
            end = "no_variant"
        if end is not None:
            await _end(db, run, iteration, progress, end)
            return None
        seed = next(v for v in variants if v.generation == 0)
        parents = [
            v
            for v in variants
            if v.status == SearchVariantStatus.SCORED.value and v.train_score is not None
        ][:PARENTS]
        count = min(options["per_generation"], options["max_variants"] - tried)
        prompt = await _prompt(db, run, progress, parents, count=count)
        helper = DatasetHelper.model_validate(run.helper_settings or {})
        estimate = await _proposal_price(
            db, ctx, helper.model_profile_id, prompt, count=count, seed=seed.instructions
        )
        if estimate > left:
            await _end(db, run, iteration, progress, "budget")
            return None
        progress = SearchProgress(
            **{**progress, "best_before": max((p.train_score or 0 for p in parents), default=None)}
        )
        await self._claimed(db, run, iteration, progress)
        return _Propose(
            ctx=ctx,
            run_id=run.id,
            iteration_id=iteration.id,
            generation=progress["generation"] + 1,
            count=count,
            parent_ids=[p.id for p in parents],
            seed=spec.instructions,
            prompt=prompt,
            improver_agent_id=run.improver_agent_id,
            helper=helper,
        )

    async def _claimed(
        self,
        db: AsyncSession,
        run: ImprovementRun,
        iteration: ImprovementIteration,
        progress: SearchProgress,
    ) -> None:
        await improvement_repo.update_iteration(
            db, iteration=iteration, values={"search": progress}
        )
        await improvement_repo.update_run(db, run=run, values={"heartbeat_at": datetime.now(UTC)})

    async def _questions(
        self, db: AsyncSession, run: ImprovementRun, progress: SearchProgress
    ) -> list[_Question]:
        """The attempt's drawn training questions as they stand now; an erased one drops out."""
        cases = await ImprovementSearchService(db).train_questions(
            organization_id=self.organization_id,
            dataset_id=run.dataset_id,
            dataset_version=run.dataset_version,
            drawn={UUID(case_id) for case_id in progress["case_ids"]},
        )
        return [
            _Question(
                case_id=case.case_id,
                input=case.input,
                history=[
                    HistoryMessage(role=turn["role"], content=turn["content"])
                    for turn in case.history or []
                ],
                view=CaseView(
                    input=case.input,
                    history=case.history,
                    reference_answer=case.reference_answer,
                    counter_example=case.counter_example,
                    expected_tool_calls=case.expected_tool_calls,
                    order_mode=case.order_mode,
                    checks=case.checks,
                    note=case.note,
                    tags=case.tags,
                ),
            )
            for case in cases
        ]

    async def _answer_all(self, unit: _Score) -> dict[UUID, _Answered]:
        gate = asyncio.Semaphore(CASE_PARALLELISM)

        async def one(question: _Question) -> tuple[UUID, _Answered]:
            async with gate:
                # Every answer is paid for, so a session stopped meanwhile asks no more.
                if not await self._still_searching(unit):
                    return question.case_id, _Answered(counted=False)
                return question.case_id, await self._answer(unit, question)

        return dict(await asyncio.gather(*(one(q) for q in unit.questions)))

    async def _still_searching(self, unit: _Score) -> bool:
        async with self.sessions() as db:
            run = await improvement_repo.get_run(
                db, unit.run_id, organization_id=self.organization_id
            )
            return (
                run is not None
                and run.status == ImprovementStatus.RUNNING.value
                and run.stage == ImprovementStage.SEARCHING.value
            )

    async def _answer(self, unit: _Score, question: _Question) -> _Answered:
        """Answer one training question with the variant and grade it, in its own session."""
        async with self.sessions() as db:
            calls: list[RecordedToolCall] = []
            try:
                output, agent_run = await AgentRunnerService(db).execute(
                    unit.ctx,
                    unit.agent_id,
                    question.input,
                    surface=RunSurface.EVAL,
                    message_history=build_message_history(question.history),
                    isolation=RunIsolation(improvement_run_id=unit.run_id),
                    candidate=UnpublishedCandidate(unit.spec),
                    tool_calls=calls,
                    run_limit_usd=unit.answer_cap,
                )
            except Exception:
                logger.exception("A search variant could not answer case %s", question.case_id)
                return _Answered(failed=[_UNANSWERED])
            if agent_run.status == RunStatus.BUDGET_EXCEEDED.value:
                return _Answered(budget=True, failed=[_UNANSWERED])
            if agent_run.status not in (
                RunStatus.COMPLETED.value,
                RunStatus.GUARDRAIL_BLOCKED.value,
            ):
                return _Answered(failed=[_UNANSWERED])
            if agent_run.status == RunStatus.GUARDRAIL_BLOCKED.value:
                output = "The request was blocked by a guardrail. " + (
                    agent_run.error or "No guardrail detail was recorded."
                )
            intercepted = await intercepted_tool_call_repo.list_for_run(
                db, run_id=agent_run.id, organization_id=self.organization_id
            )
            rows = trajectory(calls, intercepted)
            answer = ScoredAnswer(
                text=output,
                calls=tuple(
                    ScoredCall(
                        tool=call.tool_name,
                        args=call.args,
                        blocked=row["outcome"] == InterceptionOutcome.BLOCKED.value,
                    )
                    for call, row in zip(calls, rows, strict=True)
                ),
                cost_usd=agent_run.cost_usd,
                latency_ms=None,
                run_id=agent_run.id,
                agent_id=agent_run.agent_id,
            )
            try:
                evaluation = await ScoringService(db).evaluate(
                    unit.ctx,
                    question.view,
                    answer,
                    unit.scoring,
                    judge_version_id=unit.judge_version_id,
                    judge_pinned=unit.judge_version_id is not None,
                    improvement_run_id=unit.run_id,
                )
            except AppException:
                logger.exception("A search variant's answer to %s was not graded", question.case_id)
                return _Answered(failed=[_UNGRADED])
            required = [r for r in evaluation.results if r.required]
            return _Answered(
                share=case_share(evaluation.results) or 0.0,
                failed=[r.name for r in required if r.status != "pass"],
                budget=any(r.reason_code == "judge_budget" for r in evaluation.results),
                counted=bool(required),
            )

    async def _record_score(self, unit: _Score, answered: dict[UUID, _Answered]) -> None:
        async with self.sessions() as db:
            found = await self._searching(db)
            if found is None or found[1].id != unit.iteration_id:
                return
            run, iteration, progress = found
            variant = await improvement_repo.get_variant(
                db,
                unit.variant_id,
                organization_id=self.organization_id,
                iteration_id=iteration.id,
            )
            if variant is None or variant.status != SearchVariantStatus.PENDING.value:
                return
            shares = [a.share for a in answered.values() if a.counted]
            spent = await improvement_repo.spent(db, run.id, organization_id=self.organization_id)
            score = sum(shares) / len(shares) if shares else None
            await improvement_repo.update_variant(
                db,
                variant=variant,
                values={
                    "status": SearchVariantStatus.FAILED.value
                    if score is None
                    else SearchVariantStatus.SCORED.value,
                    "train_score": score,
                    "cases_scored": len(shares),
                    "cases_passed": sum(1 for share in shares if share == 1.0),
                    "failures": [
                        VariantFailure(case_id=str(case_id), failed=a.failed)
                        for case_id, a in answered.items()
                        if a.failed
                    ],
                    "cost_usd": max(Decimal(0), spent - unit.spent_at_claim),
                    "scored_at": datetime.now(UTC),
                },
            )
            updated = SearchProgress(
                **{
                    **progress,
                    "cost_usd": str(search_cost(progress, spent=spent)),
                }
            )
            if variant.generation == 0:
                updated["seed_score"] = score
            if any(a.budget for a in answered.values()):
                await _end(db, run, iteration, updated, "budget")
                return
            await improvement_repo.update_iteration(
                db, iteration=iteration, values={"search": updated}
            )
            await ImprovementSearchService(db).queue(run)

    async def _propose(self, unit: _Propose) -> InstructionVariants | None:
        async with self.sessions() as db:
            try:
                result = await SystemAgentRunner(db).run(
                    unit.ctx,
                    key=IMPROVER.key,
                    agent_id=unit.improver_agent_id,
                    model_profile_id=unit.helper.model_profile_id,
                    instructions=unit.helper.instructions,
                    prompt=unit.prompt,
                    output_type=InstructionVariants,
                    improvement_run_id=unit.run_id,
                )
            except AppException:
                logger.exception("A search round's proposal failed for session %s", unit.run_id)
                return None
            return result.output

    async def _record_proposal(self, unit: _Propose, proposed: InstructionVariants | None) -> None:
        async with self.sessions() as db:
            found = await self._searching(db)
            if found is None or found[1].id != unit.iteration_id:
                return
            run, iteration, progress = found
            spent = await improvement_repo.spent(db, run.id, organization_id=self.organization_id)
            updated = SearchProgress(
                **{
                    **progress,
                    "cost_usd": str(search_cost(progress, spent=spent)),
                }
            )
            if proposed is None:
                await _end(db, run, iteration, updated, "proposal")
                return
            kept = [
                variant
                for variant in proposed.variants
                if keeps_placeholders(unit.seed, variant.instructions)
                and variant.instructions.strip() != unit.seed.strip()
            ][: unit.count]
            parent = unit.parent_ids[0] if unit.parent_ids else None
            await improvement_repo.add_variants(
                db,
                organization_id=self.organization_id,
                iteration_id=iteration.id,
                generation=unit.generation,
                variants=[
                    (parent, v.instructions, variant_hash(v.instructions), v.rationale)
                    for v in kept
                ],
            )
            updated["generation"] = unit.generation
            await improvement_repo.update_iteration(
                db, iteration=iteration, values={"search": updated}
            )
            await ImprovementSearchService(db).queue(run)


async def _pinned(db: AsyncSession, run: ImprovementRun, agent: Agent) -> bool:
    """Whether the agent and its grading are still what the session pinned at its start.

    A changed draft would score variants on another model or other tools, and a
    variant adopted onto it would undo the change.
    """
    dataset = await dataset_repo.get(db, run.dataset_id, organization_id=run.organization_id)
    newest = await agent_repo.newest_version(
        db, agent_id=agent.id, organization_id=run.organization_id
    )
    return (
        agent.status != AgentStatus.ARCHIVED.value
        and spec_hash(AgentSpec.model_validate(agent.draft_spec)) == run.base_draft_hash
        and dataset is not None
        and scoring_hash(DatasetScoring.model_validate(dataset.scoring)) == run.scoring_hash
        and (None if newest is None else newest.id) == run.base_version_id
    )


def _grading(run: ImprovementRun, options: SearchSettings) -> DatasetScoring:
    """The session's pinned grading, on the model the person chose for the search."""
    scoring = DatasetScoring.model_validate(run.pinned_scoring)
    chosen = options["grading_model_profile_id"]
    if chosen is None:
        return scoring
    return scoring.model_copy(
        update={"judge": scoring.judge.model_copy(update={"model_profile_id": UUID(chosen)})}
    )


def _close_generation(
    progress: SearchProgress, variants: Sequence[ImprovementSearchVariant]
) -> SearchProgress:
    """Count a finished round of proposals as one that found something better, or not."""
    generation = progress["generation"]
    if generation == 0 or progress["closed_generation"] >= generation:
        return progress
    best_before = progress.get("best_before")
    best_now = max(
        (
            v.train_score
            for v in variants
            if v.generation == generation and v.train_score is not None
        ),
        default=None,
    )
    improved = best_now is not None and (best_before is None or best_now > best_before)
    return SearchProgress(
        **{
            **progress,
            "closed_generation": generation,
            "stale_generations": 0 if improved else progress["stale_generations"] + 1,
        }
    )


async def _end(
    db: AsyncSession,
    run: ImprovementRun,
    iteration: ImprovementIteration,
    progress: SearchProgress,
    reason: SearchEnd,
) -> None:
    """Say the search ended and let the session's own step hand on what it found."""
    spent = await improvement_repo.spent(db, run.id, organization_id=run.organization_id)
    await improvement_repo.update_iteration(
        db,
        iteration=iteration,
        values={
            "search": {
                **progress,
                "cost_usd": str(search_cost(progress, spent=spent)),
                "stop_reason": reason,
            }
        },
    )
    await _advance(db, run)


async def _advance(db: AsyncSession, run: ImprovementRun) -> None:
    await enqueue(
        db,
        ADVANCE_IMPROVEMENT,
        AdvanceImprovement(run_id=run.id, organization_id=run.organization_id),
        organization_id=run.organization_id,
        concurrency_key=f"improvement:{run.agent_id}",
        dedupe_key=f"{run.id}:search:{run.iteration}",
    )


async def _prompt(
    db: AsyncSession,
    run: ImprovementRun,
    progress: SearchProgress,
    parents: Sequence[ImprovementSearchVariant],
    *,
    count: int,
) -> str:
    """The improver's task: the best instructions so far and the training questions they fail.

    Only the attempt's drawn training questions are named; the questions the
    attempt is measured on are never read here.
    """
    cases = {
        case.case_id: case
        for case in await ImprovementSearchService(db).train_questions(
            organization_id=run.organization_id,
            dataset_id=run.dataset_id,
            dataset_version=run.dataset_version,
            drawn={UUID(case_id) for case_id in progress["case_ids"]},
        )
    }
    blocks = []
    for number, parent in enumerate(parents, start=1):
        shown = [
            (cases[UUID(failure["case_id"])], failure["failed"])
            for failure in parent.failures
            if UUID(failure["case_id"]) in cases
        ][:FAILURES_SHOWN]
        failures = [
            f"<question>\n{case.input}"
            + (f"\nA good answer: {case.reference_answer}" if case.reference_answer else "")
            + f"\nFailed: {', '.join(failed)}\n</question>"
            for case, failed in shown
        ]
        blocks.append(
            f'<version number="{number}" score="{parent.train_score or 0:.2f}">\n'
            f"<instructions>\n{parent.instructions}\n</instructions>\n"
            f"<still_failing>\n{chr(10).join(failures) or 'None of the scored questions.'}\n"
            "</still_failing>\n</version>"
        )
    return (
        "You are improving an AI agent's instructions. Below are its best versions of the "
        "instructions so far, each with its score - the share of required checks its answers "
        "passed on a fixed set of training questions - and the questions it still fails, with "
        "the checks each failed.\n\n"
        f"Write {count} new versions of the instructions. Each must be the complete instructions, "
        "not a fragment or a list of edits. Make each a different attempt at the failures: keep "
        "what already works, change what makes the failing answers fail, and do not quote or "
        "name the questions - the versions are judged later on questions they have not seen. "
        "Keep every {{placeholder}} exactly as written. Give a one-sentence rationale for each."
        f"\n\n{chr(10).join(blocks)}"
    )


async def _proposal_price(
    db: AsyncSession,
    ctx: AuthContext,
    model_profile_id: UUID | None,
    prompt: str,
    *,
    count: int,
    seed: str,
) -> Decimal:
    """What one round of proposals costs: the prompt read once, `count` rewrites written."""
    usage = RunUsage(
        input_tokens=len(prompt) // 4 + settings.EVAL_FALLBACK_INPUT_TOKENS,
        output_tokens=count * (len(seed) // 4 + settings.EVAL_FALLBACK_OUTPUT_TOKENS),
    )
    if model_profile_id is not None:
        model = await ModelProfileService(db).resolve(ctx, profile_id=model_profile_id)
        priced = price_request(usage, model.model, model.provider)
        if priced is not None:
            return Decimal(priced)
    return settings.EVAL_FALLBACK_CASE_COST_USD * count

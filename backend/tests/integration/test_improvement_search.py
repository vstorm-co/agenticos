"""A search attempt across real PostgreSQL transactions, with scripted answers and proposals."""

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
    ValidationError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import AgentRun
from app.db.models.authoring import SpecProposalBatch, SpecProposalHunk
from app.db.models.background_job import BackgroundJob
from app.db.models.credential import ModelProfile
from app.db.models.dataset import Dataset, DatasetCase
from app.db.models.improvement import ImprovementIteration, ImprovementRun, ImprovementSearchVariant
from app.repositories import improvement_repo
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.schemas.improvement import (
    ImprovementStart,
    ImprovementTarget,
    SearchChoice,
    SearchOptions,
)
from app.services.dataset import DatasetService
from app.services.eval_run import EvalRunService
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.improvement_search import (
    ImprovementSearchService,
    SearchWorker,
)
from app.services.scoring import ScoringService
from tests.integration._keys import provider_key
from tests.integration.test_authoring import INSTRUCTIONS, _answering, _sessions, _setup
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_eval_suites import _member, _owner
from tests.integration.test_improvement_pipeline import _next_step

pytestmark = [pytest.mark.anyio, pytest.mark.security, pytest.mark.usefixtures("_environment")]

_WINDOW = INSTRUCTIONS + "\nRefunds take 30 days."
_KINDLY = INSTRUCTIONS + "\nSay kindly that refunds take 30 days."
_POLITE = INSTRUCTIONS + "\nBe polite."


class Searcher:
    """Stands in for every model: the agent answers by its instructions, the improver by script."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        variants: list[dict[str, Any]] | None = None,
        cost: Callable[[dict[str, Any]], Decimal] = lambda kw: Decimal("0.01"),
        status: Callable[[str], str] = lambda prompt: "completed",
        before: Callable[[str], Any] | None = None,
        crash: str | None = None,
        proposing: Callable[[], Any] | None = None,
    ) -> None:
        self.db = db
        self.variants = (
            variants
            if variants is not None
            else [
                {"instructions": _WINDOW, "rationale": "Name the window"},
                {"instructions": _POLITE, "rationale": "Tone"},
            ]
        )
        self.cost = cost
        self.status = status
        self.before = before
        self.crash = crash
        self.on_proposal = proposing
        self.asked: list[str] = []
        self.proposals: list[str] = []

    async def execute(self, runner: Any, ctx: AuthContext, agent_id: Any, prompt: str, **kw: Any):
        proposing = kw.get("output_schema") is not None
        if not proposing and self.before is not None:
            await self.before(prompt)
        if prompt == self.crash and not proposing:
            raise RuntimeError("the provider hung up")
        now = datetime.now(UTC)
        run = AgentRun(
            improvement_run_id=kw["isolation"].improvement_run_id if kw.get("isolation") else None,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            user_id=ctx.user_id,
            surface=kw["surface"].value,
            status="completed" if proposing else self.status(prompt),
            model_label="gpt-test",
            cost_usd=Decimal("0.02") if proposing else self.cost(kw),
            started_at=now,
            ended_at=now,
        )
        self.db.add(run)
        await self.db.flush()
        if proposing:
            if self.on_proposal is not None:
                await self.on_proposal()
            self.proposals.append(prompt)
            answer = {"variants": self.variants}
            kw["structured"].append(answer)
            return json.dumps(answer), run
        self.asked.append(prompt)
        candidate = kw["candidate"]
        window = "30 days" if "30 days" in candidate.spec.instructions else "90 days"
        return f"You have {window}.", run


async def _dataset(
    db: AsyncSession, ctx: AuthContext, *, train: int = 12, held: int = 5
) -> Dataset:
    service = DatasetService(db)
    dataset = await service.create(
        ctx,
        DatasetCreate(name=f"refunds-{uuid.uuid4().hex[:6]}", improvement_holdout_share=Decimal(1)),
    )
    for name, count in (("Train", train), ("Held", held)):
        for index in range(count):
            await service.add_case(
                ctx,
                dataset.id,
                DatasetCaseCreate(
                    input=f"{name} question {index}",
                    checks=[{"type": "contains", "value": "30 days"}],
                ),
            )
    rows = await db.scalars(select(DatasetCase).where(DatasetCase.dataset_id == dataset.id))
    for row in rows:
        row.improvement_partition = "train" if row.input.startswith("Train") else "holdout"
    await db.flush()
    stored = await db.get(Dataset, dataset.id)
    assert stored is not None
    return stored


def _options(**values: Any) -> SearchOptions:
    values.setdefault("budget_usd", Decimal("3"))
    values.setdefault("max_variants", 4)
    values.setdefault("per_generation", 2)
    values.setdefault("patience", 1)
    return SearchOptions(**values)


async def _start(db: AsyncSession, *, search: SearchOptions | None = None, **dataset: int):
    ctx, agent, _ = await _setup(db)
    data = await _dataset(db, ctx, **dataset)
    read = await ImprovementPipelineService(db).start(
        ctx,
        agent.id,
        ImprovementStart(
            dataset_id=data.id,
            max_iterations=2,
            budget_usd=Decimal("10"),
            mode="search",
            search=search or _options(),
        ),
    )
    return ctx, agent, data, read


async def _to_search(db: AsyncSession, ctx: AuthContext, run_id: uuid.UUID) -> None:
    """Through Understand, then the person's next step, then the search's first advance."""
    service = ImprovementPipelineService(db)
    for _ in range(2):
        await service.advance(run_id, ctx.organization_id)
    run = await db.get(ImprovementRun, run_id)
    assert run is not None and run.status == "waiting"
    await _next_step(db, ctx, run_id)
    assert run.status == "running" and run.stage == "searching"
    await service.advance(run_id, ctx.organization_id)


async def _iteration(db: AsyncSession, run_id: uuid.UUID, number: int = 1) -> ImprovementIteration:
    run = await db.get(ImprovementRun, run_id)
    assert run is not None
    iteration = await improvement_repo.get_iteration(
        db, organization_id=run.organization_id, run_id=run_id, number=number
    )
    assert iteration is not None and iteration.search is not None
    return iteration


async def _units(db: AsyncSession, ctx: AuthContext, run_id: uuid.UUID, model: Searcher) -> None:
    """Run the search's units until it says it ended, as its jobs would one after another."""
    # One session stands in for each unit's own, so answers are asked one at a time.
    with _answering(model), patch("app.services.improvement_search.CASE_PARALLELISM", 1):
        for _ in range(40):
            await SearchWorker(run_id, ctx.organization_id, sessions=_sessions(db)).run()
            if (await _iteration(db, run_id)).search.get("stop_reason") is not None:  # ty: ignore[possibly-missing-attribute]
                return
    raise AssertionError("the search never ended")


async def _finish(db: AsyncSession, ctx: AuthContext, run_id: uuid.UUID) -> ImprovementRun:
    service = ImprovementPipelineService(db)
    for _ in range(2):
        await service.advance(run_id, ctx.organization_id)
    run = await db.get(ImprovementRun, run_id)
    assert run is not None
    return run


def _priced(per_case: str = "0.01", cases: int = 17):
    """A fixed eval price per case, so a test can say what the search may start."""
    estimate = SimpleNamespace(
        total_usd=Decimal(per_case) * cases,
        cases=cases,
        arms=[SimpleNamespace(cost_per_case_usd=Decimal(per_case))],
    )
    return patch.object(EvalRunService, "estimate", new=AsyncMock(return_value=estimate))


def _proposal_costs(amount: str = "0.02"):
    return patch(
        "app.services.improvement_search._proposal_price",
        new=AsyncMock(return_value=Decimal(amount)),
    )


class TestSearch:
    async def test_the_best_variant_reaches_changes_without_any_held_out_question_being_read(
        self, db
    ):
        ctx, agent, _, read = await _start(db, search=_options(max_variants=3))
        service = ImprovementPipelineService(db)
        for _ in range(2):
            await service.advance(read.id, ctx.organization_id)
        waiting = await service.read(ctx, agent.id, read.id)
        assert waiting.mode == "search" and waiting.next_step == "search"
        unbegun = waiting.iterations[0].variant_search
        assert unbegun is not None and unbegun.cost_usd == 0 and unbegun.questions == 0
        await _next_step(db, ctx, read.id)
        await service.advance(read.id, ctx.organization_id)
        with pytest.raises(BadRequestError, match="only at Changes"):
            await service.choose_variant(
                ctx, agent.id, read.id, SearchChoice(variant_id=uuid.uuid4())
            )
        model = Searcher(db)

        await _units(db, ctx, read.id, model)
        run = await _finish(db, ctx, read.id)

        assert run.status == "waiting" and run.stage == "filtering"
        assert model.asked and all(prompt.startswith("Train question") for prompt in model.asked)
        assert model.proposals and not any("Held question" in p for p in model.proposals)
        assert "Train question" in model.proposals[0] and "Failed:" in model.proposals[0]
        iteration = await _iteration(db, read.id)
        hunks = list(
            await db.scalars(
                select(SpecProposalHunk).where(SpecProposalHunk.batch_id == iteration.batch_id)
            )
        )
        assert len(hunks) == 1 and hunks[0].new_text.endswith("Refunds take 30 days.")
        batch = await db.get(SpecProposalBatch, iteration.batch_id)
        assert batch is not None and batch.status == "candidate" and batch.request_id is None
        found = (await service.read(ctx, agent.id, read.id)).iterations[0].variant_search
        assert found is not None and found.stop_reason == "max_variants"
        assert found.seed_score == 0.0 and found.best_score == 1.0
        assert [v.instructions for v in found.top] == [_WINDOW]
        assert found.chosen_variant_id == found.top[0].id
        assert found.cost_usd > 0 and found.questions == 12 and found.pending == 0
        assert (await service.read(ctx, agent.id, read.id)).next_step == "check"

    async def test_a_search_that_beats_nothing_stops_the_session(self, db):
        ctx, _, _, read = await _start(db)
        await _to_search(db, ctx, read.id)

        await _units(db, ctx, read.id, Searcher(db, variants=[{"instructions": _POLITE}]))
        assert (await _iteration(db, read.id)).search["stop_reason"] == "patience"  # ty: ignore[not-subscriptable]
        await SearchWorker(read.id, ctx.organization_id, sessions=_sessions(db)).run()
        run = await _finish(db, ctx, read.id)

        assert run.status == "stopped" and run.stop_reason == "no_variant"
        assert run.stage == "searching"

    async def test_a_variant_that_adds_a_template_variable_or_repeats_the_instructions_is_dropped(
        self, db
    ):
        ctx, _, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        variants = [
            {"instructions": _WINDOW + " {{secret}}"},
            {"instructions": INSTRUCTIONS},
        ]

        await _units(db, ctx, read.id, Searcher(db, variants=variants))

        iteration = await _iteration(db, read.id)
        assert iteration.search["stop_reason"] == "patience"  # ty: ignore[not-subscriptable]
        tried = await improvement_repo.list_variants(
            db, organization_id=ctx.organization_id, iteration_id=iteration.id
        )
        assert [v.generation for v in tried] == [0]

    async def test_the_quote_counts_the_search_budget_and_its_winners_check(self, db):
        ctx, agent, data, _ = await _start(db)
        service = ImprovementPipelineService(db)
        steps = await service.estimate(ctx, agent.id, ImprovementTarget(dataset_id=data.id))
        search = await service.estimate(
            ctx,
            agent.id,
            ImprovementTarget(dataset_id=data.id, mode="search", search=_options()),
        )
        assert search.search_usd == Decimal("3") and search.train_questions == 12
        assert search.total_usd == steps.total_usd + Decimal("3") + search.eval_usd

    async def test_try_again_searches_on_its_own_draw(self, db):
        """Try again keeps the search settings; this dataset keeps every question aside then."""
        ctx, _, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        run = await db.get(ImprovementRun, read.id)
        iteration = await _iteration(db, read.id)
        assert run is not None
        run.status, run.stage, run.stop_reason = "stopped", "judging", "no_change"
        iteration.verdict = "no_change"
        await db.flush()

        await _next_step(db, ctx, read.id)
        following = await _iteration(db, read.id, number=2)
        assert following.search == {"settings": iteration.search["settings"]}  # ty: ignore[not-subscriptable]
        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)

        assert run.status == "stopped" and run.stop_reason == "no_data"
        assert "10 training questions" in (run.error or "")


class TestDraftEdits:
    """A variant is a rewrite from the search's start: adopted onto an edited draft it
    would undo the edit, so an edited draft ends the session instead."""

    async def test_a_draft_edited_during_the_search_ends_the_session_before_any_hunk(self, db):
        ctx, agent, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        await _units(db, ctx, read.id, Searcher(db))

        agent.draft_spec = {**agent.draft_spec, "instructions": INSTRUCTIONS + "\nNew rule."}
        await db.flush()
        run = await _finish(db, ctx, read.id)

        assert run.status == "stale" and run.stop_reason == "stale"
        assert (await _iteration(db, read.id)).batch_id is None
        assert await db.scalar(select(SpecProposalHunk)) is None

    async def test_another_variant_is_not_brought_onto_an_edited_draft(self, db):
        ctx, agent, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        model = Searcher(
            db,
            variants=[{"instructions": _KINDLY}, {"instructions": _WINDOW}],
        )
        await _units(db, ctx, read.id, model)
        await _finish(db, ctx, read.id)
        service = ImprovementPipelineService(db)
        found = (await service.read(ctx, agent.id, read.id)).iterations[0].variant_search
        assert found is not None and len(found.top) == 2
        batch = (await _iteration(db, read.id)).batch_id

        agent.draft_spec = {**agent.draft_spec, "instructions": INSTRUCTIONS + "\nNew rule."}
        await db.flush()
        with pytest.raises(ConcurrentChangeError, match="stale"):
            await service.choose_variant(
                ctx, agent.id, read.id, SearchChoice(variant_id=found.top[1].id)
            )

        assert (await _iteration(db, read.id)).batch_id == batch


class TestBudget:
    async def test_the_search_goes_over_its_budget_by_at_most_the_variant_it_was_scoring(self, db):
        ctx, _, _, read = await _start(
            db, search=_options(budget_usd=Decimal("0.40"), max_variants=10)
        )
        await _to_search(db, ctx, read.id)
        # Each answer spends its whole cap: twice its share of the estimate.
        model = Searcher(
            db,
            cost=lambda kw: kw["run_limit_usd"],
            variants=[{"instructions": _WINDOW}, {"instructions": _KINDLY}],
        )

        with _priced(), _proposal_costs():
            await _units(db, ctx, read.id, model)
        iteration = await _iteration(db, read.id)
        variants = await improvement_repo.list_variants(
            db, organization_id=ctx.organization_id, iteration_id=iteration.id
        )
        run = await _finish(db, ctx, read.id)

        progress = iteration.search
        assert progress is not None and progress["stop_reason"] == "budget"
        one_variant = Decimal("0.02") * 12
        assert Decimal(progress["cost_usd"]) == Decimal("0.50")
        assert Decimal(progress["cost_usd"]) <= Decimal("0.40") + one_variant
        never_started = [v for v in variants if v.status == "pending"]
        assert len(never_started) == 1 and never_started[0].attempts == 0
        assert (run.status, run.stage, run.stop_reason, run.error) == (
            "waiting",
            "filtering",
            None,
            None,
        )

    async def test_a_round_of_proposals_that_does_not_fit_ends_the_search(self, db):
        ctx, _, _, read = await _start(db, search=_options(budget_usd=Decimal("0.25")))
        await _to_search(db, ctx, read.id)

        with _priced(), _proposal_costs():
            await _units(db, ctx, read.id, Searcher(db, cost=lambda kw: kw["run_limit_usd"]))
        run = await _finish(db, ctx, read.id)

        assert (await _iteration(db, read.id)).search["stop_reason"] == "budget"  # ty: ignore[not-subscriptable]
        assert run.status == "stopped" and run.stop_reason == "no_variant"

    async def test_an_answer_stopped_by_a_budget_ends_the_search(self, db):
        ctx, _, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        model = Searcher(
            db, status=lambda p: "budget_exceeded" if p == "Train question 0" else "completed"
        )

        await _units(db, ctx, read.id, model)

        assert (await _iteration(db, read.id)).search["stop_reason"] == "budget"  # ty: ignore[not-subscriptable]


class TestAnswers:
    async def test_each_kind_of_answer_counts_as_it_should(self, db):
        """A crash fails the question, a guardrail's refusal is graded, the rest is skipped."""
        ctx, _, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        statuses = {
            "Train question 0": "failed",
            "Train question 1": "cancelled",
            "Train question 2": "guardrail_blocked",
        }
        model = Searcher(
            db, status=lambda p: statuses.get(p, "completed"), crash="Train question 3"
        )
        evaluate = ScoringService.evaluate

        async def grading(self, ctx, case, answer, scoring, **kw):
            if case.input == "Train question 4":
                raise BadRequestError(message="The judge is gone")
            return await evaluate(self, ctx, case, answer, scoring, **kw)

        with patch.object(ScoringService, "evaluate", new=grading):
            await _units(db, ctx, read.id, model)

        iteration = await _iteration(db, read.id)
        variants = await improvement_repo.list_variants(
            db, organization_id=ctx.organization_id, iteration_id=iteration.id
        )
        seed = next(v for v in variants if v.generation == 0)
        best = next(v for v in variants if v.instructions == _WINDOW)
        # Every question stays in the score: what was not answered or graded fails.
        assert seed.cases_scored == best.cases_scored == 12
        assert best.train_score == pytest.approx(7 / 12, abs=1e-5)
        reasons = [f["failed"][0] for f in best.failures]
        assert len(reasons) == 5
        assert reasons.count("not answered") == 3 and reasons.count("not graded") == 1


class TestRecovery:
    async def test_a_search_unit_waits_in_the_organizations_one_lane(self, db):
        ctx, _, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        await db.execute(BackgroundJob.__table__.delete())

        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)

        job = await db.scalar(
            select(BackgroundJob).where(BackgroundJob.kind == "search-improvement")
        )
        assert job is not None and job.pool == "eval"
        assert job.concurrency_key == f"improvement-search:{ctx.organization_id}"
        assert job.dedupe_key == f"improvement-search:{read.id}"

    async def test_a_variant_whose_scoring_keeps_dying_is_given_up(self, db):
        ctx, _, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        seed = await db.scalar(select(ImprovementSearchVariant))
        assert seed is not None
        seed.attempts = 2
        await db.flush()

        await _units(db, ctx, read.id, Searcher(db))

        assert seed.status == "failed"
        assert (await _iteration(db, read.id)).search["stop_reason"] == "no_variant"  # ty: ignore[not-subscriptable]

    async def test_a_result_for_a_variant_already_settled_is_dropped(self, db):
        ctx, _, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        seed = await db.scalar(select(ImprovementSearchVariant))
        assert seed is not None

        async def settled_elsewhere(prompt: str) -> None:
            seed.status = "failed"

        await _units(db, ctx, read.id, Searcher(db, before=settled_elsewhere))

        assert seed.train_score is None and seed.cases_scored == 0

    async def test_a_unit_that_finishes_after_the_session_moved_on_records_nothing(self, db):
        ctx, _, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        run = await db.get(ImprovementRun, read.id)
        assert run is not None

        async def stopped(prompt: str) -> None:
            run.status = "cancelled"

        model = Searcher(db, before=stopped)
        with (
            _answering(model),
            patch("app.services.improvement_search.CASE_PARALLELISM", 1),
        ):
            await SearchWorker(read.id, ctx.organization_id, sessions=_sessions(db)).run()
            seed = await db.scalar(select(ImprovementSearchVariant))
            assert seed is not None and seed.status == "pending" and seed.attempts == 1
            await SearchWorker(read.id, ctx.organization_id, sessions=_sessions(db)).run()
        assert seed.attempts == 1
        # The questions still waiting when the session stopped were never asked.
        assert len(model.asked) == 1

    async def test_a_unit_after_the_draft_changed_spends_nothing(self, db):
        ctx, agent, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        agent.draft_spec = {**agent.draft_spec, "instructions": INSTRUCTIONS + "\nNew rule."}
        await db.flush()
        model = Searcher(db)

        with _answering(model):
            await SearchWorker(read.id, ctx.organization_id, sessions=_sessions(db)).run()

        assert model.asked == [] and model.proposals == []
        seed = await db.scalar(select(ImprovementSearchVariant))
        assert seed is not None and seed.attempts == 0
        advance = await db.scalar(
            select(BackgroundJob).where(BackgroundJob.dedupe_key == f"{read.id}:search:1")
        )
        assert advance is not None
        run = await _finish(db, ctx, read.id)
        assert run.status == "stale"

    async def test_a_search_that_makes_no_progress_fails_and_can_be_retried(self, db):
        ctx, agent, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        run = await db.get(ImprovementRun, read.id)
        assert run is not None
        long_ago = datetime.now(UTC) - timedelta(hours=2)
        run.heartbeat_at = run.stage_started_at = run.created_at = long_ago
        await db.flush()

        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)

        assert (run.status, run.stage, run.stop_reason) == ("failed", "searching", "stalled")
        await db.execute(BackgroundJob.__table__.delete())
        retried = await ImprovementPipelineService(db).retry(ctx, agent.id, read.id)
        assert (retried.status, retried.stage) == ("running", "searching")
        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
        assert await db.scalar(
            select(BackgroundJob).where(BackgroundJob.kind == "search-improvement")
        )

        # Stalled again, the next step the console offers resumes the same search.
        run.heartbeat_at = run.stage_started_at = long_ago
        await db.flush()
        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
        assert run.stop_reason == "stalled"
        resumed = await _next_step(db, ctx, read.id)
        assert (resumed.status, resumed.stage) == ("running", "searching")

    async def test_a_proposal_that_returns_after_the_session_moved_on_records_nothing(self, db):
        ctx, _, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        run = await db.get(ImprovementRun, read.id)
        assert run is not None

        async def cancelled() -> None:
            run.status = "cancelled"

        with (
            _answering(Searcher(db, proposing=cancelled)),
            patch("app.services.improvement_search.CASE_PARALLELISM", 1),
        ):
            for _ in range(2):
                await SearchWorker(read.id, ctx.organization_id, sessions=_sessions(db)).run()

        assert [v.generation for v in await db.scalars(select(ImprovementSearchVariant))] == [0]

    async def test_a_search_whose_questions_were_erased_ends(self, db):
        ctx, _, data, read = await _start(db)
        await _to_search(db, ctx, read.id)
        for row in await db.scalars(select(DatasetCase).where(DatasetCase.dataset_id == data.id)):
            if row.input.startswith("Train"):
                row.anonymised_at = datetime.now(UTC)
        await db.flush()

        await _units(db, ctx, read.id, Searcher(db))

        assert (await _iteration(db, read.id)).search["stop_reason"] == "questions"  # ty: ignore[not-subscriptable]

    async def test_a_search_whose_questions_cannot_be_priced_ends(self, db):
        ctx, _, _, read = await _start(db)
        await _to_search(db, ctx, read.id)

        with patch.object(
            EvalRunService, "estimate", new=AsyncMock(side_effect=BadRequestError(message="No"))
        ):
            await _units(db, ctx, read.id, Searcher(db))

        assert (await _iteration(db, read.id)).search["stop_reason"] == "questions"  # ty: ignore[not-subscriptable]

    async def test_a_proposal_that_fails_ends_the_search(self, db):
        ctx, _, _, read = await _start(db)
        await _to_search(db, ctx, read.id)

        await _units(db, ctx, read.id, Searcher(db, variants=[{"not": "a variant"}]))

        assert (await _iteration(db, read.id)).search["stop_reason"] == "proposal"  # ty: ignore[not-subscriptable]

    async def test_a_unit_whose_actor_lost_access_hands_the_session_back(self, db):
        ctx, _, _, read = await _start(db)
        await _to_search(db, ctx, read.id)

        with patch(
            "app.services.improvement_search.job_context",
            new=AsyncMock(side_effect=AuthenticationError(message="gone")),
        ):
            await SearchWorker(read.id, ctx.organization_id, sessions=_sessions(db)).run()

        advance = await db.scalar(
            select(BackgroundJob).where(BackgroundJob.dedupe_key == f"{read.id}:search:1")
        )
        assert advance is not None and advance.kind == "advance-improvement"
        assert (await _iteration(db, read.id)).search.get("stop_reason") is None  # ty: ignore[possibly-missing-attribute]

    async def test_a_unit_does_nothing_for_a_session_not_searching(self, db):
        ctx, _, _, read = await _start(db)

        await SearchWorker(read.id, ctx.organization_id, sessions=_sessions(db)).run()

        assert await db.scalar(select(ImprovementSearchVariant)) is None

    async def test_the_pinned_questions_of_a_missing_version_are_none(self, db):
        ctx, _, data, _ = await _start(db)
        questions = await ImprovementSearchService(db).train_questions(
            organization_id=ctx.organization_id, dataset_id=data.id, dataset_version=99, drawn=None
        )
        assert questions == []


class TestChoice:
    async def _at_changes(self, db):
        ctx, agent, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        model = Searcher(
            db,
            variants=[
                {"instructions": _KINDLY, "rationale": "Kindly"},
                {"instructions": _WINDOW, "rationale": "Name the window"},
            ],
        )
        await _units(db, ctx, read.id, model)
        await _finish(db, ctx, read.id)
        return ctx, agent, read

    async def test_a_person_brings_another_of_the_best_variants_to_changes(self, db):
        ctx, agent, read = await self._at_changes(db)
        service = ImprovementPipelineService(db)
        found = (await service.read(ctx, agent.id, read.id)).iterations[0].variant_search
        assert found is not None and [v.instructions for v in found.top] == [_WINDOW, _KINDLY]
        first = (await _iteration(db, read.id)).batch_id

        chosen = await service.choose_variant(
            ctx, agent.id, read.id, SearchChoice(variant_id=found.top[1].id)
        )
        await service.advance(read.id, ctx.organization_id)

        iteration = await _iteration(db, read.id)
        assert chosen.iterations[0].variant_search.chosen_variant_id == found.top[1].id  # ty: ignore[possibly-missing-attribute]
        replaced = await db.get(SpecProposalBatch, first)
        assert replaced is not None and replaced.status == "superseded"
        hunks = await db.scalars(
            select(SpecProposalHunk.new_text).where(SpecProposalHunk.batch_id == iteration.batch_id)
        )
        assert [text.endswith("Say kindly that refunds take 30 days.") for text in hunks] == [True]
        run = await db.get(ImprovementRun, read.id)
        assert run is not None and run.status == "waiting" and run.stage == "filtering"
        again = await service.choose_variant(
            ctx, agent.id, read.id, SearchChoice(variant_id=found.top[1].id)
        )
        assert again.iterations[0].batch_id == iteration.batch_id

    async def test_only_the_offered_variants_and_only_in_the_sessions_organization(self, db):
        ctx, agent, read = await self._at_changes(db)
        service = ImprovementPipelineService(db)
        seed = await db.scalar(
            select(ImprovementSearchVariant).where(ImprovementSearchVariant.generation == 0)
        )
        assert seed is not None
        with pytest.raises(NotFoundError, match="not one of the search's best"):
            await service.choose_variant(ctx, agent.id, read.id, SearchChoice(variant_id=seed.id))
        stranger = await _owner(db)
        with pytest.raises(NotFoundError):
            await service.choose_variant(
                stranger, agent.id, read.id, SearchChoice(variant_id=seed.id)
            )


class TestVariantText:
    async def test_a_viewer_reads_the_search_but_not_its_variants(self, db):
        """A variant is written from training questions and reference answers, which
        need runs:view; a Viewer sees the search's progress without them."""
        ctx, agent, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        await _units(db, ctx, read.id, Searcher(db))
        await _finish(db, ctx, read.id)
        viewer = await _member(db, ctx, OrgRoleName.VIEWER)
        agent.visibility = "org"
        await db.flush()
        service = ImprovementPipelineService(db)

        owner = (await service.read(ctx, agent.id, read.id)).iterations[0].variant_search
        seen = (await service.read(viewer, agent.id, read.id)).iterations[0].variant_search

        assert owner is not None and owner.top
        assert seen is not None and seen.top == []
        assert seen.best_score == owner.best_score and seen.tried == owner.tried

    async def test_without_running_the_dataset_the_variants_stay_hidden(self, db):
        ctx, agent, _, read = await _start(db)
        await _to_search(db, ctx, read.id)
        await _units(db, ctx, read.id, Searcher(db))
        await _finish(db, ctx, read.id)

        with patch.object(
            DatasetService, "get", new=AsyncMock(side_effect=AuthorizationError(message="No"))
        ):
            seen = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)

        search = seen.iterations[0].variant_search
        assert search is not None and search.top == [] and search.best_score == 1.0

    async def test_another_organization_cannot_read_the_search(self, db):
        ctx, agent, _, read = await _start(db)
        stranger = await _owner(db)
        with pytest.raises(NotFoundError):
            await ImprovementPipelineService(db).read(stranger, agent.id, read.id)


class TestRefusals:
    async def test_a_search_needs_ten_training_questions(self, db):
        ctx, agent, _ = await _setup(db)
        data = await _dataset(db, ctx, train=9)
        with pytest.raises(ValidationError) as refused:
            await ImprovementPipelineService(db).start(
                ctx,
                agent.id,
                ImprovementStart(
                    dataset_id=data.id, budget_usd=Decimal("10"), mode="search", search=_options()
                ),
            )
        assert refused.value.status_code == 422
        assert refused.value.details["fields"][0]["field"] == "mode"
        assert refused.value.details["train_questions"] == 9

    async def test_the_search_budget_must_fit_the_sessions(self, db):
        ctx, agent, _ = await _setup(db)
        data = await _dataset(db, ctx)
        with pytest.raises(BadRequestError, match="fit within the session"):
            await ImprovementPipelineService(db).start(
                ctx,
                agent.id,
                ImprovementStart(
                    dataset_id=data.id,
                    budget_usd=Decimal("2"),
                    mode="search",
                    search=_options(budget_usd=Decimal("3")),
                ),
            )

    @pytest.mark.parametrize(
        ("where", "model", "message"),
        [
            ("elsewhere", "gpt-4o-mini", "from this organization"),
            ("here", "text-embedding-3-small", "answers messages"),
        ],
    )
    async def test_the_grading_model_must_be_this_organizations_and_answer(
        self, db, where: str, model: str, message: str
    ):
        ctx, agent, _ = await _setup(db)
        data = await _dataset(db, ctx)
        owner = ctx if where == "here" else await _owner(db)
        profile = ModelProfile(
            id=uuid.uuid4(),
            organization_id=owner.organization_id,
            label=f"{model}-{uuid.uuid4().hex[:4]}",
            provider="openai",
            model=model,
            secret_id=await provider_key(db, owner.organization_id),
        )
        db.add(profile)
        await db.flush()
        with pytest.raises(BadRequestError, match=message):
            await ImprovementPipelineService(db).start(
                ctx,
                agent.id,
                ImprovementStart(
                    dataset_id=data.id,
                    budget_usd=Decimal("10"),
                    mode="search",
                    search=_options(grading_model_profile_id=profile.id),
                ),
            )

    async def test_a_chosen_grading_model_of_the_organization_is_kept(self, db):
        ctx, agent, _ = await _setup(db)
        data = await _dataset(db, ctx)
        profile = ModelProfile(
            id=uuid.uuid4(),
            organization_id=ctx.organization_id,
            label=f"grader-{uuid.uuid4().hex[:4]}",
            provider="openai",
            model="gpt-4o-mini",
            secret_id=await provider_key(db, ctx.organization_id),
        )
        db.add(profile)
        await db.flush()
        read = await ImprovementPipelineService(db).start(
            ctx,
            agent.id,
            ImprovementStart(
                dataset_id=data.id,
                budget_usd=Decimal("10"),
                mode="search",
                search=_options(grading_model_profile_id=profile.id),
            ),
        )
        settings = (await _iteration(db, read.id)).search["settings"]  # ty: ignore[not-subscriptable]
        assert settings["grading_model_profile_id"] == str(profile.id)

    async def test_a_viewer_cannot_start_a_search(self, db):
        ctx, agent, _ = await _setup(db)
        data = await _dataset(db, ctx)
        viewer = await _member(db, ctx, OrgRoleName.VIEWER)
        with pytest.raises(NotFoundError):
            await ImprovementPipelineService(db).start(
                viewer,
                agent.id,
                ImprovementStart(
                    dataset_id=data.id, budget_usd=Decimal("10"), mode="search", search=_options()
                ),
            )

    async def test_a_second_session_on_the_agent_is_refused(self, db):
        ctx, agent, data, _ = await _start(db)
        with pytest.raises(ConcurrentChangeError):
            await ImprovementPipelineService(db).start(
                ctx,
                agent.id,
                ImprovementStart(
                    dataset_id=data.id, budget_usd=Decimal("10"), mode="search", search=_options()
                ),
            )

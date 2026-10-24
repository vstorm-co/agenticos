"""Held-out verdicts and source exclusion across actual dataset revisions and eval jobs."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext
from app.db.models.dataset import DatasetCase
from app.schemas.dataset import (
    DatasetCaseContent,
    DatasetCaseCreate,
    DatasetCaseUpdate,
    DatasetCreate,
    DatasetUpdate,
)
from app.schemas.eval_run import EvalRunRequest, ProposalCheckRecord
from app.schemas.improvement import ImprovementStart
from app.services.agent_registry import UnpublishedCandidate
from app.services.agent_runner import AgentRunnerService
from app.services.dataset import DatasetService, GeneratedCase
from app.services.eval_run import EvalRunService
from app.services.eval_run_worker import EvalRunWorker
from app.services.improvement_data import case_partition
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_authoring import _sessions, _setup
from tests.integration.test_eval_suites import Model, _dataset, _owner

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def test_membership_is_stable_across_edits_versions_and_changed_future_share(db):
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="Stable split"))
    first = await service.add_case(
        ctx, dataset.id, DatasetCaseCreate(input="A question", reference_answer="An answer")
    )
    assigned = case_partition(first.case_id, Decimal("0.5"))
    assert first.improvement_partition == assigned
    future_share = Decimal(0) if assigned == "holdout" else Decimal(1)
    await service.update(ctx, dataset.id, DatasetUpdate(improvement_holdout_share=future_share))
    edited = await service.update_case(
        ctx, dataset.id, first.case_id, DatasetCaseUpdate(input="Edited question")
    )
    older = await service.read_case(ctx, dataset.id, first.case_id, version=1)
    assert edited.id != first.id
    assert edited.improvement_partition == older.improvement_partition == assigned
    second = await service.add_case(
        ctx, dataset.id, DatasetCaseCreate(input="New question", reference_answer="Another answer")
    )
    assert second.improvement_partition != assigned
    read = await service.read(ctx, dataset.id)
    assert (read.stats.train_cases, read.stats.holdout_cases) == (1, 1)
    assert read.improvement_holdout_share == future_share


class Answers(Model):
    def __init__(self, db: AsyncSession, *, train_passes: bool) -> None:
        super().__init__(db)
        self.train_passes = train_passes

    async def execute(
        self,
        runner: AgentRunnerService,
        ctx: AuthContext,
        agent_id: UUID,
        prompt: str,
        **kw: object,
    ):
        candidate = kw["candidate"]
        assert isinstance(candidate, UnpublishedCandidate)
        _, run = await super().execute(runner, ctx, agent_id, prompt, **kw)
        changed = "30 days" in candidate.spec.instructions
        train = prompt in {"Question 0", "Question 1"}
        return ("30 days" if changed and (not train or self.train_passes) else "90 days"), run


async def test_verdict_ignores_training_results_but_preserves_them_for_the_next_round(db):
    ctx, agent, _ = await _setup(db)
    dataset = await _dataset(db, ctx, cases=7)
    revisions = list(
        await db.scalars(
            select(DatasetCase)
            .where(DatasetCase.dataset_id == dataset.id, DatasetCase.removed_in.is_(None))
            .order_by(DatasetCase.position)
        )
    )
    for row in revisions[:2]:
        row.improvement_partition = "train"
    await db.flush()
    service = EvalRunService(db)
    baseline = AgentSpec.model_validate(agent.draft_spec)
    candidate = baseline.model_copy(update={"instructions": baseline.instructions + " 30 days"})
    comparisons = []
    raw = []
    for train_passes in [True, False]:
        started = await service.start(
            ctx,
            agent.id,
            EvalRunRequest(dataset_id=dataset.id, paired_baseline=True),
            candidate_spec=candidate,
            baseline_spec=baseline,
            proposal_check=ProposalCheckRecord(
                kind="agent", base_version=None, on_draft=True, suggestions=1
            ),
        )
        assert started.proposal_check is not None and started.proposal_check.measurement is not None
        assert len(started.proposal_check.measurement.train_case_ids) == 2
        assert started.proposal_check.measurement.gradable_holdout == 5
        model = Answers(db, train_passes=train_passes)

        async def execute(runner, *args, _model=model, **kwargs):
            return await _model.execute(runner, *args, **kwargs)

        with (
            patch.object(AgentRunnerService, "execute", new=execute),
            patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
        ):
            await EvalRunWorker(
                started.id, ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock()
            ).run()
        comparisons.append(await service.compare(ctx, started.id))
        raw.append(await service.compare(ctx, started.id, measurement_only=False))
    assert [
        (result.verdict, result.fixed_confirmed, result.candidate_summary.pass_rate)
        for result in comparisons
    ] == [("better", 5, 1.0), ("better", 5, 1.0)]
    assert [result.fixed_confirmed for result in raw] == [7, 5]
    assert all(result.compared == 5 for result in comparisons)


async def test_hand_entered_and_generated_evidence_copies_cannot_become_holdout(db):
    ctx, agent, source = await _setup(db)
    service = DatasetService(db)
    dataset = await _dataset(db, ctx, cases=5)
    pack = await ImprovementPipelineService(db).authoring.evidence.for_agent(
        ctx, agent.id, window_days=30
    )
    [evidence] = pack.runs
    duplicate = await service.add_case(
        ctx,
        dataset.id,
        DatasetCaseCreate(input="  " + evidence.prompt.upper() + "  ", reference_answer="30 days"),
    )
    locked = await service.lock_for_edit(ctx, dataset.id)
    await service.add_generated(
        ctx,
        locked,
        [
            GeneratedCase(
                content=DatasetCaseContent(
                    input="Generated paraphrase from this run", reference_answer="30 days"
                ),
                source_run_id=source.id,
            )
        ],
    )
    generated = await db.scalar(
        select(DatasetCase).where(
            DatasetCase.dataset_id == dataset.id, DatasetCase.source_run_id == source.id
        )
    )
    assert generated is not None
    draft = AgentSpec.model_validate(agent.draft_spec)
    estimate = await EvalRunService(db).estimate(
        ctx,
        agent.id,
        EvalRunRequest(dataset_id=dataset.id, paired_baseline=True),
        candidate_spec=draft,
        baseline_spec=draft,
        proposal_check=ProposalCheckRecord(
            kind="agent",
            base_version=None,
            on_draft=True,
            suggestions=1,
            evidence_run_ids=[source.id],
        ),
    )
    assert estimate.proposal_check is not None and estimate.proposal_check.measurement is not None
    measured = estimate.proposal_check.measurement
    assert set(measured.excluded_case_ids) == {duplicate.case_id, generated.case_id}
    assert measured.gradable_holdout == 5


async def test_a_session_below_the_holdout_minimum_stops_with_an_actionable_reason(db):
    ctx, agent, _ = await _setup(db)
    dataset = await _dataset(db, ctx, cases=4)
    service = ImprovementPipelineService(db)
    started = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, budget_usd=Decimal(5), max_iterations=1),
    )
    await service.advance(started.id, ctx.organization_id)
    await service.advance(started.id, ctx.organization_id)
    stopped = await service.read(ctx, agent.id, started.id)
    assert (stopped.status, stopped.stop_reason) == ("stopped", "no_data")
    assert stopped.error == "Add 1 more held-out test questions to measure a change"
    assert stopped.iterations[0].authoring_request_id is None
    assert stopped.iterations[0].verdict_detail["missing_holdout"] == 1


async def test_improver_reads_train_failures_review_notes_and_aggregates_without_holdout_text(db):
    from app.core.permissions import OrgRoleName
    from app.db.models.authoring import HunkKind
    from app.db.models.case_score import CaseScore
    from app.db.models.eval_run import EvalRunArm, EvalRunCase
    from app.repositories import authoring_repo, personal_data_repo
    from app.schemas.authoring import AuthoringStart
    from app.services.authoring import AuthoringService
    from app.services.authoring_worker import AuthoringWorker
    from tests.integration.test_authoring import Improver, _answering, _member

    ctx, agent, _ = await _setup(db)
    reviewer = await _member(db, ctx, OrgRoleName.BUILDER)
    dataset = await _dataset(db, ctx, cases=7)
    revisions = list(
        await db.scalars(
            select(DatasetCase)
            .where(DatasetCase.dataset_id == dataset.id)
            .order_by(DatasetCase.position)
        )
    )
    for index, row in enumerate(revisions):
        train = index < 2
        row.improvement_partition = "train" if train else "holdout"
        row.input = f"{'TRAIN' if train else 'HOLDOUT'}_INPUT_MARKER_{index}"
        row.tags = ["TRAIN_TAG_MARKER" if train else "HOLDOUT_TAG_MARKER"]
    await db.flush()
    draft = AgentSpec.model_validate(agent.draft_spec)
    started = await EvalRunService(db).start(
        ctx,
        agent.id,
        EvalRunRequest(dataset_id=dataset.id, paired_baseline=True),
        candidate_spec=draft,
        baseline_spec=draft,
        proposal_check=ProposalCheckRecord(
            kind="agent", base_version=None, on_draft=True, suggestions=1
        ),
    )
    model = Model(
        db,
        answer=lambda prompt: (
            "90 days "
            + ("TRAIN_ANSWER_MARKER" if prompt.startswith("TRAIN") else "HOLDOUT_ANSWER_MARKER")
        ),
    )

    async def execute(runner, *args, **kwargs):
        return await model.execute(runner, *args, **kwargs)

    with (
        patch.object(AgentRunnerService, "execute", new=execute),
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
    ):
        await EvalRunWorker(
            started.id, ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock()
        ).run()
    rows = await db.execute(
        select(CaseScore, DatasetCase, EvalRunCase)
        .join(DatasetCase, DatasetCase.id == CaseScore.case_revision_id)
        .join(EvalRunCase, EvalRunCase.case_score_id == CaseScore.id)
        .join(EvalRunArm, EvalRunArm.id == EvalRunCase.arm_id)
        .where(CaseScore.eval_run_id == started.id, EvalRunArm.role == "candidate")
    )
    train_run_id = None
    for score, revision, attempt in rows:
        train = revision.improvement_partition == "train"
        score.human_note = "TRAIN_REVIEW_MARKER" if train else "HOLDOUT_REVIEW_MARKER"
        score.reviewed_by_user_id = reviewer.user_id if train else ctx.user_id
        score.results = [
            *score.results,
            {
                "scorer": "judge",
                "name": "TRAIN_CRITERION_MARKER" if train else "HOLDOUT_CRITERION_MARKER",
                "required": True,
                "status": "fail",
                "score": 0,
                "reason": "TRAIN_JUDGE_REASON_MARKER" if train else "HOLDOUT_JUDGE_REASON_MARKER",
            },
        ]
        if train:
            train_run_id = attempt.agent_run_id
    await db.flush()
    assert train_run_id is not None
    assistant = Improver(db)
    request = await AuthoringService(db).start_agent(ctx, agent.id, AuthoringStart())
    with _answering(assistant):
        await AuthoringWorker(request.id, ctx.organization_id, sessions=_sessions(db)).run()
    prompt = "\n".join(assistant.prompts)
    for marker in [
        "TRAIN_INPUT_MARKER",
        "TRAIN_ANSWER_MARKER",
        "TRAIN_REVIEW_MARKER",
        "TRAIN_TAG_MARKER",
        "TRAIN_CRITERION_MARKER",
        "TRAIN_JUDGE_REASON_MARKER",
    ]:
        assert marker in prompt
    assert "HOLDOUT_" not in prompt
    assert "TRAIN_TAG_MARKER: 0/2 passed" in prompt
    assert "TRAIN_CRITERION_MARKER: 0/2 passed" in prompt
    # Copies of a reviewer's words are erased even when somebody else ran the eval.
    batch = await authoring_repo.get_open_batch(
        db, organization_id=ctx.organization_id, agent_id=agent.id
    )
    assert batch is not None
    [note, answer] = await authoring_repo.add_hunks(
        db,
        organization_id=ctx.organization_id,
        batch_id=batch.id,
        hunks=[
            {
                "kind": HunkKind.INSTRUCTIONS.value,
                "origin": "improve",
                "old_text": "",
                "new_text": "A suggestion",
                "evidence": [{"run_id": str(train_run_id), "quote": quoted}],
            }
            for quoted in ["TRAIN_REVIEW_MARKER", "TRAIN_ANSWER_MARKER"]
        ],
    )
    comments = await personal_data_repo.comments_of(db, reviewer.user_id)
    assert "TRAIN_REVIEW_MARKER" in comments[train_run_id]
    await personal_data_repo.purge_evidence_of(db, reviewer.user_id, comments=comments)
    assert note.evidence == []
    assert answer.evidence == [{"run_id": str(train_run_id), "quote": "TRAIN_ANSWER_MARKER"}]


async def test_session_freezes_chat_sources_and_excludes_later_conversations(db):
    from app.db.models.conversation import Message
    from tests.integration.test_authoring import _rated

    ctx, agent, original = await _setup(db)
    dataset = await _dataset(db, ctx, cases=5)
    pipeline = ImprovementPipelineService(db)
    started = await pipeline.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, budget_usd=Decimal(5), max_iterations=1),
    )
    later = await _rated(db, ctx, agent, comment="LATER_CHAT_MARKER")
    message = await db.scalar(
        select(Message).where(Message.run_id == later.id, Message.role == "user")
    )
    assert message is not None
    message.content = "LATER_QUESTION_MARKER"
    await db.flush()
    fresh = await pipeline.authoring.evidence.for_agent(ctx, agent.id, window_days=30)
    assert later.id in {item.run_id for item in fresh.runs}
    frozen = await pipeline.authoring.evidence.for_improvement(ctx, started.id)
    assert {item.run_id for item in frozen.runs} == {original.id}
    assert "LATER_" not in "\n".join(item.source for item in frozen.runs)
    from app.services.authoring_worker import AuthoringWorker
    from tests.integration.test_authoring import Improver, _answering
    from tests.integration.test_improvement_pipeline import _until_child

    await _until_child(db, ctx, started.id)
    queued = await pipeline.read(ctx, agent.id, started.id)
    request_id = queued.iterations[0].authoring_request_id
    assert request_id is not None
    improver = Improver(db)
    with _answering(improver):
        await AuthoringWorker(request_id, ctx.organization_id, sessions=_sessions(db)).run()
    assert improver.prompts
    assert "LATER_" not in "\n".join(improver.prompts)


async def test_queued_proposal_rechecks_session_pins_before_paying(db):
    from app.services.authoring import AuthoringService
    from app.services.authoring_worker import AuthoringWorker
    from tests.integration.test_authoring import Improver, _answering
    from tests.integration.test_improvement_pipeline import _started, _until_child

    ctx, agent, _, started = await _started(db)
    await _until_child(db, ctx, started.id)
    read = await ImprovementPipelineService(db).read(ctx, agent.id, started.id)
    request_id = read.iterations[0].authoring_request_id
    assert request_id is not None
    agent.draft_spec = {**agent.draft_spec, "instructions": "Changed by a person"}
    await db.flush()
    improver = Improver(db)
    with _answering(improver):
        await AuthoringWorker(request_id, ctx.organization_id, sessions=_sessions(db)).run()
    request = (await AuthoringService(db).for_agent(ctx, agent.id)).latest
    assert request is not None and request.id == request_id and request.status == "failed"
    assert not improver.prompts

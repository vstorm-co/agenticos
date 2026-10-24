"""A draft's measured effect stays separate from the changes to the agent."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConcurrentChangeError
from app.db.models.agent import AgentVersion
from app.db.models.context import ContextFile
from app.db.models.rag_document import RAGDocument
from app.db.models.run_manifest import RunManifest
from app.repositories import dataset_repo, eval_run_repo, knowledge_gap_repo, personal_data_repo
from app.schemas.improvement import ImprovementStart, KnowledgeCheckConsent, KnowledgeCheckTarget
from app.schemas.knowledge_gap import KnowledgeGapContent, KnowledgeGapReport, KnowledgeGapSource
from app.services.agent_registry import UnpublishedCandidate
from app.services.agent_runner import AgentRunnerService
from app.services.eval_run import EvalRunService
from app.services.eval_run_worker import EvalRunWorker
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.knowledge_gaps import KnowledgeGapService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_authoring import _sessions, _setup
from tests.integration.test_eval_suites import Model, _dataset
from tests.integration.test_improvement_pipeline import _ready_proposal
from tests.integration.test_knowledge_gaps import _a_topic

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def _world(db, *, knowledge_search=False):
    ctx, agent, _ = await _setup(db)
    kb, _, topic_id = await _a_topic(db, ctx)
    agent.draft_spec = {**agent.draft_spec, "collection_ids": [str(kb.id)]}
    if knowledge_search:
        agent.draft_spec = {
            **agent.draft_spec,
            "capabilities": [*agent.draft_spec.get("capabilities", []), {"id": "knowledge"}],
        }
    published = await db.get(AgentVersion, agent.current_version_id)
    published.spec = agent.draft_spec
    dataset = await _dataset(db, ctx, cases=8)
    version = await dataset_repo.get_version(
        db, dataset.id, dataset.latest_version, organization_id=ctx.organization_id
    )
    cases = await dataset_repo.list_cases(
        db, version.id, organization_id=ctx.organization_id, limit=None
    )
    evidence = await knowledge_gap_repo.topic_evidence(
        db, topic_id, organization_id=ctx.organization_id
    )
    cases[0].input = "  Where CAN visitors   park? "
    cases[1].improvement_partition = "train"
    cases[2].source_run_id = evidence[0].run_id
    cases[2].source_conversation_id = evidence[0].conversation_id
    await KnowledgeGapService(db).record_draft(
        ctx,
        KnowledgeGapReport(
            topic_id=topic_id,
            title="Returns",
            content="Returns take 30 days.",
            sources=[KnowledgeGapSource(kind="question", id=evidence[0].id)],
        ),
    )
    await db.flush()
    service = ImprovementPipelineService(db)
    started = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, max_iterations=1, budget_usd=Decimal("5")),
    )
    with patch(
        "tests.integration.test_improvement_pipeline._started",
        new=AsyncMock(return_value=(ctx, agent, dataset, started)),
    ):
        _, _, ready = await _ready_proposal(db)
    target = KnowledgeCheckTarget(
        topic_id=topic_id, round=1, case_ids=[case.case_id for case in cases]
    )
    return ctx, agent, ready, target


async def _start(db):
    ctx, agent, ready, target = await _world(db)
    service = ImprovementPipelineService(db)
    quote = await service.estimate_knowledge(ctx, agent.id, ready.id, target)
    assert quote.can_measure and quote.affordable and quote.cases == 5 and quote.excluded == 3
    assert quote.supported is False
    child = await service.start_knowledge(
        ctx,
        agent.id,
        ready.id,
        KnowledgeCheckConsent(
            **target.model_dump(),
            confirmed=True,
            estimate_usd=quote.total_usd,
            draft_hash=quote.draft_hash,
        ),
    )
    return ctx, agent, ready, target, child


async def _answer(db, ctx, child, *, during=None):
    model = Model(db)
    seen = set()

    async def answer(runner, *args, **kwargs):
        candidate = kwargs["candidate"]
        assert isinstance(candidate, UnpublishedCandidate)
        seen.add(bool(candidate.context_bodies))
        _, paid = await model.execute(runner, *args, **kwargs)
        if during is not None:
            await during()
        return ("30 days" if candidate.context_bodies else "90 days"), paid

    with (
        patch.object(AgentRunnerService, "execute", new=answer),
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
    ):
        await EvalRunWorker(
            child.id, ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock()
        ).run()
    return seen


async def test_knowledge_has_its_own_verdict_and_never_creates_a_resource(db: AsyncSession):
    ctx, agent, ready, _, child = await _start(db)
    assert await _answer(db, ctx, child) == {False, True}
    comparison = await EvalRunService(db).compare(ctx, child.id)
    assert comparison.fixed_confirmed == 5 and comparison.regressions_confirmed == 0
    assert comparison.candidate_summary.cases == 5
    after = await ImprovementPipelineService(db).read(ctx, agent.id, ready.id)
    assert after.iterations[0].verdict == ready.iterations[0].verdict
    assert after.iterations[0].eval_run_ids == ready.iterations[0].eval_run_ids
    assert after.knowledge_eval_run_ids == [child.id]
    assert after.spent_usd > ready.spent_usd
    assert await db.scalar(select(func.count()).select_from(ContextFile)) == 0
    assert await db.scalar(select(func.count()).select_from(RAGDocument)) == 0
    arms = await eval_run_repo.list_arms(db, [child.id], organization_id=ctx.organization_id)
    assert all(arm.context_bodies is None for arm in arms)
    assert len({arm.spec_hash for arm in arms}) == 2


async def test_only_source_questions_cannot_be_measured_and_no_paid_child_is_written(db):
    ctx, agent, ready, target = await _world(db)
    service = ImprovementPipelineService(db)
    excluded = target.model_copy(update={"case_ids": target.case_ids[:3]})
    quote = await service.estimate_knowledge(ctx, agent.id, ready.id, excluded)
    assert not quote.can_measure and quote.cases == 0 and quote.total_usd == 0
    with pytest.raises(BadRequestError, match="cannot be measured"):
        await service.start_knowledge(
            ctx,
            agent.id,
            ready.id,
            KnowledgeCheckConsent(
                **excluded.model_dump(),
                confirmed=True,
                estimate_usd=quote.total_usd,
                draft_hash=quote.draft_hash,
            ),
        )
    assert (await service.read(ctx, agent.id, ready.id)).knowledge_eval_run_ids == []


async def test_consent_is_bound_to_price_draft_and_one_active_check(db):
    ctx, agent, ready, target, _ = await _start(db)
    service = ImprovementPipelineService(db)
    quote = await service.estimate_knowledge(ctx, agent.id, ready.id, target)
    for price, hashed in [
        (quote.total_usd + Decimal("1"), quote.draft_hash),
        (quote.total_usd, "0" * 64),
    ]:
        with pytest.raises(ConcurrentChangeError, match="changed"):
            await service.start_knowledge(
                ctx,
                agent.id,
                ready.id,
                KnowledgeCheckConsent(
                    **target.model_dump(), confirmed=True, estimate_usd=price, draft_hash=hashed
                ),
            )
    with pytest.raises(ConcurrentChangeError, match="already running"):
        await service.start_knowledge(
            ctx,
            agent.id,
            ready.id,
            KnowledgeCheckConsent(
                **target.model_dump(),
                confirmed=True,
                estimate_usd=quote.total_usd,
                draft_hash=quote.draft_hash,
            ),
        )


async def test_replacing_a_draft_revokes_a_queued_overlay_before_model_calls(db):
    ctx, agent, ready, target, child = await _start(db)
    await KnowledgeGapService(db).save_content(
        ctx,
        target.topic_id,
        KnowledgeGapContent(title="Updated", content="Check the actual policy."),
    )
    stored = await EvalRunService(db).get(ctx, child.id)
    assert stored.status == "failed" and stored.proposal_check.knowledge.invalidated
    assert await _answer(db, ctx, child) == set()
    arms = await eval_run_repo.list_arms(db, [child.id], organization_id=ctx.organization_id)
    assert all(arm.context_bodies is None for arm in arms)


async def test_erasure_removes_completed_derived_answers_and_overlay(db):
    ctx, agent, ready, _, child = await _start(db)
    await _answer(db, ctx, child)
    attempts = await eval_run_repo.list_cases(db, child.id, organization_id=ctx.organization_id)
    manifest = RunManifest(
        run_id=attempts[0].agent_run_id,
        organization_id=ctx.organization_id,
        payload={
            "system_prompts": ["A source person's private detail"],
            "messages": ["Quoted draft"],
        },
    )
    db.add(manifest)
    await db.flush()
    assert await personal_data_repo.clear_gap_drafts_of(db, ctx.user_id) == 1
    await db.refresh(manifest)
    assert manifest.payload == {} and manifest.truncated
    attempts = await eval_run_repo.list_cases(db, child.id, organization_id=ctx.organization_id)
    assert attempts and all(attempt.answer is None and attempt.calls == [] for attempt in attempts)
    comparison = await EvalRunService(db).compare(ctx, child.id)
    assert comparison.verdict == "invalid"


async def test_cancelling_the_session_cancels_its_knowledge_check_and_clears_bodies(db):
    ctx, agent, ready, _, child = await _start(db)
    await ImprovementPipelineService(db).cancel(ctx, agent.id, ready.id)
    assert (await EvalRunService(db).get(ctx, child.id)).status == "cancelled"
    arms = await eval_run_repo.list_arms(db, [child.id], organization_id=ctx.organization_id)
    assert all(arm.context_bodies is None for arm in arms)


async def test_erasure_while_answering_cannot_recreate_derived_content(db):
    ctx, _, _, _, child = await _start(db)
    called = False

    async def erase():
        nonlocal called
        if not called:
            called = True
            await personal_data_repo.clear_gap_drafts_of(db, ctx.user_id)

    await _answer(db, ctx, child, during=erase)
    attempts = await eval_run_repo.list_cases(db, child.id, organization_id=ctx.organization_id)
    assert called and all(attempt.answer is None and not attempt.calls for attempt in attempts)
    assert (await EvalRunService(db).get(ctx, child.id)).status == "failed"


async def test_too_few_independent_cases_refuse_spend_and_unknown_case_ids_are_rejected(db):
    ctx, agent, ready, target = await _world(db)
    service = ImprovementPipelineService(db)
    selected = target.model_copy(update={"case_ids": target.case_ids[4:]})
    quote = await service.estimate_knowledge(ctx, agent.id, ready.id, selected)
    assert quote.cases == 4 and not quote.can_measure and not quote.affordable
    with pytest.raises(BadRequestError, match="distinct questions"):
        await service.estimate_knowledge(
            ctx, agent.id, ready.id, target.model_copy(update={"case_ids": [uuid4()]})
        )


async def test_erasure_finds_derived_checks_after_source_memberships_were_deleted(db):
    ctx, _, _, _, child = await _start(db)
    await _answer(db, ctx, child)
    await personal_data_repo.purge_knowledge_searches_of(db, ctx.user_id)
    assert await personal_data_repo.clear_gap_drafts_of(db, ctx.user_id) == 1
    attempts = await eval_run_repo.list_cases(db, child.id, organization_id=ctx.organization_id)
    assert all(attempt.answer is None and not attempt.calls for attempt in attempts)


async def test_a_deleted_uncited_question_does_not_become_independent_test_data(db):
    from sqlalchemy import delete

    from app.db.models.knowledge_gap import KnowledgeSearch

    ctx, agent, ready, target = await _world(db)
    await db.execute(
        delete(KnowledgeSearch).where(
            KnowledgeSearch.organization_id == ctx.organization_id,
            KnowledgeSearch.query == "visitor parking",
        )
    )
    quote = await ImprovementPipelineService(db).estimate_knowledge(ctx, agent.id, ready.id, target)
    assert quote.cases == 5 and quote.excluded == 3


async def test_legacy_untracked_draft_is_not_mislabeled_as_a_fresh_measurement(db):
    ctx, agent, ready, target = await _world(db)
    topic = await knowledge_gap_repo.get_topic(
        db, target.topic_id, organization_id=ctx.organization_id
    )
    topic.draft_evidence_run_ids = None
    topic.draft_evidence_input_hashes = None
    await db.flush()
    quote = await ImprovementPipelineService(db).estimate_knowledge(ctx, agent.id, ready.id, target)
    assert (
        quote.reason == "untracked_draft_sources" and not quote.can_measure and quote.total_usd == 0
    )


async def test_draft_provenance_allows_erasure_before_any_check_after_memberships_are_gone(db):
    ctx, _, _, target = await _world(db)
    await personal_data_repo.purge_knowledge_searches_of(db, ctx.user_id)
    assert await personal_data_repo.clear_gap_drafts_of(db, ctx.user_id) == 1
    topic = await knowledge_gap_repo.get_topic(
        db, target.topic_id, organization_id=ctx.organization_id
    )
    await db.refresh(topic)
    assert (
        topic.draft_content is None
        and topic.draft_evidence_run_ids is None
        and topic.draft_evidence_input_hashes is None
    )

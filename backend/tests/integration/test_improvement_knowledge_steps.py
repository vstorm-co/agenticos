"""Automatic knowledge work uses frozen sources, caller scopes and the session ledger."""

from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.agents.capabilities.budget import record_ambient_cost
from app.agents.system_agents import KNOWLEDGE_GAP_CLASSIFIER, KNOWLEDGE_GAP_DRAFTER
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import OrgRoleName, Perm
from app.db.models.agent import AgentVersion
from app.db.models.agent_run import AgentRun
from app.db.models.api_key import ApiKey
from app.db.models.authoring import AuthoringRequest
from app.db.models.background_job import BackgroundJob
from app.db.models.improvement import ImprovementRun
from app.db.models.ingestion_spend import IngestionSpend
from app.db.models.knowledge_gap import KnowledgeGapMember, KnowledgeGapTopic
from app.repositories import dataset_repo, improvement_repo, knowledge_gap_repo
from app.schemas.api_key import ApiKeyCreate
from app.schemas.improvement import EvidenceDecisionUpdate, ImprovementStart, ImprovementTarget
from app.services.api_key import ApiKeyService
from app.services.embedding_resolution import EmbeddingKeySource, ResolvedEmbeddings
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.knowledge_gaps import KnowledgeGapService
from app.services.model_profile import ModelProfileService
from app.worker.jobs import ClassifyGaps, DraftGaps
from app.worker.tasks.knowledge_gap_tasks import classify_knowledge_gaps, draft_knowledge_gaps
from tests.integration.test_authoring import Improver, _answering, _published, _sessions, _setup
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_eval_suites import _dataset
from tests.integration.test_knowledge_gap_signals import _ANSWER, _asked, _decide, _rated_down
from tests.integration.test_knowledge_gaps import _knowledge_base, _meaning, _member, _searched

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


class Helpers(Improver):
    def _answer(self, prompt):
        text = prompt.split("\n\nAnswer with one JSON object")[0]
        if text.startswith("An agent answered these questions"):
            return {
                "answers": [
                    {"number": int(n), "signal": _decide(block), "reason": "Source classification"}
                    for n, block in _ANSWER.findall(text)
                ]
            }
        if text.startswith('The knowledge base "'):
            return {
                "title": "Parking",
                "content": "Visitors can park at {{parking location}}.",
                "questions": [1, 2],
            }
        return super()._answer(prompt)


@contextmanager
def _providers(db, ctx, *, fail_draft=False):
    resolved = ResolvedEmbeddings(
        model="text-embedding-3-small",
        dim=3,
        api_key="fixture",
        key_source=EmbeddingKeySource.ORGANIZATION,
        base_url="https://api.openai.com/v1",
        provider="openai",
        vector_tenant=ctx.organization_id,
    )
    model = Helpers(db)
    if fail_draft:
        original = model._answer

        def answer(prompt):
            if prompt.startswith('The knowledge base "'):
                return {"invalid": True}
            return original(prompt)

        model._answer = answer

    def embed(queries):
        record_ambient_cost("text-embedding-3-small", Decimal("0.0002"))
        return [_meaning(q) for q in queries]

    with (
        patch.object(
            ModelProfileService,
            "resolve",
            new=AsyncMock(
                return_value=SimpleNamespace(model="gpt-4o-mini", provider="openai", label="Helper")
            ),
        ),
        patch(
            "app.services.knowledge_gaps.embeddings_for_collection",
            new=AsyncMock(return_value=resolved),
        ),
        patch(
            "app.services.knowledge_gaps.embedder_for",
            return_value=SimpleNamespace(embed_queries=embed),
        ),
        patch("app.worker.tasks.knowledge_gap_tasks.get_worker_db_context", _sessions(db)),
        patch(
            "app.worker.tasks.knowledge_gap_tasks.change_feed.connect_in_worker", new=AsyncMock()
        ),
        patch(
            "app.worker.tasks.knowledge_gap_tasks.change_feed.publish_knowledge_gaps_grouped",
            new=AsyncMock(),
        ),
        _answering(model),
    ):
        yield model


async def _world(db, *, askers=2):
    ctx, agent, original = await _setup(db)
    kb = await _knowledge_base(db, ctx)
    agent.draft_spec = {**agent.draft_spec, "collection_ids": [str(kb.id)]}
    version = await db.get(AgentVersion, agent.current_version_id)
    version.spec = agent.draft_spec
    for definition in (KNOWLEDGE_GAP_CLASSIFIER, KNOWLEDGE_GAP_DRAFTER):
        await _published(
            db,
            ctx,
            name=definition.name,
            spec={"name": definition.name},
            kind=definition.kind.value,
            system_key=definition.key,
        )
    source_ids = [original.id]
    actors = [ctx] + [await _member(db, ctx, OrgRoleName.MEMBER) for _ in range(askers - 1)]
    for actor in actors:
        run, answer = await _asked(
            db,
            actor,
            agent,
            question="Parking for visitors?",
            answer="I don't know.",
            version=version,
        )
        await _rated_down(db, answer, actor.user_id, "Missing parking instructions")
        source_ids.append(run.id)
    dataset = await _dataset(db, ctx, cases=5)
    held_version = await dataset_repo.get_version(
        db, dataset.id, dataset.latest_version, organization_id=ctx.organization_id
    )
    held_cases = await dataset_repo.list_cases(
        db, held_version.id, organization_id=ctx.organization_id, limit=None
    )
    held_cases[0].input = "HELD_OUT_ONLY_MUST_STAY_PRIVATE"
    await db.flush()
    return ctx, agent, kb, dataset, source_ids


async def _start(db, ctx, agent, dataset):
    service = ImprovementPipelineService(db)
    quote = await service.estimate(
        ctx, agent.id, ImprovementTarget(dataset_id=dataset.id, max_iterations=1)
    )
    assert quote.knowledge_usd > 0
    assert quote.total_usd == quote.per_round_usd + quote.knowledge_usd
    run = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, max_iterations=1, budget_usd=Decimal("5")),
    )
    for _ in range(3):
        await service.advance(run.id, ctx.organization_id)
    return await service.read(ctx, agent.id, run.id)


async def _job(db, run, *, draft=False):
    iteration = await improvement_repo.get_iteration(
        db, organization_id=run.organization_id, run_id=run.id, number=1
    )
    job = await db.get(
        BackgroundJob, iteration.draft_job_id if draft else iteration.classify_job_id
    )
    return job, DraftGaps.model_validate(job.payload) if draft else ClassifyGaps.model_validate(
        job.payload
    )


async def _classify(db, ctx, agent, read):
    stored = await db.get(ImprovementRun, read.id)
    job, payload = await _job(db, stored)
    found = await classify_knowledge_gaps(payload)
    job.status = "succeeded"
    await db.flush()
    service = ImprovementPipelineService(db)
    await service.advance(read.id, ctx.organization_id)
    await service.advance(read.id, ctx.organization_id)
    return stored, found


async def test_session_classifies_and_drafts_frozen_sources_without_changing_the_agent(db):
    ctx, agent, kb, dataset, sources = await _world(db)
    original = dict(agent.draft_spec)
    with _providers(db, ctx) as model:
        read = await _start(db, ctx, agent, dataset)
        outsider, answer = await _asked(
            db, ctx, agent, question="UNRELATED_SOURCE parking", answer="I don't know."
        )
        await _rated_down(db, answer, ctx.user_id, "missing")
        await _searched(db, ctx, outsider, kb, query="UNRELATED_SOURCE parking")
        stored, found = await _classify(db, ctx, agent, read)
        assert found == 2 and stored.stage == "drafting"
        job, payload = await _job(db, stored, draft=True)
        assert await draft_knowledge_gaps(payload) == 1
        job.status = "succeeded"
        await db.flush()
        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
        assert stored.stage == "proposing"
        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
        current = await improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=read.id, number=1
        )
        request = await db.get(AuthoringRequest, current.authoring_request_id)
        assert len(request.excluded_message_ids) == 2
        remaining = await ImprovementPipelineService(db).authoring.evidence.for_improvement(
            ctx, read.id, excluded_message_ids=request.excluded_message_ids
        )
        assert [item.run_id for item in remaining.runs] == sources[:1]
        assert not any("UNRELATED_SOURCE" in prompt for prompt in model.prompts)
        assert not any("HELD_OUT_ONLY_MUST_STAY_PRIVATE" in prompt for prompt in model.prompts)
    topics = list((await db.scalars(select(KnowledgeGapTopic))).all())
    [draft] = [topic for topic in topics if topic.draft_content]
    assert set(draft.draft_evidence_run_ids) <= set(sources)
    assert len(draft.draft_evidence_run_ids) == 2
    assert "{{parking location}}" in draft.draft_content
    assert agent.draft_spec == original
    assert await db.scalar(select(func.count()).select_from(KnowledgeGapMember)) == 2
    runs = list(
        (await db.scalars(select(AgentRun).where(AgentRun.improvement_run_id == read.id))).all()
    )
    spend = await db.scalar(
        select(IngestionSpend).where(IngestionSpend.improvement_run_id == read.id)
    )
    assert len(runs) == 2 and spend.cost_usd == Decimal("0.0002")
    assert await improvement_repo.spent(db, read.id, organization_id=ctx.organization_id) == sum(
        (r.cost_usd for r in runs), spend.cost_usd
    )
    assert await improvement_repo.spent(db, read.id, organization_id=uuid4()) == 0


async def test_a_dead_classifier_leaves_raw_evidence_for_the_agent(db):
    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        stored = await db.get(ImprovementRun, read.id)
        job, _ = await _job(db, stored)
        job.status = "dead"
        await db.flush()
        service = ImprovementPipelineService(db)
        await service.advance(read.id, ctx.organization_id)
        assert stored.stage == "proposing"
        assert any(
            e.action == "improvement.classification_failed"
            for e in (await service.read(ctx, agent.id, read.id)).timeline
        )


async def test_cancelled_session_refuses_queued_classifier_before_a_paid_call(db):
    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx) as model:
        read = await _start(db, ctx, agent, dataset)
        stored = await db.get(ImprovementRun, read.id)
        job, payload = await _job(db, stored)
        await ImprovementPipelineService(db).cancel(ctx, agent.id, read.id)
        await db.refresh(job)
        assert job.status == "cancelled"
        with pytest.raises(BadRequestError, match="stopped"):
            await classify_knowledge_gaps(payload)
        assert not model.prompts


async def test_full_step_cost_is_checked_again_when_the_worker_starts(db):
    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx) as model:
        read = await _start(db, ctx, agent, dataset)
        stored = await db.get(ImprovementRun, read.id)
        _, payload = await _job(db, stored)
        stored.budget_usd = Decimal("0.000001")
        await db.flush()
        assert await classify_knowledge_gaps(payload) == 0
        assert (stored.status, stored.stop_reason) == ("stopped", "budget")
        assert not model.prompts


async def test_a_failed_draft_retains_grouping_and_model_spend(db):
    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx, fail_draft=True):
        read = await _start(db, ctx, agent, dataset)
        stored, _ = await _classify(db, ctx, agent, read)
        _, payload = await _job(db, stored, draft=True)
        from app.core.exceptions import SystemAgentOutputError

        with pytest.raises(SystemAgentOutputError):
            await draft_knowledge_gaps(payload)
    assert await improvement_repo.spent(
        db, read.id, organization_id=ctx.organization_id
    ) == Decimal("0.0402")
    assert (
        await db.scalar(
            select(func.count())
            .select_from(KnowledgeGapTopic)
            .where(KnowledgeGapTopic.draft_content.is_not(None))
        )
        == 0
    )


async def test_a_narrowed_api_key_is_not_rebuilt_as_its_owners_full_role(db):
    ctx, agent, _, dataset, _ = await _world(db)
    key = await ApiKeyService(db).create(
        ctx,
        ApiKeyCreate(
            name="improvement",
            scopes=[
                Perm.AGENTS_VIEW,
                Perm.AGENTS_EDIT,
                Perm.AGENTS_RUN,
                Perm.RUNS_VIEW,
                Perm.DATASETS_RUN,
                Perm.COLLECTIONS_VIEW,
                Perm.COLLECTIONS_EDIT,
            ],
        ),
    )
    keyed = await ApiKeyService(db).context_for_key(key.id, organization_id=ctx.organization_id)
    with _providers(db, ctx) as model:
        read = await _start(db, keyed, agent, dataset)
        stored = await db.get(ImprovementRun, read.id)
        _, payload = await _job(db, stored)
        row = await db.get(ApiKey, key.id)
        row.scopes = [scope for scope in row.scopes if scope != Perm.RUNS_VIEW.value]
        await db.flush()
        with pytest.raises(AuthorizationError, match="runs:view"):
            await classify_knowledge_gaps(payload)
        assert not model.prompts


async def test_a_knowledge_only_session_leaves_documents_for_a_human_without_an_empty_version(db):
    from app.db.models.conversation import Message

    ctx, agent, _, dataset, sources = await _world(db)
    answer = await db.scalar(
        select(Message).where(Message.run_id == sources[0], Message.role == "assistant")
    )
    answer.content = "I don't know where visitors can park."
    await db.flush()
    before = agent.current_version_id
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        stored, _ = await _classify(db, ctx, agent, read)
        job, payload = await _job(db, stored, draft=True)
        assert await draft_knowledge_gaps(payload) == 1
        job.status = "succeeded"
        await db.flush()
        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
        assert (stored.status, stored.stop_reason) == ("stopped", "knowledge_only")
        assert agent.current_version_id == before
        iteration = await improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=read.id, number=1
        )
        assert iteration.batch_id is None and not iteration.eval_run_ids
        from app.schemas.improvement import KnowledgeCheckConsent, KnowledgeCheckTarget

        topic = await db.scalar(
            select(KnowledgeGapTopic).where(KnowledgeGapTopic.draft_content.is_not(None))
        )
        version = await dataset_repo.get_version(
            db, dataset.id, stored.dataset_version, organization_id=ctx.organization_id
        )
        cases = await dataset_repo.list_cases(
            db, version.id, organization_id=ctx.organization_id, limit=None
        )
        target = KnowledgeCheckTarget(
            topic_id=topic.id, round=1, case_ids=[case.case_id for case in cases]
        )
        service = ImprovementPipelineService(db)
        quote = await service.estimate_knowledge(ctx, agent.id, read.id, target)
        assert quote.can_measure and quote.affordable and quote.cases == 5
        child = await service.start_knowledge(
            ctx,
            agent.id,
            read.id,
            KnowledgeCheckConsent(
                **target.model_dump(),
                confirmed=True,
                draft_hash=quote.draft_hash,
                estimate_usd=quote.total_usd,
            ),
        )
        assert child.proposal_check.knowledge.topic_id == topic.id
        assert agent.current_version_id == before


async def test_one_source_asker_cannot_borrow_an_unrelated_asker_to_trigger_automatic_drafting(db):
    from app.db.models.knowledge_gap import KnowledgeSearch

    ctx, agent, kb, dataset, _ = await _world(db)
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        stored, _ = await _classify(db, ctx, agent, read)
        _, payload = await _job(db, stored, draft=True)
        await draft_knowledge_gaps(payload)
        [topic] = list((await db.scalars(select(KnowledgeGapTopic))).all())
        topic.draft_content = None
        topic.draft_author = None
        await db.flush()
        [one_source] = (
            await knowledge_gap_repo.topic_evidence(
                db, topic.id, organization_id=ctx.organization_id
            )
        )[:1]
        with pytest.raises(BadRequestError, match="Too few independent"):
            await KnowledgeGapService(db).draft(
                ctx,
                topic.id,
                automatic=True,
                improvement_run_id=read.id,
                source_run_ids=[one_source.run_id],
            )
        assert await db.scalar(select(func.count()).select_from(KnowledgeSearch)) >= 2


async def test_unknown_prices_refuse_the_estimate_without_a_paid_call(db):
    ctx, agent, _, dataset, _ = await _world(db)
    with (
        _providers(db, ctx) as model,
        patch("app.services.knowledge_gaps.price_request", return_value=None),
    ):
        with pytest.raises(BadRequestError, match="no known model price"):
            await ImprovementPipelineService(db).estimate(
                ctx, agent.id, ImprovementTarget(dataset_id=dataset.id)
            )
        assert not model.prompts


async def test_a_draft_finished_after_cancellation_keeps_spend_but_not_content(db):
    from sqlalchemy import update

    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx) as model:
        read = await _start(db, ctx, agent, dataset)
        stored, _ = await _classify(db, ctx, agent, read)
        _, payload = await _job(db, stored, draft=True)
        original = model.execute

        async def execute(runner, *args, **kwargs):
            result = await original(runner, *args, **kwargs)
            await db.execute(
                update(ImprovementRun)
                .where(ImprovementRun.id == read.id)
                .values(status="cancelled")
                .execution_options(synchronize_session=False)
            )
            return result

        model.execute = execute
        with pytest.raises(BadRequestError, match="stopped"):
            await draft_knowledge_gaps(payload)
    assert await improvement_repo.spent(
        db, read.id, organization_id=ctx.organization_id
    ) == Decimal("0.0402")
    assert (
        await db.scalar(
            select(func.count())
            .select_from(KnowledgeGapTopic)
            .where(KnowledgeGapTopic.draft_content.is_not(None))
        )
        == 0
    )


async def test_examples_group_by_topic_and_a_persons_triage_reaches_later_rounds(db):
    ctx, agent, _, dataset, sources = await _world(db)
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        stored, _ = await _classify(db, ctx, agent, read)
        job, payload = await _job(db, stored, draft=True)
        await draft_knowledge_gaps(payload)
        service = ImprovementPipelineService(db)
        items = {
            item.run_id: item
            for item in (await service.evidence(ctx, agent.id, run_id=read.id)).items
        }
        assert items[sources[1]].topic_id is not None
        assert items[sources[1]].topic_id == items[sources[2]].topic_id
        assert items[sources[0]].topic_id is None and items[sources[0]].decision is None
        await service.decide_evidence(
            ctx, agent.id, read.id, sources[1], EvidenceDecisionUpdate(decision="agent")
        )
        decided = await service.decide_evidence(
            ctx, agent.id, read.id, sources[0], EvidenceDecisionUpdate(decision="ignored")
        )
        items = {item.run_id: item for item in decided.items}
        assert items[sources[1]].branch == "agent" and items[sources[1]].decision == "agent"
        assert items[sources[0]].decision == "ignored"
        messages = await knowledge_gap_repo.answers_for_runs(
            db, organization_id=ctx.organization_id, run_ids=sources
        )
        excluded = await service._knowledge_exclusions(ctx, stored)
        assert set(excluded) == {messages[sources[0]], messages[sources[2]]}
        undone = await service.decide_evidence(
            ctx, agent.id, read.id, sources[1], EvidenceDecisionUpdate(decision=None)
        )
        item = next(item for item in undone.items if item.run_id == sources[1])
        assert item.branch == "missing_knowledge" and item.decision is None
        assert stored.evidence_decisions == {str(sources[0]): "ignored"}


@pytest.mark.parametrize(("askers", "drafted", "reason"), [(1, 0, "too_few_askers"), (2, 1, None)])
async def test_drafting_says_why_a_topic_one_person_asked_about_is_left_undrafted(
    db, askers, drafted, reason
):
    ctx, agent, _, dataset, _ = await _world(db, askers=askers)
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        stored, _ = await _classify(db, ctx, agent, read)
        assert stored.stage == "drafting"
        _, payload = await _job(db, stored, draft=True)
        assert await draft_knowledge_gaps(payload) == drafted
    timeline = (await ImprovementPipelineService(db).read(ctx, agent.id, read.id)).timeline
    [finished] = [e for e in timeline if e.action == "improvement.drafting_finished"]
    assert finished.reason == reason

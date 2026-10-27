"""Knowledge work: a session sorts and groups on its own ledger, a person asks for each draft."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.agents.capabilities.budget import record_ambient_cost
from app.agents.system_agents import KNOWLEDGE_GAP_CLASSIFIER, KNOWLEDGE_GAP_DRAFTER
from app.core.exceptions import (
    AiAssistanceDisabledError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    SystemAgentOutputError,
)
from app.core.permissions import OrgRoleName, Perm
from app.db.models.agent import AgentVersion
from app.db.models.agent_run import AgentRun
from app.db.models.api_key import ApiKey
from app.db.models.authoring import AuthoringRequest
from app.db.models.background_job import BackgroundJob
from app.db.models.improvement import ImprovementRun
from app.db.models.ingestion_spend import IngestionSpend
from app.db.models.knowledge_gap import KnowledgeGapMember, KnowledgeGapTopic
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.rag_document import RAGDocument
from app.repositories import dataset_repo, improvement_repo, knowledge_gap_repo
from app.schemas.api_key import ApiKeyCreate
from app.schemas.improvement import ImprovementStart, ImprovementTarget
from app.services.api_key import ApiKeyService
from app.services.embedding_resolution import EmbeddingKeySource, ResolvedEmbeddings
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.knowledge_gaps import KnowledgeGapService
from app.services.model_profile import ModelProfileService
from app.worker.jobs import ClassifyGaps, DraftTopic
from app.worker.tasks.knowledge_gap_tasks import classify_knowledge_gaps, draft_knowledge_gap
from tests.integration.test_authoring import Improver, _answering, _published, _sessions, _setup
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_eval_suites import _dataset
from tests.integration.test_improvement_pipeline import _next_step
from tests.integration.test_knowledge_gap_signals import _ANSWER, _asked, _decide, _rated_down
from tests.integration.test_knowledge_gaps import _knowledge_base, _meaning, _member, _searched

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment", "knowledge_search")]


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
    assert quote.total_usd == quote.knowledge_usd
    run = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, max_iterations=1, budget_usd=Decimal("5")),
    )
    for _ in range(3):
        await service.advance(run.id, ctx.organization_id)
    return await service.read(ctx, agent.id, run.id)


async def _job(db, run):
    iteration = await improvement_repo.get_iteration(
        db, organization_id=run.organization_id, run_id=run.id, number=1
    )
    job = await db.get(BackgroundJob, iteration.classify_job_id)
    return job, ClassifyGaps.model_validate(job.payload)


async def _draft_jobs(db) -> list[BackgroundJob]:
    return list(
        (
            await db.scalars(
                select(BackgroundJob).where(BackgroundJob.kind == "draft-knowledge-gap")
            )
        ).all()
    )


async def _classify(db, ctx, agent, read):
    stored = await db.get(ImprovementRun, read.id)
    job, payload = await _job(db, stored)
    found = await classify_knowledge_gaps(payload)
    job.status = "succeeded"
    await db.flush()
    service = ImprovementPipelineService(db)
    await service.advance(read.id, ctx.organization_id)
    # Only the agent's own faults are taken on to a proposal; missing knowledge stops.
    if stored.status == "waiting":
        await _next_step(db, ctx, read.id)
        await service.advance(read.id, ctx.organization_id)
    return stored, found


async def test_a_session_sorts_and_groups_frozen_sources_drafts_nothing_and_keeps_the_agent(db):
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
        assert found == 2 and stored.stage == "proposing"
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
        assert not any(prompt.startswith('The knowledge base "') for prompt in model.prompts)
    [topic] = (await KnowledgeGapService(db).list_for_agent(ctx, agent.id)).items
    assert not topic.has_draft and not topic.drafting
    assert await _draft_jobs(db) == []
    assert agent.draft_spec == original
    assert await db.scalar(select(func.count()).select_from(KnowledgeGapMember)) == 2
    runs = list(
        (await db.scalars(select(AgentRun).where(AgentRun.improvement_run_id == read.id))).all()
    )
    spend = await db.scalar(
        select(IngestionSpend).where(IngestionSpend.improvement_run_id == read.id)
    )
    assert len(runs) == 1 and spend.cost_usd == Decimal("0.0002")
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
        assert (stored.status, stored.stage) == ("waiting", "classifying")
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
        assert (stored.status, stored.stop_reason) == ("stopped", "knowledge_only")
        assert await _draft_jobs(db) == []
        [gap] = (await KnowledgeGapService(db).list_for_agent(ctx, agent.id)).items
        await KnowledgeGapService(db).request_draft(ctx, gap.id)
        [job] = await _draft_jobs(db)
        assert await draft_knowledge_gap(DraftTopic.model_validate(job.payload))
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


async def test_examples_group_by_topic_and_later_rounds_read_every_example(db):
    ctx, agent, _, dataset, sources = await _world(db)
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        stored, _ = await _classify(db, ctx, agent, read)
        service = ImprovementPipelineService(db)
        items = {
            item.run_id: item
            for item in (await service.evidence(ctx, agent.id, run_id=read.id)).items
        }
        assert items[sources[1]].topic_id is not None
        assert items[sources[1]].topic_id == items[sources[2]].topic_id
        assert items[sources[0]].topic_id is None
        assert items[sources[0]].branch == "agent"
        messages = await knowledge_gap_repo.answers_for_runs(
            db, organization_id=ctx.organization_id, run_ids=sources
        )
        excluded = await service._knowledge_exclusions(ctx, stored)
        # What the classifier left to the knowledge base stays out of the agent's
        # changes; its next round reads every other example.
        assert set(excluded) == {messages[sources[1]], messages[sources[2]]}


async def _advances_queued_later(db, run_id) -> int:
    from sqlalchemy import func, select

    return await db.scalar(
        select(func.count())
        .select_from(BackgroundJob)
        .where(
            BackgroundJob.kind == "advance-improvement",
            BackgroundJob.status == "queued",
            BackgroundJob.payload["run_id"].astext == str(run_id),
            BackgroundJob.run_after > func.now(),
        )
    )


async def test_a_finished_knowledge_step_wakes_its_session_once_the_queue_records_it(db):
    from sqlalchemy import update

    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        stored = await db.get(ImprovementRun, read.id)
        _, classify = await _job(db, stored)
        await db.execute(
            update(BackgroundJob).where(BackgroundJob.status == "queued").values(status="succeeded")
        )
        await classify_knowledge_gaps(classify)
        assert await _advances_queued_later(db, read.id) == 1


async def _gap(db, ctx, agent, dataset):
    """The topic a stopped session left missing from the knowledge base."""
    read = await _start(db, ctx, agent, dataset)
    await _classify(db, ctx, agent, read)
    [gap] = (await KnowledgeGapService(db).list_for_agent(ctx, agent.id)).items
    return gap


async def _document(db, kb, filename, *, added=None) -> RAGDocument:
    document = RAGDocument(
        id=uuid4(),
        collection_name=kb.collection_name,
        filename=filename,
        filesize=10,
        filetype="md",
        organization_id=kb.organization_id,
        knowledge_base_id=kb.id,
        status="done",
    )
    if added is not None:
        document.created_at = added
    db.add(document)
    await db.flush()
    return document


async def test_a_draft_asked_for_runs_once_reads_the_knowledge_base_now_and_goes_stale(
    db, knowledge_search
):
    ctx, agent, kb, dataset, _ = await _world(db)
    with _providers(db, ctx) as model:
        gap = await _gap(db, ctx, agent, dataset)
        service = KnowledgeGapService(db)
        queued = await service.request_draft(ctx, gap.id)
        again = await service.request_draft(ctx, gap.id)
        [job] = await _draft_jobs(db)
        assert queued.drafting and again.drafting and not queued.has_draft
        await _document(db, kb, "visitors.md")
        knowledge_search.return_value = (
            "[1] Source: visitors.md (score: 0.910)\nVisitors park on level -2."
        )
        assert await draft_knowledge_gap(DraftTopic.model_validate(job.payload))
        job.status = "succeeded"
        await db.flush()
    [prompt] = [p for p in model.prompts if p.startswith('The knowledge base "')]
    assert "## What the knowledge base holds now" in prompt
    assert "Visitors park on level -2." in prompt
    assert "1. visitors.md" in prompt
    assert knowledge_search.await_args.kwargs["kb_collection_names"] == [kb.collection_name]
    drafted = await service.read(ctx, gap.id)
    assert drafted.has_draft and not drafted.drafting and not drafted.draft_failed
    assert not drafted.draft_stale and drafted.draft_askers == 2
    await _document(db, kb, "lifts.md", added=datetime.now(UTC) + timedelta(minutes=1))
    assert (await service.read(ctx, gap.id)).draft_stale


async def test_a_draft_that_fails_is_shown_failed_until_a_newer_one_replaces_it(db):
    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx, fail_draft=True):
        gap = await _gap(db, ctx, agent, dataset)
        await KnowledgeGapService(db).request_draft(ctx, gap.id)
        [job] = await _draft_jobs(db)
        with pytest.raises(SystemAgentOutputError):
            await draft_knowledge_gap(DraftTopic.model_validate(job.payload))
        job.status = "dead"
        await db.flush()
    failed = await KnowledgeGapService(db).read(ctx, gap.id)
    assert failed.draft_failed and not failed.drafting and not failed.has_draft


async def test_a_draft_is_estimated_before_it_is_asked_for_and_unpriced_without_a_price(db):
    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx):
        gap = await _gap(db, ctx, agent, dataset)
        service = KnowledgeGapService(db)
        assert (await service.draft_estimate(ctx, gap.id)).total_usd > 0
        with patch("app.services.knowledge_gaps.price_request", return_value=None):
            assert (await service.draft_estimate(ctx, gap.id)).total_usd is None


async def test_a_draft_is_refused_up_front_with_ai_assistance_off_or_without_access(db):
    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx):
        gap = await _gap(db, ctx, agent, dataset)
        service = KnowledgeGapService(db)
        reader = await _member(db, ctx, OrgRoleName.OPERATOR)
        with pytest.raises(NotFoundError):
            await service.request_draft(reader, gap.id)
        with pytest.raises(NotFoundError):
            await service.draft_estimate(reader, gap.id)
        with (
            patch("app.services.knowledge_gaps.current_impersonator", return_value=uuid4()),
            pytest.raises(AuthorizationError, match="signed in as yourself"),
        ):
            await service.request_draft(ctx, gap.id)
        organization = await db.get(Organization, ctx.organization_id)
        organization.ai_assistance_enabled = False
        await db.flush()
        with pytest.raises(AiAssistanceDisabledError):
            await service.request_draft(ctx, gap.id)
        with pytest.raises(AiAssistanceDisabledError):
            await service.draft_estimate(ctx, gap.id)
    assert await _draft_jobs(db) == []


async def test_a_draft_asked_for_by_somebody_who_left_is_not_written(db):
    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx) as model:
        gap = await _gap(db, ctx, agent, dataset)
        asked = await _member(db, ctx, OrgRoleName.ADMIN)
        await KnowledgeGapService(db).request_draft(asked, gap.id)
        [job] = await _draft_jobs(db)
        member = await db.scalar(
            select(OrganizationMember).where(OrganizationMember.user_id == asked.user_id)
        )
        await db.delete(member)
        await db.flush()
        assert not await draft_knowledge_gap(DraftTopic.model_validate(job.payload))
        assert not any(p.startswith('The knowledge base "') for p in model.prompts)


async def test_a_knowledge_gaps_check_groups_what_it_reads_and_drafts_nothing(db):
    ctx, agent, kb, _, sources = await _world(db)
    messages = await knowledge_gap_repo.answers_for_runs(
        db, organization_id=ctx.organization_id, run_ids=sources
    )
    with _providers(db, ctx) as model:
        await classify_knowledge_gaps(
            ClassifyGaps(
                organization_id=ctx.organization_id,
                knowledge_base_ids=[kb.id],
                user_id=ctx.user_id,
                message_ids=list(messages.values()),
            )
        )
        assert not any(p.startswith('The knowledge base "') for p in model.prompts)
    [gap] = (await KnowledgeGapService(db).list_for_agent(ctx, agent.id)).items
    assert not gap.has_draft and not gap.drafting
    assert await _draft_jobs(db) == []


async def test_a_session_left_drafting_moves_on_without_drafting(db):
    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        stored = await db.get(ImprovementRun, read.id)
        job, payload = await _job(db, stored)
        await classify_knowledge_gaps(payload)
        job.status = "succeeded"
        stored.stage = "drafting"
        await db.flush()
        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    assert (stored.status, stored.stage) == ("waiting", "classifying")
    assert await _draft_jobs(db) == []


async def test_an_answer_whose_knowledge_was_added_since_is_not_counted_missing(db):
    from app.db.models.conversation import Message

    ctx, agent, kb, dataset, sources = await _world(db)
    answer = await db.scalar(
        select(Message).where(Message.run_id == sources[0], Message.role == "assistant")
    )
    answer.content = "I don't know where visitors can park."
    await db.flush()
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        stored = await db.get(ImprovementRun, read.id)
        job, payload = await _job(db, stored)
        await classify_knowledge_gaps(payload)
        job.status = "succeeded"
        [topic] = list((await db.scalars(select(KnowledgeGapTopic))).all())
        # The person added the document after the answers it covers were given.
        document = await _document(db, kb, "parking.md")
        topic.status = "covered"
        topic.covered_by_document_id = document.id
        topic.covered_at = datetime.now(UTC)
        await db.flush()
        service = ImprovementPipelineService(db)
        await service.advance(read.id, ctx.organization_id)
        assert (stored.status, stored.stop_reason) == ("stopped", "no_proposal")
        evidence = {
            item.run_id: item
            for item in (await service.evidence(ctx, agent.id, run_id=read.id)).items
        }
    for source in sources:
        item = evidence[source]
        assert item.branch == "missing_knowledge" and item.topic_id == topic.id
        assert item.knowledge_added is not None
        assert (item.knowledge_added.document_id, item.knowledge_added.filename) == (
            document.id,
            "parking.md",
        )
        assert item.knowledge_added.knowledge_base_id == kb.id
        assert item.knowledge_added.added_at == topic.covered_at


async def test_a_document_that_failed_to_ingest_leaves_the_knowledge_missing(db):
    ctx, agent, kb, dataset, sources = await _world(db)
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        await _classify(db, ctx, agent, read)
        [topic] = list((await db.scalars(select(KnowledgeGapTopic))).all())
        document = await _document(db, kb, "parking.md")
        document.status = "error"
        topic.status = "covered"
        topic.covered_by_document_id = document.id
        topic.covered_at = datetime.now(UTC)
        await db.flush()
        items = (await ImprovementPipelineService(db).evidence(ctx, agent.id, run_id=read.id)).items
    assert all(item.knowledge_added is None for item in items)

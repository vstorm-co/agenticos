"""A search-only draft cannot earn a fix unless search actually returned it."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from app.agents.capabilities.knowledge._search import search_knowledge_base
from app.core.exceptions import AppException
from app.db.vector_tables import VectorScope
from app.repositories import eval_run_repo
from app.schemas.improvement import KnowledgeCheckConsent
from app.services.agent_runner import AgentRunnerService
from app.services.embedding_resolution import EmbeddingKeySource, ResolvedEmbeddings
from app.services.eval_run import EvalRunService
from app.services.eval_run_worker import EvalRunWorker
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.knowledge_gaps import KnowledgeGapService
from app.services.rag.config import RAGSettings
from app.services.rag.filters import RetrievalFilters, TenantScope
from app.services.rag.overlay import with_overlay
from app.services.rag.retrieval import RetrievalService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_authoring import _sessions
from tests.integration.test_eval_suites import Model
from tests.integration.test_improvement_knowledge import _world
from tests.integration.test_knowledge_gap_content import _add
from tests.integration.test_knowledge_gap_content import uploads as uploads
from tests.integration.test_rag_filter_scope import _store

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def _prepared(db, engine, *, model="text-embedding-3-small"):
    ctx, agent, session, target = await _world(db, knowledge_search=True)
    target.mode = "retrieval"
    topic = await KnowledgeGapService(db)._topic(ctx, target.topic_id)
    kb = await KnowledgeGapService(db)._knowledge_base(ctx, topic.knowledge_base_id)
    resolved = ResolvedEmbeddings(
        model=model,
        dim=3,
        api_key="",
        key_source=EmbeddingKeySource.KEYLESS,
        base_url="https://example.invalid/v1",
        provider="openai",
        vector_scope=VectorScope(tenant=ctx.organization_id),
    )
    pipeline = ImprovementPipelineService(db)
    with patch(
        "app.services.improvement_pipeline.embeddings_for_collection",
        new=AsyncMock(return_value=resolved),
    ):
        quote = await pipeline.estimate_knowledge(ctx, agent.id, session.id, target)
        if not quote.can_measure:
            return ctx, agent, session, target, quote, None, None
        child = await pipeline.start_knowledge(
            ctx,
            agent.id,
            session.id,
            KnowledgeCheckConsent(
                **target.model_dump(),
                confirmed=True,
                estimate_usd=quote.total_usd,
                draft_hash=quote.draft_hash,
            ),
        )
    assert child.estimate_usd + child.rerun_ceiling_usd == quote.total_usd
    assert child.proposal_check.knowledge.embedding_estimate_usd > 0
    store = _store(engine)
    embedder, _ = await store._for_collection(kb.collection_name)
    embedder.provider.model = resolved.model
    embedder.embed_queries = MagicMock(side_effect=lambda texts: [[0.25] * 3 for _ in texts])
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    service = RetrievalService(store, RAGSettings())
    service.resolve_scope = AsyncMock(return_value=TenantScope(organization_id=ctx.organization_id))
    return ctx, agent, session, target, quote, child, service


async def _run(db, ctx, child, retrieval, *, found=True, break_embedding=False):
    model = Model(db)
    observed = []
    if break_embedding:
        embedder, _ = await retrieval.store._for_collection("unused")
        embedder.embed_queries = MagicMock(return_value=[[0.5]])

    async def answer(runner, *args, **kwargs):
        state = kwargs["isolation"].knowledge_overlay
        _, paid = await model.execute(runner, *args, **kwargs)
        if state is None:
            return "90 days", paid
        # The ordinary runner owns this context around the Pydantic AI call.
        with with_overlay(state):
            doc = state.documents[0]
            try:
                result = await search_knowledge_base(
                    "returns",
                    [doc.collection_name],
                    organization_id=ctx.organization_id,
                    filters=None if found else RetrievalFilters(source=["s3"]),
                )
                observed.append(result)
            except AppException:
                # A model can ignore a tool error; that must not turn into a fix.
                pass
        return "30 days", paid

    with (
        patch.object(AgentRunnerService, "execute", new=answer),
        patch(
            "app.agents.capabilities.knowledge._search.get_retrieval_service",
            return_value=retrieval,
        ),
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
    ):
        await EvalRunWorker(
            child.id, ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock()
        ).run()
    return observed


async def test_retrieval_check_records_only_final_hits_and_keeps_no_overlay(db, engine):
    ctx, agent, session, target, quote, child, retrieval = await _prepared(db, engine)
    answers = await _run(db, ctx, child, retrieval)
    assert answers and all("Returns take 30 days." in answer for answer in answers)
    compared = await EvalRunService(db).compare(ctx, child.id)
    assert compared.verdict == "better" and compared.fixed_confirmed == 5
    attempts = await eval_run_repo.list_cases(db, child.id, organization_id=ctx.organization_id)
    arms = await eval_run_repo.list_arms(db, [child.id], organization_id=ctx.organization_id)
    candidate = next(arm for arm in arms if arm.role == "candidate")
    assert all(
        attempt.knowledge_overlay_topic_ids == [target.topic_id]
        for attempt in attempts
        if attempt.arm_id == candidate.id
    )
    assert all(arm.context_bodies is None for arm in arms)
    assert candidate.spec["context_ids"] == []
    assert not await retrieval.store._collection_exists(
        child.proposal_check.knowledge.collection_name
    )


async def test_a_better_answer_without_a_retrieved_draft_is_not_credited(db, engine):
    ctx, _, _, _, _, child, retrieval = await _prepared(db, engine)
    answers = await _run(db, ctx, child, retrieval, found=False)
    assert answers and all("No relevant documents" in answer for answer in answers)
    compared = await EvalRunService(db).compare(ctx, child.id)
    assert compared.verdict == "invalid"
    assert compared.invalid_reason_code == "knowledge_not_retrieved"
    assert (
        compared.invalid_reason == "Search did not return the draft for every confirmed improvement"
    )
    assert compared.candidate_summary.passed == 5  # Actual grades are preserved.
    attempts = await eval_run_repo.list_cases(db, child.id, organization_id=ctx.organization_id)
    assert all(attempt.knowledge_overlay_topic_ids == [] for attempt in attempts)


async def test_a_swallowed_retrieval_error_cannot_become_a_success(db, engine):
    ctx, _, _, _, _, child, retrieval = await _prepared(db, engine)
    await _run(db, ctx, child, retrieval, break_embedding=True)
    compared = await EvalRunService(db).compare(ctx, child.id)
    assert compared.verdict == "invalid" and compared.candidate_summary.passed == 0
    attempts = await eval_run_repo.list_cases(db, child.id, organization_id=ctx.organization_id)
    assert any(
        attempt.error == "Knowledge draft retrieval failed" and attempt.fault == "infrastructure"
        for attempt in attempts
    )


async def test_an_unpriced_embedding_model_cannot_start_a_paid_check(db, engine):
    _, _, _, _, quote, child, _ = await _prepared(
        db, engine, model="unpriced-private-embedding-model"
    )
    assert child is None and quote.reason == "embedding_price_unavailable" and quote.total_usd == 0


async def test_adding_a_document_during_the_check_revokes_the_counterfactual(db, engine, uploads):
    ctx, _, _, target, _, child, _ = await _prepared(db, engine)
    await _add(db, ctx, target.topic_id, "Returns take 30 days.", title="Returns")
    run = await EvalRunService(db).get(ctx, child.id)
    assert run.status == "failed" and run.proposal_check.knowledge.invalidated
    arms = await eval_run_repo.list_arms(db, [child.id], organization_id=ctx.organization_id)
    assert all(arm.context_bodies is None for arm in arms)

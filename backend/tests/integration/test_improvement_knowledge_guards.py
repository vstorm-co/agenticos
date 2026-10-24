"""A knowledge check needs a current draft, independent sources and a usable retrieval boundary."""

from dataclasses import replace
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConcurrentChangeError, PaymentRequiredError
from app.db.models.eval_run import EvalRun
from app.db.models.improvement import ImprovementRun
from app.repositories import authoring_repo, improvement_repo, knowledge_gap_repo
from app.schemas.improvement import KnowledgeCheckConsent
from app.services.embedding_resolution import EmbeddingKeySource, ResolvedEmbeddings
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_improvement_evidence import _serial_worker as _serial_worker
from tests.integration.test_improvement_knowledge import _world

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


@pytest.mark.parametrize("state", ["dismissed", "empty", "changed_candidate"])
async def test_a_closed_empty_or_unmeasured_draft_cannot_start_a_check(
    db: AsyncSession, state: str
) -> None:
    ctx, agent, session, target = await _world(db)
    topic = await knowledge_gap_repo.get_topic(
        db, target.topic_id, organization_id=ctx.organization_id
    )
    assert topic is not None
    if state == "dismissed":
        topic.status = "dismissed"
    elif state == "empty":
        topic.draft_content = None
        topic.draft_author = None
    else:
        iteration = await improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=session.id, number=1
        )
        assert iteration is not None
        iteration.candidate_spec_hash = "0" * 64
    await db.flush()
    before = await db.scalar(select(func.count()).select_from(EvalRun))
    error = ConcurrentChangeError if state == "changed_candidate" else BadRequestError
    with pytest.raises(error):
        await ImprovementPipelineService(db).estimate_knowledge(ctx, agent.id, session.id, target)
    assert await db.scalar(select(func.count()).select_from(EvalRun)) == before


@pytest.mark.security
async def test_truncated_source_provenance_is_refused_instead_of_calling_it_independent(
    db: AsyncSession,
) -> None:
    ctx, agent, session, target = await _world(db)
    with (
        patch(
            "app.services.improvement_pipeline.authoring_repo.evidence_inputs",
            AsyncMock(
                return_value=authoring_repo.EvidenceInputs(inputs=[], run_ids=set(), truncated=True)
            ),
        ),
        pytest.raises(BadRequestError, match="too large"),
    ):
        await ImprovementPipelineService(db).estimate_knowledge(ctx, agent.id, session.id, target)


@pytest.mark.security
async def test_oversized_topic_evidence_is_refused_before_any_paid_check(db: AsyncSession) -> None:
    ctx, agent, session, target = await _world(db)
    evidence = await knowledge_gap_repo.topic_evidence(
        db, target.topic_id, organization_id=ctx.organization_id
    )
    # The repository returns at most 1001 turns; 1001 is its overflow sentinel.
    with (
        patch(
            "app.services.improvement_pipeline.knowledge_gap_repo.topic_evidence",
            AsyncMock(return_value=evidence * 1001),
        ),
        pytest.raises(BadRequestError, match="too much source"),
    ):
        await ImprovementPipelineService(db).estimate_knowledge(ctx, agent.id, session.id, target)


@pytest.mark.parametrize("boundary", ["disabled", "missing", "other_tenant", "no_key"])
@pytest.mark.security
async def test_retrieval_is_unavailable_without_this_tenants_usable_embedding_boundary(
    db: AsyncSession, boundary: str
) -> None:
    ctx, agent, session, target = await _world(db, knowledge_search=boundary != "disabled")
    target.mode = "retrieval"
    resolved = ResolvedEmbeddings(
        model="text-embedding-3-small",
        dim=3,
        api_key="",
        key_source=EmbeddingKeySource.KEYLESS,
        base_url="https://example.invalid/v1",
        provider="openai",
        vector_tenant=ctx.organization_id,
    )
    if boundary == "other_tenant":
        resolved = replace(resolved, vector_tenant=uuid4())
    if boundary == "no_key":
        resolved = replace(resolved, key_source=EmbeddingKeySource.NONE_CHOSEN)
    with patch(
        "app.services.improvement_pipeline.embeddings_for_collection",
        AsyncMock(return_value=None if boundary == "missing" else resolved),
    ):
        quote = await ImprovementPipelineService(db).estimate_knowledge(
            ctx, agent.id, session.id, target
        )
    assert not quote.affordable and not quote.can_measure
    assert quote.reason == (
        "knowledge_search_disabled" if boundary == "disabled" else "embedding_unavailable"
    )
    assert quote.total_usd == 0


@pytest.mark.security
async def test_a_knowledge_quote_does_not_allow_spending_past_the_session_budget(
    db: AsyncSession,
) -> None:
    ctx, agent, session, target = await _world(db)
    row = await db.get(ImprovementRun, session.id)
    assert row is not None
    row.budget_usd = Decimal("0.000001")
    await db.flush()
    service = ImprovementPipelineService(db)
    quote = await service.estimate_knowledge(ctx, agent.id, session.id, target)
    assert quote.can_measure and not quote.affordable
    before = await db.scalar(select(func.count()).select_from(EvalRun))
    with pytest.raises(PaymentRequiredError, match="remaining budget"):
        await service.start_knowledge(
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
    assert await db.scalar(select(func.count()).select_from(EvalRun)) == before

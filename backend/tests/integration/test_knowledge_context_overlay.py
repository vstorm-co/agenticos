"""Draft knowledge is visible only in the paired check that was consented to."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.context import ContextBody
from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.db.models.context import ContextFile
from app.db.models.rag_document import RAGDocument
from app.repositories import dataset_repo, eval_run_repo
from app.schemas.eval_run import EvalRunRequest
from app.services.agent_registry import AgentRegistryService, UnpublishedCandidate
from app.services.agent_runner import AgentRunnerService
from app.services.context import ContextService
from app.services.eval_run import EvalRunService, spec_hash
from app.services.eval_run_worker import EvalRunWorker
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_authoring import _sessions, _setup
from tests.integration.test_eval_suites import Model, _dataset

_VALIDATE = AgentRegistryService.validate_spec

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def test_two_candidates_read_different_run_only_context_without_creating_resources(
    db: AsyncSession,
):
    ctx, agent, _ = await _setup(db)
    dataset = await _dataset(db, ctx, cases=5)
    topic_id = uuid4()
    spec = AgentSpec.model_validate(agent.draft_spec).model_copy(update={"context_ids": [topic_id]})
    baseline = {
        topic_id: ContextBody(name="shipping-draft", description=None, content="Ships in 90 days.")
    }
    candidate = {
        topic_id: ContextBody(name="shipping-draft", description=None, content="Ships in 30 days.")
    }
    versions, _ = await dataset_repo.list_versions(
        db, dataset.id, organization_id=ctx.organization_id
    )
    cases = await dataset_repo.list_cases(
        db, versions[0].id, organization_id=ctx.organization_id, limit=None
    )
    request = EvalRunRequest(
        dataset_id=dataset.id,
        candidate="draft",
        paired_baseline=True,
        reruns=1,
        case_ids=[c.case_id for c in cases[:2]],
    )
    service = EvalRunService(db)
    run = await service.start(
        ctx,
        agent.id,
        request,
        candidate_spec=spec,
        candidate_contexts=candidate,
        baseline_spec=spec,
        baseline_contexts=baseline,
    )
    assert run.excluded_case_ids and len(run.excluded_case_ids) == 3
    seen = set()
    model = Model(db)

    async def answer(runner, *args, **kwargs):
        projected = kwargs["candidate"]
        assert isinstance(projected, UnpublishedCandidate)
        files = await ContextService(db).resolve_for_agent(
            ctx, projected.spec.context_ids, projected=projected.context_bodies
        )
        assert len(files) == 1 and files[0] not in db
        seen.add(files[0].content)
        _, paid = await model.execute(runner, *args, **kwargs)
        return ("30 days" if "30 days" in files[0].content else "90 days"), paid

    with (
        patch.object(AgentRunnerService, "execute", new=answer),
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
    ):
        await EvalRunWorker(
            run.id, ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock()
        ).run()
    finished = await service.get(ctx, run.id)
    assert finished.status == "completed"
    assert seen == {"Ships in 90 days.", "Ships in 30 days."}
    assert await db.scalar(select(func.count()).select_from(ContextFile)) == 0
    assert await db.scalar(select(func.count()).select_from(RAGDocument)) == 0
    assert await ContextService(db).resolve_for_agent(ctx, [topic_id]) == []
    assert spec_hash(spec, context_bodies=baseline) != spec_hash(spec, context_bodies=candidate)
    arms = await eval_run_repo.list_arms(db, [run.id], organization_id=ctx.organization_id)
    assert len({arm.spec_hash for arm in arms}) == 2


async def test_overlay_does_not_authorize_other_missing_files_and_rejects_name_collisions(
    db: AsyncSession,
):
    ctx, agent, _ = await _setup(db)
    topic_id, missing = uuid4(), uuid4()
    spec = AgentSpec.model_validate(agent.draft_spec).model_copy(
        update={"context_ids": [topic_id, missing]}
    )
    body = ContextBody(name="shipping-draft", description=None, content="Needs verification")
    registry = AgentRegistryService(db)
    with (
        patch.object(AgentRegistryService, "validate_spec", new=_VALIDATE),
        pytest.raises(BadRequestError),
    ):
        await registry.get_candidate_spec(
            ctx, agent.id, UnpublishedCandidate(spec, context_bodies={topic_id: body})
        )
    with pytest.raises(BadRequestError, match="distinct names"):
        await registry.get_candidate_spec(
            ctx,
            agent.id,
            UnpublishedCandidate(
                spec, context_bodies={topic_id: body, missing: replace(body, content="Other text")}
            ),
        )

"""A session's proposal is recorded once, and only while its session is still going."""

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.authoring import SpecProposalBatch
from app.repositories import authoring_repo
from app.schemas.improvement import ImprovementStart
from app.services.authoring_worker import AuthoringRun, AuthoringWorker
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import Improver, _answering, _sessions, _setup
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_eval_suites import _dataset

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def _proposing(db: AsyncSession) -> tuple[AuthContext, Agent, UUID, UUID]:
    """A session whose proposal request waits for the improver."""
    ctx, agent, _ = await _setup(db)
    dataset = await _dataset(db, ctx, cases=5)
    pipeline = ImprovementPipelineService(db)
    session = await pipeline.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, max_iterations=1, budget_usd=Decimal("5")),
    )
    for _ in range(3):
        await pipeline.advance(session.id, ctx.organization_id)
    read = await pipeline.read(ctx, agent.id, session.id)
    request_id = read.iterations[0].authoring_request_id
    assert request_id is not None
    return ctx, agent, session.id, request_id


async def _batches(db: AsyncSession, request_id: UUID) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(SpecProposalBatch)
        .where(SpecProposalBatch.request_id == request_id)
    )


class StoppedWhileProposing(Improver):
    """The session's creator stops it while the improver writes its proposal."""

    def __init__(self, db: AsyncSession, ctx: AuthContext, agent: Agent, session_id: UUID) -> None:
        super().__init__(db)
        self.stop = (ctx, agent.id, session_id)

    async def execute(self, runner: Any, ctx: AuthContext, agent_id: Any, prompt: str, **kw: Any):
        answered = await super().execute(runner, ctx, agent_id, prompt, **kw)
        await ImprovementPipelineService(self.db).cancel(*self.stop)
        return answered


async def test_a_session_stopped_while_proposing_records_no_batch(db):
    ctx, agent, session_id, request_id = await _proposing(db)

    with _answering(StoppedWhileProposing(db, ctx, agent, session_id)):
        await AuthoringWorker(request_id, ctx.organization_id, sessions=_sessions(db)).run()

    request = await authoring_repo.get_request(db, request_id, organization_id=ctx.organization_id)
    assert request is not None
    assert (request.status, request.error) == ("failed", "The improvement session stopped.")
    assert await _batches(db, request_id) == 0


async def test_carrying_out_a_session_request_again_keeps_its_one_batch(db):
    ctx, _, _, request_id = await _proposing(db)
    with _answering(Improver(db)):
        await AuthoringWorker(request_id, ctx.organization_id, sessions=_sessions(db)).run()
    request = await authoring_repo.get_request(db, request_id, organization_id=ctx.organization_id)
    assert request is not None and request.status == "completed"
    recorded = request.report["recorded"]
    assert recorded > 0

    with _answering(Improver(db)):
        await AuthoringRun(db, ctx, request).execute()

    assert await _batches(db, request_id) == 1
    assert request.report["recorded"] == recorded

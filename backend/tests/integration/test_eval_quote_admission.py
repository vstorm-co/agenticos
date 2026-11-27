"""Accepted quotes fence parallel admissions and the next paid grading on Postgres."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.agent_run import AgentRun
from app.db.models.dataset import DatasetCase
from app.db.models.eval_run import EvalRun
from app.repositories import eval_run_repo
from app.schemas.dataset import DatasetCaseCreate
from app.schemas.eval_run import EvalRunRequest
from app.services.dataset import DatasetService
from app.services.eval_run import EvalRunService
from app.services.eval_run_worker import EvalRunWorker
from tests.integration.test_eval_runs import (
    Model,
    _agent,
    _assist,
    _dataset,
    _owner,
    _quoted,
    _run_to_end,
)
from tests.integration.test_eval_runs import _environment as _environment

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("quoted", [True, False])
async def test_concurrent_claims_keep_only_quoted_runs_serial(
    db: AsyncSession, engine: AsyncEngine, quoted: bool
) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=6)
    request = EvalRunRequest(dataset_id=dataset.id)
    if quoted:
        run, _ = await _quoted(db, ctx, agent, request)
    else:
        run = await EvalRunService(db).start(ctx, agent.id, request)
    await db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    gate = asyncio.Event()

    async def claim() -> UUID | None:
        await gate.wait()
        async with sessions.begin() as session:
            case = await eval_run_repo.claim_next(
                session,
                run.id,
                organization_id=ctx.organization_id,
                org_limit=4,
                now=datetime.now(UTC),
            )
            return None if case is None else case.id

    tasks = [asyncio.create_task(claim()) for _ in range(4)]
    gate.set()
    try:
        claimed = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert sum(value is not None for value in claimed) == (1 if quoted else 4)


async def test_idle_drainer_waits_for_the_quoted_answer_instead_of_stopping_it(
    db: AsyncSession,
) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    started, _ = await _quoted(db, ctx, agent, EvalRunRequest(dataset_id=dataset.id))
    run = await db.get(EvalRun, started.id)
    assert run is not None and run.quoted_usd is not None
    # A prior attempt used most of the quote; the active one must settle first.
    cases = await eval_run_repo.list_cases(db, run.id, organization_id=ctx.organization_id)
    cases[0].status = "running"
    cases[0].cost_usd = run.quoted_usd - Decimal("0.01")
    await db.flush()
    worker = EvalRunWorker(run.id, ctx.organization_id)
    assert await worker._quote_reached(db) is None


async def test_grading_admission_counts_the_next_grading_estimate(db: AsyncSession) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    started, _ = await _quoted(db, ctx, agent, EvalRunRequest(dataset_id=dataset.id))
    run = await db.get(EvalRun, started.id)
    assert run is not None
    run.scoring = {"reference": {"enabled": True}}
    run.quoted_usd = Decimal("0.15")
    run.grading_estimate_usd = Decimal("0.05")
    answer = AgentRun(cost_usd=Decimal("0.11"))
    assert await EvalRunWorker(run.id, ctx.organization_id)._graded_past_quote(db, run, answer)


@pytest.mark.parametrize("kind", ["rubric", "reference", "case", "default"])
async def test_run_freezes_every_paid_grading_source(db: AsyncSession, kind: str) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    if kind == "rubric":
        dataset.scoring = {
            "judge": {"enabled": True, "criteria": [{"name": "Tone", "description": "Polite"}]}
        }
    elif kind == "reference":
        dataset.scoring = {"reference": {"enabled": True}}
    elif kind == "default":
        dataset.scoring = {"checks": {"defaults": [{"type": "judge", "criterion": "Polite"}]}}
    else:
        service = DatasetService(db)
        await service.add_case(
            ctx,
            dataset.id,
            DatasetCaseCreate(
                input="Judge this", checks=[{"type": "judge", "criterion": "Polite"}]
            ),
        )
    await db.flush()
    started, _ = await _quoted(db, ctx, agent, EvalRunRequest(dataset_id=dataset.id))
    row = await db.get(EvalRun, started.id)
    assert row is not None
    assert row.grading_estimate_usd == Decimal("0.05")


@pytest.mark.parametrize("kind", ["rubric", "case"])
async def test_worker_keeps_answer_but_refuses_its_unaffordable_grading(
    db: AsyncSession, kind: str
) -> None:
    ctx = await _owner(db)
    await _assist(db, ctx, on=True)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    if kind == "rubric":
        dataset.scoring = {
            "judge": {"enabled": True, "criteria": [{"name": "Tone", "description": "Polite"}]}
        }
    else:
        revision = await db.scalar(select(DatasetCase).where(DatasetCase.dataset_id == dataset.id))
        assert revision is not None
        revision.checks = [{"type": "judge", "criterion": "Polite"}]
    await db.flush()
    started, quoted = await _quoted(db, ctx, agent, EvalRunRequest(dataset_id=dataset.id))
    model = Model(db, cost=lambda _: quoted - Decimal("0.04"))
    await _run_to_end(db, model, started.id, ctx)
    read = await EvalRunService(db).get(ctx, started.id)
    assert len(model.calls) == 1
    assert read.status == "budget_exceeded"
    cases = await eval_run_repo.list_cases(db, started.id, organization_id=ctx.organization_id)
    assert cases[0].answer is not None
    assert cases[0].case_score_id is None
    assert read.cost_usd == quoted - Decimal("0.04")


async def test_large_accepted_quotes_keep_the_existing_money_range(db: AsyncSession) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    ceiling = Decimal("1000000.123456")
    started = await EvalRunService(db).start(
        ctx, agent.id, EvalRunRequest(dataset_id=dataset.id, quoted_usd=ceiling)
    )
    await db.flush()
    row = await db.get(EvalRun, started.id)
    assert row is not None and row.quoted_usd == ceiling

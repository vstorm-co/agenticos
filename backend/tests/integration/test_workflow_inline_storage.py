"""Retained inline results are bounded across attempts, runs and organizations."""

import asyncio
import itertools
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models.workflow import Workflow
from app.db.models.workflow_run import NodeAttempt, NodeRun, WorkflowRun
from app.repositories import workflow_run as run_repo
from app.services.workflow_execution import dispatcher
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import drive, seed_run

pytestmark = pytest.mark.anyio


def _graph(copies: int, *, chars: int = 1000) -> WorkflowGraph:
    nodes = [
        NodeInstance(
            id=uuid.uuid4(),
            definition_id="core.input",
            definition_version=1,
            layout=NodePosition(x=0, y=0),
        )
    ]
    nodes.extend(
        NodeInstance(
            id=uuid.uuid4(),
            definition_id="debug.echo",
            definition_version=1,
            config={"message": "x" * chars},
            layout=NodePosition(x=0, y=0),
        )
        for _ in range(copies)
    )
    edges = tuple(
        Edge(
            id=uuid.uuid4(),
            source_node_id=a.id,
            source_port="out",
            target_node_id=b.id,
            target_port="in",
        )
        for a, b in itertools.pairwise(nodes)
    )
    return WorkflowGraph(entry_node_id=nodes[0].id, nodes=tuple(nodes), edges=edges)


@pytest.mark.security
async def test_one_run_cannot_amplify_a_small_result_through_a_long_chain(engine, monkeypatch):
    monkeypatch.setattr(settings, "WORKFLOW_RUN_MAX_INLINE_RESULT_BYTES", 3000)
    original = dispatcher.call_handler

    async def paid(begun):
        return replace(await original(begun), cost=Decimal("0.25"))

    monkeypatch.setattr(dispatcher, "call_handler", paid)
    seeded = await seed_run(engine, _graph(8))
    run = await drive(seeded)
    assert run.status == "failed" and run.error["code"] == "WORKFLOW_INLINE_RESULT_LIMIT"
    assert run.error["details"]["scope"] == "run"
    assert run.inline_result_bytes < 3000 + 4096
    async with seeded.factory() as db:
        attempts = (
            await db.scalars(
                select(NodeAttempt).join(NodeRun).where(NodeRun.workflow_run_id == run.id)
            )
        ).all()
        assert len(attempts) < 8
        assert run.spent_cost == Decimal("0.25") * len(attempts)
        assert attempts[-1].result is not None
        assert sum(len(json.dumps(a.result)) for a in attempts) < 7000


@pytest.mark.security
async def test_organization_results_span_runs_and_release_on_retention(engine, monkeypatch):
    monkeypatch.setattr(settings, "WORKFLOW_ORG_MAX_INLINE_RESULT_BYTES", 2400)
    first = await seed_run(engine, _graph(1, chars=1500))
    assert (await drive(first)).status == "succeeded"
    second = await seed_run(engine, _graph(1, chars=1500), member=(first.principal, first.org))
    refused = await drive(second)
    assert refused.status == "failed" and refused.error["details"]["scope"] == "organization"
    other = await seed_run(engine, _graph(1, chars=1500))
    assert (await drive(other)).status == "succeeded"
    async with first.factory() as db:
        before = await dispatcher.workflow_run_repo.inline_result_bytes(db, first.org.id)
        workflow = await db.get(Workflow, first.run.workflow_id)
        row = await db.get(WorkflowRun, first.run.id)
        assert workflow is not None and row is not None
        workflow.settings = {"run_retention_days": 1}
        row.ended_at = datetime.now(UTC) - timedelta(days=3)
        await db.flush()
        removed = await run_repo.take_expired_runs(db, now=datetime.now(UTC), limit=10)
        assert first.run.id in dict(removed)
        await db.commit()
        assert await dispatcher.workflow_run_repo.inline_result_bytes(db, first.org.id) < before
    third = await seed_run(engine, _graph(1, chars=1500), member=(first.principal, first.org))
    assert (await drive(third)).status == "succeeded"


@pytest.mark.security
async def test_two_parallel_runs_share_one_serialized_result_allowance(engine, monkeypatch):
    monkeypatch.setattr(settings, "WORKFLOW_ORG_MAX_INLINE_RESULT_BYTES", 1800)
    first = await seed_run(engine, _graph(1))
    second = await seed_run(engine, _graph(1), member=(first.principal, first.org))
    runs = await asyncio.gather(drive(first), drive(second))
    assert sorted(run.status for run in runs) == ["failed", "succeeded"]
    failed = next(run for run in runs if run.status == "failed")
    assert failed.error["details"]["scope"] == "organization"


async def test_maintenance_skips_busy_tenant_locks_and_can_take_them_after_commit(engine):
    from app.db.locks import LockScope, hold_subject, try_hold_subject

    seeded = await seed_run(engine, _graph(1))
    async with seeded.factory() as first, seeded.factory() as maintenance:
        await hold_subject(first, LockScope.WORKFLOW_INLINE_RESULTS_PER_ORG, seeded.org.id)
        assert (
            await try_hold_subject(
                maintenance, LockScope.WORKFLOW_INLINE_RESULTS_PER_ORG, seeded.org.id
            )
            is False
        )
        await first.commit()
        assert (
            await try_hold_subject(
                maintenance, LockScope.WORKFLOW_INLINE_RESULTS_PER_ORG, seeded.org.id
            )
            is True
        )

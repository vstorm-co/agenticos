"""Parallel steps under one workflow budget: who is handed what, and who waits (#1800 slice 2).

A step that spends money (a model call, a knowledge search) is handed the most it may
spend when its attempt begins: what the run's cap leaves after what is spent and what
other steps still hold. The hold lasts while the attempt is in flight. Two parallel
spenders therefore never hold more than the cap between them - the second waits - and a
hold ends by itself when the attempt settles, parks, or is resolved as uncertain.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    NodeAttempt,
    NodeAttemptStatus,
    NodeRun,
    NodeRunStatus,
    WorkflowEvent,
)
from app.repositories import workflow_run as workflow_run_repo
from app.services.workflow_execution import budget, context, dispatcher
from app.workflows._registry import REGISTRY, load_builtins, register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.contracts.results import Completed, NodeResult, Waiting
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import (
    SeededRun,
    begin,
    seed_run,
    settle,
    start_attempt,
    tick,
)

pytestmark = pytest.mark.anyio


class _Empty(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Capped(BaseModel):
    max_cost_usd: float | None = None


seen: dict[uuid.UUID, list[Decimal | None]] = {}
parks: set[uuid.UUID] = set()
costs: dict[uuid.UUID, Decimal] = {}


async def _spend(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    current = context.current()
    seen.setdefault(current.node_instance_id, []).append(current.budget_remaining)
    if current.node_instance_id in parks and current.attempt_no == 1:
        return Waiting(
            reason="timer", resume_token="t", resume_at=datetime.now(UTC) + timedelta(hours=1)
        )
    if current.node_instance_id in costs:
        context.report_cost(costs[current.node_instance_id])
    return Completed[_Empty](output=_Empty())


def _definition(node_id: str, *, spends: bool) -> NodeDefinition:
    return NodeDefinition(
        id=node_id,
        version=1,
        name=node_id,
        category="test",
        description="A test node.",
        kind="action",
        config_schema=_Capped,
        input_schema=None,
        output_schema=_Empty,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=_Empty),
        ),
        effect_kind="write",
        retry_guarantee="none",
        handler=_spend,
        spends_budget=spends,
    )


@pytest.fixture
def spenders() -> Iterator[None]:
    definitions = [
        _definition("test.spender", spends=True),
        _definition("test.free", spends=False),
    ]
    for definition in definitions:
        register(definition)
    seen.clear()
    parks.clear()
    costs.clear()
    yield
    for definition in definitions:
        REGISTRY.pop(definition.id, None)


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, target: NodeInstance) -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port="out",
        target_node_id=target.id,
        target_port="in",
    )


async def _two_spenders(
    engine: AsyncEngine,
    *,
    limit: str | None,
    kind: str = "test.spender",
    first_config: dict[str, Any] | None = None,
) -> tuple[SeededRun, NodeInstance, NodeInstance, NodeInstance]:
    entry, first, second = _node("core.input"), _node(kind, first_config), _node(kind)
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, first, second),
        edges=(_edge(entry, first), _edge(entry, second)),
    )
    seeded = await seed_run(engine, graph)
    if limit is not None:
        async with seeded.factory() as db:
            await workflow_run_repo.update_run(
                db, run=seeded.run, update_data={"budget_limit": Decimal(limit)}
            )
            await db.commit()
    async with seeded.factory() as db:
        entry_row = await _row(seeded, entry)
        assert entry_row is not None
    await tick(seeded, entry_row.id)
    return seeded, entry, first, second


async def _row(seeded: SeededRun, node: NodeInstance) -> NodeRun | None:
    async with seeded.factory() as db:
        return (
            await db.execute(
                select(NodeRun).where(
                    NodeRun.workflow_run_id == seeded.run.id,
                    NodeRun.node_instance_id == node.id,
                )
            )
        ).scalar_one_or_none()


async def _row_id(seeded: SeededRun, node: NodeInstance) -> uuid.UUID:
    row = await _row(seeded, node)
    assert row is not None
    return row.id


async def _attempts(seeded: SeededRun, node: NodeInstance) -> list[NodeAttempt]:
    row = await _row(seeded, node)
    assert row is not None
    async with seeded.factory() as db:
        return list(
            (
                await db.execute(
                    select(NodeAttempt)
                    .where(NodeAttempt.node_run_id == row.id)
                    .order_by(NodeAttempt.attempt_no)
                )
            )
            .scalars()
            .all()
        )


async def _tick(seeded: SeededRun, node: NodeInstance) -> None:
    row = await _row(seeded, node)
    assert row is not None
    await tick(seeded, row.id)


async def _due_now(seeded: SeededRun, node: NodeInstance) -> None:
    """Bring a step's waiting dispatch row forward, as the clock eventually does."""
    row = await _row(seeded, node)
    assert row is not None
    async with seeded.factory() as db:
        await db.execute(
            update(DispatchOutbox)
            .where(
                DispatchOutbox.node_run_id == row.id,
                DispatchOutbox.status == DispatchOutboxStatus.PENDING.value,
            )
            .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()


async def _delay_of_the_wait(seeded: SeededRun, node: NodeInstance) -> float:
    waiting = await _row(seeded, node)
    assert waiting is not None
    async with seeded.factory() as db:
        due = (
            await db.execute(
                select(DispatchOutbox).where(
                    DispatchOutbox.node_run_id == waiting.id,
                    DispatchOutbox.status == DispatchOutboxStatus.PENDING.value,
                )
            )
        ).scalar_one()
    return (due.available_at - datetime.now(UTC)).total_seconds()


async def _wait_began_ago(seeded: SeededRun, node: NodeInstance, ago: timedelta) -> None:
    waiting = await _row(seeded, node)
    assert waiting is not None
    async with seeded.factory() as db:
        await db.execute(
            update(WorkflowEvent)
            .where(
                WorkflowEvent.node_run_id == waiting.id, WorkflowEvent.kind == "node_budget_wait"
            )
            .values(created_at=WorkflowEvent.created_at - ago)
        )
        await db.commit()


async def test_a_waiting_spender_backs_off_with_how_long_it_has_waited_and_logs_once(
    engine: AsyncEngine, spenders: None
):
    seeded, _entry, first, second = await _two_spenders(engine, limit="1.00")
    await begin(seeded, await _row_id(seeded, first))
    base = settings.WORKFLOW_RETRY_BACKOFF_BASE_SECONDS
    cap = settings.WORKFLOW_RETRY_BACKOFF_MAX_SECONDS

    await _tick(seeded, second)
    assert base - 3 < await _delay_of_the_wait(seeded, second) <= base + 1

    await _wait_began_ago(seeded, second, timedelta(seconds=100))
    await _due_now(seeded, second)
    await _tick(seeded, second)
    assert 95 < await _delay_of_the_wait(seeded, second) < 110

    await _wait_began_ago(seeded, second, timedelta(days=10))
    await _due_now(seeded, second)
    await _tick(seeded, second)
    assert cap - 3 < await _delay_of_the_wait(seeded, second) <= cap + 1

    waiting = await _row(seeded, second)
    assert waiting is not None
    async with seeded.factory() as db:
        logged = (
            (
                await db.execute(
                    select(WorkflowEvent).where(
                        WorkflowEvent.node_run_id == waiting.id,
                        WorkflowEvent.kind == "node_budget_wait",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(logged) == 1


async def test_a_spender_is_handed_its_own_cap_when_it_is_below_what_is_free(
    engine: AsyncEngine, spenders: None
):
    seeded, _entry, first, _second = await _two_spenders(
        engine, limit="1.00", first_config={"max_cost_usd": 0.25}
    )

    await _tick(seeded, first)

    assert seen[first.id] == [Decimal("0.25")]
    assert [attempt.reserved_usd for attempt in await _attempts(seeded, first)] == [Decimal("0.25")]


async def test_two_parallel_spenders_never_hold_more_than_the_budget(
    engine: AsyncEngine, spenders: None
):
    seeded, _entry, first, second = await _two_spenders(engine, limit="1.00")

    held, _outcome = await begin(seeded, await _row_id(seeded, first))
    await _tick(seeded, second)

    assert [attempt.reserved_usd for attempt in await _attempts(seeded, first)] == [Decimal("1.00")]
    assert await _attempts(seeded, second) == []
    waiting = await _row(seeded, second)
    assert waiting is not None and waiting.status == NodeRunStatus.PENDING.value
    async with seeded.factory() as db:
        due = (
            await db.execute(
                select(DispatchOutbox).where(
                    DispatchOutbox.node_run_id == waiting.id,
                    DispatchOutbox.status == DispatchOutboxStatus.PENDING.value,
                )
            )
        ).scalar_one()
        assert due.available_at > datetime.now(UTC)
        events = (
            (await db.execute(select(WorkflowEvent).where(WorkflowEvent.node_run_id == waiting.id)))
            .scalars()
            .all()
        )
        assert "node_budget_wait" in {event.kind for event in events}
    assert held.attempt_no == 1


async def test_a_waiting_spender_starts_once_the_first_settles(engine: AsyncEngine, spenders: None):
    seeded, _entry, first, second = await _two_spenders(engine, limit="1.00")
    costs[first.id] = Decimal("0.40")
    begun, outcome = await begin(seeded, await _row_id(seeded, first))
    await _tick(seeded, second)
    assert second.id not in seen

    await settle(seeded, begun, outcome)
    await _due_now(seeded, second)
    await _tick(seeded, second)

    assert seen[second.id] == [Decimal("0.60")]


async def test_a_parked_step_releases_its_reservation(engine: AsyncEngine, spenders: None):
    seeded, _entry, first, second = await _two_spenders(engine, limit="1.00")
    parks.add(first.id)

    await _tick(seeded, first)
    await _tick(seeded, second)

    assert seen[second.id] == [Decimal("1.00")]
    parked = (await _attempts(seeded, first))[0]
    assert parked.status == NodeAttemptStatus.COMPLETED.value


async def test_an_orphaned_attempts_reservation_is_released_once_resolved(
    engine: AsyncEngine, spenders: None
):
    seeded, _entry, first, second = await _two_spenders(engine, limit="1.00")
    begun = await start_attempt(seeded, await _row_id(seeded, first))
    await _tick(seeded, second)
    assert second.id not in seen

    async with seeded.factory() as db:
        run = await workflow_run_repo.get_run_by_id_for_update(db, seeded.run.id)
        node_run = await workflow_run_repo.get_node_run_by_id_for_update(db, begun.node_run_id)
        attempt = await workflow_run_repo.get_attempt(db, begun.attempt_id)
        outbox = await workflow_run_repo.get_outbox_for_node_run_for_update(
            db, node_run_id=begun.node_run_id
        )
        assert run is not None and node_run is not None and attempt is not None
        assert await budget.unreserved(db, run) == Decimal("0")
        await dispatcher.resolve_orphaned_attempt(
            db, run=run, node_run=node_run, attempt=attempt, outbox=outbox
        )
        assert await budget.unreserved(db, run) == Decimal("1.00")
        await db.commit()

    await _due_now(seeded, second)
    await _tick(seeded, second)
    assert seen[second.id] == [Decimal("1.00")]


async def test_a_run_without_a_budget_reserves_nothing(engine: AsyncEngine, spenders: None):
    seeded, _entry, first, second = await _two_spenders(engine, limit=None)

    await _tick(seeded, first)
    await _tick(seeded, second)

    assert seen[first.id] == [None] and seen[second.id] == [None]
    assert [a.reserved_usd for a in await _attempts(seeded, first)] == [None]


async def test_a_step_that_spends_nothing_neither_reserves_nor_waits(
    engine: AsyncEngine, spenders: None
):
    seeded, _entry, first, second = await _two_spenders(engine, limit="1.00", kind="test.free")

    begun, _outcome = await begin(seeded, await _row_id(seeded, first))
    await _tick(seeded, second)

    assert begun.attempt_no == 1
    assert [a.reserved_usd for a in await _attempts(seeded, first)] == [None]
    assert len(await _attempts(seeded, second)) == 1


def test_the_model_and_knowledge_steps_are_the_spenders():
    load_builtins()
    ids = {
        node_id
        for node_id, versions in REGISTRY.items()
        if any(definition.spends_budget for definition in versions.values())
    }
    assert {
        "agent.run",
        "ai.prompt",
        "ai.extract",
        "ai.classify",
        "ai.rewrite",
        "decide.yes_no",
        "decide.choose",
        "decide.score",
        "knowledge.search",
        "workflow.run",
    } <= ids

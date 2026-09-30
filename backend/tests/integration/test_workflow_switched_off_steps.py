"""A step with its own name, and one switched off: skipped when reached, refused where it breaks."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.workflow_run import NodeAttempt, NodeRun, NodeRunStatus, WorkflowRunStatus
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from tests.integration.workflow_run_support import drive, node_statuses, seed_run

pytestmark = pytest.mark.anyio

MAPPING = {
    "mappings": [{"target_field": "label", "source_path": "'mapped'", "coerce_to": "string"}]
}


def _node(definition_id: str, config: dict[str, Any] | None = None, **extra: Any) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
        **extra,
    )


def _edge(source: NodeInstance, target: NodeInstance, port: str = "out") -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port=port,
        target_node_id=target.id,
        target_port="in",
    )


def _bind(target: NodeInstance, field: str, source: NodeInstance, *path: str) -> Binding:
    return Binding(
        target_node_id=target.id,
        target_field=field,
        source=NodeOutputRef(node_id=source.id, port="out", field_path=tuple(path)),
    )


def _line(middle: NodeInstance, *, reads_middle: bool = False) -> WorkflowGraph:
    entry = _node("core.input")
    output = _node("core.output")
    return WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, middle, output),
        edges=(_edge(entry, middle), _edge(middle, output)),
        bindings=(
            _bind(middle, "source", entry, "payload"),
            _bind(output, "text", middle, "value", "values", "label")
            if reads_middle
            else _bind(output, "text", entry, "payload", "name"),
        ),
    )


async def _problems(engine: AsyncEngine, graph: WorkflowGraph) -> list[str]:
    seeded = await seed_run(engine, graph)
    async with async_sessionmaker(engine)() as db:
        with pytest.raises(GraphValidationError) as refused:
            await validate_graph(db, seeded.ctx, graph)
    return [problem["message"] for problem in refused.value.details["fields"]]


async def test_a_switched_off_step_is_skipped_and_the_run_goes_on(engine: AsyncEngine):
    middle = _node("data.map", MAPPING, disabled=True, label="Tidy the lead")
    graph = _line(middle)
    seeded = await seed_run(engine, graph, run_input={"name": "Ada"})
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output["text"] == "Ada"
    statuses = await node_statuses(seeded)
    assert statuses[middle.id] == NodeRunStatus.SUCCEEDED.value
    async with seeded.factory() as db:
        attempt = (
            await db.execute(
                select(NodeAttempt)
                .join(NodeRun, NodeRun.id == NodeAttempt.node_run_id)
                .where(NodeRun.node_instance_id == middle.id)
            )
        ).scalar_one()
    # It hands on what came into it: the trigger's output, untouched.
    assert attempt.result["output"]["payload"] == {"name": "Ada"}


async def test_a_later_step_reads_a_field_through_a_step_that_is_off(engine: AsyncEngine):
    first = _node("data.map", MAPPING)
    middle = _node("data.map", MAPPING, disabled=True)
    entry, output = _node("core.input"), _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, first, middle, output),
        edges=(_edge(entry, first), _edge(first, middle), _edge(middle, output)),
        bindings=(
            _bind(first, "source", entry, "payload"),
            _bind(middle, "source", entry, "payload"),
            # `first` hands on `values.label`, and `middle` declares `values` too.
            _bind(output, "text", middle, "values", "label"),
        ),
    )
    seeded = await seed_run(engine, graph, run_input={"name": "Ada"})
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output["text"] == "mapped"


async def test_a_step_that_is_off_with_two_ways_in_hands_on_nothing(engine: AsyncEngine):
    left, right = _node("data.map", MAPPING), _node("data.map", MAPPING)
    middle = _node("data.map", MAPPING, disabled=True)
    entry, output = _node("core.input"), _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, left, right, middle, output),
        edges=(
            _edge(entry, left),
            _edge(entry, right),
            _edge(left, middle),
            _edge(right, middle),
            _edge(middle, output),
        ),
        bindings=(
            _bind(left, "source", entry, "payload"),
            _bind(right, "source", entry, "payload"),
            _bind(middle, "source", entry, "payload"),
            _bind(output, "text", entry, "payload", "name"),
        ),
    )
    seeded = await seed_run(engine, graph, run_input={"name": "Ada"})

    await drive(seeded)

    async with seeded.factory() as db:
        attempt = (
            await db.execute(
                select(NodeAttempt)
                .join(NodeRun, NodeRun.id == NodeAttempt.node_run_id)
                .where(NodeRun.node_instance_id == middle.id)
            )
        ).scalar_one()
    assert attempt.result == {"status": "completed", "output": {"skipped": True}}


async def test_a_read_through_a_step_that_is_off_is_refused_when_what_comes_in_lacks_it(
    engine: AsyncEngine,
):
    before = _node("data.map", MAPPING, disabled=True)
    middle = _node("data.map", MAPPING, disabled=True)
    entry, output = _node("core.input"), _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, before, middle, output),
        edges=(_edge(entry, before), _edge(before, middle), _edge(middle, output)),
        bindings=(
            _bind(before, "source", entry, "payload"),
            _bind(middle, "source", entry, "payload"),
            # What reaches `middle` comes from a step that is off too.
            _bind(output, "text", middle, "values", "label"),
        ),
    )

    assert "This reads a step that is switched off, so it would receive nothing" in (
        await _problems(engine, graph)
    )


async def test_nothing_may_read_a_switched_off_step(engine: AsyncEngine):
    graph = _line(_node("data.map", MAPPING, disabled=True), reads_middle=True)

    assert "This reads a step that is switched off, so it would receive nothing" in (
        await _problems(engine, graph)
    )


async def test_the_trigger_and_a_deciding_step_cannot_be_switched_off(engine: AsyncEngine):
    entry = _node("core.input", disabled=True)
    decide = _node("logic.if", {"condition": "value.name == 'Ada'"}, disabled=True)
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, decide, output),
        edges=(_edge(entry, decide), _edge(decide, output, "true")),
        bindings=(
            _bind(decide, "value", entry, "payload"),
            _bind(output, "text", entry, "payload", "name"),
        ),
    )

    problems = await _problems(engine, graph)

    assert "The trigger cannot be switched off" in problems
    assert "A step that decides which way the run goes cannot be switched off" in problems


async def test_two_steps_may_not_share_a_name(engine: AsyncEngine):
    first = _node("data.map", MAPPING, label="Tidy")
    second = _node("data.map", MAPPING, label=" tidy ")
    entry = _node("core.input")
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, first, second, output),
        edges=(_edge(entry, first), _edge(first, second), _edge(second, output)),
        bindings=(
            _bind(first, "source", entry, "payload"),
            _bind(second, "source", entry, "payload"),
            _bind(output, "text", entry, "payload", "name"),
        ),
    )

    assert "Another step is already called 'tidy'" in await _problems(engine, graph)

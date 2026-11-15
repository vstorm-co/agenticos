"""A step with its own name, and one switched off: skipped when reached, refused where it breaks."""

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.workflow_run import NodeAttempt, NodeRun, NodeRunStatus, WorkflowRunStatus
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import set_aside, validate_graph
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


async def test_a_connected_step_that_is_off_is_not_asked_for_inputs_or_settings(
    engine: AsyncEngine,
):
    """Off, a step is handed neither input nor config, so nothing it leaves unset is
    missing: a Combine lists with no list bound, a Map with no mapping."""
    combine = _node("data.combine", disabled=True)
    unset = _node("data.map", disabled=True)
    entry, output = _node("core.input"), _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, combine, unset, output),
        edges=(_edge(entry, combine), _edge(combine, unset), _edge(unset, output)),
        bindings=(_bind(output, "text", entry, "payload", "name"),),
    )
    seeded = await seed_run(engine, graph, run_input={"name": "Ada"})
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output["text"] == "Ada"


async def test_the_settings_of_a_step_that_is_off_are_not_checked(engine: AsyncEngine):
    """It reads none of them; switching it back on is a change to publish, checked then.
    A half-filled mapping, a key mode with no key, an agent step with no agent."""
    half = _node("data.map", {"mappings": [{}]}, disabled=True)
    keyless = _node("data.combine", {"mode": "by_key"}, disabled=True)
    agentless = _node("agent.run", disabled=True)
    entry, output = _node("core.input"), _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, half, keyless, output, agentless),
        edges=(_edge(entry, half), _edge(half, keyless), _edge(keyless, output)),
        bindings=(_bind(output, "text", entry, "payload", "name"),),
    )
    seeded = await seed_run(engine, graph, run_input={"name": "Ada"})
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)

    switched_on = graph.model_copy(
        update={"nodes": tuple(n.model_copy(update={"disabled": False}) for n in graph.nodes)}
    )
    problems = await _problems(engine, switched_on)
    assert any("key" in problem for problem in problems)
    assert "Pick an agent from the catalog or configure one in this step" in " ".join(problems)


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


async def test_a_switched_off_step_with_no_edges_is_set_aside(engine: AsyncEngine):
    """Switching a step off is enough to park it beside the line, wires removed."""
    parked = _node("data.combine", {"mode": "append"}, disabled=True, label="Test data")
    graph = _line(_node("data.map", MAPPING))
    graph = graph.model_copy(update={"nodes": (*graph.nodes, parked)})
    seeded = await seed_run(engine, graph, run_input={"name": "Ada"})

    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)
    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert parked.id not in await node_statuses(seeded)


async def test_a_step_set_aside_keeps_its_bindings(engine: AsyncEngine):
    """Unwired, it still reads what it read: wired back in, it runs as it was."""
    parked = _node("data.combine", {"mode": "append"}, disabled=True)
    graph = _line(_node("data.map", MAPPING))
    entry = graph.nodes[0]
    graph = graph.model_copy(
        update={
            "nodes": (*graph.nodes, parked),
            "bindings": (
                *graph.bindings,
                _bind(parked, "first", entry, "payload", "items"),
                _bind(parked, "second", entry, "payload", "items"),
            ),
        }
    )
    seeded = await seed_run(engine, graph)

    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)


async def test_nothing_may_read_a_step_set_aside(engine: AsyncEngine):
    parked = _node("data.map", MAPPING, disabled=True)
    graph = _line(_node("data.map", MAPPING))
    entry, middle, output = graph.nodes
    graph = graph.model_copy(
        update={
            "nodes": (*graph.nodes, parked),
            "bindings": (
                _bind(middle, "source", entry, "payload"),
                _bind(output, "text", parked, "value", "values", "label"),
            ),
        }
    )

    assert "This reads a step that is switched off, so it would receive nothing" in (
        await _problems(engine, graph)
    )


async def test_a_step_with_no_edges_that_is_on_is_still_unreachable(engine: AsyncEngine):
    island = _node("data.combine", {"mode": "append"})
    graph = _line(_node("data.map", MAPPING))
    graph = graph.model_copy(update={"nodes": (*graph.nodes, island)})

    assert "This node is not reachable from the entry node" in await _problems(engine, graph)


async def test_a_switched_off_step_wired_out_of_nowhere_is_still_unreachable(
    engine: AsyncEngine,
):
    """Only a step with no edge at all is set aside: one feeding the line is not."""
    entry = _node("core.input")
    stray = _node("data.map", MAPPING, disabled=True)
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, stray, output),
        edges=(_edge(entry, output), _edge(stray, output)),
        bindings=(_bind(output, "text", entry, "payload", "name"),),
    )

    assert "This node is not reachable from the entry node" in await _problems(engine, graph)


async def test_a_deciding_step_set_aside_may_be_switched_off(engine: AsyncEngine):
    """With no connection it has no way to decide, so switching it off breaks nothing."""
    parked = _node("logic.if", {"condition": "value.name == 'Ada'"}, disabled=True)
    graph = _line(_node("data.map", MAPPING))
    graph = graph.model_copy(update={"nodes": (*graph.nodes, parked)})
    seeded = await seed_run(engine, graph, run_input={"name": "Ada"})

    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)
    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert parked.id not in await node_statuses(seeded)


async def test_a_loop_result_step_cannot_be_switched_off_even_unwired(engine: AsyncEngine):
    entry = _node("core.input")
    loop = _node("control.foreach")
    item = _node("loop.item", scope_id=loop.id)
    result = _node("loop.yield", scope_id=loop.id, disabled=True)
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, loop, item, result, output),
        edges=(_edge(entry, loop), _edge(loop, output, "done")),
        bindings=(_bind(loop, "items", entry, "payload", "items"),),
    )

    assert "A loop's item or result step cannot be switched off" in await _problems(engine, graph)


async def test_a_trigger_switched_off_with_no_edges_is_never_set_aside():
    """A run can start at any trigger, wired or not: set aside, its run would wait
    on no step while its own row is already written, and never end."""
    entry = _node("core.input")
    webhook = _node("trigger.webhook", disabled=True)
    parked = _node("data.map", MAPPING, disabled=True)
    graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry, webhook, parked))

    assert set_aside(graph) == {parked.id}


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


@pytest.mark.parametrize("definition_id", ["data.map", "logic.split", "error.handle"])
async def test_a_parked_step_keeps_its_error_routing_policy(
    engine: AsyncEngine, definition_id: str
) -> None:
    from app.workflows.contracts.policy import NodePolicy

    entry, output = _node("core.input"), _node("core.output")
    parked = _node(definition_id, disabled=True, policy=NodePolicy(on_error="route"))
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, output, parked),
        edges=(_edge(entry, output),),
        bindings=(_bind(output, "text", entry, "payload", "name"),),
    )
    seeded = await seed_run(engine, graph, run_input={"name": "Ada"})
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)
    assert (await drive(seeded)).status == WorkflowRunStatus.SUCCEEDED.value


@pytest.mark.parametrize("kind", ["table", "file"])
async def test_switched_off_resource_bindings_are_checked_only_when_enabled(
    engine: AsyncEngine, kind: str
) -> None:
    from app.workflows.contracts.io import FileRef, TableIORef

    source = (
        TableIORef(table_id=uuid.uuid4(), schema_version=1)
        if kind == "table"
        else FileRef(file_id=uuid.uuid4(), content_type="text/plain", byte_size=1)
    )
    entry, output = _node("core.input"), _node("core.output")
    parked = _node("data.map", MAPPING, disabled=True)
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, output, parked),
        edges=(_edge(entry, output),),
        bindings=(
            _bind(output, "text", entry, "payload", "name"),
            Binding(target_node_id=parked.id, target_field="source", source=source),
        ),
    )
    seeded = await seed_run(engine, graph, run_input={"name": "Ada"})
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)
    assert (await drive(seeded)).status == WorkflowRunStatus.SUCCEEDED.value
    enabled = graph.model_copy(
        update={"nodes": tuple(n.model_copy(update={"disabled": False}) for n in graph.nodes)}
    )
    assert any(
        "does not exist or is not accessible" in message
        for message in await _problems(engine, enabled)
    )

"""The graph-boundary, data and branching nodes, run end to end (#1789).

A graph is published through the real validator and then driven through the
real dispatcher against Postgres, so what is proved is what a user's workflow
does: the input reaches the graph, only the taken branch runs, the other is
skipped node by node, the merge carries the branch that ran, and the output is
recorded on the run.
"""

import uuid
from typing import Any

import pytest
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.workflow_run import NodeRunStatus, WorkflowRunStatus
from app.workflows.contracts.io import Binding, LiteralValue, NodeOutputRef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from tests.integration.workflow_run_support import SeededRun, drive, node_statuses, seed_run

pytestmark = pytest.mark.anyio


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, target: NodeInstance, source_port: str = "out") -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port=source_port,
        target_node_id=target.id,
        target_port="in",
    )


def _bind(target: NodeInstance, field: str, source: NodeInstance, port: str, *path: str) -> Binding:
    return Binding(
        target_node_id=target.id,
        target_field=field,
        source=NodeOutputRef(node_id=source.id, port=port, field_path=tuple(path)),
    )


class _Branching:
    """input -> if -> (true: map "approved" | false: map "rejected") -> merge -> output."""

    def __init__(self) -> None:
        self.entry = _node("core.input")
        self.decide = _node("logic.if", {"condition": "value.amount > `100`"})
        mapping = lambda label: {  # noqa: E731 - two one-line configs
            "mappings": [
                {"target_field": "label", "source_path": f"'{label}'", "coerce_to": "string"},
                {"target_field": "amount", "source_path": "source.amount", "coerce_to": "number"},
            ]
        }
        self.approve = _node("data.map", mapping("approved"))
        self.reject = _node("data.map", mapping("rejected"))
        self.merge = _node("logic.merge")
        self.output = _node("core.output")
        self.graph = WorkflowGraph(
            entry_node_id=self.entry.id,
            nodes=(self.entry, self.decide, self.approve, self.reject, self.merge, self.output),
            edges=(
                _edge(self.entry, self.decide),
                _edge(self.decide, self.approve, "true"),
                _edge(self.decide, self.reject, "false"),
                _edge(self.approve, self.merge),
                _edge(self.reject, self.merge),
                _edge(self.merge, self.output),
            ),
            bindings=(
                _bind(self.decide, "value", self.entry, "out", "payload"),
                _bind(self.approve, "source", self.entry, "out", "payload"),
                _bind(self.reject, "source", self.entry, "out", "payload"),
                _bind(self.output, "text", self.merge, "out", "value", "values", "label"),
                _bind(self.output, "structured", self.merge, "out", "value", "values"),
            ),
        )


async def _published(engine: AsyncEngine, graph: WorkflowGraph, seeded_ctx: Any) -> WorkflowGraph:
    async with async_sessionmaker(engine)() as db:
        return await validate_graph(db, seeded_ctx, graph)


async def _run(engine: AsyncEngine, graph: WorkflowGraph, run_input: dict[str, Any]) -> SeededRun:
    seeded = await seed_run(engine, graph, run_input=run_input)
    await _published(engine, graph, seeded.ctx)
    return seeded


@pytest.mark.parametrize(
    ("amount", "taken", "label"),
    [(250, "approve", "approved"), (40, "reject", "rejected")],
    ids=["true-branch", "false-branch"],
)
async def test_only_the_taken_branch_runs_and_the_merge_carries_it_to_the_output(
    engine: AsyncEngine, amount: int, taken: str, label: str
):
    shape = _Branching()
    seeded = await _run(engine, shape.graph, {"amount": amount, "customer": "Ada"})

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    statuses = await node_statuses(seeded)
    ran, skipped = (
        (shape.approve, shape.reject) if taken == "approve" else (shape.reject, shape.approve)
    )
    assert statuses[ran.id] == NodeRunStatus.SUCCEEDED.value
    assert statuses[skipped.id] == NodeRunStatus.SKIPPED.value
    assert statuses[shape.merge.id] == NodeRunStatus.SUCCEEDED.value
    assert run.output == {
        "text": label,
        "sources": [],
        "artifacts": [],
        "structured": {"label": label, "amount": float(amount)},
    }


async def test_a_skipped_branch_is_skipped_node_by_node_down_to_the_merge(engine: AsyncEngine):
    """A two-node untaken branch: both nodes are recorded skipped, neither runs."""
    entry = _node("core.input")
    decide = _node("logic.if", {"condition": "value.go"})
    first = _node("data.map", {"mappings": [{"target_field": "a", "source_path": "'x'"}]})
    second = _node("data.map", {"mappings": [{"target_field": "b", "source_path": "'y'"}]})
    direct = _node("data.map", {"mappings": [{"target_field": "c", "source_path": "'z'"}]})
    merge = _node("logic.merge")
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, decide, first, second, direct, merge, output),
        edges=(
            _edge(entry, decide),
            _edge(decide, first, "true"),
            _edge(first, second),
            _edge(second, merge),
            _edge(decide, direct, "false"),
            _edge(direct, merge),
            _edge(merge, output),
        ),
        bindings=(_bind(decide, "value", entry, "out", "payload"),),
    )
    seeded = await _run(engine, graph, {"go": False})

    run = await drive(seeded)

    statuses = await node_statuses(seeded)
    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert statuses[first.id] == statuses[second.id] == NodeRunStatus.SKIPPED.value
    assert statuses[direct.id] == NodeRunStatus.SUCCEEDED.value
    assert run.output == {"text": None, "sources": [], "artifacts": [], "structured": None}


async def test_a_value_that_cannot_take_its_declared_type_fails_the_run_before_the_output(
    engine: AsyncEngine,
):
    entry = _node("core.input")
    mapping = _node(
        "data.map",
        {"mappings": [{"target_field": "n", "source_path": "source.n", "coerce_to": "integer"}]},
    )
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, mapping, output),
        edges=(_edge(entry, mapping), _edge(mapping, output)),
        bindings=(_bind(mapping, "source", entry, "out", "payload"),),
    )
    seeded = await _run(engine, graph, {"n": "not a number"})

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "MAPPING_COERCION_FAILED"
    assert run.output is None
    assert output.id not in await node_statuses(seeded)


def _held_value_graph(value: Any, *text_path: str) -> tuple[WorkflowGraph, NodeInstance]:
    """input -> data.value (typed in) -> output, with `text` read from a path into the
    held value and `structured` from the whole of it."""
    entry = _node("core.input")
    data = _node("data.value")
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, data, output),
        edges=(_edge(entry, data), _edge(data, output)),
        bindings=(
            Binding(target_node_id=data.id, target_field="value", source=LiteralValue(value=value)),
            _bind(output, "text", data, "out", "value", *text_path),
            _bind(output, "structured", data, "out", "value"),
        ),
    )
    return graph, data


async def test_a_typed_in_object_is_held_for_later_steps_whole_and_by_path(engine: AsyncEngine):
    held = {"customer": {"email": "ada@example.com"}, "tags": ["vip", "eu"], "limit": 10}
    graph, data = _held_value_graph(held, "customer", "email")
    seeded = await _run(engine, graph, {})

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert (await node_statuses(seeded))[data.id] == NodeRunStatus.SUCCEEDED.value
    assert run.output == {
        "text": "ada@example.com",
        "sources": [],
        "artifacts": [],
        "structured": held,
    }


async def test_a_path_into_the_held_value_of_the_wrong_type_fails_at_dispatch(
    engine: AsyncEngine,
):
    """The held value has no schema, so a path into it publishes and is checked when
    the step reading it runs: a list where text is wanted fails that step."""
    graph, _ = _held_value_graph({"tags": ["vip", "eu"]}, "tags")
    seeded = await _run(engine, graph, {})

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "INVALID_BINDING"


async def test_a_bound_path_the_payload_lacks_fails_the_target_node_at_dispatch(
    engine: AsyncEngine,
):
    """Paths into the payload are checked when the node runs, not at publish."""
    entry = _node("core.input")
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, output),
        edges=(_edge(entry, output),),
        bindings=(_bind(output, "text", entry, "out", "payload", "answer"),),
    )
    seeded = await _run(engine, graph, {"answer": {"not": "text"}})

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "INVALID_BINDING"


async def test_a_literal_binding_the_type_check_can_see_is_still_refused_at_publish(
    engine: AsyncEngine,
):
    entry = _node("core.input")
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, output),
        edges=(_edge(entry, output),),
        bindings=(
            Binding(target_node_id=output.id, target_field="text", source=LiteralValue(value=42)),
        ),
    )
    seeded = await seed_run(engine, graph)

    with pytest.raises(GraphValidationError):
        await _published(engine, graph, seeded.ctx)


@pytest.mark.parametrize(
    "condition",
    ["value.[", "sort_by(value, &name)", "map(&x, value)"],
    ids=["malformed", "expression-reference", "map"],
)
async def test_a_condition_that_does_not_parse_or_calls_a_refused_function_cannot_publish(
    engine: AsyncEngine, condition: str
):
    entry = _node("core.input")
    decide = _node("logic.if", {"condition": condition})
    graph = WorkflowGraph(
        entry_node_id=entry.id, nodes=(entry, decide), edges=(_edge(entry, decide),)
    )
    seeded = await seed_run(engine, graph)

    with pytest.raises(GraphValidationError) as refused:
        await _published(engine, graph, seeded.ctx)

    assert any(
        problem["field"].startswith(f"nodes.{decide.id}")
        for problem in refused.value.details["fields"]
    )


async def test_a_merge_whose_branches_leave_the_same_port_cannot_publish(engine: AsyncEngine):
    """Both would run together, so the merge could not tell which one to carry."""
    entry = _node("core.input")
    decide = _node("logic.if", {"condition": "value"})
    left = _node("data.map", {"mappings": [{"target_field": "a", "source_path": "'x'"}]})
    right = _node("data.map", {"mappings": [{"target_field": "b", "source_path": "'y'"}]})
    merge = _node("logic.merge")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, decide, left, right, merge),
        edges=(
            _edge(entry, decide),
            _edge(decide, left, "true"),
            _edge(decide, right, "true"),
            _edge(left, merge),
            _edge(right, merge),
        ),
    )
    seeded = await seed_run(engine, graph)

    with pytest.raises(GraphValidationError) as refused:
        await _published(engine, graph, seeded.ctx)

    assert f"nodes.{merge.id}" in {problem["field"] for problem in refused.value.details["fields"]}


@pytest.mark.parametrize(
    ("held", "definition", "config", "field", "result_key", "expected"),
    [
        ("hello", "text.compare", {}, "a", "score", 1.0),
        ([1, 2], "data.filter", {"condition": "item != `null`"}, "items", "items", [1, 2]),
        (
            {"x": 7},
            "data.map",
            {"mappings": [{"target_field": "x", "source_path": "source.x"}]},
            "source",
            "values",
            {"x": 7},
        ),
    ],
)
async def test_a_whole_data_value_reaches_a_typed_consumer(
    engine: AsyncEngine,
    held: JsonValue,
    definition: str,
    config: dict[str, JsonValue],
    field: str,
    result_key: str,
    expected: JsonValue,
) -> None:
    entry, data, reader, output = (
        _node("core.input"),
        _node("data.value"),
        _node(definition, config),
        _node("core.output"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, data, reader, output),
        edges=(_edge(entry, data), _edge(data, reader), _edge(reader, output)),
        bindings=(
            Binding(target_node_id=data.id, target_field="value", source=LiteralValue(value=held)),
            _bind(reader, field, data, "out", "value"),
            *(
                (
                    Binding(
                        target_node_id=reader.id,
                        target_field="b",
                        source=LiteralValue(value="hello"),
                    ),
                )
                if definition == "text.compare"
                else ()
            ),
            _bind(output, "structured", reader, "out"),
        ),
    )
    run = await drive(await _run(engine, graph, {}))
    assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
    assert run.output is not None and run.output["structured"][result_key] == expected


async def test_a_typed_upstream_value_can_be_held_by_data(engine: AsyncEngine) -> None:
    first, data, output = (
        _node("debug.echo", {"message": "hello"}),
        _node("data.value"),
        _node("core.output"),
    )
    graph = WorkflowGraph(
        entry_node_id=first.id,
        nodes=(first, data, output),
        edges=(_edge(first, data), _edge(data, output)),
        bindings=(
            _bind(data, "value", first, "out", "echoed"),
            _bind(output, "text", data, "out", "value"),
        ),
    )
    run = await drive(await _run(engine, graph, {}))
    assert run.status == WorkflowRunStatus.SUCCEEDED.value, run.error
    assert run.output is not None and run.output["text"] == "hello"


@pytest.mark.parametrize("customer", ["scalar", ["array"], 3, False, None])
async def test_a_dynamic_path_through_a_non_object_fails_as_invalid_binding(
    engine: AsyncEngine,
    customer: JsonValue,
) -> None:
    entry, data, reader = _node("core.input"), _node("data.value"), _node("text.compare")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, data, reader),
        edges=(_edge(entry, data), _edge(data, reader)),
        bindings=(
            Binding(
                target_node_id=data.id,
                target_field="value",
                source=LiteralValue(value={"customer": customer}),
            ),
            _bind(reader, "a", data, "out", "value", "customer", "email"),
            Binding(target_node_id=reader.id, target_field="b", source=LiteralValue(value="hello")),
        ),
    )
    seeded = await _run(engine, graph, {})
    run = await drive(seeded)
    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "INVALID_BINDING"
    assert (await node_statuses(seeded))[reader.id] == NodeRunStatus.FAILED.value

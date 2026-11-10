"""A loop's body is the steps that name it, not the steps its wires reach (#2770).

Membership used to be derived by walking wires from the loop's `body` port, so
deleting a wire inside a body dropped what came after it out of the loop, a
second wire from `body` made a step reachable from the start of every iteration
without the editor drawing it, and a pasted step landed outside the body. Each
step now stores the loop it belongs to (`scope_id`); a body starts at its
`loop.item` by definition, and the loop has no `body` port to wire at all.
"""

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.core.permissions import AuthContext, OrgRoleName
from app.workflows import _registry
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.legacy import adopt_named_loop_bodies
from app.workflows.graph.model import (
    Edge,
    NodeInstance,
    NodePosition,
    WorkflowGraph,
    loop_item_of,
)
from app.workflows.graph.validate import (
    analyze_graph,
    derive_scopes,
    graph_size_problems,
    node_scope_map,
    validate_graph,
)
from app.workflows.triggers import entry_graph

pytestmark = pytest.mark.anyio


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


def _node(definition_id: str, scope: NodeInstance | None = None, **extra: Any) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        layout=NodePosition(x=0, y=0),
        scope_id=None if scope is None else scope.id,
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


def _bind(target: NodeInstance, field: str, source: NodeInstance, port: str, *path: str) -> Binding:
    return Binding(
        target_node_id=target.id,
        target_field=field,
        source=NodeOutputRef(node_id=source.id, port=port, field_path=path),
    )


_MAP = {"mappings": [{"target_field": "n", "source_path": "source", "coerce_to": "number"}]}


async def _problems(graph: WorkflowGraph) -> list[str]:
    try:
        await validate_graph(MagicMock(), _ctx(), graph)
    except GraphValidationError as exc:
        return [problem["message"] for problem in exc.details["fields"]]
    return []


class _Loop:
    """entry -> loop -done-> out; inside the loop: item -> step -> yield."""

    def __init__(self) -> None:
        self.entry = _node("core.input")
        self.loop = _node("control.foreach")
        self.item = _node("loop.item", self.loop)
        self.step = _node("data.map", self.loop, config=_MAP)
        self.yield_ = _node("loop.yield", self.loop)
        self.out = _node("core.output")

    def graph(
        self,
        *,
        nodes: tuple[NodeInstance, ...] | None = None,
        edges: tuple[Edge, ...] | None = None,
        bindings: tuple[Binding, ...] = (),
    ) -> WorkflowGraph:
        return WorkflowGraph(
            entry_node_id=self.entry.id,
            nodes=nodes
            if nodes is not None
            else (self.entry, self.loop, self.item, self.step, self.yield_, self.out),
            edges=edges
            if edges is not None
            else (
                _edge(self.entry, self.loop),
                _edge(self.item, self.step),
                _edge(self.step, self.yield_),
                _edge(self.loop, self.out, "done"),
            ),
            bindings=(
                _bind(self.loop, "items", self.entry, "out", "payload", "xs"),
                _bind(self.step, "source", self.item, "out", "item"),
                *bindings,
            ),
        )


# The definitions


def test_a_loop_has_no_port_to_wire_its_body_from():
    foreach = _registry.get("control.foreach", 1)
    assert [port.id for port in foreach.ports if port.kind == "output"] == ["done"]


def test_a_loop_item_takes_no_wire_in():
    item = _registry.get("loop.item", 1)
    assert [port.id for port in item.ports if port.kind == "input"] == []


# Membership


def test_a_body_is_the_steps_that_name_their_loop():
    shape = _Loop()
    scopes = derive_scopes(shape.graph()).scopes
    assert len(scopes) == 1
    assert scopes[0].scope_node_id == shape.loop.id
    assert scopes[0].body_node_ids == frozenset({shape.item.id, shape.step.id, shape.yield_.id})


def test_a_step_cut_off_inside_a_body_stays_in_that_body():
    shape = _Loop()
    graph = shape.graph(
        edges=(
            _edge(shape.entry, shape.loop),
            _edge(shape.step, shape.yield_),
            _edge(shape.loop, shape.out, "done"),
        )
    )
    owners = node_scope_map(derive_scopes(graph))
    assert owners[shape.step.id] == shape.loop.id
    assert owners[shape.yield_.id] == shape.loop.id


def test_a_nested_body_belongs_to_its_innermost_loop_and_counts_in_the_outer_one():
    shape = _Loop()
    inner = _node("control.foreach", shape.loop)
    inner_item = _node("loop.item", inner)
    inner_yield = _node("loop.yield", inner)
    graph = shape.graph(
        nodes=(
            shape.entry,
            shape.loop,
            shape.item,
            inner,
            inner_item,
            inner_yield,
            shape.yield_,
            shape.out,
        ),
        edges=(
            _edge(shape.entry, shape.loop),
            _edge(shape.item, inner),
            _edge(inner_item, inner_yield),
            _edge(inner, shape.yield_, "done"),
            _edge(shape.loop, shape.out, "done"),
        ),
    )
    derived = derive_scopes(graph)
    owners = node_scope_map(derived)
    assert owners[inner.id] == shape.loop.id
    assert owners[inner_item.id] == inner.id
    outer = next(scope for scope in derived.scopes if scope.scope_node_id == shape.loop.id)
    assert {inner_item.id, inner_yield.id} <= outer.body_node_ids


def test_the_loop_item_of_a_loop_is_found_by_membership():
    shape = _Loop()
    assert loop_item_of(derive_scopes(shape.graph()), shape.loop.id) == shape.item.id


# Publishing


async def test_a_loop_without_any_wire_into_its_body_publishes():
    shape = _Loop()
    graph = shape.graph(bindings=(_bind(shape.yield_, "value", shape.entry, "out", "payload"),))
    assert await _problems(graph) == []


async def test_a_body_step_the_loop_item_does_not_reach_is_refused():
    shape = _Loop()
    graph = shape.graph(
        edges=(
            _edge(shape.entry, shape.loop),
            _edge(shape.step, shape.yield_),
            _edge(shape.loop, shape.out, "done"),
        )
    )
    problems = await _problems(graph)
    assert "This step is not reachable from its loop's item step" in problems
    assert "This node is not reachable from the entry node" not in problems


async def test_a_body_step_reached_by_two_paths_is_reached():
    shape = _Loop()
    graph = shape.graph(
        edges=(
            _edge(shape.entry, shape.loop),
            _edge(shape.item, shape.step),
            _edge(shape.item, shape.yield_),
            _edge(shape.step, shape.yield_),
            _edge(shape.loop, shape.out, "done"),
        )
    )
    assert "This step is not reachable from its loop's item step" not in await _problems(graph)


async def test_a_wire_from_outside_a_body_into_it_is_refused():
    shape = _Loop()
    graph = shape.graph(
        edges=(
            _edge(shape.entry, shape.loop),
            _edge(shape.entry, shape.step),
            _edge(shape.item, shape.step),
            _edge(shape.step, shape.yield_),
            _edge(shape.loop, shape.out, "done"),
        )
    )
    assert "This edge crosses a scope boundary" in await _problems(graph)


async def test_a_step_naming_something_that_is_not_a_loop_is_refused():
    shape = _Loop()
    stray = _node("data.map", shape.entry, config=_MAP)
    graph = shape.graph(
        nodes=(shape.entry, shape.loop, shape.item, shape.step, shape.yield_, shape.out, stray),
    )
    assert any("is not a loop" in p for p in await _problems(graph))


async def test_a_step_naming_a_loop_not_in_the_graph_is_refused():
    shape = _Loop()
    stray = NodeInstance(
        id=uuid.uuid4(),
        definition_id="data.map",
        definition_version=1,
        config=_MAP,
        layout=NodePosition(x=0, y=0),
        scope_id=uuid.uuid4(),
    )
    graph = shape.graph(
        nodes=(shape.entry, shape.loop, shape.item, shape.step, shape.yield_, shape.out, stray),
    )
    assert any("is not in this graph" in p for p in await _problems(graph))


async def test_a_body_without_its_item_step_is_refused():
    shape = _Loop()
    graph = shape.graph(
        nodes=(shape.entry, shape.loop, shape.step, shape.yield_, shape.out),
        edges=(
            _edge(shape.entry, shape.loop),
            _edge(shape.step, shape.yield_),
            _edge(shape.loop, shape.out, "done"),
        ),
    )
    graph = graph.model_copy(update={"bindings": graph.bindings[:1]})
    assert any("start at exactly one loop item" in p for p in await _problems(graph))


def test_a_body_step_may_read_what_ran_before_the_loop():
    shape = _Loop()
    precede = analyze_graph(shape.graph()).precede
    assert {shape.loop.id, shape.item.id} <= precede[shape.step.id]


# A run started from one of several triggers


def test_a_run_from_a_trigger_keeps_the_whole_body_of_every_loop_it_reaches():
    shape = _Loop()
    kept = entry_graph(shape.graph(), shape.entry.id)
    ids = {node.id for node in kept.nodes}
    assert {shape.item.id, shape.step.id, shape.yield_.id} <= ids


# Graphs written before #2770


def _legacy(shape: _Loop, *extra_edges: dict[str, Any]) -> dict[str, Any]:
    def node(instance: NodeInstance) -> dict[str, Any]:
        return {
            "id": str(instance.id),
            "definition_id": instance.definition_id,
            "definition_version": 1,
            "config": instance.config,
            "layout": {"x": 0, "y": 0},
        }

    def edge(source: NodeInstance, port: str, target: NodeInstance) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "source_node_id": str(source.id),
            "source_port": port,
            "target_node_id": str(target.id),
            "target_port": "in",
        }

    return {
        "entry_node_id": str(shape.entry.id),
        "nodes": [node(n) for n in (shape.entry, shape.loop, shape.item, shape.step, shape.yield_)],
        "edges": [
            edge(shape.entry, "out", shape.loop),
            edge(shape.loop, "body", shape.item),
            edge(shape.item, "out", shape.step),
            edge(shape.step, "out", shape.yield_),
            *extra_edges,
        ],
        "bindings": [],
        "scopes": [
            {
                "scope_node_id": str(shape.loop.id),
                "body_node_ids": [str(shape.item.id), str(shape.step.id), str(shape.yield_.id)],
                "entry_port": "body",
                "exit_node_id": str(shape.loop.id),
                "exit_port": "done",
            }
        ],
    }


def test_a_graph_wired_through_the_body_port_reads_as_members_of_the_loop():
    shape = _Loop()
    graph = WorkflowGraph.model_validate(_legacy(shape))
    by_id = graph.node_by_id
    assert by_id[shape.item.id].scope_id == shape.loop.id
    assert by_id[shape.step.id].scope_id == shape.loop.id
    assert by_id[shape.yield_.id].scope_id == shape.loop.id
    assert by_id[shape.loop.id].scope_id is None
    assert not any(edge.source_port == "body" for edge in graph.edges)
    assert len(graph.edges) == 3


def test_a_second_wire_from_the_body_port_starts_at_the_loop_item_instead():
    shape = _Loop()
    stray = {
        "id": str(uuid.uuid4()),
        "source_node_id": str(shape.loop.id),
        "source_port": "body",
        "target_node_id": str(shape.yield_.id),
        "target_port": "in",
    }
    graph = WorkflowGraph.model_validate(_legacy(shape, stray))
    rewired = next(edge for edge in graph.edges if edge.id == uuid.UUID(stray["id"]))
    assert rewired.source_node_id == shape.item.id
    assert rewired.source_port == "out"
    assert rewired.target_node_id == shape.yield_.id


async def test_two_loops_named_inside_each_other_are_refused_without_hanging():
    shape = _Loop()
    first = NodeInstance(
        id=uuid.uuid4(),
        definition_id="control.foreach",
        definition_version=1,
        layout=NodePosition(x=0, y=0),
    )
    second = _node("control.foreach", first)
    first = first.model_copy(update={"scope_id": second.id})
    graph = shape.graph(
        nodes=(
            shape.entry,
            shape.loop,
            shape.item,
            shape.step,
            shape.yield_,
            shape.out,
            first,
            second,
        )
    )
    scopes = {scope.scope_node_id: scope for scope in derive_scopes(graph).scopes}
    assert scopes[first.id].body_node_ids == frozenset({second.id})
    assert "A loop cannot sit inside itself" in await _problems(graph)


def test_a_second_body_wire_already_drawn_from_the_loop_item_is_not_drawn_twice():
    shape = _Loop()
    again = {
        "id": str(uuid.uuid4()),
        "source_node_id": str(shape.loop.id),
        "source_port": "body",
        "target_node_id": str(shape.step.id),
        "target_port": "in",
    }
    graph = WorkflowGraph.model_validate(_legacy(shape, again))
    from_item = [edge for edge in graph.edges if edge.source_node_id == shape.item.id]
    assert [edge.target_node_id for edge in from_item] == [shape.step.id]


def test_a_legacy_graph_past_the_size_ceiling_is_left_for_the_size_check_to_refuse(
    monkeypatch: pytest.MonkeyPatch,
):
    """Converting would remove the very edges the ceiling counts, and costs work on each."""
    monkeypatch.setattr("app.core.config.settings.WORKFLOW_GRAPH_MAX_EDGES", 4)
    shape = _Loop()
    repeated = [
        {
            "id": str(uuid.uuid4()),
            "source_node_id": str(shape.loop.id),
            "source_port": "body",
            "target_node_id": str(shape.step.id),
            "target_port": "in",
        }
        for _ in range(3)
    ]
    raw = _legacy(shape, *repeated)
    kept = adopt_named_loop_bodies(raw)
    assert kept["edges"] is raw["edges"] and kept["nodes"] is raw["nodes"]
    assert graph_size_problems(WorkflowGraph.model_validate(raw)) == [
        ("edges", "A graph holds at most 4 edges")
    ]


def test_a_legacy_graph_sent_without_scopes_still_reads_as_members_of_the_loop():
    shape = _Loop()
    raw = _legacy(shape)
    del raw["scopes"]
    graph = WorkflowGraph.model_validate(raw)
    assert graph.node_by_id[shape.step.id].scope_id == shape.loop.id


@pytest.mark.parametrize(
    ("where", "field"),
    [
        ("nodes", "id"),
        ("edges", "source_node_id"),
        ("edges", "target_node_id"),
        ("edges", "source_port"),
    ],
)
def test_a_legacy_graph_with_a_malformed_identifier_is_a_validation_error(where: str, field: str):
    """Read before the fields are validated, a list where an id belongs must not raise `TypeError`."""
    shape = _Loop()
    raw = _legacy(shape)
    raw[where][1][field] = []
    with pytest.raises(ValidationError):
        WorkflowGraph.model_validate(raw)

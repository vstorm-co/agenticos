"""Serialization tests for the graph shape, and layout invariance (AC3/AC4).

AC3: layout moves do not alter execution semantics. AC4: contract
serialization tests cover nested bindings.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.workflows.contracts.io import Binding, LiteralValue, NodeOutputRef
from app.workflows.graph.model import NodeInstance, NodePosition, ScopeBoundary, WorkflowGraph


def _node(**overrides: object) -> NodeInstance:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "definition_id": "debug.echo",
        "definition_version": 1,
        "config": {"message": "hi"},
        "layout": NodePosition(x=0, y=0),
    }
    defaults.update(overrides)
    return NodeInstance(**defaults)  # type: ignore[arg-type]


def test_a_workflow_graph_with_a_scope_boundary_round_trips_body_node_ids():
    scope_owner = uuid4()
    body_a, body_b = uuid4(), uuid4()
    entry = _node()
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry,),
        scopes=(
            ScopeBoundary(
                scope_node_id=scope_owner,
                body_node_ids=frozenset({body_a, body_b}),
                entry_port="body",
                exit_port="done",
            ),
        ),
    )
    restored = WorkflowGraph.model_validate(graph.model_dump(mode="json"))
    assert restored.scopes[0].body_node_ids == frozenset({body_a, body_b})
    assert restored.scopes[0].scope_node_id == scope_owner


def test_a_graph_with_a_nested_node_output_ref_binding_round_trips():
    source, target = _node(), _node()
    binding = Binding(
        target_node_id=target.id,
        target_field="message",
        source=NodeOutputRef(node_id=source.id, port="out", field_path=("echoed",)),
    )
    graph = WorkflowGraph(entry_node_id=source.id, nodes=(source, target), bindings=(binding,))
    restored = WorkflowGraph.model_validate(graph.model_dump(mode="json"))
    assert restored.bindings == (binding,)
    assert isinstance(restored.bindings[0].source, NodeOutputRef)
    assert restored.bindings[0].source.field_path == ("echoed",)


def test_a_graph_rejects_an_unknown_top_level_field():
    node = _node()
    payload = {
        "entry_node_id": str(node.id),
        "nodes": [node.model_dump(mode="json")],
        "not_a_real_field": True,
    }
    with pytest.raises(ValidationError):
        WorkflowGraph.model_validate(payload)


def test_layout_differences_alone_do_not_change_the_graphs_edges_or_bindings():
    """AC3: layout moves do not alter execution semantics.

    Two graphs identical except for `NodePosition` compare equal on every
    field validation actually reads - nothing here, or in `validate_graph`,
    ever dereferences `.layout`.
    """
    node_id = uuid4()
    a = WorkflowGraph(
        entry_node_id=node_id,
        nodes=(_node(id=node_id, layout=NodePosition(x=0, y=0)),),
    )
    b = WorkflowGraph(
        entry_node_id=node_id,
        nodes=(_node(id=node_id, layout=NodePosition(x=999, y=-42)),),
    )
    assert a.entry_node_id == b.entry_node_id
    assert a.edges == b.edges
    assert a.bindings == b.bindings
    assert [n.id for n in a.nodes] == [n.id for n in b.nodes]
    assert a.nodes[0].layout != b.nodes[0].layout


def test_a_literal_binding_round_trips():
    binding = Binding(target_node_id=uuid4(), target_field="x", source=LiteralValue(value={"a": 1}))
    restored = Binding.model_validate(binding.model_dump(mode="json"))
    assert restored == binding

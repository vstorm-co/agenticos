"""The graph a step test runs: the step, the steps it depends on, and their known data.

Testing one step should not mean running the whole workflow again. The step
keeps only what leads to it - its ancestors along the edges, and the whole body
of any loop among them - and every ancestor with data already known (from the
author's pin or from the last test run) hands that data on instead of running.
What the step leads to is left out, so nothing after it runs.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.workflows import _registry
from app.workflows.graph.errors import StepNotTestableError
from app.workflows.graph.model import WorkflowGraph
from app.workflows.graph.validate import node_scope_map


def step_subgraph(
    graph: WorkflowGraph, node_id: UUID, known_outputs: Mapping[UUID, dict[str, Any]]
) -> WorkflowGraph:
    """The part of a validated `graph` a test of `node_id` runs.

    The step itself always runs: its own pin is dropped. An ancestor's own pin
    wins over `known_outputs`, and a control step (a branch, a loop) always runs,
    since what it decides is the route rather than data to hand on.

    Raises:
        StepNotTestableError: `graph` has no step `node_id`, or the step sits
            inside a loop's body.
    """
    if node_id not in graph.node_by_id:
        raise StepNotTestableError(
            node_id=node_id, reason="unknown_step", message="This workflow has no such step"
        )
    if node_id in node_scope_map(graph):
        raise StepNotTestableError(
            node_id=node_id,
            reason="inside_a_loop",
            message="A step inside a loop runs once per item; test the loop instead",
        )

    kept = _with_ancestors(graph, {node_id})
    nodes = []
    for node in graph.nodes:
        if node.id not in kept:
            continue
        if node.id == node_id:
            nodes.append(node.model_copy(update={"pinned_output": None}))
            continue
        known = known_outputs.get(node.id)
        is_control = _registry.get(node.definition_id, node.definition_version).kind == "control"
        if node.pinned_output is None and known is not None and not is_control:
            node = node.model_copy(update={"pinned_output": known})
        nodes.append(node)
    return graph.model_copy(
        update={
            "nodes": tuple(nodes),
            "edges": tuple(
                edge
                for edge in graph.edges
                if edge.source_node_id in kept and edge.target_node_id in kept
            ),
            "bindings": tuple(
                binding for binding in graph.bindings if binding.target_node_id in kept
            ),
            "scopes": tuple(scope for scope in graph.scopes if scope.scope_node_id in kept),
            "notes": (),
        }
    )


def _with_ancestors(graph: WorkflowGraph, start: set[UUID]) -> set[UUID]:
    """`start`, everything with an edge path into it, and every kept loop's whole body."""
    predecessors: dict[UUID, set[UUID]] = {}
    for edge in graph.edges:
        predecessors.setdefault(edge.target_node_id, set()).add(edge.source_node_id)
    bodies = {scope.scope_node_id: scope.body_node_ids for scope in graph.scopes}
    kept: set[UUID] = set()
    pending = list(start)
    while pending:
        current = pending.pop()
        if current in kept:
            continue
        kept.add(current)
        pending.extend(predecessors.get(current, ()))
        pending.extend(bodies.get(current, ()))
    return kept

"""Reading a graph written before steps named their loop (#2770).

Until #2770 a `control.foreach` body was whatever its `body` port's wires
reached, and `ScopeBoundary` carried that port as `entry_port`. A graph in
that shape still arrives - an exported `.workflow.json`, a client or an
assistant that learned the old wiring - so it is read as the same loop in the
new shape rather than refused:

- every step the old walk put in a body names its innermost loop in `scope_id`;
- the wire from the loop's `body` to its `loop.item` goes, since a body starts
  at its item by definition;
- any other wire from `body` leaves from that `loop.item` instead, which is
  where it started each iteration anyway - or goes too when the body has no
  item to start from, leaving the step in the body for validation to report;
- `entry_port` is dropped from the stored scopes, which are re-derived anyway.

A graph past the node or edge ceiling keeps its wires: the conversion would remove
the very edges `graph_size_problems` counts, and costs work per edge, so an
oversized import is left for that check to refuse. Only `entry_port` is dropped,
so the refusal is the size check's rather than a schema error.

Only raw JSON is read here: a graph already built from model instances is in
the new shape by construction. That JSON is not validated yet, so a node or an
edge whose ids or ports could not key a lookup is left as it was, for field
validation to refuse rather than to fail on here.
`alembic/versions/0301_workflow_loop_scope.py` holds a frozen copy of this
conversion for the rows stored before it.
"""

from collections import deque
from collections.abc import Hashable
from typing import Any, TypeGuard
from uuid import UUID

from app.core.config import settings

FOREACH = "control.foreach"
LOOP_ITEM = "loop.item"
LEGACY_BODY_PORT = "body"
LOOP_ITEM_PORT = "out"


def adopt_named_loop_bodies(graph: dict[str, Any]) -> dict[str, Any]:
    """`graph` in the named-body shape; returned as it is when nothing is legacy."""
    nodes, edges, scopes = graph.get("nodes"), graph.get("edges"), graph.get("scopes")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return graph
    if (
        len(nodes) > settings.WORKFLOW_GRAPH_MAX_NODES
        or len(edges) > settings.WORKFLOW_GRAPH_MAX_EDGES
    ):
        return _without_entry_ports(graph)
    raw_nodes = [node for node in nodes if _keyed_node(node)]
    raw_edges = [edge for edge in edges if _keyed_edge(edge)]
    loops = {node.get("id") for node in raw_nodes if node.get("definition_id") == FOREACH}
    body_wires = [
        edge
        for edge in raw_edges
        if edge.get("source_node_id") in loops and edge.get("source_port") == LEGACY_BODY_PORT
    ]
    legacy_scopes = isinstance(scopes, list) and any(
        isinstance(scope, dict) and "entry_port" in scope for scope in scopes
    )
    if not body_wires and not legacy_scopes:
        return graph

    owner = _innermost_owners(raw_edges, body_wires)
    definition = {node.get("id"): node.get("definition_id") for node in raw_nodes}
    items: dict[Hashable, Hashable] = {}
    for wire in body_wires:
        loop, target = wire["source_node_id"], wire.get("target_node_id")
        if loop not in items and definition.get(target) == LOOP_ITEM and owner.get(target) == loop:
            items[loop] = target

    moving = {id(wire) for wire in body_wires}
    kept: list[Any] = [edge for edge in edges if id(edge) not in moving]
    wired = {_signature(edge) for edge in raw_edges if id(edge) not in moving}
    for wire in body_wires:
        item = items.get(wire["source_node_id"])
        if item is None or wire.get("target_node_id") == item:
            continue
        moved = {**wire, "source_node_id": item, "source_port": LOOP_ITEM_PORT}
        if _signature(moved) in wired:
            continue
        wired.add(_signature(moved))
        kept.append(moved)

    return _without_entry_ports(
        {
            **graph,
            "nodes": [
                {**node, "scope_id": owner[node["id"]]}
                if _keyed_node(node) and node["id"] in owner
                else node
                for node in nodes
            ],
            "edges": kept,
        }
    )


def _keyed_node(node: object) -> TypeGuard[dict[str, Any]]:
    """Whether `node` is an object whose id can key a lookup."""
    return isinstance(node, dict) and isinstance(node.get("id"), str | UUID)


def _keyed_edge(edge: object) -> TypeGuard[dict[str, Any]]:
    """Whether `edge` is an object whose ends and ports can key a lookup."""
    return (
        isinstance(edge, dict)
        and isinstance(edge.get("source_node_id"), str | UUID)
        and isinstance(edge.get("target_node_id"), str | UUID)
        and isinstance(edge.get("source_port"), str)
        and isinstance(edge.get("target_port"), str)
    )


def _without_entry_ports(graph: dict[str, Any]) -> dict[str, Any]:
    """`graph` with `entry_port` dropped from each stored scope."""
    scopes = graph.get("scopes")
    if not isinstance(scopes, list):
        return graph
    return {
        **graph,
        "scopes": [
            {key: value for key, value in scope.items() if key != "entry_port"}
            if isinstance(scope, dict)
            else scope
            for scope in scopes
        ],
    }


def _innermost_owners(
    edges: list[dict[str, Any]], body_wires: list[dict[str, Any]]
) -> dict[Hashable, Hashable]:
    """Each step's innermost loop, by the old walk: what `body` reaches, not re-entering the loop.

    A nested body is a subset of its outer one, so the smallest body holding a
    step is the loop it sits directly in.
    """
    forward: dict[Hashable, list[Hashable]] = {}
    for edge in edges:
        forward.setdefault(edge.get("source_node_id"), []).append(edge.get("target_node_id"))
    starts: dict[Hashable, list[Hashable]] = {}
    for wire in body_wires:
        starts.setdefault(wire["source_node_id"], []).append(wire.get("target_node_id"))
    bodies: dict[Hashable, set[Hashable]] = {}
    for loop, targets in starts.items():
        seen: set[Hashable] = set()
        queue = deque(targets)
        while queue:
            current = queue.popleft()
            if current in seen or current == loop:
                continue
            seen.add(current)
            queue.extend(forward.get(current, ()))
        bodies[loop] = seen
    owner: dict[Hashable, Hashable] = {}
    for loop, body in sorted(bodies.items(), key=lambda entry: -len(entry[1])):
        for step in body:
            owner[step] = loop
    return owner


def _signature(edge: dict[str, Any]) -> tuple[Any, ...]:
    return (
        edge.get("source_node_id"),
        edge.get("source_port"),
        edge.get("target_node_id"),
        edge.get("target_port"),
    )

"""A loop's steps name their loop instead of hanging off its `body` port (#2770).

Until now a `control.foreach` body was derived on every read: whatever its `body`
port's wires reached. That made membership a side effect of wiring. Deleting a
wire inside a body moved everything after it out of the loop; a second wire from
`body` - which the editor drew in no view, since it crosses scopes - made a step
reachable from the start of every iteration, and publishing refused the graph
with "A loop's body must start at exactly one loop item step" while the builder
could see nothing wrong. Each step now stores its loop in `scope_id`, the loop
has no `body` port, and a body starts at its `loop.item` by definition.

Every stored graph is rewritten - drafts, published versions (runs execute them)
and the draft snapshots test runs keep - the same way
`app.workflows.graph.legacy` reads one that arrives in the old shape:

* each step the old walk put in a body names its innermost loop;
* the wire from `body` to the body's `loop.item` goes;
* any other wire from `body` leaves from that `loop.item` instead. This is the
  repair for the graphs the bug broke: the step ran at the start of every
  iteration through that wire, and `loop.item` is exactly where an iteration
  starts, so it keeps its place and the graph publishes again. A body with no
  `loop.item` loses the wire and keeps the step, which publishing then reports;
* `entry_port` is dropped from the stored scopes, which are re-derived anyway.

The conversion is a frozen copy rather than an import: the application's module
may change after this revision, and this one must keep converting the same way.

**Downgrade** wires each body from its loop to its `loop.item` again, puts
`entry_port` back on the scopes and drops `scope_id`. A wire moved onto
`loop.item` stays there: the old walk reaches that step the same way. A body step
nothing reaches from `loop.item` - possible only after the upgrade - is outside
the body again under the old reading, as it was before this revision.

Revision ID: 0301_workflow_loop_scope
Revises: 0300_unfiled_writer_provenance
"""

import json
import uuid
from collections import deque
from collections.abc import Callable, Hashable, Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "0301_workflow_loop_scope"
down_revision: str | Sequence[str] | None = "0300_unfiled_writer_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FOREACH = "control.foreach"
LOOP_ITEM = "loop.item"
BODY_PORT = "body"
LOOP_ITEM_PORT = "out"

# Every JSONB column holding a whole workflow graph: table, key column, graph column.
_GRAPH_COLUMNS = (
    ("workflows", "id", "draft_graph"),
    ("workflow_versions", "id", "graph"),
    ("workflow_runs", "id", "draft_graph_snapshot"),
)


def upgrade_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """`graph` with each loop's steps naming it; returned as it is when nothing is legacy."""
    nodes, edges, scopes = graph.get("nodes"), graph.get("edges"), graph.get("scopes")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return graph
    loops = {node.get("id") for node in nodes if node.get("definition_id") == FOREACH}
    body_wires = [
        edge
        for edge in edges
        if edge.get("source_node_id") in loops and edge.get("source_port") == BODY_PORT
    ]
    legacy_scopes = isinstance(scopes, list) and any("entry_port" in scope for scope in scopes)
    if not body_wires and not legacy_scopes:
        return graph

    owner = _innermost_owners(edges, body_wires)
    definition = {node.get("id"): node.get("definition_id") for node in nodes}
    items: dict[Hashable, Hashable] = {}
    for wire in body_wires:
        loop, target = wire["source_node_id"], wire.get("target_node_id")
        if loop not in items and definition.get(target) == LOOP_ITEM and owner.get(target) == loop:
            items[loop] = target

    moving = {id(wire) for wire in body_wires}
    kept = [edge for edge in edges if id(edge) not in moving]
    wired = {_signature(edge) for edge in kept}
    for wire in body_wires:
        item = items.get(wire["source_node_id"])
        if item is None or wire.get("target_node_id") == item:
            continue
        moved = {**wire, "source_node_id": item, "source_port": LOOP_ITEM_PORT}
        if _signature(moved) in wired:
            continue
        wired.add(_signature(moved))
        kept.append(moved)

    upgraded = {
        **graph,
        "nodes": [
            {**node, "scope_id": owner[node["id"]]} if node.get("id") in owner else node
            for node in nodes
        ],
        "edges": kept,
    }
    if isinstance(scopes, list):
        upgraded["scopes"] = [
            {key: value for key, value in scope.items() if key != "entry_port"} for scope in scopes
        ]
    return upgraded


def downgrade_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """`graph` with each body wired from its loop's `body` port again."""
    nodes, edges, scopes = graph.get("nodes"), graph.get("edges"), graph.get("scopes")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return graph
    named = any("scope_id" in node for node in nodes)
    unported = isinstance(scopes, list) and any("entry_port" not in scope for scope in scopes)
    if not named and not unported:
        return graph
    restored_edges = list(edges)
    started: set[Any] = set()
    for node in nodes:
        loop = node.get("scope_id")
        if loop is None or loop in started or node.get("definition_id") != LOOP_ITEM:
            continue
        started.add(loop)
        restored_edges.append(
            {
                "id": str(uuid.uuid4()),
                "source_node_id": loop,
                "source_port": BODY_PORT,
                "target_node_id": node["id"],
                "target_port": "in",
            }
        )
    restored = {
        **graph,
        "nodes": [
            {key: value for key, value in node.items() if key != "scope_id"} for node in nodes
        ],
        "edges": restored_edges,
    }
    if isinstance(scopes, list):
        restored["scopes"] = [{**scope, "entry_port": BODY_PORT} for scope in scopes]
    return restored


def _innermost_owners(
    edges: list[dict[str, Any]], body_wires: list[dict[str, Any]]
) -> dict[Hashable, Hashable]:
    """Each step's innermost loop, by the old walk: what `body` reaches, not re-entering the loop."""
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
    # Smallest last: a nested body is a subset of its outer one, so the innermost wins.
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


def _rewrite(convert: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    # The identifiers are the fixed ones above; only values are bound.
    connection = op.get_bind()
    for table, key, column in _GRAPH_COLUMNS:
        rows = connection.execute(
            sa.text(f"SELECT {key}, {column} FROM {table} WHERE {column}::text LIKE '%{FOREACH}%'")
        ).all()
        for row_id, graph in rows:
            if not isinstance(graph, dict):
                continue
            converted = convert(graph)
            if converted is graph:
                continue
            connection.execute(
                sa.text(f"UPDATE {table} SET {column} = CAST(:graph AS jsonb) WHERE {key} = :id"),
                {"graph": json.dumps(converted), "id": row_id},
            )


def upgrade() -> None:
    _rewrite(upgrade_graph)


def downgrade() -> None:
    _rewrite(downgrade_graph)

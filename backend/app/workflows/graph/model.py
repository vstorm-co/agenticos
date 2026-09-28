"""The graph shape: nodes, edges, bindings and scope boundaries.

Five frozen, `extra="forbid"` models. `layout` carries only `NodePosition` -
nothing execution-relevant reads it, which is what makes "layout moves do not
alter execution semantics" (AC3) testable rather than merely asserted:
`validate_graph` and every future consumer never dereference `.layout`.

`scopes` is **not client-authored**. The editor sends nodes, edges and
bindings; `app.workflows.graph.validate.derive_scopes` computes
`body_node_ids` from the graph's own topology and the server persists that
computed set, overwriting whatever a client claimed. See its docstring for
why a plain forward walk is not enough.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.workflows.contracts.io import Binding


class NodePosition(BaseModel):
    """Where the editor draws a node. Never read by validation or execution.

    `allow_inf_nan=False` on both fields: an unconstrained `float` accepts
    a JSON coordinate like `1e400` (parsed as infinity) or a literal
    `Infinity`/`NaN` token, which `model_dump(mode="json")` still carries as
    a Python `float`. PostgreSQL's `jsonb` follows the JSON RFC and has no
    such tokens, so that value reaching the `draft_graph` column turns an
    otherwise valid draft write into a database error instead of a 422.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class NodeInstance(BaseModel):
    """One node in the graph: which definition, pinned to which version, configured how."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    definition_id: str
    definition_version: int
    config: dict[str, Any] = Field(default_factory=dict)
    layout: NodePosition


class Edge(BaseModel):
    """One control-flow or data-flow connection between two node ports."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    source_node_id: UUID
    source_port: str
    target_node_id: UUID
    target_port: str


class ScopeBoundary(BaseModel):
    """A control node and the body it owns, as the server has computed it.

    `entry_port` is always a port of `scope_node_id` itself: the control node
    is the single node a client wires into and out of in the editor, and the
    body's own reachability walk starts from `scope_node_id`'s outgoing
    `entry_port` edges - never ambiguous, never delegated.

    `exit_port` belongs to `exit_node_id`, which is **not** always
    `scope_node_id`. For the simplest scope owners the two coincide - every
    scope `app.workflows.graph.validate.derive_scopes` computes today sets
    `exit_node_id = scope_node_id`, since #1786 ships no control node whose
    body needs a distinct exit point. But the shape exists for a node whose
    body ends at an explicit, referenceable point rather than at the control
    node's own second port: `#1790`'s `control.foreach` is the concrete case
    - its body's last node, `loop.yield`, owns the scope's real exit, and
    `loop.yield`'s own outgoing edge (not `control.foreach`'s) is what
    continues the outer graph. See `1786-node-contracts.md`'s "ScopeBoundary:
    the settled shape" section for the two contradictory readings this
    resolves.

    `exit_node_id` is either `scope_node_id` itself, or a member of
    `body_node_ids` - never a node outside the scope, and never a *different*
    scope's node. Whichever it is, it is itself still a body member when it
    is not the control node (it is typically the body's last node), but
    nothing reachable only by crossing *out of* `exit_port`'s own outgoing
    edges is.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope_node_id: UUID
    body_node_ids: frozenset[UUID]
    entry_port: str
    exit_node_id: UUID
    exit_port: str

    @model_validator(mode="after")
    def _exit_node_is_the_control_node_or_a_body_member(self) -> "ScopeBoundary":
        if self.exit_node_id != self.scope_node_id and self.exit_node_id not in self.body_node_ids:
            raise ValueError("exit_node_id must be scope_node_id or a member of body_node_ids")
        return self


class WorkflowGraph(BaseModel):
    """One workflow graph: what a draft holds and what a published version freezes.

    `scopes` defaults to empty and is always replaced by
    `app.workflows.graph.validate.derive_scopes` before a graph is persisted -
    see that function and the `ScopeBoundary` docstring above.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_node_id: UUID
    nodes: tuple[NodeInstance, ...]
    edges: tuple[Edge, ...] = ()
    bindings: tuple[Binding, ...] = ()
    scopes: tuple[ScopeBoundary, ...] = ()

    @model_validator(mode="after")
    def _no_duplicate_node_ids(self) -> "WorkflowGraph":
        seen: set[UUID] = set()
        for node in self.nodes:
            if node.id in seen:
                raise ValueError(f"Duplicate node id: {node.id}")
            seen.add(node.id)
        return self

    @property
    def node_by_id(self) -> dict[UUID, NodeInstance]:
        return {node.id: node for node in self.nodes}

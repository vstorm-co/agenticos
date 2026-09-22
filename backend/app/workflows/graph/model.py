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

from pydantic import BaseModel, ConfigDict, Field

from app.workflows.contracts.io import Binding


class NodePosition(BaseModel):
    """Where the editor draws a node. Never read by validation or execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    x: float
    y: float


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

    `entry_port` is the port of `scope_node_id` whose outgoing edges start the
    body. `exit_port` is the port - on whichever node the walk reaches it -
    whose outgoing edges leave the body and are not themselves part of it;
    the node that owns `exit_port` is itself still a body member (it is
    typically the body's last node), but nothing reachable only by crossing
    *out of* `exit_port` is.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope_node_id: UUID
    body_node_ids: frozenset[UUID]
    entry_port: str
    exit_port: str


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

    @property
    def node_by_id(self) -> dict[UUID, NodeInstance]:
        return {node.id: node for node in self.nodes}

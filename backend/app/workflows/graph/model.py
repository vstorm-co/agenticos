"""The graph shape: nodes, edges, bindings and scope boundaries.

Five frozen, `extra="forbid"` models. `layout` carries only `NodePosition` -
nothing execution-relevant reads it, which is what makes "layout moves do not
alter execution semantics" (AC3) testable rather than merely asserted:
`validate_graph` and every future consumer never dereference `.layout`.

A step inside a loop names that loop in `NodeInstance.scope_id`; that is the
one statement of which body a step belongs to, and wires never change it.
`scopes` is **not client-authored**: `app.workflows.graph.validate.derive_scopes`
computes each body from those names and the server persists that, overwriting
whatever a client claimed. A graph in the pre-#2770 shape, whose bodies hung
off the loop's `body` port, is read through `app.workflows.graph.legacy`.
"""

import json
import math
import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.workflows.contracts.io import Binding
from app.workflows.contracts.policy import NodePolicy
from app.workflows.graph.legacy import adopt_named_loop_bodies


class NodePosition(BaseModel):
    """Where the editor draws a node. Never read by validation or execution.

    `allow_inf_nan=False` on both fields: an unconstrained `float` accepts
    a JSON coordinate like `1e400` (parsed as infinity) or a literal
    `Infinity`/`NaN` token, which `model_dump(mode="json")` still carries as
    a Python `float`. PostgreSQL's `jsonb` follows the JSON RFC and has no
    such tokens, so that value reaching the `draft_graph` column turns an
    otherwise valid draft write into a database error instead of a 422.

    `width` and `height` are the size a person dragged the step to; absent
    means the editor's default and is left out of a dump, so a client never
    receives a `null` size. The bounds are loose guards, the editor
    enforces the real limits.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)
    width: float | None = Field(
        default=None, ge=120, le=1200, allow_inf_nan=False, exclude_if=lambda size: size is None
    )
    height: float | None = Field(
        default=None, ge=40, le=1200, allow_inf_nan=False, exclude_if=lambda size: size is None
    )


MAX_PINNED_BYTES = 64_000
"""How much data one step may have pinned: enough to stand in for a real output."""


_JSONB_FORBIDDEN_TEXT = re.compile(r"[\x00\ud800-\udfff]")


def jsonb_value_fits(value: object) -> None:
    """Refuse workflow text and numeric values PostgreSQL JSONB cannot represent."""
    if isinstance(value, str):
        if _JSONB_FORBIDDEN_TEXT.search(value) is not None:
            raise ValueError("Input strings must be representable in PostgreSQL JSONB")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Workflow numbers must be finite")
    elif isinstance(value, BaseModel):
        jsonb_value_fits(value.model_dump(mode="json"))
    elif isinstance(value, dict):
        for key, item in value.items():
            jsonb_value_fits(key)
            jsonb_value_fits(item)
    elif isinstance(value, list | tuple):
        for item in value:
            jsonb_value_fits(item)


def pinned_output_fits(value: dict[str, Any]) -> dict[str, Any]:
    """`value`, when it is small enough to stand in for a step's output.

    Raises:
        ValueError: It is over `MAX_PINNED_BYTES` as compact UTF-8 JSON - the
            measure the editor checks before it saves one.
    """
    if (
        len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())
        > MAX_PINNED_BYTES
    ):
        raise ValueError(f"Pinned data may take at most {MAX_PINNED_BYTES} bytes")
    return value


DEFAULT_QUICK_LOG_MESSAGE = "{{step}} → {{outcome}}"
MAX_QUICK_LOG_MESSAGE = 500


class QuickLog(BaseModel):
    """A step's Quick Log: after each run of the step, one line in the workflow's log.

    Not a node and not a step of the run: the line is written in the transaction that
    settles the step, never changes how the run goes, and costs nothing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(
        default=DEFAULT_QUICK_LOG_MESSAGE,
        min_length=1,
        max_length=MAX_QUICK_LOG_MESSAGE,
        description="The line written, a template. `{{step}}` is the step's name and "
        "`{{outcome}}` the port it left by, or `error`; `{{field}}` and `{{a.b}}` read "
        "the step's own output; `{{error.code}}` and `{{error.message}}` read the error "
        "of a failed step (`error.details` is never available). A reference that has "
        "no value on this run renders empty and never fails the run",
    )
    outputs: tuple[str, ...] | None = Field(
        default=None,
        description="The output ports that log, `error` among them when the step routes "
        "its errors. Unset: every outcome of the step logs",
    )

    @field_validator("message")
    @classmethod
    def _message_fits(cls, value: str) -> str:
        jsonb_value_fits(value)
        return value


class NodeInstance(BaseModel):
    """One node in the graph: which definition, pinned to which version, configured how."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    definition_id: str
    definition_version: int
    config: dict[str, Any] = Field(default_factory=dict)
    policy: NodePolicy | None = None
    layout: NodePosition
    label: str | None = Field(
        default=None,
        max_length=64,
        description="What the builder calls this step, unique in the graph; the step's "
        "name from the catalog when unset",
    )
    notes: str | None = Field(
        default=None, max_length=2000, description="A note on the step, shown on the canvas"
    )
    scope_id: UUID | None = Field(
        default=None,
        description="The loop this step sits directly inside, or null at the top level. "
        "Which body a step belongs to; its wires never change it",
    )
    disabled: bool = Field(
        default=False,
        description="Switched off: the step is skipped when the run reaches it and "
        "passes on to the next, without doing anything",
    )
    pinned_output: dict[str, Any] | None = Field(
        default=None,
        description="Data a test run hands on as this step's output instead of running "
        "it. A published version never carries it, so a real run always runs the step",
    )

    quick_log: QuickLog | None = Field(
        default=None,
        description="Writes a line to the workflow's log after each run of this step",
    )

    @field_validator("pinned_output")
    @classmethod
    def _pinned_output_fits(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return value if value is None else pinned_output_fits(value)

    @property
    def routes_errors(self) -> bool:
        """Whether a failure leaves this node by its `error` port rather than failing the run."""
        return self.policy is not None and self.policy.on_error == "route"


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

    `body_node_ids` is every step whose chain of `scope_id`s leads to
    `scope_node_id` - transitive, so a nested loop's body is in its outer
    loop's too. No wire enters a body: it starts at its `loop.item`.

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
    exit_node_id: UUID
    exit_port: str

    @model_validator(mode="after")
    def _exit_node_is_the_control_node_or_a_body_member(self) -> ScopeBoundary:
        if self.exit_node_id != self.scope_node_id and self.exit_node_id not in self.body_node_ids:
            raise ValueError("exit_node_id must be scope_node_id or a member of body_node_ids")
        return self


MAX_CANVAS_NOTES = 50

NoteColor = Literal["default", "yellow", "green", "blue", "purple", "red"]
"""A note's tint, from a small palette so a workflow's notes can be told apart by
kind - a warning in red, a to-do in yellow - and the console draws each one."""


class CanvasNote(BaseModel):
    """A note on the canvas, beside the steps: text, where it sits and how big it is.

    Not a step - nothing runs it, nothing validates it, and a run never reads it -
    but kept in the graph, so versions, restores and copies keep it with the steps
    it explains.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    text: str = Field(default="", max_length=4000, description="Markdown")
    layout: NodePosition
    width: float = Field(default=240, ge=120, le=1200)
    height: float = Field(default=140, ge=60, le=1200)
    color: NoteColor = "default"


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
    notes: tuple[CanvasNote, ...] = Field(default=(), max_length=MAX_CANVAS_NOTES)

    @model_validator(mode="before")
    @classmethod
    def _named_loop_bodies(cls, data: Any) -> Any:
        return adopt_named_loop_bodies(data) if isinstance(data, dict) else data

    @model_validator(mode="after")
    def _no_duplicate_node_ids(self) -> WorkflowGraph:
        seen: set[UUID] = set()
        for node in self.nodes:
            if node.id in seen:
                raise ValueError(f"Duplicate node id: {node.id}")
            seen.add(node.id)
        return self

    @property
    def node_by_id(self) -> dict[UUID, NodeInstance]:
        return {node.id: node for node in self.nodes}


def loop_item_of(graph: WorkflowGraph, loop_id: UUID) -> UUID | None:
    """The `loop.item` step a loop's body starts at, or None when the body has none.

    Found by membership, not by a wire: each iteration starts there because it is
    the body's item step (#2770). A body with two is refused at publish.
    """
    return next(
        (
            node.id
            for node in graph.nodes
            if node.scope_id == loop_id and node.definition_id == "loop.item"
        ),
        None,
    )

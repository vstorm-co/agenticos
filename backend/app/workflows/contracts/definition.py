"""`NodeDefinition`: what a node declares about itself when it registers.

Mirrors `app.agents.capabilities._registry.CapabilityDef` deliberately - a
`dataclass` rather than a Pydantic model, because nothing here is deserialized
off the wire; it is written once in code and looked up by id and version.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from app.workflows.contracts.results import NodeResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.permissions import AuthContext


@dataclass(frozen=True)
class Port:
    """One connection point on a node, as the editor draws it.

    `kind` is not inferable from `id` alone - `#1793` caught a graph reading
    direction off naming convention, which broke the first control node whose
    ports were not called `in`/`out`.
    """

    id: str
    label: str
    kind: Literal["input", "output"]
    schema: type[BaseModel] | None = None
    """`None` for a control port that carries no payload - a plain trigger edge."""


NodeHandler = Callable[[BaseModel | None, BaseModel | None], Awaitable[NodeResult]]

TRIGGER_CATEGORY = "triggers"
"""The category of the nodes a workflow starts from - one per workflow, and its entry."""
"""What a node actually does: `(config, input) -> NodeResult`.

Both arguments are already validated against `config_schema`/`input_schema`
before a handler ever sees them - the same division of labor as a capability
builder receiving an already-validated config. `None` until an execution issue
(`#1788`) supplies a caller; a `NodeDefinition` with no handler is still a
complete catalog entry, since the catalog only describes shape.
"""


RetryGuarantee = Literal["none", "idempotent", "at_least_once"]


RouteSelector = Callable[[dict[str, Any] | None], frozenset[str]]
"""Which output ports a completed node leaves by, read off its stored output.

`None` on a definition means every output port - an action node's one `out`.
A branching node answers with the port its output chose: `logic.if` the
`true` or `false` it evaluated. The dispatcher follows only edges leaving a
chosen port and skips whatever becomes unreachable, so the choice has to be
recoverable from the stored result alone - a node settled before a restart is
advanced from its row, not from a handler call still in memory.
"""


ResourceCheck = Callable[
    ["AsyncSession", "AuthContext", BaseModel], Awaitable[list[tuple[str, str]]]
]
"""What a validated config names, checked against the person validating the graph.

A node whose config pins a resource - a collection, an agent version, a vault
secret, a member to notify - declares one of these so `validate_graph` refuses a
graph whose author could not reach what it names, before a run ever tries. Each
problem is `(field path within the config, message)`. It is not the only check:
a handler re-checks the run's own principal when it runs, since access can be
revoked between publishing a graph and running it.
"""


@dataclass(frozen=True)
class NodeDefinition:
    """A node type, as `_registry.get()` returns it and the catalog serializes it.

    `id` is permanent, like a capability id: it is what a graph stores and
    what a client's exported workflow names. `version` is bumped on a
    breaking config/IO change; a graph pins `(id, version)`, so an old
    published graph may still reference a version this deployment has since
    superseded - `_registry.REGISTRY` keeps every version it has ever seen,
    never only the latest.
    """

    id: str
    version: int
    name: str
    category: str
    description: str
    kind: Literal["action", "control", "waiting"]
    config_schema: type[BaseModel] | None
    input_schema: type[BaseModel] | None
    output_schema: type[BaseModel] | None
    ports: tuple[Port, ...]
    effect_kind: Literal["pure", "read", "write"]
    retry_guarantee: RetryGuarantee
    scopes: frozenset[str] = frozenset()
    handler: NodeHandler | None = None
    routes: RouteSelector | None = None
    resource_check: ResourceCheck | None = None
    retry_guarantee_for: Callable[[BaseModel | None], RetryGuarantee] | None = None
    """The guarantee one configured call gives, when it is not the kind's own.

    `retry_guarantee` above is the conservative default for the kind;
    `http.request` is `at_least_once` as a kind, but a `GET` - or a write sent
    with an idempotency header the far side honours - is `idempotent`. Called
    with the resolved config when an attempt is created, before the handler."""
    ports_for: Callable[[BaseModel | None], tuple[Port, ...]] | None = None
    """This instance's ports, when its config declares some of them.

    `error.handle`'s branches are the author's, one output port each, so they
    cannot live in `ports`, which is fixed per kind. Called with the validated
    config (`None` if it does not validate); `ports` is what the catalog shows."""
    loop_body_only: bool = False
    """Whether the node exists only inside a `control.foreach` body - `loop.item`
    and `loop.yield`, which mean nothing outside an iteration."""

"""`NodeDefinition`: what a node declares about itself when it registers.

Mirrors `app.agents.capabilities._registry.CapabilityDef` deliberately - a
`dataclass` rather than a Pydantic model, because nothing here is deserialized
off the wire; it is written once in code and looked up by id and version.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.workflows.contracts.results import NodeResult


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
"""What a node actually does: `(config, input) -> NodeResult`.

Both arguments are already validated against `config_schema`/`input_schema`
before a handler ever sees them - the same division of labor as a capability
builder receiving an already-validated config. `None` until an execution issue
(`#1788`) supplies a caller; a `NodeDefinition` with no handler is still a
complete catalog entry, since the catalog only describes shape.
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
    retry_guarantee: Literal["none", "idempotent", "at_least_once"]
    scopes: frozenset[str] = frozenset()
    handler: NodeHandler | None = None

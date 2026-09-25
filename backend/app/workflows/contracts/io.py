"""What a node's input may be bound to: a literal, another node's output, a file
or a table.

Four `kind`-discriminated variants make up `BindingSource`. `FileRef` and
`TableIORef` are resolved against real resources - the storage backing behind a
`FileRef` is #1791's; the table it names is `app.db.models.virtual_table`'s -
while `NodeOutputRef` and `LiteralValue` resolve entirely within the graph
itself. `Binding` is what a `NodeInstance.config` field actually points at; see
`app.workflows.graph.model` for how it is validated against the graph's shape.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FileRef(BaseModel):
    """A reference to an uploaded file: an opaque id, a declared type and size.

    Thin and unopinionated by design (56-shared-contracts.md, decision 1): no
    storage backing lives here. `#1791` adds real validation against
    authorized storage without changing this shape, only what enforces it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["file"] = "file"
    file_id: UUID
    content_type: str = Field(max_length=255)
    byte_size: int = Field(ge=0)


class TableIORef(BaseModel):
    """A reference into one virtual table, optionally narrowed to some columns.

    `column_ids=None` means "all live columns". `schema_version` is the
    version this binding was checked against at bind time - not necessarily
    the table's current one, which is what lets `validate_graph`'s resource
    pass detect a table whose schema moved since the binding was made.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["table"] = "table"
    table_id: UUID
    column_ids: tuple[UUID, ...] | None = None
    schema_version: int = Field(ge=1)


class NodeOutputRef(BaseModel):
    """A reference to another node's output port, or a field within it.

    `field_path=()` means "the whole port value". A non-empty path walks the
    source port's `output_schema.model_fields` - `("text",)` off an
    `AgentRunOutput` for its `text: str` field - so a node whose output is a
    structured model can still feed a single scalar field to a target that
    only accepts one. `app.workflows.graph.validate` resolves the *path's*
    terminal type for rule 3 (type compatibility), not the port's.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["node_output"] = "node_output"
    node_id: UUID
    port: str
    field_path: tuple[str, ...] = ()


class LiteralValue(BaseModel):
    """A constant value, typed by whatever field it is bound to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["literal"] = "literal"
    value: Any


BindingSource = Annotated[
    FileRef | TableIORef | NodeOutputRef | LiteralValue, Field(discriminator="kind")
]
"""What a target field's binding resolves to."""


class Binding(BaseModel):
    """One field of one node instance, bound to a source.

    `target_field` names a field of the target node's `input_schema` (or
    `config_schema`, for a value that is configuration rather than runtime
    input) - `app.workflows.graph.validate` is what confirms the field, the
    node and the source all actually agree.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_node_id: UUID
    target_field: str
    source: BindingSource

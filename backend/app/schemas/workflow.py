"""Schemas for the workflow registry and the node catalog.

Mirrors `app.schemas.agent`: `WorkflowRead`/`WorkflowDetail`/`WorkflowList`
for the resource, `WorkflowDraftUpdate`/`WorkflowPublish` for the two writes,
and `NodeCatalog`/`NodeCatalogEntry` for the editor palette - the same shape
`CapabilityCatalog`/`CapabilityCatalogEntry` give the Builder.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.db.models.resource_grant import Visibility
from app.schemas.base import BaseSchema
from app.workflows.graph.model import WorkflowGraph


class WorkflowRead(BaseSchema):
    """A workflow as the Builder lists it."""

    id: UUID
    slug: str
    name: str
    description: str | None = None
    status: str
    visibility: str
    owner_user_id: UUID | None = None
    current_version_id: UUID | None = None
    draft_revision: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkflowDetail(WorkflowRead):
    """A workflow plus the graph currently being edited.

    `draft_graph` is `None` for a workflow nobody has ever edited: the row's
    `draft_graph` column starts at `{}`, which is not a valid `WorkflowGraph`
    (`entry_node_id` and `nodes` are required) - there is no meaningful empty
    graph to report instead, only the absence of one.
    """

    draft_graph: WorkflowGraph | None


class WorkflowList(BaseSchema):
    items: list[WorkflowRead]
    total: int


class WorkflowCreate(BaseSchema):
    """Create a workflow. The handle is derived from the name, an empty graph to start."""

    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    visibility: Visibility = Field(
        default=Visibility.ORG,
        description=(
            "Who can find this workflow. `org` - the default - is everyone in the "
            "organization; `private` is the owner and whoever they grant it to. A "
            "draft cannot run either way, so this decides who sees it, not what it does."
        ),
    )


class WorkflowDraftUpdate(BaseSchema):
    """Replace the draft graph, gated on the revision the caller last read.

    Mirrors `app.schemas.virtual_table.RecordUpdate`'s `expected_revision`
    field exactly: a stale value raises `RevisionConflictError` (409) before
    the graph itself is even looked at. `graph` is a raw JSON object rather
    than `WorkflowGraph`, the same way `RecordUpdate.values` is a raw dict
    rather than typed record columns - a `WorkflowGraph` field here would
    have FastAPI validate its full nested shape while parsing the request
    body, ahead of authorization, the archived check and the revision
    compare-and-set, turning an authorized, current write's malformed graph
    into a 422 instead of the 403/404/409 that ordering promises for
    everything else. `WorkflowRegistryService.update_draft` parses it, after
    those checks, into `GraphValidationError`'s own field-problem shape.
    """

    graph: dict[str, Any]
    expected_revision: int = Field(ge=0)


class WorkflowPublish(BaseSchema):
    """Publish the current draft, gated on the same revision the draft write is."""

    note: str | None = Field(
        default=None, max_length=500, description="Why this version exists - a commit message"
    )
    expected_revision: int = Field(ge=0)


class WorkflowVersionRead(BaseSchema):
    id: UUID
    version: int
    note: str | None = None
    published_by_user_id: UUID | None = None
    budget_limit: float | None = None
    created_at: datetime | None = None


class WorkflowVersionList(BaseSchema):
    items: list[WorkflowVersionRead]


class NodeCatalogPort(BaseSchema):
    """One port of a catalog entry, as the editor draws a connection point."""

    id: str
    label: str
    kind: Literal["input", "output"]
    schema_: dict[str, Any] | None = Field(
        default=None,
        alias="schema",
        description="JSON Schema for this port's payload; null for a control port with no payload",
    )


class NodeCatalogEntry(BaseSchema):
    """One registered node, as the editor's palette shows it.

    Mirrors `CapabilityCatalogEntry`: the three schemas are served as JSON
    Schema so the editor can build a form from them, and nothing here carries
    a handler - `NodeDefinition.handler` is an in-process callable, not
    something safe or meaningful to serialize onto the wire.
    """

    id: str
    version: int
    name: str
    category: str
    description: str
    kind: Literal["action", "control", "waiting"]
    config_schema: dict[str, Any] | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    ports: list[NodeCatalogPort]
    effect_kind: Literal["pure", "read", "write"]
    retry_guarantee: Literal["none", "idempotent", "at_least_once"]
    scopes: list[str] = Field(default_factory=list)


class NodeCatalog(BaseSchema):
    items: list[NodeCatalogEntry]
    total: int

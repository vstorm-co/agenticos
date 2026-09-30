"""Schemas for the workflow registry and the node catalog.

Mirrors `app.schemas.agent`: `WorkflowRead`/`WorkflowDetail`/`WorkflowList`
for the resource, `WorkflowDraftUpdate`/`WorkflowPublish` for the two writes,
and `NodeCatalog`/`NodeCatalogEntry` for the editor palette - the same shape
`CapabilityCatalog`/`CapabilityCatalogEntry` give the Builder.
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ConfigDict, Field, StringConstraints, field_validator

from app.db.models.resource_grant import Visibility
from app.schemas.base import BaseSchema
from app.schemas.workflow_exposure import WorkflowExposureRead
from app.workflows.graph.model import WorkflowGraph

MAX_RETENTION_DAYS = 3650
MAX_DEFAULT_DEADLINE_SECONDS = 30 * 24 * 3600


class WorkflowSettings(BaseSchema):
    """What a workflow is run with rather than what it does - the workflow's, not a
    version's, so a change applies to every later run and publishing keeps it."""

    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(
        default="UTC",
        max_length=64,
        description="An IANA timezone, such as Europe/Warsaw: the one a schedule's cron "
        "expression is read in",
    )
    default_deadline_seconds: int | None = Field(
        default=None,
        ge=1,
        le=MAX_DEFAULT_DEADLINE_SECONDS,
        description="The deadline a run gets when whatever starts it names none",
    )
    error_workflow_id: UUID | None = Field(
        default=None,
        description="A published workflow that starts from On failure of a workflow, "
        "started once when a run of this one fails",
    )
    run_retention_days: int | None = Field(
        default=None,
        ge=1,
        le=MAX_RETENTION_DAYS,
        description="Remove a run, and the files it stored, this many days after it "
        "ended; kept for good when unset",
    )
    keep_succeeded_runs: bool = Field(
        default=True,
        description="Keep runs that succeeded; when false, they are removed the day "
        "after they end, and only the ones that did not are kept",
    )

    @field_validator("timezone")
    @classmethod
    def _a_timezone_that_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"{value} is not a timezone") from exc
        return value


class StoredWorkflowSettings(WorkflowSettings):
    """The settings as the workflow holds them: with the member an error workflow
    runs as, the one who chose it, set by the service and never by a caller."""

    error_workflow_run_as: UUID | None = None


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
    live_trigger: str | None = Field(
        default=None,
        description="The trigger node the published version starts from - `core.input`, "
        "`trigger.chat`, `trigger.webhook`, `trigger.schedule`, `trigger.table_record` - "
        "or null when it starts from no trigger (by hand) or was never published",
    )
    tags: list[str] = Field(default_factory=list)
    trigger_active: bool | None = Field(
        default=None,
        description="Whether the published version's unattended trigger - a webhook, a "
        "schedule, a new table record - is on. Null when the live version has none: it "
        "starts by hand, from an API call or from chat, or was never published",
    )
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
    settings: StoredWorkflowSettings = Field(default_factory=StoredWorkflowSettings)
    can_edit: bool = Field(
        default=False,
        description="Whether this caller may edit this workflow: role scope or an explicit "
        "grant, resolved server-side, and false once it is archived - so the editor never "
        "mounts controls every write behind them would refuse.",
    )


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


MAX_TAGS = 10

WorkflowTag = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=32),
]


class WorkflowUpdate(BaseSchema):
    """Rename a workflow, describe it or file it under tags. An absent field is kept.

    The handle stays: it is what API callers and exports name the workflow by.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[WorkflowTag] | None = Field(default=None, max_length=MAX_TAGS)


class WorkflowActiveUpdate(BaseSchema):
    model_config = ConfigDict(extra="forbid")

    is_active: bool = Field(description="Switch the live version's trigger on, or pause it")


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


class WorkflowVersionRestore(BaseSchema):
    """Make a published version's graph the draft again, gated like a draft write.

    The published version is never modified and no version is created: the
    draft takes the version's frozen graph and its revision advances, so an
    autosave still holding the old revision answers a conflict instead of
    writing the pre-restore graph back over it.
    """

    expected_revision: int = Field(ge=0)


class WorkflowVersionRead(BaseSchema):
    id: UUID
    version: int
    note: str | None = None
    published_by_user_id: UUID | None = None
    budget_limit: float | None = None
    created_at: datetime | None = None


class WorkflowPublished(WorkflowVersionRead):
    """The publish response: the new version, and the trigger it switched on.

    `exposure` is the webhook or schedule the version now runs from, with the
    webhook's address; `webhook_secret` is that webhook's signing secret,
    returned only by the publish that first switched it on and never again.
    """

    trigger: str | None = None
    exposure: WorkflowExposureRead | None = None
    webhook_secret: str | None = None


class WorkflowVersionDetail(WorkflowVersionRead):
    """One version plus its frozen graph, for viewing a past version read-only.

    The list stays lean - `WorkflowVersionList` never carries a graph, the same
    split `WorkflowList`/`WorkflowDetail` keeps - and the editor fetches this
    detail on demand when a version is opened. Typed rather than raw because a
    stored version graph always parsed at publish; it never round-trips back as
    a draft write.
    """

    graph: WorkflowGraph


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
    loop_body_only: bool = Field(
        default=False, description="Whether the node exists only inside a for-each loop's body"
    )


class NodeCatalog(BaseSchema):
    items: list[NodeCatalogEntry]
    total: int

"""A workflow as a file: what `GET .../export` gives and `POST /workflows/import` takes (#1953)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema
from app.schemas.workflow import MAX_TAGS, WorkflowRead, WorkflowSettings, WorkflowTag

EXPORT_FORMAT = "agenticos.workflow"


class UnresolvedResource(BaseSchema):
    """A pin the file does not carry: the step, the field, and what it chose."""

    node_id: UUID
    step: str = Field(description="The step's name, as the editor shows it")
    field: str
    kind: str = Field(description="What the field picks: agent, table, secret, member, ...")


class WorkflowExport(BaseSchema):
    """One workflow's draft as another deployment can take it.

    It carries no id of this deployment's: every resource a step pinned - an
    agent, a table, a vault secret, a member, a bot, another workflow - is left
    out and listed in `unresolved`, pinned test data is left out, and the
    settings leave out the error workflow. It never holds a secret's value.
    """

    format: Literal["agenticos.workflow"] = EXPORT_FORMAT
    format_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[WorkflowTag] = Field(default_factory=list, max_length=MAX_TAGS)
    settings: WorkflowSettings = Field(default_factory=WorkflowSettings)
    graph: dict[str, Any] | None = Field(
        default=None,
        description="The draft graph, or null for a workflow with no steps. On import it "
        "is parsed, and stripped of any id it names, before it is stored.",
    )
    unresolved: list[UnresolvedResource] = Field(default_factory=list)


class WorkflowImported(BaseSchema):
    """The draft an import made, and every pin its builder has to choose again."""

    workflow: WorkflowRead
    unresolved: list[UnresolvedResource]

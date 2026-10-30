"""Projects: a shared container, standing instructions and the chats held in them."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.db.models.resource_grant import Visibility
from app.schemas.base import BaseSchema
from app.schemas.resource_grant import AudienceChoice

MAX_INSTRUCTIONS = 20_000
"""Instructions reach every run in the project, so they are kept to a page or two."""


class ProjectCreate(AudienceChoice):
    """A new project. Private to its creator unless an audience is named."""

    # Not `team`: no role reaches a project at team scope, so a team project was
    # one only its creator could see, whatever the request said. Narrowed here
    # rather than by a validator, so the API schema lists the two values; the
    # only write the base class makes is `PRIVATE`, which this type admits.
    visibility: Literal[Visibility.PRIVATE, Visibility.ORG] = Field(  # ty: ignore[invalid-mutable-override]
        default=Visibility.PRIVATE,
        description=(
            "`private` - the default - is the creator and whoever they share it with; "
            "`org` is everyone in the organization. Naming `group_ids` or `user_ids` "
            "keeps it private and shares it with them."
        ),
    )
    backend: Literal["auto", "service", "state"] = Field(
        default="auto",
        description="Automatic sandbox selection, a service container, or stored files without a shell",
    )
    sandbox_connection_id: UUID | None = Field(
        default=None, description="The organization's sandbox connection; omitted uses its default"
    )
    name: str = Field(min_length=1, max_length=120, description="What the project is called")
    description: str | None = Field(
        default=None, max_length=500, description="One line on what the project is for"
    )
    instructions: str = Field(
        default="",
        max_length=MAX_INSTRUCTIONS,
        description="Told to every agent that answers in the project, after its own instructions",
    )
    default_agent_id: UUID | None = Field(
        default=None, description="The agent a new chat in the project starts with"
    )


class ProjectUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    instructions: str | None = Field(default=None, max_length=MAX_INSTRUCTIONS)
    default_agent_id: UUID | None = None
    runtime: str | None = Field(
        default=None,
        max_length=64,
        description="Which environment the container runs, from the connection's list",
    )


class ProjectWorkspaceMoveRequest(BaseSchema):
    backend: Literal["service", "state"]
    sandbox_connection_id: UUID | None = None


class ProjectWorkspaceMoveRead(BaseSchema):
    job_id: UUID
    status: Literal["queued", "running", "succeeded", "dead", "cancelled"]
    target_name: str
    copied_files: int = 0
    total_files: int = 0
    copied_bytes: int = 0


class ProjectWorkspaceProgress(BaseSchema):
    copied_files: int = 0
    total_files: int = 0
    copied_bytes: int = 0


class ProjectRead(BaseSchema):
    workspace_move: ProjectWorkspaceMoveRead | None = None
    sandbox_connection_id: UUID | None = None
    sandbox_connection_name: str | None = None
    id: UUID
    name: str
    description: str | None = None
    instructions: str
    default_agent_id: UUID | None = Field(
        default=None,
        description="The agent a new chat starts with - null when the caller may not run it",
    )
    default_agent_name: str | None = Field(
        default=None, description="The default agent's name, when the caller may run it"
    )
    owner_user_id: UUID | None = None
    visibility: str
    backend: str = Field(
        description="`service` - a container with a shell - or `state`, files the platform stores"
    )
    runtime: str | None = None
    chat_count: int = Field(
        default=0, description="How many chats it holds, whoever started them; archived ones aside"
    )
    last_active_at: datetime | None = Field(
        default=None, description="When its latest chat was active, whoever wrote in it"
    )
    shared_groups: list[str] = Field(default_factory=list)
    can_use: bool = Field(default=False, description="Whether the caller may chat and add files")
    can_edit: bool = Field(
        default=False, description="Whether the caller may change, share or delete it"
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectList(BaseSchema):
    items: list[ProjectRead]
    total: int


class ProjectFolderCreate(BaseSchema):
    path: str = Field(min_length=1, max_length=500, description="The folder to create")


class ProjectPathMove(BaseSchema):
    source: str = Field(min_length=1, max_length=500)
    destination: str = Field(min_length=1, max_length=500)


class ProjectFileText(BaseSchema):
    model_config = {"str_strip_whitespace": False}
    content: str
    revision: str


class ProjectFileEdit(BaseSchema):
    # Preserve leading/trailing whitespace: it is the file, not a form label.
    model_config = {"str_strip_whitespace": False}
    content: str = Field(max_length=1_048_576)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")

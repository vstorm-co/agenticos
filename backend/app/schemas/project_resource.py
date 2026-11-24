"""Project membership is distinct from access to the linked resource."""

from uuid import UUID

from pydantic import Field

from app.db.models.project_resource import ProjectResourceKind
from app.schemas.base import BaseSchema


class ProjectResourceRef(BaseSchema):
    kind: ProjectResourceKind
    resource_id: UUID


class ProjectResourceRead(ProjectResourceRef):
    name: str
    description: str | None = None
    is_entrypoint: bool = False


class ProjectResourceList(BaseSchema):
    items: list[ProjectResourceRead]
    total: int


class ProjectResourcesAdd(BaseSchema):
    resources: list[ProjectResourceRef] = Field(min_length=1, max_length=100)


class ProjectEntrypointUpdate(BaseSchema):
    workflow_id: UUID | None

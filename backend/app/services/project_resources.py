"""Group existing resources without changing their permissions, versions or schedules."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.artifact import Artifact
from app.db.models.project_resource import ProjectResourceKind
from app.repositories import project_resource as resource_repo
from app.schemas.project_resource import (
    ProjectResourceList,
    ProjectResourceRead,
    ProjectResourceRef,
)
from app.services.access import (
    AGENT,
    ARTIFACT,
    TABLE,
    WORKFLOW,
    ResourceType,
    accessible_ids,
    resolve_access,
)
from app.services.project import ProjectService

ACCESS: dict[ProjectResourceKind, ResourceType] = {
    ProjectResourceKind.AGENT: AGENT,
    ProjectResourceKind.WORKFLOW: WORKFLOW,
    ProjectResourceKind.APP: ARTIFACT,
    ProjectResourceKind.TABLE: TABLE,
}


class ProjectResourceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.projects = ProjectService(db)

    async def member_ids(
        self, ctx: AuthContext, project_id: UUID, kind: ProjectResourceKind
    ) -> list[UUID]:
        await self.projects.get(ctx, project_id)
        return await resource_repo.member_ids(
            self.db, organization_id=ctx.organization_id, project_id=project_id, kind=kind
        )

    async def list_resources(
        self, ctx: AuthContext, project_id: UUID, *, search: str = ""
    ) -> ProjectResourceList:
        await self.projects.get(ctx, project_id)
        items: list[ProjectResourceRead] = []
        for kind, access in ACCESS.items():
            rows = await resource_repo.list_resources(
                self.db, organization_id=ctx.organization_id, project_id=project_id, kind=kind
            )
            visible = await accessible_ids(
                self.db, ctx, [resource for _, resource in rows], access.view, resource_type=access
            )
            for link, resource in rows:
                if resource.id not in visible:
                    continue
                name = resource.title if isinstance(resource, Artifact) else resource.name
                description = None if isinstance(resource, Artifact) else resource.description
                if (
                    search
                    and search.casefold()
                    not in f"{name} {resource.name} {description or ''}".casefold()
                ):
                    continue
                items.append(
                    ProjectResourceRead(
                        kind=kind,
                        resource_id=resource.id,
                        name=name,
                        description=description,
                        is_entrypoint=link.is_entrypoint,
                    )
                )
        return ProjectResourceList(items=items, total=len(items))

    async def add(
        self, ctx: AuthContext, project_id: UUID, resources: list[ProjectResourceRef]
    ) -> ProjectResourceList:
        await self.projects.get(ctx, project_id, perm=Perm.PROJECTS_EDIT)
        for ref in resources:
            resource = await resource_repo.get_resource(
                self.db,
                kind=ref.kind,
                resource_id=ref.resource_id,
                organization_id=ctx.organization_id,
            )
            access = ACCESS[ref.kind]
            if resource is None or not await resolve_access(
                self.db, ctx, resource, access.view, resource_type=access
            ):
                raise NotFoundError(
                    message="Resource not found", details={"resource_id": ref.resource_id}
                )
        for ref in resources:
            await resource_repo.add(
                self.db, project_id=project_id, kind=ref.kind, resource_id=ref.resource_id
            )
        return await self.list_resources(ctx, project_id)

    async def remove(self, ctx: AuthContext, project_id: UUID, ref: ProjectResourceRef) -> None:
        await self.projects.get(ctx, project_id, perm=Perm.PROJECTS_EDIT)
        await resource_repo.remove(
            self.db, project_id=project_id, kind=ref.kind, resource_id=ref.resource_id
        )

    async def set_entrypoint(
        self, ctx: AuthContext, project_id: UUID, workflow_id: UUID | None
    ) -> ProjectResourceList:
        await self.projects.get(ctx, project_id, perm=Perm.PROJECTS_EDIT)
        if workflow_id is not None:
            visible = await self.list_resources(ctx, project_id)
            if not any(
                item.kind is ProjectResourceKind.WORKFLOW and item.resource_id == workflow_id
                for item in visible.items
            ):
                raise BadRequestError(
                    message="Choose a workflow already linked to this project", details={}
                )
        await resource_repo.set_entrypoint(self.db, project_id=project_id, workflow_id=workflow_id)
        return await self.list_resources(ctx, project_id)

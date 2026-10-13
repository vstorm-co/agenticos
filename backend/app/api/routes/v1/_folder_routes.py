"""The folder endpoints of one resource kind, built once per kind (#2124).

A helper module beside the endpoints rather than an endpoint module, for the
reason `_sharing_routes` is one: the four kinds get the same routes, and the
collection routes' gate is the kind's own permission, so the factory takes it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Auth, DBSession, FolderSvc, require
from app.api.routes.v1._sharing_routes import ResourceLoader
from app.schemas.folder import FileInFolder, FolderCreate, FolderList, FolderRead, FolderUpdate
from app.schemas.resource_grant import AudienceChoice
from app.services.access import FOLDER_TYPES
from app.services.folder import FolderView


def _read(view: FolderView) -> FolderRead:
    folder = view.folder
    return FolderRead(
        id=folder.id,
        kind=folder.kind,
        parent_id=folder.parent_id,
        name=folder.name,
        owner_user_id=folder.owner_user_id,
        visibility=folder.visibility,
        group_ids=view.group_ids,
        user_ids=view.user_ids,
        item_count=view.item_count,
        can_edit=view.can_edit,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


def build_folder_router(*, kind: str, load: ResourceLoader) -> APIRouter:
    """Folders of one kind, and filing one of its resources in one.

    Args:
        kind: The grant key of the resource type the folders hold.
        load: How to fetch one resource of that type inside an organization.
    """
    router = APIRouter()
    types = FOLDER_TYPES[kind]

    @router.get("", response_model=FolderList, dependencies=[Depends(require(types.view))])
    async def list_folders(ctx: Auth, service: FolderSvc) -> Any:
        """Every folder of this kind the caller can see."""
        views = await service.list(ctx, kind=kind)
        return FolderList(items=[_read(view) for view in views], total=len(views))

    @router.post(
        "",
        response_model=FolderRead,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require(types.edit))],
    )
    async def create_folder(data: FolderCreate, ctx: Auth, service: FolderSvc) -> Any:
        """Create a folder - at the top level or inside one, never wider than its parent."""
        folder = await service.create(ctx, kind=kind, data=data)
        return _read(await service.view(ctx, folder))

    @router.patch("/{folder_id}", response_model=FolderRead)
    async def update_folder(
        folder_id: UUID, data: FolderUpdate, ctx: Auth, service: FolderSvc
    ) -> Any:
        """Rename a folder, or move it under another."""
        folder = await service.get(ctx, kind=kind, folder_id=folder_id)
        folder = await service.update(ctx, folder, data)
        return _read(await service.view(ctx, folder))

    @router.put("/{folder_id}/audience", response_model=FolderRead)
    async def set_folder_audience(
        folder_id: UUID, data: AudienceChoice, ctx: Auth, service: FolderSvc
    ) -> Any:
        """Replace who a folder reaches; what it holds and its subfolders follow."""
        folder = await service.get(ctx, kind=kind, folder_id=folder_id)
        folder = await service.set_audience(ctx, folder, data)
        return _read(await service.view(ctx, folder))

    @router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
    async def delete_folder(
        folder_id: UUID,
        ctx: Auth,
        service: FolderSvc,
        move_to: UUID | None = Query(
            default=None,
            description="Where its contents go; none moves them to the top level.",
        ),
    ) -> None:
        """Delete a folder; what it holds moves to `move_to`, or the top level."""
        folder = await service.get(ctx, kind=kind, folder_id=folder_id)
        await service.delete(ctx, folder, move_to=move_to)

    @router.put("/items/{resource_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
    async def file_resource(
        resource_id: UUID, data: FileInFolder, db: DBSession, ctx: Auth, service: FolderSvc
    ) -> None:
        """File a resource in a folder, or move it to the top level."""
        resource = await load(db, resource_id, ctx.organization_id)
        await service.file(ctx, kind=kind, resource=resource, folder_id=data.folder_id)

    return router

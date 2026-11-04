"""Project routes: the projects themselves, their files and their chats.

The collection carries a `require(...)` gate; one project's routes delegate to
`ProjectService`, which decides against the project's own grants - a role gate
would refuse a member a project somebody shared with them.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status

from app.api.deps import Auth, ProjectSvc, ProjectTransferSvc, require
from app.api.public_api import PUBLIC
from app.api.routes.v1._workspace_bytes import file_response
from app.core.config import settings
from app.core.permissions import Perm
from app.schemas.conversation import ProjectChatList
from app.schemas.project import (
    ProjectCreate,
    ProjectFileEdit,
    ProjectFileText,
    ProjectFolderCreate,
    ProjectList,
    ProjectPathMove,
    ProjectRead,
    ProjectUpdate,
    ProjectWorkspaceMoveRead,
    ProjectWorkspaceMoveRequest,
)
from app.schemas.workspace import WorkspaceFileRead, WorkspaceListing
from app.services.sandbox_workspace import owner_label, stored_ceiling

router = APIRouter(dependencies=[PUBLIC])


@router.get("", response_model=ProjectList, dependencies=[Depends(require(Perm.PROJECTS_VIEW))])
async def list_projects(
    service: ProjectSvc,
    ctx: Auth,
    q: str | None = Query(None, max_length=100, description="Match on name or description"),
    group_id: UUID | None = Query(None, description="Only what is shared with this group"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The projects the caller may see, most recently changed first."""
    return await service.list_projects(ctx, search=q, group_id=group_id, skip=skip, limit=limit)


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.PROJECTS_EDIT))],
)
async def create_project(data: ProjectCreate, service: ProjectSvc, ctx: Auth) -> Any:
    """Create a project; it is private to its creator unless an audience is named."""
    return await service.read(ctx, await service.create(ctx, data))


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: UUID, service: ProjectSvc, ctx: Auth) -> Any:
    return await service.read(ctx, await service.get(ctx, project_id))


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: UUID, data: ProjectUpdate, service: ProjectSvc, ctx: Auth
) -> Any:
    return await service.read(ctx, await service.update(ctx, project_id, data))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_project(project_id: UUID, service: ProjectSvc, ctx: Auth) -> None:
    """Delete the project and its files. Its chats remain, as ordinary chats."""
    await service.delete(ctx, project_id)


@router.get("/{project_id}/chats", response_model=ProjectChatList)
async def list_project_chats(
    project_id: UUID,
    service: ProjectSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The project's chats, whoever started them, most recently active first.

    Each names whose it is, who has had it open and whose run is at work in it,
    because a project's chats are its members' to read and continue.
    """
    items, total = await service.chats(ctx, project_id, skip=skip, limit=limit)
    return ProjectChatList(items=items, total=total)


@router.get("/{project_id}/files", response_model=WorkspaceListing)
async def list_project_files(project_id: UUID, service: ProjectSvc, ctx: Auth) -> Any:
    """What the project's container holds. Empty until something is put in it."""
    project, row, contents = await service.files(ctx, project_id)
    items = [
        WorkspaceFileRead(
            path=str(entry.get("path")),
            size=entry.get("size"),
            is_dir=bool(entry.get("is_dir")),
            modified_at=entry.get("modified_at"),
            preview=contents.previews.get(str(entry.get("path"))),
            thumbnail=contents.thumbnails.get(str(entry.get("path"))),
        )
        for entry in contents.entries
    ]
    return WorkspaceListing(
        scope="project",
        backend=row.backend if row is not None else project.backend,
        owner_label=owner_label(row) if row is not None else "This project",
        items=items,
        total=len(items),
        bytes_total=row.bytes_total if row is not None else 0,
        bytes_limit=stored_ceiling(row) if row is not None else None,
        unreadable_reason=contents.unreadable_reason,
        truncated=contents.truncated,
    )


@router.get("/{project_id}/files/raw", response_model=None)
async def read_project_file(
    project_id: UUID,
    service: ProjectSvc,
    ctx: Auth,
    path: str = Query(description="Path inside the project, as the listing gives it"),
    download: bool = Query(False, description="Force a download rather than a preview"),
) -> Response:
    """One file as bytes: a download, or a file a viewer can render in place."""
    return file_response(
        await service.file_bytes(ctx, project_id, path=path), path=path, download=download
    )


@router.post("/{project_id}/files", status_code=status.HTTP_201_CREATED, response_model=None)
async def upload_project_file(
    project_id: UUID,
    service: ProjectSvc,
    ctx: Auth,
    file: UploadFile = File(...),
    path: str | None = Form(
        default=None, description="Where to put it; the file's own name at the top by default"
    ),
) -> dict[str, str]:
    """Add a file to the project, for every agent working in it."""
    target = path or file.filename or "upload"
    # One byte past the ceiling, so the service refuses an over-large file on a
    # length it can see - without the whole body copied into memory first, which
    # a chunked upload with no Content-Length would otherwise get.
    data = await file.read(settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024 + 1)
    return {"path": await service.add_file(ctx, project_id, path=target, data=data)}


@router.post("/{project_id}/folders", status_code=status.HTTP_201_CREATED, response_model=None)
async def create_project_folder(
    project_id: UUID, data: ProjectFolderCreate, service: ProjectSvc, ctx: Auth
) -> dict[str, str]:
    return {"path": await service.add_folder(ctx, project_id, path=data.path)}


@router.delete("/{project_id}/files", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_project_file(
    project_id: UUID,
    service: ProjectSvc,
    ctx: Auth,
    path: str = Query(description="The file or folder to remove, with everything in it"),
) -> None:
    await service.remove(ctx, project_id, path=path)


@router.post("/{project_id}/files/move", response_model=None)
async def move_project_path(
    project_id: UUID, data: ProjectPathMove, service: ProjectSvc, ctx: Auth
) -> dict[str, str]:
    """Move or rename a file or folder. Existing destinations are never replaced."""
    return {
        "path": await service.move_path(
            ctx, project_id, source=data.source, destination=data.destination
        )
    }


@router.get("/{project_id}/files/text", response_model=ProjectFileText)
async def editable_project_file(
    project_id: UUID,
    service: ProjectSvc,
    ctx: Auth,
    path: str = Query(min_length=1, max_length=500),
) -> Any:
    """Read a complete UTF-8 file up to 1 MiB for editing, with its revision."""
    return await service.editable_file(ctx, project_id, path=path)


@router.put("/{project_id}/files/text", response_model=ProjectFileText)
async def edit_project_file(
    project_id: UUID,
    data: ProjectFileEdit,
    service: ProjectSvc,
    ctx: Auth,
    path: str = Query(min_length=1, max_length=500),
) -> Any:
    """Save a text file; refuse a revision that changed since the editor opened."""
    return await service.edit_file(
        ctx, project_id, path=path, content=data.content, revision=data.revision
    )


@router.post(
    "/{project_id}/workspace-move",
    response_model=ProjectWorkspaceMoveRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def move_project_workspace(
    project_id: UUID, data: ProjectWorkspaceMoveRequest, service: ProjectTransferSvc, ctx: Auth
) -> Any:
    """Queue a verified copy to a different sandbox. Writes and new runs wait until it ends.

    Transfers preserve user files and empty folders, with a limit of 10,000 entries,
    64 MiB per file and 1 GiB total. Symbolic links must be removed first. The old
    workspace remains selected on failure; the target is activated only after verification.
    """
    return await service.queue(ctx, project_id, data)

"""Skill routes - an organization's reusable know-how.

Skills are content: a support lead edits the refund policy here and every agent
bound to it is current on the next run, with no deploy and no version bump to
chase.

Routes acting on the collection carry a `require(...)` gate; routes acting on
one skill deliberately do not, and delegate to `SkillService` instead. A
role-level gate cannot see the grants on a row, so it would refuse a viewer who
was explicitly given edit on a single skill - the exact case sharing exists for.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.deps import Auth, SkillSvc, require
from app.core.permissions import Perm
from app.repositories.skill import SkillSort
from app.schemas.skill import (
    LibrarySkillList,
    SkillCreate,
    SkillList,
    SkillRead,
    SkillResourceCreate,
    SkillResourceList,
    SkillResourceRead,
    SkillResourceUpdate,
    SkillUpdate,
)

router = APIRouter()


@router.get("", response_model=SkillList, dependencies=[Depends(require(Perm.SKILLS_VIEW))])
async def list_skills(
    service: SkillSvc,
    ctx: Auth,
    q: str | None = Query(None, max_length=100, description="Match on name or description"),
    category: list[str] | None = Query(None, description="Exact categories to filter to"),
    sort: SkillSort = Query("name", description="`name` A-Z, or `updated` newest change first"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Names and descriptions - the Builder's picker, not the bodies.

    Carries the whole organization's categories and the suggested ones
    alongside the page, so the filters around it survive paging.
    """
    return await service.list_readable(
        ctx, search=q, categories=category, sort=sort, skip=skip, limit=limit
    )


@router.post(
    "",
    response_model=SkillRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.SKILLS_EDIT))],
)
async def create_skill(data: SkillCreate, service: SkillSvc, ctx: Auth) -> Any:
    return await service.create(
        ctx,
        name=data.name,
        description=data.description,
        content=data.content,
        category=data.category,
    )


@router.get(
    "/library",
    response_model=LibrarySkillList,
    dependencies=[Depends(require(Perm.SKILLS_VIEW))],
)
async def list_library(service: SkillSvc, ctx: Auth) -> Any:
    """The skills this deployment ships with, and whether they are installed.

    Declared above `/{skill_id}` because that route parses its segment as a
    UUID and would answer this path with a 422 instead.
    """
    return await service.list_library(ctx)


@router.post(
    "/library/{key}/install",
    response_model=SkillRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.SKILLS_EDIT))],
)
async def install_from_library(key: str, service: SkillSvc, ctx: Auth) -> Any:
    """Copy a bundled skill into this organization, files and all.

    A copy: from here it is an ordinary skill the organization owns and edits.
    """
    return await service.install_from_library(ctx, key)


@router.get("/{skill_id}", response_model=SkillRead)
async def get_skill(skill_id: UUID, service: SkillSvc, ctx: Auth) -> Any:
    return await service.get(ctx, skill_id)


@router.patch("/{skill_id}", response_model=SkillRead)
async def update_skill(skill_id: UUID, data: SkillUpdate, service: SkillSvc, ctx: Auth) -> Any:
    """Edit a skill. Every agent bound to it is current on the next run."""
    return await service.update(ctx, skill_id, data.model_dump(exclude_unset=True))


@router.delete(
    "/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_skill(skill_id: UUID, service: SkillSvc, ctx: Auth) -> None:
    await service.delete(ctx, skill_id)


@router.post(
    "/{skill_id}/resources",
    response_model=SkillResourceRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_resource(
    skill_id: UUID, data: SkillResourceCreate, service: SkillSvc, ctx: Auth
) -> Any:
    """Attach a file to a skill - a reference table, a template, a worked example.

    The body says how the work is done; a file is the detail that would bury the
    instructions if it were inlined, and that the model loads only when it
    decides it needs it.
    """
    return await service.add_resource(
        ctx,
        skill_id,
        name=data.name,
        description=data.description,
        content=data.content,
    )


@router.post(
    "/{skill_id}/resources/upload",
    response_model=SkillResourceList,
    status_code=status.HTTP_201_CREATED,
)
async def upload_resources(
    skill_id: UUID,
    service: SkillSvc,
    ctx: Auth,
    files: list[UploadFile] = File(...),
) -> Any:
    """Write several files at once - a dropped folder, or a handful of files.

    Each file keeps the relative path the browser sent, so a folder arrives as a
    folder: `references/workflows.md` is one resource whose name says where it
    sits. A path that already exists is replaced, because somebody dropping a
    corrected folder in means the corrected version.
    """
    uploaded = [
        # `filename` carries the relative path when a directory was picked, and
        # only the basename when single files were. Both are names here.
        (file.filename or "file", await file.read())
        for file in files
    ]
    written = await service.put_resources(ctx, skill_id, uploaded)
    return SkillResourceList(items=written, total=len(written))


@router.get("/{skill_id}/resources/{resource_id}", response_model=SkillResourceRead)
async def get_resource(skill_id: UUID, resource_id: UUID, service: SkillSvc, ctx: Auth) -> Any:
    """One file with its body. The skill's listing carries only the names."""
    return await service.get_resource(ctx, skill_id, resource_id)


@router.patch("/{skill_id}/resources/{resource_id}", response_model=SkillResourceRead)
async def update_resource(
    skill_id: UUID,
    resource_id: UUID,
    data: SkillResourceUpdate,
    service: SkillSvc,
    ctx: Auth,
) -> Any:
    return await service.update_resource(
        ctx, skill_id, resource_id, data.model_dump(exclude_unset=True)
    )


@router.delete(
    "/{skill_id}/resources/{resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def remove_resource(skill_id: UUID, resource_id: UUID, service: SkillSvc, ctx: Auth) -> None:
    await service.remove_resource(ctx, skill_id, resource_id)

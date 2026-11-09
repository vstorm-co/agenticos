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

from app.api.deps import (
    Auth,
    SkillAgentSvc,
    SkillCatchUpSvc,
    SkillSvc,
    SkillVersionSvc,
    require,
)
from app.api.public_api import PUBLIC
from app.core.permissions import Perm
from app.repositories.skill import SkillSort
from app.schemas.skill import (
    GalleryInstallRequest,
    GalleryInstallResult,
    GallerySkillPreview,
    SkillCreate,
    SkillGallery,
    SkillList,
    SkillRead,
    SkillResourceCreate,
    SkillResourceList,
    SkillResourceRead,
    SkillResourceUpdate,
    SkillUpdate,
)
from app.schemas.skill_usage import SkillUsageRead
from app.schemas.skill_version import (
    BehindMainList,
    ReturnedToMain,
    ReturnToMain,
    SkillAgentList,
    SkillBindingChange,
    SkillBindingChanged,
    SkillForkCreate,
    SkillForkList,
    SkillForkRead,
    SkillForkUpdate,
    SkillVersionCreate,
    SkillVersionList,
    SkillVersionRead,
    SkillVersionRestore,
    VersionResourceRead,
)

router = APIRouter(dependencies=[PUBLIC])


@router.get("", response_model=SkillList, dependencies=[Depends(require(Perm.SKILLS_VIEW))])
async def list_skills(
    service: SkillSvc,
    ctx: Auth,
    q: str | None = Query(None, max_length=100, description="Match on name or description"),
    category: list[str] | None = Query(None, description="Exact categories to filter to"),
    sort: SkillSort = Query("name", description="`name` A-Z, or `updated` newest change first"),
    group_id: UUID | None = Query(None, description="Only what is shared with this group"),
    shared_with_me: bool = Query(
        False, description="Only what was shared with the caller - never their own rows"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Names and descriptions - the Builder's picker, not the bodies.

    Carries the whole organization's categories and the suggested ones
    alongside the page, so the filters around it survive paging.
    """
    return await service.list_readable(
        ctx,
        shared_with_me=shared_with_me,
        search=q,
        categories=category,
        group_id=group_id,
        sort=sort,
        skip=skip,
        limit=limit,
    )


@router.post(
    "",
    response_model=SkillRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.SKILLS_EDIT))],
)
async def create_skill(data: SkillCreate, service: SkillSvc, ctx: Auth) -> Any:
    skill = await service.create(
        ctx,
        name=data.name,
        description=data.description,
        content=data.content,
        category=data.category,
        visibility=data.visibility,
        group_ids=data.group_ids,
        user_ids=data.user_ids,
    )
    return await service.read(ctx, skill)


@router.get(
    "/behind-main",
    response_model=BehindMainList,
    dependencies=[Depends(require(Perm.SKILLS_VIEW))],
)
async def skills_behind_main(service: SkillCatchUpSvc, ctx: Auth) -> Any:
    """The pinned agents and the forks main has moved past, across the organization.

    Nothing catches up by itself: each item is one a person may bring along. Skills
    the caller may not view are left out, and pinned agents it may not view are
    counted in `hidden`. Declared before `/{skill_id}`, which would read the path as
    a malformed id.
    """
    return await service.behind_main(ctx)


@router.get(
    "/gallery",
    response_model=SkillGallery,
    dependencies=[Depends(require(Perm.SKILLS_VIEW))],
)
async def skill_gallery(service: SkillSvc, ctx: Auth) -> Any:
    """The industry gallery - names, descriptions and what is already installed.

    Declared before `/{skill_id}`: that path parses a UUID, so a later
    declaration would answer this URL with a 422 about a malformed id rather
    than reaching here.
    """
    return await service.gallery(ctx)


@router.get(
    "/gallery/preview",
    response_model=GallerySkillPreview,
    dependencies=[Depends(require(Perm.SKILLS_VIEW))],
)
async def preview_gallery_skill(
    service: SkillSvc, key: str = Query(..., description="`<industry>/<folder>`")
) -> Any:
    """One gallery skill's body and the names of its files, before installing it; 404
    for a key the gallery does not hold. Declared before `/{skill_id}`, as the gallery is."""
    return await service.gallery_preview(key)


@router.post(
    "/gallery/install",
    response_model=GalleryInstallResult,
    dependencies=[Depends(require(Perm.SKILLS_EDIT))],
)
async def install_from_gallery(data: GalleryInstallRequest, service: SkillSvc, ctx: Auth) -> Any:
    """Copy one gallery skill, or a whole shelf, into this organization.

    Answers 200 with what happened to each key rather than refusing the request
    over one of them - installing ten where one is already present must not
    lose the other nine.
    """
    return await service.install_gallery(ctx, data.keys)


@router.get("/{skill_id}", response_model=SkillRead)
async def get_skill(skill_id: UUID, service: SkillSvc, ctx: Auth) -> Any:
    return await service.read(ctx, await service.get(ctx, skill_id))


@router.get("/{skill_id}/usage", response_model=SkillUsageRead)
async def get_skill_usage(
    skill_id: UUID,
    service: SkillSvc,
    ctx: Auth,
    days: int = Query(30, ge=1, le=90, description="How far back to count"),
) -> Any:
    """How often each agent used this skill: opened it, or read one of its files.

    Runs of evals and of the Builder's test panel are not counted, and a
    delegate's use counts under the delegate. Needs `runs:view`; agents the
    caller cannot see are a count, never named.
    """
    return await service.usage(ctx, skill_id, days=days)


@router.patch("/{skill_id}", response_model=SkillRead)
async def update_skill(skill_id: UUID, data: SkillUpdate, service: SkillSvc, ctx: Auth) -> Any:
    """Edit a skill's main line: a changed text is a new main version.

    Agents on main read it from their next run; pinned agents and forks keep theirs.
    `POST /skills/{skill_id}/versions` does the same with a check that nobody saved a
    newer version since it was read.
    """
    return await service.read(ctx, await service.update(ctx, skill_id, data))


@router.delete(
    "/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_skill(
    skill_id: UUID,
    service: SkillSvc,
    ctx: Auth,
    remove_from_agents: bool = Query(
        False,
        description=(
            "Take the skill out of every agent that uses it first, publishing a version "
            "without it where an environment that follows publishes serves it; all or "
            "nothing. Without it, a skill in use is refused with 409"
        ),
    ),
) -> None:
    """Delete a skill, with every version and fork it has."""
    await service.delete(ctx, skill_id, remove_from_agents=remove_from_agents)


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
    return await service.update_resource(ctx, skill_id, resource_id, data)


@router.delete(
    "/{skill_id}/resources/{resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def remove_resource(skill_id: UUID, resource_id: UUID, service: SkillSvc, ctx: Auth) -> None:
    await service.remove_resource(ctx, skill_id, resource_id)


@router.get("/{skill_id}/versions", response_model=SkillVersionList)
async def list_versions(
    skill_id: UUID,
    service: SkillVersionSvc,
    ctx: Auth,
    fork_id: UUID | None = Query(None, description="A fork's own versions; unset lists main's"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """One line's versions, newest first, without their text."""
    return await service.list_versions(ctx, skill_id, fork_id=fork_id, skip=skip, limit=limit)


@router.post(
    "/{skill_id}/versions",
    response_model=SkillVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_version(
    skill_id: UUID, data: SkillVersionCreate, service: SkillVersionSvc, ctx: Auth
) -> Any:
    """Save an edit of the text and description as a new version of main or of a fork.

    Refused with 409 when the line has a newer version than `base_version_id`, so an
    edit made on an old text never replaces a newer one unseen.
    """
    return await service.edit(ctx, skill_id, data)


@router.get("/{skill_id}/versions/{version_id}", response_model=SkillVersionRead)
async def read_version(
    skill_id: UUID, version_id: UUID, service: SkillVersionSvc, ctx: Auth
) -> Any:
    """One version with its text and the list of its files."""
    return await service.read_version(ctx, skill_id, version_id)


@router.get(
    "/{skill_id}/versions/{version_id}/resources/{name:path}", response_model=VersionResourceRead
)
async def read_version_resource(
    skill_id: UUID, version_id: UUID, name: str, service: SkillVersionSvc, ctx: Auth
) -> Any:
    """One file as that version had it."""
    return await service.read_resource(ctx, skill_id, version_id, name)


@router.post(
    "/{skill_id}/versions/{version_id}/restore",
    response_model=SkillVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def restore_version(
    skill_id: UUID,
    version_id: UUID,
    data: SkillVersionRestore,
    service: SkillVersionSvc,
    ctx: Auth,
) -> Any:
    """Bring an earlier version back as the newest version of its own line."""
    return await service.restore(ctx, skill_id, version_id, data)


@router.get("/{skill_id}/forks", response_model=SkillForkList)
async def list_forks(
    skill_id: UUID,
    service: SkillVersionSvc,
    ctx: Auth,
    archived: bool = Query(False, description="List the archived forks instead"),
) -> Any:
    return await service.list_forks(ctx, skill_id, archived=archived)


@router.post(
    "/{skill_id}/forks",
    response_model=SkillForkRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_fork(
    skill_id: UUID, data: SkillForkCreate, service: SkillVersionSvc, ctx: Auth
) -> Any:
    """Start a fork from a main version; a fork of a fork is refused."""
    return await service.create_fork(ctx, skill_id, data)


@router.patch("/{skill_id}/forks/{fork_id}", response_model=SkillForkRead)
async def rename_fork(
    skill_id: UUID, fork_id: UUID, data: SkillForkUpdate, service: SkillVersionSvc, ctx: Auth
) -> Any:
    return await service.rename_fork(ctx, skill_id, fork_id, data)


@router.post("/{skill_id}/forks/{fork_id}/archive", response_model=SkillForkRead)
async def archive_fork(skill_id: UUID, fork_id: UUID, service: SkillVersionSvc, ctx: Auth) -> Any:
    """Archive a fork. It keeps its versions; it is never deleted."""
    return await service.archive_fork(ctx, skill_id, fork_id)


@router.post("/{skill_id}/forks/{fork_id}/return-to-main", response_model=ReturnedToMain)
async def return_fork_to_main(
    skill_id: UUID, fork_id: UUID, data: ReturnToMain, service: SkillCatchUpSvc, ctx: Auth
) -> Any:
    """Move a fork's agents back to main's newest version, and archive the fork once
    nobody reads it.

    Each agent moves as Change version moves it, and one that cannot be moved stays on
    the fork with the reason. Agents the caller may not see are counted and left alone.
    """
    return await service.return_to_main(ctx, skill_id, fork_id, data)


@router.get("/{skill_id}/agents", response_model=SkillAgentList)
async def list_skill_agents(skill_id: UUID, service: SkillAgentSvc, ctx: Auth) -> Any:
    """The agents that use the skill, with the version each reads in each environment.

    Agents the caller may not see are counted in `hidden` and not named.
    """
    return await service.agents(ctx, skill_id)


@router.put("/{skill_id}/agents/{agent_id}/binding", response_model=SkillBindingChanged)
async def change_skill_binding(
    skill_id: UUID,
    agent_id: UUID,
    data: SkillBindingChange,
    service: SkillAgentSvc,
    ctx: Auth,
) -> Any:
    """Move an agent to main's newest version, a main version, or a fork of this skill.

    With `agents:publish` on the agent, its published spec with only this binding
    changed goes live as a new agent version and the draft takes the same change;
    with `agents:edit` alone, only the draft changes and `published` is false.
    """
    return await service.change_binding(ctx, skill_id, agent_id, data)

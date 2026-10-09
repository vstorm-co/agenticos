"""Artifact routes - opening, sharing and managing pages agents published.

Routes acting on the collection carry a `require(...)` gate; routes acting on
one artifact deliberately do not, and delegate to `ArtifactService`, whose
`resolve_access` sees the grants a role gate cannot.

Nothing here publishes. An artifact's content is written by a run, through the
`artifacts` capability, and a person changes it by asking the agent again - or
by restoring one of its kept versions, which republishes bytes a run wrote.

Three routers take no account at all, and all three are deliberate:
`public_router` answers an "anyone with the link" key, `content_router` serves
the bytes behind a signed address minted by one of the authenticated routes -
so the page can be served where no cookie reaches it - and the library set those
pages load, and `embed_router` serves the document another site frames for a
public link.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    ArtifactSvc,
    Auth,
    limit_artifact_content,
    limit_public_artifact,
    require,
)
from app.api.public_api import PUBLIC
from app.api.routes.v1._artifact_bytes import (
    artifact_response,
    embed_response,
    library_response,
)
from app.core.permissions import Perm
from app.schemas.artifact import (
    ArtifactAgentList,
    ArtifactDetail,
    ArtifactList,
    ArtifactPublicLinkUpdate,
    ArtifactUpdate,
    ArtifactVersionList,
    ArtifactView,
    PublicArtifactRead,
    PublicArtifactUnlock,
)
from app.services.artifact import library_file

router = APIRouter(dependencies=[PUBLIC])
public_router = APIRouter()
content_router = APIRouter()
embed_router = APIRouter()


@router.get("", response_model=ArtifactList, dependencies=[Depends(require(Perm.ARTIFACTS_VIEW))])
async def list_artifacts(
    service: ArtifactSvc,
    ctx: Auth,
    q: str | None = Query(None, max_length=100, description="Match on title or name"),
    shared_with_me: bool = Query(
        False, description="Only what was shared with the caller - never their own rows"
    ),
    agent_id: UUID | None = Query(None, description="Only the pages this agent published"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The artifacts the caller may open, most recently published first."""
    return await service.list_readable(
        ctx, shared_with_me=shared_with_me, search=q, agent_id=agent_id, skip=skip, limit=limit
    )


@router.get(
    "/agents",
    response_model=ArtifactAgentList,
    dependencies=[Depends(require(Perm.ARTIFACTS_VIEW))],
)
async def list_artifact_agents(service: ArtifactSvc, ctx: Auth) -> Any:
    """The agents behind the artifacts the caller may open, by name - the list's filter."""
    return await service.publishing_agents(ctx)


@router.get("/{artifact_id}", response_model=ArtifactDetail)
async def get_artifact(artifact_id: UUID, service: ArtifactSvc, ctx: Auth) -> Any:
    return await service.read(ctx, artifact_id)


@router.patch("/{artifact_id}", response_model=ArtifactDetail)
async def update_artifact(
    artifact_id: UUID, data: ArtifactUpdate, service: ArtifactSvc, ctx: Auth
) -> Any:
    """Retitle an artifact. Its content changes only when the agent republishes it."""
    return await service.update(ctx, artifact_id, data)


@router.delete("/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_artifact(artifact_id: UUID, service: ArtifactSvc, ctx: Auth) -> None:
    """Delete it with every version, its grants and its public link."""
    await service.delete(ctx, artifact_id)


@router.get("/{artifact_id}/versions", response_model=ArtifactVersionList)
async def list_artifact_versions(artifact_id: UUID, service: ArtifactSvc, ctx: Auth) -> Any:
    """The versions still kept, newest first."""
    return await service.versions(ctx, artifact_id)


@router.post("/{artifact_id}/versions/{version_id}/restore", response_model=ArtifactDetail)
async def restore_artifact_version(
    artifact_id: UUID, version_id: UUID, service: ArtifactSvc, ctx: Auth
) -> Any:
    """Make a kept version current again, as a new version. History is never rewritten."""
    return await service.restore_version(ctx, artifact_id, version_id)


@router.put("/{artifact_id}/follow", response_model=ArtifactDetail)
async def follow_artifact(artifact_id: UUID, service: ArtifactSvc, ctx: Auth) -> Any:
    """Be notified in the inbox when the page gets a new version."""
    return await service.follow(ctx, artifact_id)


@router.delete("/{artifact_id}/follow", response_model=ArtifactDetail)
async def unfollow_artifact(artifact_id: UUID, service: ArtifactSvc, ctx: Auth) -> Any:
    """Stop being notified about new versions."""
    return await service.unfollow(ctx, artifact_id)


@router.get("/{artifact_id}/view", response_model=ArtifactView)
async def view_artifact(
    artifact_id: UUID,
    service: ArtifactSvc,
    ctx: Auth,
    version_id: UUID | None = Query(None, description="A kept version; omit for the current one"),
) -> Any:
    """A short-lived signed address for the page, for a frame to load."""
    return await service.view(ctx, artifact_id, version_id=version_id)


@router.put("/{artifact_id}/public-link", response_model=ArtifactDetail)
async def set_artifact_public_link(artifact_id: UUID, service: ArtifactSvc, ctx: Auth) -> Any:
    """Turn on the "anyone with the link" address, or rotate the one that is on."""
    return await service.set_public_link(ctx, artifact_id)


@router.patch("/{artifact_id}/public-link", response_model=ArtifactDetail)
async def update_artifact_public_link(
    artifact_id: UUID, data: ArtifactPublicLinkUpdate, service: ArtifactSvc, ctx: Auth
) -> Any:
    """Change the link's expiry, pinned version, password or embedding sites."""
    return await service.update_public_link(ctx, artifact_id, data)


@router.delete("/{artifact_id}/public-link", response_model=ArtifactDetail)
async def clear_artifact_public_link(artifact_id: UUID, service: ArtifactSvc, ctx: Auth) -> Any:
    """Turn the public address off. The old link stops opening anything."""
    return await service.clear_public_link(ctx, artifact_id)


@public_router.get(
    "/{public_key}",
    response_model=PublicArtifactRead,
    dependencies=[Depends(limit_public_artifact)],
)
async def get_public_artifact(public_key: str, service: ArtifactSvc) -> Any:
    """The version behind a public link - no account needed, nothing about its owner.

    Behind a password, only that one is needed.
    """
    return await service.public_view(public_key)


@public_router.post(
    "/{public_key}/unlock",
    response_model=PublicArtifactRead,
    dependencies=[Depends(limit_public_artifact)],
)
async def unlock_public_artifact(
    public_key: str, data: PublicArtifactUnlock, service: ArtifactSvc
) -> Any:
    """The version behind a public link with a password. Counted against the link's limit."""
    return await service.public_view(public_key, password=data.password)


@content_router.get("/lib/{name}", response_class=Response)
async def get_artifact_library_file(name: str) -> Response:
    """One file of the library set pages may load. Static, versioned by name."""
    data, media_type = await library_file(name)
    return library_response(data, media_type)


@content_router.get(
    "/{token}", response_class=Response, dependencies=[Depends(limit_artifact_content)]
)
async def get_artifact_content(token: str, service: ArtifactSvc) -> Response:
    """The page behind a signed address, served inside a sandbox policy.

    Counted per address before anything is read: one address is one frame's load
    and a reload or two, not a way to pull the page out of storage on a loop.
    """
    return artifact_response(await service.content(token))


@embed_router.get(
    "/{public_key}", response_class=Response, dependencies=[Depends(limit_public_artifact)]
)
async def get_artifact_embed(public_key: str, service: ArtifactSvc) -> Response:
    """The document another site puts in an `<iframe>` for a public link."""
    return embed_response(await service.embed(public_key))

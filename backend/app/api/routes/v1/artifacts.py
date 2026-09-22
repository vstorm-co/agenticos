"""Artifact routes - opening, sharing and managing pages agents published.

Routes acting on the collection carry a `require(...)` gate; routes acting on
one artifact deliberately do not, and delegate to `ArtifactService`, whose
`resolve_access` sees the grants a role gate cannot.

Nothing here publishes. An artifact's content is written by a run, through the
`artifacts` capability, and a person changes it by asking the agent again.

Two routers take no account at all, and both are deliberate:
`public_router` answers an "anyone with the link" key, and `content_router`
serves the bytes behind a signed address minted by one of the authenticated
routes - so the page can be served where no cookie reaches it.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import ArtifactSvc, Auth, limit_public_artifact, require
from app.api.routes.v1._artifact_bytes import artifact_response
from app.core.permissions import Perm
from app.schemas.artifact import (
    ArtifactDetail,
    ArtifactList,
    ArtifactUpdate,
    ArtifactVersionList,
    ArtifactView,
    PublicArtifactRead,
)

router = APIRouter()
public_router = APIRouter()
content_router = APIRouter()


@router.get("", response_model=ArtifactList, dependencies=[Depends(require(Perm.ARTIFACTS_VIEW))])
async def list_artifacts(
    service: ArtifactSvc,
    ctx: Auth,
    q: str | None = Query(None, max_length=100, description="Match on title or name"),
    shared_with_me: bool = Query(
        False, description="Only what was shared with the caller - never their own rows"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The artifacts the caller may open, most recently published first."""
    return await service.list_readable(
        ctx, shared_with_me=shared_with_me, search=q, skip=skip, limit=limit
    )


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
    """The current version behind a public link - no account needed, nothing about its owner."""
    return await service.public_view(public_key)


@content_router.get("/{token}", response_class=Response)
async def get_artifact_content(token: str, service: ArtifactSvc) -> Response:
    """The page behind a signed address, served inside a sandbox policy."""
    return artifact_response(await service.content(token))

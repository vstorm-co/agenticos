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
    ArtifactPublicDataSvc,
    ArtifactRequestSvc,
    ArtifactSvc,
    Auth,
    limit_artifact_content,
    limit_artifact_data,
    limit_public_artifact,
    require,
)
from app.api.routes.v1._artifact_bytes import (
    artifact_response,
    embed_response,
    library_response,
)
from app.core.permissions import Perm
from app.schemas.artifact import (
    ArtifactAgentList,
    ArtifactAutoConsentUpdate,
    ArtifactConsentCreate,
    ArtifactData,
    ArtifactDetail,
    ArtifactDisclosure,
    ArtifactList,
    ArtifactOwnerUpdate,
    ArtifactPublicDataCreate,
    ArtifactPublicDataDisclosure,
    ArtifactPublicLinkUpdate,
    ArtifactUpdate,
    ArtifactVersionList,
    ArtifactView,
    PublicArtifactRead,
    PublicArtifactUnlock,
)
from app.schemas.artifact_share_request import (
    ArtifactAccessRequestCreate,
    ArtifactAccessRequested,
    ArtifactShareRequestList,
    ArtifactShareRequestRead,
    ArtifactVersionReview,
)
from app.services.artifact import library_file

router = APIRouter()
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
    include_archived: bool = Query(
        False, description="List archived pages too; they are left out otherwise"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The artifacts the caller may open, most recently published first."""
    return await service.list_readable(
        ctx,
        shared_with_me=shared_with_me,
        include_archived=include_archived,
        search=q,
        agent_id=agent_id,
        skip=skip,
        limit=limit,
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
    """One artifact. An archived one is found only by a caller who may edit it."""
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


@router.post("/{artifact_id}/archive", response_model=ArtifactDetail)
async def archive_artifact(artifact_id: UUID, service: ArtifactSvc, ctx: Auth) -> Any:
    """Archive a page. It keeps its versions, grants and name, and serves nothing.

    Its public link is turned off. Until it is restored, every other route here -
    and its public link, its embed and the agent's tools - answers as though it
    were not there. Archiving an archived page changes nothing.
    """
    return await service.archive(ctx, artifact_id)


@router.post(
    "/{artifact_id}/unarchive",
    response_model=ArtifactDetail,
    responses={400: {"description": "`BAD_REQUEST`: the artifact is not archived"}},
)
async def unarchive_artifact(artifact_id: UUID, service: ArtifactSvc, ctx: Auth) -> Any:
    """Restore an archived page, so it is served again. Its public link stays off.

    Needs the same edit right as archiving.
    """
    return await service.unarchive(ctx, artifact_id)


@router.get("/{artifact_id}/versions", response_model=ArtifactVersionList)
async def list_artifact_versions(artifact_id: UUID, service: ArtifactSvc, ctx: Auth) -> Any:
    """The versions still kept that the caller may open, newest first.

    The page's audience is listed only consented or unbound versions, up to the one it
    is served.
    """
    return await service.versions(ctx, artifact_id)


@router.post("/{artifact_id}/versions/{version_id}/restore", response_model=ArtifactDetail)
async def restore_artifact_version(
    artifact_id: UUID, version_id: UUID, service: ArtifactSvc, ctx: Auth
) -> Any:
    """Make a kept version current again, as a new version. History is never rewritten.

    The version's page queries are kept and what they reach is read again. A 403
    when the caller or the page's owner cannot read a table they reach; a 400 when
    a table no longer answers one of their filters or their sort.
    """
    return await service.restore_version(ctx, artifact_id, version_id)


@router.get("/{artifact_id}/versions/{version_id}/disclosure", response_model=ArtifactDisclosure)
async def read_artifact_disclosure(
    artifact_id: UUID, version_id: UUID, service: ArtifactSvc, ctx: Auth
) -> Any:
    """What confirming a version's data would share, and with whom, in words.

    For the page's owner, or an Owner or Admin confirming for them; a 403 for anyone
    else who may open the page. `problem` says why it cannot be confirmed now.
    """
    return await service.disclosure(ctx, artifact_id, version_id)


@router.post(
    "/{artifact_id}/versions/{version_id}/consent",
    response_model=ArtifactDetail,
    responses={
        409: {"description": "`CONFLICT`: a newer version, or other page queries than shown"}
    },
)
async def confirm_artifact_data(
    artifact_id: UUID,
    version_id: UUID,
    data: ArtifactConsentCreate,
    service: ArtifactSvc,
    ctx: Auth,
) -> Any:
    """Confirm that everyone who opens the page may read the latest version's data.

    Carries the `fingerprint` of the page queries the person was shown; a 409 when the
    version is no longer the latest or its queries are not those. By the page's owner,
    or an Owner or Admin for them, signed in as themselves - a 403 for anyone else, and
    when the owner can no longer read a table the data reads.
    """
    return await service.confirm_data(ctx, artifact_id, version_id, data)


@router.delete("/{artifact_id}/consent", response_model=ArtifactDetail)
async def withdraw_artifact_consent(artifact_id: UUID, service: ArtifactSvc, ctx: Auth) -> Any:
    """Withdraw every consent to share the page's data. Anyone who may edit it, as themselves.

    The page's audience keeps the page and its data waits for the owner to confirm it
    again; auto-consent is turned off.
    """
    return await service.withdraw_consent(ctx, artifact_id)


@router.get("/{artifact_id}/public-data", response_model=ArtifactPublicDataDisclosure)
async def read_artifact_public_data(
    artifact_id: UUID, service: ArtifactPublicDataSvc, ctx: Auth
) -> Any:
    """What confirming the page's data for anyone with its link would share, and with whom.

    The served version's page queries in words, and the public audience: the link, its
    password, its expiry and each embedding site. For the page's owner, or an Owner or
    Admin confirming for them; a 403 for anyone else.
    """
    return await service.disclosure(ctx, artifact_id)


@router.post(
    "/{artifact_id}/public-data",
    response_model=ArtifactDetail,
    responses={409: {"description": "`CONFLICT`: other page queries than the ones shown"}},
)
async def confirm_artifact_public_data(
    artifact_id: UUID, data: ArtifactPublicDataCreate, service: ArtifactPublicDataSvc, ctx: Auth
) -> Any:
    """Confirm that anyone with the page's link may read the data of the version it serves.

    Carries the `fingerprint` of the page queries shown and `confirmed: true`. By the
    page's owner, or an Owner or Admin for them, signed in as themselves - a 403 for
    anyone else. A 400 while the organization's switch is off, the page has no link, or the
    version has no consent from the members.
    """
    return await service.confirm(ctx, artifact_id, data)


@router.delete("/{artifact_id}/public-data", response_model=ArtifactDetail)
async def withdraw_artifact_public_data(
    artifact_id: UUID, service: ArtifactPublicDataSvc, ctx: Auth
) -> Any:
    """Take back the consent to show the page's data on its public link. Anyone who may
    edit it, as themselves."""
    return await service.withdraw(ctx, artifact_id)


@router.patch("/{artifact_id}/auto-consent", response_model=ArtifactDetail)
async def update_artifact_auto_consent(
    artifact_id: UUID, data: ArtifactAutoConsentUpdate, service: ArtifactSvc, ctx: Auth
) -> Any:
    """Turn "don't ask for consent on republish" on or off.

    Only the page's owner, signed in as themselves, turns it on, confirming the text
    that says what it does; the owner or an Owner or Admin turns it off.
    """
    return await service.set_auto_consent(ctx, artifact_id, data)


@router.put("/{artifact_id}/owner", response_model=ArtifactDetail)
async def change_artifact_owner(
    artifact_id: UUID, data: ArtifactOwnerUpdate, service: ArtifactSvc, ctx: Auth
) -> Any:
    """Hand the page to another active member of its organization.

    Its owner, or an Owner or Admin for any page (one whose owner has left included),
    signed in as themselves. Immediate: the page's data waits for the new owner to
    confirm it, and auto-consent goes off. The old and the new owner are told.
    """
    return await service.change_owner(ctx, artifact_id, data)


@router.get("/{artifact_id}/versions/{version_id}/review", response_model=ArtifactVersionReview)
async def review_artifact_version(
    artifact_id: UUID, version_id: UUID, service: ArtifactRequestSvc, ctx: Auth
) -> Any:
    """What a version's page queries read that the audience's version did not.

    Binding by binding - added, removed, or changed field by field, filter by filter,
    linked table by linked table, the limit and the order - each marked as widening
    what is read, narrowing it, or neither. For the page's owner, or an Owner or Admin
    for them; a 403 for anyone else who may open the page.
    """
    return await service.review(ctx, artifact_id, version_id)


@router.get("/{artifact_id}/share-requests", response_model=ArtifactShareRequestList)
async def list_artifact_share_requests(
    artifact_id: UUID,
    service: ArtifactRequestSvc,
    ctx: Auth,
    include_decided: bool = Query(
        False, description="Approved, declined and voided requests too; only pending ones otherwise"
    ),
) -> Any:
    """The requests about a page that the caller may see, newest first.

    Whoever decides them - the owner, or an Owner or Admin - sees every one. An editor
    sees their own, and the requests for access to a page that reads no data; anyone
    else who may open the page sees their own.
    """
    return await service.list_requests(ctx, artifact_id, pending_only=not include_decided)


@router.post(
    "/{artifact_id}/access-requests",
    response_model=ArtifactAccessRequested,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "`BAD_REQUEST`: the caller can open the page already"},
        429: {"description": "`RATE_LIMIT_EXCEEDED`: too many requests in the last hour"},
    },
)
async def request_artifact_access(
    artifact_id: UUID, data: ArtifactAccessRequestCreate, service: ArtifactRequestSvc, ctx: Auth
) -> Any:
    """Ask for access to a page the caller cannot open.

    For an active member of the page's organization; anyone else is told it was not
    found. A second request replaces the first. It is the page's owner who is told - or
    the Owners and Admins, when it has none left.
    """
    return await service.request_access(ctx, artifact_id, data)


@router.post(
    "/{artifact_id}/share-requests/{request_id}/approve",
    response_model=ArtifactShareRequestRead,
    responses={409: {"description": "`CONCURRENT_CHANGE`: it was decided or voided meanwhile"}},
)
async def approve_artifact_share_request(
    artifact_id: UUID, request_id: UUID, service: ArtifactRequestSvc, ctx: Auth
) -> Any:
    """Approve a request: confirm the version's data, or share the page as asked.

    For a page that reads data, by its owner or an Owner or Admin, signed in as
    themselves - approving is the consent its data needs. Access to a page that reads
    none may be approved by any editor of it.
    """
    return await service.approve(ctx, artifact_id, request_id)


@router.post(
    "/{artifact_id}/share-requests/{request_id}/decline",
    response_model=ArtifactShareRequestRead,
    responses={409: {"description": "`CONCURRENT_CHANGE`: it was decided or voided meanwhile"}},
)
async def decline_artifact_share_request(
    artifact_id: UUID, request_id: UUID, service: ArtifactRequestSvc, ctx: Auth
) -> Any:
    """Decline a request. A declined version is marked so in the page's history and its
    audience keeps the version it was served; by whoever may approve it."""
    return await service.decline(ctx, artifact_id, request_id)


@router.get("/{artifact_id}/view", response_model=ArtifactView)
async def view_artifact(
    artifact_id: UUID,
    service: ArtifactSvc,
    ctx: Auth,
    version_id: UUID | None = Query(None, description="A kept version; omit for the current one"),
    data: bool = Query(
        False,
        description=(
            "Serve the page with its bindings' data written in. Only the console's page "
            "viewer asks; thumbnails, cards and history previews leave it off"
        ),
    ),
) -> Any:
    """A short-lived signed address for the page, for a frame to load.

    Without `version_id`, the version the caller is served: the latest for the page's
    owner, its editors and the roles that read every table, the newest consented one
    for anyone else - a 404 with `not_available_yet` when there is none.

    The address is the caller's own: framed by the console alone, and for `data` it
    carries the caller, so the page is served with the data they are allowed -
    each binding's page query, read once on load. Without `data` the page has none.
    """
    return await service.view(ctx, artifact_id, version_id=version_id, data=data)


@router.get(
    "/{artifact_id}/versions/{version_id}/data",
    response_model=ArtifactData,
    dependencies=[Depends(limit_artifact_data)],
)
async def read_artifact_data(
    artifact_id: UUID, version_id: UUID, service: ArtifactSvc, ctx: Auth, response: Response
) -> Any:
    """The records a live page's bindings read: each page query, read with the owner's access.

    Everyone served the data reads the same records, whatever their own access to
    the tables. The owner and the roles that read every table are always served it;
    anyone else only while the owner's consent to that version holds, and otherwise
    gets every binding `unavailable` with `awaiting_consent`. A binding is also
    `unavailable` when its owner is gone or can no longer read a table it reaches, or
    when what it reaches changed since it was published; why is said only to a
    caller who may edit the page. Only the version the caller is served gets data. A
    404 for a version the caller may not open. Never cached.
    """
    response.headers["Cache-Control"] = "private, no-store"
    return await service.data(ctx, artifact_id, version_id)


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
    and a reload or two, not a way to pull the page out of storage on a loop. A
    member's page served with its data also counts against that member's data
    loads, which the data route shares. Never cached: the body can hold records.
    """
    return artifact_response(await service.content(token))


@embed_router.get(
    "/{public_key}", response_class=Response, dependencies=[Depends(limit_public_artifact)]
)
async def get_artifact_embed(public_key: str, service: ArtifactSvc) -> Response:
    """The document another site puts in an `<iframe>` for a public link."""
    return embed_response(await service.embed(public_key))

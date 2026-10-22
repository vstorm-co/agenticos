"""Filing, replacing and voiding requests about a page (#1974).

Three kinds of request (see :mod:`app.db.models.artifact_share_request`), one rule for all:
at most one pending request per page, person and kind, and one pending `version` request
per page. A newer one replaces the older, which is voided `replaced`, under the page's lock
so two people filing at once cannot both win.

Who decides a request is the page's owner, or - when it has none left, or none who is an
active member - every holder of `artifacts:edit` at scope `ALL`. The same people are the
ones told of it. The page's other editors may decide only an `access` request on a page
that reads no data, which is a plain grant to open it.

A request goes stale without anyone deciding it, and is voided then (:class:`VoidReason`):
a new version whose page queries are not the ones it was made about, a new owner, an
archived page.

What this module does not do is decide: approving a request confirms data or applies a
grant, and that is :class:`app.services.artifact_request_service.ArtifactRequestService`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import ConflictError, RateLimitError
from app.core.permissions import ROLE_PERMS, AuthContext, Perm, Scope
from app.db.models.artifact import Artifact, ArtifactVersion, ConsentState
from app.db.models.artifact_share_request import (
    ArtifactShareRequest,
    ShareRequestKind,
    ShareRequestStatus,
    VoidReason,
)
from app.db.models.resource_grant import GRANT_ORDER, GrantLevel, Visibility
from app.repositories import (
    artifact_repo,
    artifact_share_request_repo,
    member_repo,
    resource_grant_repo,
    user_repo,
)
from app.services import rate_limit
from app.services.access import ARTIFACT
from app.services.artifact_consent import owner_membership_id
from app.services.notifications import NotificationService
from app.services.sharing import ShareChange

EDIT_ALL_ROLES: tuple[str, ...] = tuple(
    role for role, perms in ROLE_PERMS.items() if perms.get(Perm.ARTIFACTS_EDIT) is Scope.ALL
)
"""The roles that edit every page: who decides for a page whose owner is gone."""

_VISIBILITY_RANK: dict[str, int] = {
    Visibility.PRIVATE.value: 0,
    Visibility.TEAM.value: 1,
    Visibility.ORG.value: 2,
}


async def name_of(db: AsyncSession, user_id: UUID) -> str:
    """A person as people know them: their name, or their address without one."""
    user = await user_repo.get_by_id(db, user_id)
    assert user is not None  # a member or an owner: a row that points at them keeps them
    return user.full_name or user.email


async def deciders(db: AsyncSession, artifact: Artifact) -> list[UUID]:
    """Who decides a page's requests, and is told of them: its owner, or - with none who
    is an active member - the holders of `artifacts:edit` at scope `ALL`."""
    if artifact.owner_user_id is not None and await owner_membership_id(db, artifact) is not None:
        return [artifact.owner_user_id]
    return await member_repo.list_member_ids_by_role(
        db, organization_id=artifact.organization_id, roles=list(EDIT_ALL_ROLES)
    )


async def held_level(
    db: AsyncSession, artifact: Artifact, change: ShareChange
) -> GrantLevel | None:
    """The level the person or group `change` names holds on the page now, if any."""
    for grant in await resource_grant_repo.list_for_resource(
        db,
        organization_id=artifact.organization_id,
        resource_type=ARTIFACT.key,
        resource_id=artifact.id,
    ):
        if (grant.subject_user_id, grant.subject_group_id) == (
            change.subject_user_id,
            change.subject_group_id,
        ):
            return GrantLevel(grant.level)
    return None


async def widens(db: AsyncSession, artifact: Artifact, change: ShareChange) -> bool:
    """Whether `change` lets more people open the page than do now: a wider visibility, or
    a grant to someone who has none or a lower level."""
    if change.visibility is not None:
        return _VISIBILITY_RANK[change.visibility.value] > _VISIBILITY_RANK[artifact.visibility]
    assert change.level is not None  # a change is a visibility or a level
    held = await held_level(db, artifact, change)
    return held is None or GRANT_ORDER[change.level] > GRANT_ORDER[held]


async def _admit(ctx: AuthContext) -> None:
    decision = await rate_limit.consume_with_local_floor(
        surface="artifact_share_request",
        caller=f"org:{ctx.organization_id}:user:{ctx.subject_id}",
        limit=rate_limit.artifact_share_request_limit(),
    )
    if not decision.allowed:
        raise RateLimitError(
            message="Too many requests in the last hour. Wait and try again.",
            details={"retry_after_seconds": decision.retry_after_seconds},
        )


def _higher(held: str | None, level: GrantLevel) -> str:
    if held is None or GRANT_ORDER[level] > GRANT_ORDER[GrantLevel(held)]:
        return level.value
    return held


def _merged(
    visibility: str | None, subjects: dict[str, list[dict[str, str]]], change: ShareChange
) -> tuple[str | None, dict[str, list[dict[str, str]]]]:
    """What a request asks for after `change` joins it: the widest visibility and the
    highest level for each person or group named, over what it asks for already."""
    people = {item["user_id"]: item["level"] for item in subjects.get("people", [])}
    groups = {item["group_id"]: item["level"] for item in subjects.get("groups", [])}
    if change.visibility is not None and (
        visibility is None
        or _VISIBILITY_RANK[change.visibility.value] > _VISIBILITY_RANK[visibility]
    ):
        visibility = change.visibility.value
    if change.level is not None and change.subject_user_id is not None:
        key = str(change.subject_user_id)
        people[key] = _higher(people.get(key), change.level)
    elif change.level is not None and change.subject_group_id is not None:
        key = str(change.subject_group_id)
        groups[key] = _higher(groups.get(key), change.level)
    return visibility, {
        "people": [{"user_id": key, "level": level} for key, level in people.items()],
        "groups": [{"group_id": key, "level": level} for key, level in groups.items()],
    }


async def _file(
    db: AsyncSession,
    ctx: AuthContext,
    artifact: Artifact,
    *,
    kind: ShareRequestKind,
    note: str | None = None,
    changes: Sequence[ShareChange] | None = None,
    via_run: Mapping[str, str | None] | None = None,
) -> ArtifactShareRequest:
    """Replace the caller's pending request of this kind, if any, with a new one and tell
    whoever decides it.

    Raises:
        ConflictError: The page is archived: nobody decides a request about it.
        RateLimitError: Too many requests in the last hour.
    """
    assert ctx.user_id is not None  # a request is a person's
    if artifact.archived_at is not None:
        raise ConflictError(
            message="This page is archived, so nothing can be requested of it.",
            details={"artifact_id": artifact.id},
        )
    await _admit(ctx)
    # The page's lock, as a publish takes it: the version this is made against is the
    # latest one, and the older request is gone before the new one is written.
    await artifact_repo.lock(db, artifact.id)
    earlier = await artifact_share_request_repo.pending(
        db, artifact.id, kind=kind, requester_user_id=ctx.user_id
    )
    visibility = earlier.requested_visibility if earlier is not None else None
    subjects = dict(earlier.requested_subjects or {}) if earlier is not None else {}
    for change in changes or ():
        visibility, subjects = _merged(visibility, subjects, change)
    if earlier is not None:
        await artifact_share_request_repo.settle(
            db, earlier, status=ShareRequestStatus.VOIDED, void_reason=VoidReason.REPLACED
        )
    latest = await artifact_repo.latest_version(db, artifact.id)
    membership = await member_repo.get_active(
        db, organization_id=artifact.organization_id, user_id=ctx.user_id
    )
    request = await artifact_share_request_repo.create(
        db,
        organization_id=artifact.organization_id,
        artifact_id=artifact.id,
        kind=kind.value,
        requester_user_id=ctx.user_id,
        requester_membership_id=membership.id if membership is not None else None,
        version_id=latest.id if latest is not None else None,
        query_fingerprint=latest.query_fingerprint if latest is not None else None,
        requested_visibility=visibility,
        requested_subjects=subjects if changes is not None else None,
        note=note,
    )
    await _announce(db, artifact, request, actor_user_id=ctx.subject_id, via_run=via_run)
    return request


async def _announce(
    db: AsyncSession,
    artifact: Artifact,
    request: ArtifactShareRequest,
    *,
    actor_user_id: UUID | None,
    via_run: Mapping[str, str | None] | None = None,
) -> None:
    await record_audit(
        db,
        actor_user_id=actor_user_id,
        organization_id=artifact.organization_id,
        action="artifact.share_requested",
        target_type="artifact",
        target_id=str(artifact.id),
        details={"request_id": str(request.id), "kind": request.kind, **(via_run or {})},
    )
    recipients = [
        user_id for user_id in await deciders(db, artifact) if user_id != request.requester_user_id
    ]
    if recipients:
        await NotificationService(db).artifact_share_requested(
            artifact,
            request_id=request.id,
            kind=request.kind,
            requester_name=await name_of(db, request.requester_user_id),
            recipients=recipients,
        )


async def file_audience_request(
    db: AsyncSession,
    ctx: AuthContext,
    artifact: Artifact,
    changes: Sequence[ShareChange],
    *,
    via_run: Mapping[str, str | None] | None = None,
) -> ArtifactShareRequest:
    """An editor's attempt to widen a page, kept as a request in place of being applied.

    One request carries every change asked for at once. A second one from the same person
    replaces the first and carries what it asked for too, so sharing with two people in
    turn asks for both. `via_run` names the agent run that filed it, for the audit entry.
    """
    assert changes  # a request asks for something
    return await _file(
        db, ctx, artifact, kind=ShareRequestKind.AUDIENCE, changes=changes, via_run=via_run
    )


async def file_access_request(
    db: AsyncSession, ctx: AuthContext, artifact: Artifact, note: str | None
) -> ArtifactShareRequest:
    """A member who cannot open the page asking to."""
    return await _file(db, ctx, artifact, kind=ShareRequestKind.ACCESS, note=note)


async def on_new_version(db: AsyncSession, artifact: Artifact, version: ArtifactVersion) -> None:
    """Settle what a new version does to the requests pending on its page. Called with the
    page locked, as a version is added.

    An `audience` or `access` request made about other page queries than this version's
    is void. The pending `version` request is replaced by one for this version when
    another editor published it and it awaits consent; otherwise it is void, as there is
    nothing left to confirm in it.
    """
    await artifact_share_request_repo.void_pending(
        db,
        artifact.id,
        reason=VoidReason.PAGE_CHANGED,
        kinds=[ShareRequestKind.AUDIENCE, ShareRequestKind.ACCESS],
        fingerprint_other_than=version.query_fingerprint,
        stale_fingerprint_only=True,
    )
    publisher = version.published_by_user_id
    asks = (
        version.consent_state == ConsentState.PENDING.value
        and publisher is not None
        and publisher != artifact.owner_user_id
    )
    await artifact_share_request_repo.void_pending(
        db,
        artifact.id,
        reason=VoidReason.REPLACED if asks else VoidReason.SUPERSEDED,
        kinds=[ShareRequestKind.VERSION],
    )
    if not asks:
        return
    assert publisher is not None
    request = await artifact_share_request_repo.create(
        db,
        organization_id=artifact.organization_id,
        artifact_id=artifact.id,
        kind=ShareRequestKind.VERSION.value,
        requester_user_id=publisher,
        requester_membership_id=version.published_by_membership_id,
        version_id=version.id,
        query_fingerprint=version.query_fingerprint,
    )
    await _announce(db, artifact, request, actor_user_id=publisher)


async def void_all(db: AsyncSession, artifact: Artifact, reason: VoidReason) -> None:
    """Void every request pending on the page: it changed hands or was archived."""
    await artifact_share_request_repo.void_pending(db, artifact.id, reason=reason)


async def decide(
    db: AsyncSession,
    artifact: Artifact,
    request: ArtifactShareRequest,
    *,
    status: ShareRequestStatus,
    by_user_id: UUID | None,
) -> ArtifactShareRequest:
    """Record that a person approved or declined a pending request. Audited
    `artifact.share_request_approved` or `artifact.share_request_declined`, without any
    of the data the page reads."""
    request = await artifact_share_request_repo.settle(
        db, request, status=status, decided_by_user_id=by_user_id
    )
    await record_audit(
        db,
        actor_user_id=by_user_id,
        organization_id=artifact.organization_id,
        action=f"artifact.share_request_{status.value}",
        target_type="artifact",
        target_id=str(artifact.id),
        details={
            "request_id": str(request.id),
            "kind": request.kind,
            "requester": str(request.requester_user_id),
        },
    )
    return request


async def settle_version_request(
    db: AsyncSession,
    artifact: Artifact,
    version: ArtifactVersion,
    *,
    status: ShareRequestStatus,
    by_user_id: UUID | None,
) -> None:
    """Settle the pending `version` request for `version`, if there is one - the owner
    confirmed the version from the page's own strip, or declined it."""
    pending = await artifact_share_request_repo.pending(
        db, artifact.id, kind=ShareRequestKind.VERSION
    )
    if pending is not None and pending.version_id == version.id:
        await decide(db, artifact, pending, status=status, by_user_id=by_user_id)

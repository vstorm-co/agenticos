"""Deciding requests about a page, and asking for them (#1974).

A page that reads live data is shared by its owner. Anyone else who wants it shared, or
wants in, asks, and this is where those requests are listed, made and decided; filing and
voiding them is :mod:`app.services.artifact_requests`.

Who decides what:

- A request about a page that reads data - widening its audience, a version awaiting
  consent, access to it - is decided by its owner, or by an Owner or Admin for them
  (`artifacts:edit` at scope `ALL`), each signed in as themselves. Approving it is the
  decision to share the data, applied as that person - but never a consent to a version's
  data: widening needs the version the audience is served to hold a consent already
  (:meth:`ArtifactRequestService.widen`), and the owner confirms data on its own terms.
- A request for access to a page that reads none is a plain grant to open it, and any
  editor of the page may approve it.
- Declining, like narrowing, stops a thing rather than starting one, but it is still the
  decider's to do.

The requester is told nothing by the platform when a request is decided: the page opening,
or not, is the answer. Nobody is notified of a decision in this piece.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    ConflictError,
    ConsentRequiredError,
    NotFoundError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.artifact import Artifact, ArtifactVersion, ConsentState
from app.db.models.artifact_share_request import (
    ArtifactShareRequest,
    ShareRequestKind,
    ShareRequestStatus,
    VoidReason,
)
from app.db.models.resource_grant import GrantLevel, Visibility
from app.repositories import (
    artifact_repo,
    artifact_share_request_repo,
    group_repo,
    member_repo,
)
from app.schemas.artifact import ArtifactBinding, ArtifactConsentCreate, ArtifactVersionRead
from app.schemas.artifact_share_request import (
    ArtifactAccessRequestCreate,
    ArtifactAccessRequested,
    ArtifactShareRequestList,
    ArtifactShareRequestRead,
    ArtifactVersionReview,
    ShareRequestSubject,
)
from app.schemas.resource_grant import as_visibility
from app.services.access import ARTIFACT, resolve_access
from app.services.artifact import ArtifactService
from app.services.artifact_consent import (
    as_themselves,
    consent_holds,
    may_confirm,
    owner_membership_id,
)
from app.services.artifact_diff import diff_bindings, view_of
from app.services.artifact_requests import (
    decide,
    file_access_request,
    file_audience_request,
    name_of,
    widens,
)
from app.services.sharing import Deferred, ShareChange, SharingService


def _bindings(version: ArtifactVersion | None) -> list[ArtifactBinding]:
    return [] if version is None else [ArtifactBinding.model_validate(b) for b in version.bindings]


class ArtifactRequestService:
    """List, file and decide requests about the pages of one organization."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._pages = ArtifactService(db)

    async def widen(
        self, ctx: AuthContext, artifact: Artifact, change: ShareChange
    ) -> Deferred | None:
        """What the sharing layer asks before it widens who opens a page.

        `None` lets the change through: the page reads no data, the change narrows or
        leaves things as they are, or the caller is the page's owner - or an Owner or Admin
        for them - and the version the audience is served holds a consent. Anyone else who
        may edit the page gets a request filed for them and a
        :class:`~app.services.sharing.Deferred` to answer with; nothing is applied.

        Widening never consents: a version that is declined, pending or withdrawn stays
        so, and the owner confirms its data first, as :meth:`ArtifactService.confirm_data`.

        Raises:
            ConflictError: The page is archived.
            ConsentRequiredError: The audience's version has no consent that holds under
                the owner's membership now.
        """
        if not await widens(self.db, artifact, change):
            return None
        if artifact.archived_at is not None:
            raise ConflictError(
                message="This page is archived, so it cannot be shared.",
                details={"artifact_id": artifact.id},
            )
        latest = await artifact_repo.latest_version(self.db, artifact.id)
        if latest is None or not latest.bindings:
            return None
        if not may_confirm(ctx, artifact):
            request = await file_audience_request(self.db, ctx, artifact, [change])
            return Deferred(request_id=request.id, waiting_for=await self._waiting_for(artifact))
        served = await artifact_repo.latest_served(self.db, artifact.id)
        if served is None or (
            served.bindings
            and not consent_holds(served, artifact, await owner_membership_id(self.db, artifact))
        ):
            raise ConsentRequiredError(
                details={
                    "artifact_id": artifact.id,
                    "version_id": latest.id,
                    "version_number": latest.number,
                }
            )
        return None

    async def _waiting_for(self, artifact: Artifact) -> str | None:
        if artifact.owner_user_id is None or await owner_membership_id(self.db, artifact) is None:
            return None
        return await name_of(self.db, artifact.owner_user_id)

    async def list_requests(
        self, ctx: AuthContext, artifact_id: UUID, *, pending_only: bool = True
    ) -> ArtifactShareRequestList:
        """The page's requests the caller may see: all of them for whoever decides them,
        an editor's own and the requests for access to a page that reads no data, anyone
        else's own. Newest first.

        Raises:
            NotFoundError: The page is not the caller's to open.
        """
        artifact = await self._pages.get(ctx, artifact_id)
        can_edit = await self._can_edit(ctx, artifact)
        found = await artifact_share_request_repo.list_for_artifact(
            self.db, artifact.id, pending_only=pending_only
        )
        shown = [
            request
            for request in found
            if request.requester_user_id == ctx.user_id
            or self._may_decide(ctx, artifact, request, can_edit=can_edit)
        ]
        return ArtifactShareRequestList(
            items=await self._reads(ctx, artifact, shown), total=len(shown)
        )

    async def request_access(
        self, ctx: AuthContext, artifact_id: UUID, data: ArtifactAccessRequestCreate
    ) -> ArtifactAccessRequested:
        """Ask for access to a page the caller cannot open. Replaces their earlier request
        for it; counted against the per-person limit on requests. The answer says nothing
        of the page: whoever asks cannot open it.

        Raises:
            NotFoundError: No such live page in the caller's organization, or the caller
                is no active member of it.
            BadRequestError: The caller can open the page already.
            RateLimitError: Too many requests in the last hour.
        """
        artifact = await artifact_repo.get(
            self.db, artifact_id, organization_id=ctx.organization_id
        )
        if (
            artifact is None
            or artifact.archived_at is not None
            or ctx.user_id is None
            or await member_repo.get_active(
                self.db, organization_id=ctx.organization_id, user_id=ctx.user_id
            )
            is None
        ):
            raise NotFoundError(
                message="Artifact not found", details={"artifact_id": str(artifact_id)}
            )
        if await resolve_access(
            self.db, ctx, artifact, Perm.ARTIFACTS_VIEW, resource_type=ARTIFACT
        ):
            raise BadRequestError(
                message="You can open this page already.", details={"artifact_id": artifact.id}
            )
        request = await file_access_request(self.db, ctx, artifact, data.note)
        return ArtifactAccessRequested(
            id=request.id,
            kind=ShareRequestKind(request.kind),
            status=ShareRequestStatus(request.status),
            created_at=request.created_at,
            note=request.note,
        )

    async def approve(
        self, ctx: AuthContext, artifact_id: UUID, request_id: UUID
    ) -> ArtifactShareRequestRead:
        """Approve a pending request.

        - `version`: confirms that version's data, as :meth:`ArtifactService.confirm_data`
          does, and the request is settled with it.
        - `audience`: applies the visibility and the grants it asked for, each only where
          it still widens, as the approver; the sharing layer records the consent.
        - `access`: gives the requester the right to open the page (`read`), likewise.

        Raises:
            NotFoundError: The page or the request is not the caller's to see.
            AuthorizationError: The caller may not decide this request.
            ConcurrentChangeError: It was decided, voided or replaced in the meantime.
        """
        artifact, request = await self._pending(ctx, artifact_id, request_id)
        if request.kind == ShareRequestKind.VERSION.value:
            assert request.version_id is not None and request.query_fingerprint is not None
            await self._pages.confirm_data(
                ctx,
                artifact.id,
                request.version_id,
                ArtifactConsentCreate(fingerprint=request.query_fingerprint),
            )
            settled = await artifact_share_request_repo.get(
                self.db, request.id, artifact_id=artifact.id
            )
            assert settled is not None  # confirming the version settled it
            request = settled
        else:
            await self._apply(ctx, artifact, request)
            request = await decide(
                self.db,
                artifact,
                request,
                status=ShareRequestStatus.APPROVED,
                by_user_id=ctx.user_id,
            )
        [read] = await self._reads(ctx, artifact, [request])
        return read

    async def decline(
        self, ctx: AuthContext, artifact_id: UUID, request_id: UUID
    ) -> ArtifactShareRequestRead:
        """Decline a pending request. Nothing is shared.

        A declined `version` request marks that version declined: the page's audience
        keeps the version it was served, and a later republish asks again.

        Raises:
            NotFoundError: The page or the request is not the caller's to see.
            AuthorizationError: The caller may not decide this request.
            ConcurrentChangeError: It was decided, voided or replaced in the meantime.
        """
        artifact, request = await self._pending(ctx, artifact_id, request_id)
        if request.kind == ShareRequestKind.VERSION.value and request.version_id is not None:
            version = await artifact_repo.get_version(
                self.db, request.version_id, artifact_id=artifact.id
            )
            assert version is not None  # pruning the version took the request with it
            await artifact_repo.update_version(
                self.db,
                version=version,
                update_data={"consent_state": ConsentState.DECLINED.value},
            )
        request = await decide(
            self.db,
            artifact,
            request,
            status=ShareRequestStatus.DECLINED,
            by_user_id=ctx.user_id,
        )
        [read] = await self._reads(ctx, artifact, [request])
        return read

    async def review(
        self, ctx: AuthContext, artifact_id: UUID, version_id: UUID
    ) -> ArtifactVersionReview:
        """What a version's page queries read that the version the audience was served
        before it did not, binding by binding, each difference marked as widening or
        narrowing. For whoever may confirm the page's data.

        A binding whose tables nobody who may confirm it can read is left out, and
        `problem` says so.

        Raises:
            NotFoundError: The page is not the caller's to open, or the version is not
                one of its kept versions.
            AuthorizationError: The caller may not confirm the page's data.
        """
        artifact = await self._pages.get(ctx, artifact_id)
        ArtifactService.held_to_confirming(ctx, artifact)
        version = await self._pages.kept(artifact, version_id)
        before = await artifact_repo.served_before(self.db, artifact.id, version.number)
        now_bindings = _bindings(version)
        was_bindings = _bindings(before)
        problem, sources = await self._pages.tables_for_words(
            ctx, artifact, [*now_bindings, *was_bindings]
        )
        reviews, unchanged = diff_bindings(
            {
                b.name: view_of(b, sources)
                for b in was_bindings
                if all(table in sources for table in b.reach.tables)
            },
            {
                b.name: view_of(b, sources)
                for b in now_bindings
                if all(table in sources for table in b.reach.tables)
            },
        )
        return ArtifactVersionReview(
            version=ArtifactVersionRead.model_validate(version),
            compared_to=before.number if before is not None else None,
            publisher_name=(
                await name_of(self.db, version.published_by_user_id)
                if version.published_by_user_id is not None
                else None
            ),
            bindings=reviews,
            unchanged=unchanged,
            widens=any(review.effect == "widens" for review in reviews),
            problem=problem,
        )

    async def _pending(
        self, ctx: AuthContext, artifact_id: UUID, request_id: UUID
    ) -> tuple[Artifact, ArtifactShareRequest]:
        """The page and one of its requests, still pending, locked, for a caller who may
        decide it."""
        artifact = await self._pages.get(ctx, artifact_id)
        await artifact_repo.lock(self.db, artifact.id)
        request = await artifact_share_request_repo.get(
            self.db, request_id, artifact_id=artifact.id
        )
        if request is None:
            raise NotFoundError(
                message="Request not found", details={"request_id": str(request_id)}
            )
        can_edit = await self._can_edit(ctx, artifact)
        if not self._may_decide(ctx, artifact, request, can_edit=can_edit):
            raise AuthorizationError(
                message="You cannot decide this request.",
                details={"artifact_id": artifact.id, "request_id": request.id},
            )
        if request.status != ShareRequestStatus.PENDING.value:
            raise ConcurrentChangeError(
                message="This request was already decided, or no longer applies.",
                details={"request_id": request.id, "status": request.status},
            )
        return artifact, request

    async def _apply(
        self, ctx: AuthContext, artifact: Artifact, request: ArtifactShareRequest
    ) -> None:
        """Do what an `audience` or `access` request asks, as the approver, each part only
        while it still widens - the owner may have shared more since."""
        sharing = SharingService(self.db)
        asked = request.requested_subjects or {}
        people = [
            (UUID(item["user_id"]), GrantLevel(item["level"])) for item in asked.get("people", [])
        ]
        groups = [
            (UUID(item["group_id"]), GrantLevel(item["level"])) for item in asked.get("groups", [])
        ]
        if request.kind == ShareRequestKind.ACCESS.value:
            people = [(request.requester_user_id, GrantLevel.READ)]
        if request.requested_visibility is not None:
            visibility = Visibility(request.requested_visibility)
            if await widens(self.db, artifact, ShareChange(visibility=visibility)):
                moved = await sharing.set_visibility(
                    ctx, artifact, resource_type=ARTIFACT, visibility=visibility
                )
                assert not isinstance(moved, Deferred)  # the approver may decide for the owner
        for user_id, level in people:
            if await widens(self.db, artifact, ShareChange(subject_user_id=user_id, level=level)):
                granted = await sharing.share(
                    ctx, artifact, resource_type=ARTIFACT, subject_user_id=user_id, level=level
                )
                assert not isinstance(granted, Deferred)
        for group_id, level in groups:
            if await widens(self.db, artifact, ShareChange(subject_group_id=group_id, level=level)):
                granted = await sharing.share_with_group(
                    ctx, artifact, resource_type=ARTIFACT, group_id=group_id, level=level
                )
                assert not isinstance(granted, Deferred)

    async def _can_edit(self, ctx: AuthContext, artifact: Artifact) -> bool:
        return await resolve_access(
            self.db, ctx, artifact, Perm.ARTIFACTS_EDIT, resource_type=ARTIFACT
        )

    @staticmethod
    def _may_decide(
        ctx: AuthContext,
        artifact: Artifact,
        request: ArtifactShareRequest,
        *,
        can_edit: bool,
    ) -> bool:
        """Whether `ctx` decides `request`: the page's owner or an Owner or Admin for them,
        and for access to a page that reads no data, any editor."""
        if may_confirm(ctx, artifact):
            return True
        plain_access = (
            request.kind == ShareRequestKind.ACCESS.value and request.query_fingerprint is None
        )
        return plain_access and can_edit and as_themselves(ctx)

    async def _reads(
        self,
        ctx: AuthContext,
        artifact: Artifact,
        requests: Sequence[ArtifactShareRequest],
    ) -> list[ArtifactShareRequestRead]:
        """The requests with the names to show them by, resolved in a few queries."""
        can_edit = await self._can_edit(ctx, artifact)
        versions = {
            version.id: version.number
            for version in await artifact_repo.list_versions(self.db, artifact.id)
        }
        user_ids: set[UUID] = set()
        group_ids: set[UUID] = set()
        for request in requests:
            asked = request.requested_subjects or {}
            user_ids.update(UUID(item["user_id"]) for item in asked.get("people", []))
            group_ids.update(UUID(item["group_id"]) for item in asked.get("groups", []))
        emails = await member_repo.get_emails_for_users(
            self.db, organization_id=artifact.organization_id, user_ids=sorted(user_ids)
        )
        group_names = await group_repo.get_names(
            self.db, organization_id=artifact.organization_id, group_ids=sorted(group_ids)
        )
        names = {
            user_id: await name_of(self.db, user_id)
            for user_id in dict.fromkeys(request.requester_user_id for request in requests)
        }
        return [
            ArtifactShareRequestRead(
                id=request.id,
                artifact_id=request.artifact_id,
                kind=ShareRequestKind(request.kind),
                status=ShareRequestStatus(request.status),
                requester_user_id=request.requester_user_id,
                requester_name=names[request.requester_user_id],
                version_id=request.version_id,
                version_number=versions.get(request.version_id) if request.version_id else None,
                query_fingerprint=request.query_fingerprint,
                requested_visibility=(
                    as_visibility(request.requested_visibility)
                    if request.requested_visibility
                    else None
                ),
                requested_subjects=self._subjects(request, emails, group_names),
                note=request.note,
                void_reason=VoidReason(request.void_reason) if request.void_reason else None,
                decided_by_user_id=request.decided_by_user_id,
                decided_at=request.decided_at,
                created_at=request.created_at,
                can_decide=request.status == ShareRequestStatus.PENDING.value
                and self._may_decide(ctx, artifact, request, can_edit=can_edit),
            )
            for request in requests
        ]

    @staticmethod
    def _subjects(
        request: ArtifactShareRequest,
        emails: dict[UUID, str | None],
        group_names: dict[UUID, str],
    ) -> list[ShareRequestSubject]:
        asked = request.requested_subjects or {}
        people = [
            ShareRequestSubject(
                level=item["level"],
                user_id=UUID(item["user_id"]),
                email=emails.get(UUID(item["user_id"])),
            )
            for item in asked.get("people", [])
        ]
        groups = [
            ShareRequestSubject(
                level=item["level"],
                group_id=UUID(item["group_id"]),
                group_name=group_names.get(UUID(item["group_id"])),
            )
            for item in asked.get("groups", [])
        ]
        return people + groups

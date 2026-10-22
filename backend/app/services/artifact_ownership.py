"""Who owns a page, and handing it to someone else.

The owner (`owner_user_id`) is the page's single data owner: a bound page's data is
read with their access and only their consent shares it (see
:mod:`app.services.artifact_consent`). Ownership therefore changes only by a
deliberate act, never by a claim: the owner hands the page to an active member of its
organization, or an Owner or Admin - `artifacts:edit` at scope `ALL` - reassigns any
page, one whose owner is gone included. Both as themselves, and neither by a grant to
edit the page, which is no authority over whose data it reads.

The switch is immediate, with no acceptance step. Every switch also voids every consent
given so far (`consent_withdrawn_at`), so handing a page back never revives what its
earlier owner confirmed: the audience keeps the page and its bindings wait for the new
owner to confirm.

The generic sharing layer reaches this module through :class:`ArtifactSharingGuard`,
registered for the `artifact` resource type when the module is imported.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm, Scope
from app.db.models.artifact import Artifact
from app.db.models.artifact_share_request import VoidReason
from app.db.models.resource_grant import GrantLevel, Visibility
from app.repositories import artifact_repo, group_repo, member_repo, resource_grant_repo, user_repo
from app.services.access import ARTIFACT, OwnedResource
from app.services.artifact_consent import (
    EDIT_DATA_GROUP_WORDING,
    EDIT_DATA_PERSON_WORDING,
    EDIT_DATA_TEXTS,
    as_themselves,
    may_grant_edit_data,
)
from app.services.artifact_public_data import PublicDataVoid, void_public_data
from app.services.artifact_requests import held_level, name_of, void_all
from app.services.notifications import NotificationService
from app.services.sharing import Deferred, ShareChange, register_sharing_guard


def may_change_owner(ctx: AuthContext, artifact: Artifact) -> bool:
    """Whether `ctx` may hand the page to someone else: the owner, or `artifacts:edit` at
    scope `ALL` (any page, an owner-less one included) - each as themselves.

    A role-scope check, not `resolve_access`: a grant to edit the page does not pass.
    """
    if not as_themselves(ctx):
        return False
    return ctx.user_id == artifact.owner_user_id or ctx.scope_for(Perm.ARTIFACTS_EDIT) is Scope.ALL


def require_may_change_owner(ctx: AuthContext, artifact: Artifact) -> None:
    """Raise unless :func:`may_change_owner`."""
    if not may_change_owner(ctx, artifact):
        raise AuthorizationError(
            message=(
                "Only the page's owner, or an Owner or Admin, signed in as themselves, can "
                "change its owner."
            ),
            details={"artifact_id": str(artifact.id)},
        )


async def _name_of(db: AsyncSession, user_id: UUID) -> str:
    user = await user_repo.get_by_id(db, user_id)
    assert user is not None  # a member, or the caller
    return user.full_name or user.email


async def change_owner(
    db: AsyncSession, ctx: AuthContext, artifact: Artifact, *, new_owner_user_id: UUID
) -> Artifact:
    """Make `new_owner_user_id` the page's owner. The caller has been held to
    :func:`require_may_change_owner`.

    Auto-consent goes back off - it was the old owner's call - and every consent given
    so far is voided for good, so the audience keeps the page and its data waits for the
    new owner. Audited `artifact.owner_changed`; the old and the new owner are notified,
    the caller never.

    The caller's right is checked again on the locked row: a concurrent switch may have
    made someone else the owner since the caller was held to it.

    Every `edit_data` grant on the page drops to `edit`: the standing consent to an
    editor's republishes was the old owner's to give.

    Raises:
        AuthorizationError: The caller may no longer change the page's owner.
        BadRequestError: The new owner is the owner already, or not an active member of
            the page's organization.
    """
    await artifact_repo.lock(db, artifact.id)
    require_may_change_owner(ctx, artifact)
    if new_owner_user_id == artifact.owner_user_id:
        raise refused_field("user_id", "That member already owns this page.")
    member = await member_repo.get_active(
        db, organization_id=artifact.organization_id, user_id=new_owner_user_id
    )
    if member is None:
        raise refused_field(
            "user_id", "The new owner must be an active member of this organization."
        )
    previous = artifact.owner_user_id
    auto_consent_was_on = artifact.auto_consent
    artifact = await artifact_repo.update(
        db,
        artifact=artifact,
        update_data={
            "owner_user_id": new_owner_user_id,
            "auto_consent": False,
            "consent_withdrawn_at": datetime.now(UTC),
        },
    )
    await void_all(db, artifact, VoidReason.OWNER_CHANGED)
    artifact = await void_public_data(db, ctx, artifact, PublicDataVoid.OWNER_CHANGED)
    lowered = await resource_grant_repo.lower_edit_data(
        db, organization_id=artifact.organization_id, resource_id=artifact.id
    )
    await record_audit(
        db,
        actor_user_id=ctx.subject_id,
        organization_id=ctx.organization_id,
        action="artifact.owner_changed",
        target_type="artifact",
        target_id=str(artifact.id),
        details={
            "from": str(previous) if previous is not None else None,
            "to": str(new_owner_user_id),
            "by": str(ctx.user_id),
            "auto_consent_was_on": auto_consent_was_on,
            "edit_data_lowered": lowered,
        },
    )
    assert ctx.user_id is not None  # `as_themselves` held
    await NotificationService(db).artifact_owner_changed(
        artifact,
        previous_owner_id=previous,
        new_owner_id=new_owner_user_id,
        by_user_id=ctx.user_id,
        by_name=await _name_of(db, ctx.user_id),
        new_owner_name=await _name_of(db, new_owner_user_id),
    )
    return artifact


async def _confirm_edit_data(
    db: AsyncSession, ctx: AuthContext, artifact: Artifact, change: ShareChange
) -> None:
    """Hold a grant of `edit_data` to the owner's (or an Owner's or Admin's) own, confirmed
    act, and record the text they confirmed. A grant that is `edit_data` already needs
    neither; lowering one never reaches here.

    Raises:
        AuthorizationError: The caller is not the owner or an admin, as themselves.
        BadRequestError: The text for this subject was not confirmed.
    """
    if await held_level(db, artifact, change) is GrantLevel.EDIT_DATA:
        return
    if not may_grant_edit_data(ctx, artifact):
        raise AuthorizationError(
            message=(
                "Only the page's owner, or an Owner or Admin, signed in as themselves, can "
                "give someone the right to change its data."
            ),
            details={"artifact_id": str(artifact.id)},
        )
    if change.subject_group_id is not None:
        wording = EDIT_DATA_GROUP_WORDING
        group = await group_repo.get(
            db, organization_id=artifact.organization_id, group_id=change.subject_group_id
        )
        assert group is not None  # the sharing service checked it is the organization's
        name = group.name
    else:
        wording = EDIT_DATA_PERSON_WORDING
        assert change.subject_user_id is not None  # a level is for a person or a group
        name = await name_of(db, change.subject_user_id)
    if change.confirmed != wording:
        raise refused_field(
            "confirmed", "Confirm what this level allows before giving it to anyone."
        )
    await record_audit(
        db,
        actor_user_id=ctx.subject_id,
        organization_id=artifact.organization_id,
        action="artifact.edit_data_granted",
        target_type="artifact",
        target_id=str(artifact.id),
        details={
            "subject_user_id": str(change.subject_user_id) if change.subject_user_id else None,
            "subject_group_id": str(change.subject_group_id) if change.subject_group_id else None,
            "wording": wording,
            "wording_text": EDIT_DATA_TEXTS[wording].format(name=name),
        },
    )


class ArtifactSharingGuard:
    """What the generic sharing layer asks of a page before it acts - see
    :class:`app.services.sharing.SharingGuard`."""

    async def before_visibility(
        self, db: AsyncSession, ctx: AuthContext, resource: OwnedResource, visibility: Visibility
    ) -> None:
        """Adopting an owner-less page - making it private - is an ownership change, so it
        is `artifacts:edit` at scope `ALL`, as themselves, and nobody else's, and only a
        member of the organization can own a page."""
        assert isinstance(resource, Artifact)
        if visibility is Visibility.PRIVATE and resource.owner_user_id is None:
            require_may_change_owner(ctx, resource)

    async def before_share(
        self, db: AsyncSession, ctx: AuthContext, resource: OwnedResource, change: ShareChange
    ) -> Deferred | None:
        """Widening who opens a page that reads data is the owner's call, or an Owner's or
        Admin's for them; anyone else who may edit it files a request instead. Narrowing,
        and any change to a page that reads none, is left to every editor - unless the
        page is archived, which refuses widening altogether.

        Granting or raising to `edit_data` is the owner's (or an Owner's or Admin's), as
        themselves, with the text confirmed: :func:`_confirm_edit_data`. Lowering it is every
        editor's.

        See :meth:`app.services.artifact_request_service.ArtifactRequestService.widen`.
        """
        # Imported here: the service imports the page service, which imports this module.
        from app.services.artifact_request_service import ArtifactRequestService

        assert isinstance(resource, Artifact)
        if change.level is GrantLevel.EDIT_DATA:
            await _confirm_edit_data(db, ctx, resource, change)
        return await ArtifactRequestService(db).widen(ctx, resource, change)

    async def adopt(self, db: AsyncSession, ctx: AuthContext, resource: OwnedResource) -> None:
        """The caller becomes the owner, with every effect of any other ownership change."""
        assert isinstance(resource, Artifact) and ctx.user_id is not None
        if (
            await member_repo.get_active(
                db, organization_id=resource.organization_id, user_id=ctx.user_id
            )
            is None
        ):
            # No `user_id` field in this request: a field error would mark nothing.
            raise BadRequestError(
                message="Only a member of this organization can own a page.",
                details={"artifact_id": str(resource.id)},
            )
        await change_owner(db, ctx, resource, new_owner_user_id=ctx.user_id)


register_sharing_guard(ARTIFACT, ArtifactSharingGuard())

"""Sharing service - owner, visibility and per-member grants on one resource.

Only someone who can already edit a resource may change who else reaches it,
which keeps the rule simple: sharing is an edit. Every change is audited,
because "who gave whom access to what" is the first question asked after an
incident and the last thing anyone remembers.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.repositories import member_repo, resource_grant_repo
from app.services.access import OwnedResource, ResourceType, resolve_access


class SharingService:
    """Read and change the sharing state of any owned resource."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _require_edit(
        self,
        ctx: AuthContext,
        resource: OwnedResource,
        resource_type: ResourceType,
    ) -> None:
        allowed = await resolve_access(
            self.db, ctx, resource, resource_type.edit, resource_type=resource_type
        )
        if not allowed:
            raise AuthorizationError(
                message="You cannot change sharing for this resource",
                details={"resource_type": resource_type.key, "resource_id": str(resource.id)},
            )

    async def get_sharing(
        self,
        ctx: AuthContext,
        resource: OwnedResource,
        *,
        resource_type: ResourceType,
    ) -> tuple[list[ResourceGrant], dict[UUID, str | None]]:
        """Grants on a resource plus a user-id → email map for display.

        Seeing the share list requires being able to view the resource; the
        email lookup is a convenience so the UI does not fan out one request
        per grant.
        """
        allowed = await resolve_access(
            self.db, ctx, resource, resource_type.view, resource_type=resource_type
        )
        if not allowed:
            raise NotFoundError(
                message="Resource not found",
                details={"resource_id": str(resource.id)},
            )
        grants = await resource_grant_repo.list_for_resource(
            self.db,
            organization_id=ctx.organization_id,
            resource_type=resource_type.key,
            resource_id=resource.id,
        )
        emails = await member_repo.get_emails_for_users(
            self.db,
            organization_id=ctx.organization_id,
            user_ids=[grant.subject_user_id for grant in grants],
        )
        return grants, emails

    async def share(
        self,
        ctx: AuthContext,
        resource: OwnedResource,
        *,
        resource_type: ResourceType,
        subject_user_id: UUID,
        level: GrantLevel,
    ) -> ResourceGrant:
        """Grant a member access to one resource.

        Raises:
            BadRequestError: If the subject is not a member of this
                organization. Sharing across tenants is never allowed, and a
                grant row pointing at an outsider would be a latent hole.
        """
        await self._require_edit(ctx, resource, resource_type)

        membership = await member_repo.get(
            self.db, organization_id=ctx.organization_id, user_id=subject_user_id
        )
        if membership is None:
            raise BadRequestError(
                message="Cannot share with someone outside this organization",
                details={"subject_user_id": str(subject_user_id)},
            )

        grant = await resource_grant_repo.upsert(
            self.db,
            organization_id=ctx.organization_id,
            subject_user_id=subject_user_id,
            resource_type=resource_type.key,
            resource_id=resource.id,
            level=level,
            created_by_user_id=ctx.user_id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="resource.share",
            target_type=resource_type.key,
            target_id=str(resource.id),
            details={"subject_user_id": str(subject_user_id), "level": level.value},
        )
        return grant

    async def revoke(
        self,
        ctx: AuthContext,
        resource: OwnedResource,
        *,
        resource_type: ResourceType,
        subject_user_id: UUID,
    ) -> None:
        await self._require_edit(ctx, resource, resource_type)
        removed = await resource_grant_repo.revoke(
            self.db,
            organization_id=ctx.organization_id,
            subject_user_id=subject_user_id,
            resource_type=resource_type.key,
            resource_id=resource.id,
        )
        if not removed:
            raise NotFoundError(
                message="Share not found",
                details={"subject_user_id": str(subject_user_id)},
            )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="resource.unshare",
            target_type=resource_type.key,
            target_id=str(resource.id),
            details={"subject_user_id": str(subject_user_id)},
        )

    async def set_visibility(
        self,
        ctx: AuthContext,
        resource: OwnedResource,
        *,
        resource_type: ResourceType,
        visibility: Visibility,
    ) -> OwnedResource:
        """Change how widely a resource is exposed inside its organization.

        Going private on a row nobody owns makes the caller its owner. "Private"
        means private *to somebody*, and an unowned private row is one nobody can
        see and nobody can delete - which the database refuses outright
        (`ck_secret_private_needs_owner`), so the alternative is an
        IntegrityError arriving as a 500.

        Adopting rather than refusing, because refusing has nowhere to send
        anyone: nothing in this product transfers ownership, so "give it an owner
        first" would be an instruction with no way to follow it. It grants
        nothing new either - the caller already passed the edit check, and
        someone who can edit a key can rotate or delete it, which is strictly
        more than taking it over. It is recorded as its own audit entry, because
        "who owns this now" is not something a visibility change should quietly
        answer.
        """
        await self._require_edit(ctx, resource, resource_type)
        # `ctx.user_id` is not None past `_require_edit`: `resolve_access`
        # refuses a subject-less context outright, so there is always somebody
        # to become the owner here.
        adopted = visibility is Visibility.PRIVATE and resource.owner_user_id is None
        if adopted:
            resource.owner_user_id = ctx.user_id
        previous = resource.visibility
        resource.visibility = visibility.value
        self.db.add(resource)
        await self.db.flush()
        if adopted:
            await record_audit(
                self.db,
                actor_user_id=ctx.subject_id,
                organization_id=ctx.organization_id,
                action="resource.owner_claimed",
                target_type=resource_type.key,
                target_id=str(resource.id),
                details={"owner_user_id": str(resource.owner_user_id)},
            )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="resource.visibility_changed",
            target_type=resource_type.key,
            target_id=str(resource.id),
            details={"from": previous, "to": visibility.value},
        )
        return resource

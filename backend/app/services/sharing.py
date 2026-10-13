"""Sharing service - owner, visibility and grants to members or groups on one resource.

Only someone who can already edit a resource may change who else reaches it,
which keeps the rule simple: sharing is an edit. Every change is audited,
because "who gave whom access to what" is the first question asked after an
incident and the last thing anyone remembers.
"""

from __future__ import annotations

from typing import NamedTuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.db.models.group import Group
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.repositories import group_repo, member_repo, resource_grant_repo
from app.services.access import OwnedResource, ResourceType, resolve_access
from app.services.notifications import NotificationService


class SharingState(NamedTuple):
    """Who a resource is shared with, and the names to show for them."""

    grants: list[ResourceGrant]
    emails: dict[UUID, str | None]
    group_names: dict[UUID, str]


_CONSOLE_PATHS = {
    "agent": "/agents/{id}",
    "collection": "/rag/{id}",
    "skill": "/skills",
    "context": "/context",
    "secret": "/vault",
    "artifact": "/apps/{id}",
    "mcp_connection": "/mcp-servers",
}
"""Where the console opens a shared resource of each kind."""


def _shown_name(resource: OwnedResource) -> str:
    """What a notification calls a resource: an app by its title, the rest by name."""
    return str(getattr(resource, "title", None) or getattr(resource, "name", None) or resource.id)


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
    ) -> SharingState:
        """Grants on a resource, with the addresses and group names to display them by.

        Seeing the share list requires being able to view the resource; the
        name lookups are a convenience so the UI does not fan out one request
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
            user_ids=[grant.subject_user_id for grant in grants if grant.subject_user_id],
        )
        group_names = await group_repo.get_names(
            self.db,
            organization_id=ctx.organization_id,
            group_ids=[grant.subject_group_id for grant in grants if grant.subject_group_id],
        )
        return SharingState(grants=grants, emails=emails, group_names=group_names)

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

    async def share_with_group(
        self,
        ctx: AuthContext,
        resource: OwnedResource,
        *,
        resource_type: ResourceType,
        group_id: UUID,
        level: GrantLevel,
    ) -> ResourceGrant:
        """Grant every member of a group access to one resource.

        The grant reaches whoever is in the group when access is resolved, so
        people joining later reach the resource and people leaving stop - there
        is no per-person row to keep in step.

        Raises:
            BadRequestError: If the group is not one of this organization's. The
                same refusal as sharing with an outsider, for the same reason: a
                grant naming another tenant's group would be a latent hole.
        """
        await self._require_edit(ctx, resource, resource_type)

        group = await group_repo.get(
            self.db, organization_id=ctx.organization_id, group_id=group_id
        )
        if group is None:
            raise BadRequestError(
                message="Cannot share with a group outside this organization",
                details={"subject_group_id": str(group_id)},
            )

        grant = await resource_grant_repo.upsert_for_group(
            self.db,
            organization_id=ctx.organization_id,
            subject_group_id=group.id,
            resource_type=resource_type.key,
            resource_id=resource.id,
            level=level,
            created_by_user_id=ctx.user_id,
        )
        await self._tell_the_group(ctx, resource, resource_type, group)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="resource.share",
            target_type=resource_type.key,
            target_id=str(resource.id),
            details={"subject_group_id": str(group.id), "level": level.value},
        )
        return grant

    async def _tell_the_group(
        self, ctx: AuthContext, resource: OwnedResource, resource_type: ResourceType, group: Group
    ) -> None:
        """Let a group's members know something was shared with them (#2072).

        Everyone in it but whoever shared it, each told in their inbox and, where
        they asked for it, by email.
        """
        members = await group_repo.list_members(self.db, group.id)
        recipients = [
            member.user_id for member, _email, _name in members if member.user_id != ctx.user_id
        ]
        await NotificationService(self.db).resource_shared(
            recipients=recipients,
            organization_id=ctx.organization_id,
            resource_kind=resource_type.key,
            resource_id=resource.id,
            name=_shown_name(resource),
            path=_CONSOLE_PATHS[resource_type.key].format(id=resource.id),
            group_name=group.name,
            actor_user_id=ctx.user_id,
        )

    async def restrict_to(
        self,
        ctx: AuthContext,
        resource: OwnedResource,
        *,
        resource_type: ResourceType,
        group_ids: list[UUID],
        user_ids: list[UUID],
    ) -> None:
        """Share a resource just created with the groups and people its creator chose.

        The other half of `AudienceChoice` (#2072): the resource was created private,
        and each group and person gets a `use` grant - they find it, run it and
        attach it. The creator owns it already, so naming themselves adds nothing.
        Called inside the creating request, so a refusal here takes the new row with
        it rather than leaving it visible to nobody but its creator.

        Raises:
            BadRequestError: Naming `group_ids` or `user_ids`, when one is not this
                organization's.
        """
        groups = list(dict.fromkeys(group_ids))
        people = [user for user in dict.fromkeys(user_ids) if user != ctx.user_id]
        for group_id in groups:
            if (
                await group_repo.get(
                    self.db, organization_id=ctx.organization_id, group_id=group_id
                )
                is None
            ):
                raise refused_field("group_ids", "Choose groups from this organization.")
        for user_id in people:
            if (
                await member_repo.get(self.db, organization_id=ctx.organization_id, user_id=user_id)
                is None
            ):
                raise refused_field("user_ids", "Choose people from this organization.")
        for group_id in groups:
            await self.share_with_group(
                ctx, resource, resource_type=resource_type, group_id=group_id, level=GrantLevel.USE
            )
        for user_id in people:
            await self.share(
                ctx,
                resource,
                resource_type=resource_type,
                subject_user_id=user_id,
                level=GrantLevel.USE,
            )

    async def revoke_group(
        self,
        ctx: AuthContext,
        resource: OwnedResource,
        *,
        resource_type: ResourceType,
        group_id: UUID,
    ) -> None:
        """Stop sharing a resource with a group."""
        await self._require_edit(ctx, resource, resource_type)
        removed = await resource_grant_repo.revoke_for_group(
            self.db,
            organization_id=ctx.organization_id,
            subject_group_id=group_id,
            resource_type=resource_type.key,
            resource_id=resource.id,
        )
        if not removed:
            raise NotFoundError(
                message="Share not found",
                details={"subject_group_id": str(group_id)},
            )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="resource.unshare",
            target_type=resource_type.key,
            target_id=str(resource.id),
            details={"subject_group_id": str(group_id)},
        )

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

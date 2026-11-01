"""Sharing service - owner, visibility and grants to members or groups on one resource.

Only someone who can already edit a resource may change who else reaches it,
which keeps the rule simple: sharing is an edit. Every change is audited,
because "who gave whom access to what" is the first question asked after an
incident and the last thing anyone remembers.
"""

from dataclasses import dataclass
from typing import NamedTuple, Protocol
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


@dataclass(frozen=True)
class ShareChange:
    """What one sharing call is about to do to a resource: set its visibility, or give one
    person or one group a level on it."""

    visibility: Visibility | None = None
    subject_user_id: UUID | None = None
    subject_group_id: UUID | None = None
    level: GrantLevel | None = None
    confirmed: str | None = None
    """The id of the text the caller confirmed to grant `edit_data`."""


@dataclass(frozen=True)
class Deferred:
    """A change a guard did not apply, because it filed a request for someone else to
    decide instead. The route answers with these two."""

    request_id: UUID
    waiting_for: str | None
    """Who decides it, by name; `None` when it has nobody left to."""


class SharingGuard(Protocol):
    """What one resource type asks before sharing acts on a row of it.

    The service is generic, so a rule that holds for one type - who may adopt a page
    nobody owns - is registered by the service that owns the type
    (:func:`register_sharing_guard`) rather than written in here. A type with no guard
    behaves exactly as it always has. A guard raises to refuse; it runs after the
    caller has passed the edit check.
    """

    async def before_visibility(
        self,
        db: AsyncSession,
        ctx: AuthContext,
        resource: OwnedResource,
        visibility: Visibility,
    ) -> None:
        """Called before every visibility change."""

    async def before_share(
        self, db: AsyncSession, ctx: AuthContext, resource: OwnedResource, change: ShareChange
    ) -> Deferred | None:
        """Called before every change of visibility or grant, after `before_visibility`.

        Returns `None` to let the change be applied, :class:`Deferred` when the guard
        turned it into a request instead (nothing is applied), or raises to refuse."""

    async def adopt(self, db: AsyncSession, ctx: AuthContext, resource: OwnedResource) -> None:
        """Make the caller the owner of a row nobody owns, when its visibility is set to
        private - in place of the generic adoption, which a type that has ownership rules
        of its own must not get."""


_GUARDS: dict[str, SharingGuard] = {}


def register_sharing_guard(resource_type: ResourceType, guard: SharingGuard) -> None:
    """Install `guard` for `resource_type`, replacing any earlier one."""
    _GUARDS[resource_type.key] = guard


def _require_level_for(resource_type: ResourceType, level: GrantLevel) -> None:
    """`edit_data` is a page's level: nothing else has a data owner to consent for it."""
    if level is GrantLevel.EDIT_DATA and resource_type.key != "artifact":
        raise refused_field("level", "This level is for pages only.")


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
    "dataset": "/datasets/{id}",
    "mcp_connection": "/mcp-servers",
    "project": "/projects/{id}",
    "table": "/tables/{id}",
    "workflow": "/workflows/{id}",
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

    async def _ask_guard(
        self,
        ctx: AuthContext,
        resource: OwnedResource,
        resource_type: ResourceType,
        change: ShareChange,
    ) -> Deferred | None:
        guard = _GUARDS.get(resource_type.key)
        if guard is None:
            return None
        return await guard.before_share(self.db, ctx, resource, change)

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
        confirmed: str | None = None,
    ) -> ResourceGrant | Deferred:
        """Grant a member access to one resource.

        A resource type's guard may file a request instead of granting, and the
        :class:`Deferred` it returns is passed on with nothing applied.

        Raises:
            BadRequestError: If the subject is not a member of this
                organization. Sharing across tenants is never allowed, and a
                grant row pointing at an outsider would be a latent hole.
        """
        await self._require_edit(ctx, resource, resource_type)
        _require_level_for(resource_type, level)

        membership = await member_repo.get(
            self.db, organization_id=ctx.organization_id, user_id=subject_user_id
        )
        if membership is None:
            raise BadRequestError(
                message="Cannot share with someone outside this organization",
                details={"subject_user_id": str(subject_user_id)},
            )
        deferred = await self._ask_guard(
            ctx,
            resource,
            resource_type,
            ShareChange(subject_user_id=subject_user_id, level=level, confirmed=confirmed),
        )
        if deferred is not None:
            return deferred

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
        confirmed: str | None = None,
    ) -> ResourceGrant | Deferred:
        """Grant every member of a group access to one resource.

        Like :meth:`share`, a guard may turn it into a request.

        The grant reaches whoever is in the group when access is resolved, so
        people joining later reach the resource and people leaving stop - there
        is no per-person row to keep in step.

        Raises:
            BadRequestError: If the group is not one of this organization's. The
                same refusal as sharing with an outsider, for the same reason: a
                grant naming another tenant's group would be a latent hole.
        """
        await self._require_edit(ctx, resource, resource_type)
        _require_level_for(resource_type, level)

        group = await group_repo.get(
            self.db, organization_id=ctx.organization_id, group_id=group_id
        )
        if group is None:
            raise BadRequestError(
                message="Cannot share with a group outside this organization",
                details={"subject_group_id": str(group_id)},
            )
        deferred = await self._ask_guard(
            ctx,
            resource,
            resource_type,
            ShareChange(subject_group_id=group.id, level=level, confirmed=confirmed),
        )
        if deferred is not None:
            return deferred

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
    ) -> OwnedResource | Deferred:
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
        guard = _GUARDS.get(resource_type.key)
        if guard is not None:
            await guard.before_visibility(self.db, ctx, resource, visibility)
            deferred = await guard.before_share(
                self.db, ctx, resource, ShareChange(visibility=visibility)
            )
            if deferred is not None:
                return deferred
        # `ctx.user_id` is not None past `_require_edit`: `resolve_access`
        # refuses a subject-less context outright, so there is always somebody
        # to become the owner here.
        adopted = visibility is Visibility.PRIVATE and resource.owner_user_id is None
        if adopted and guard is not None:
            await guard.adopt(self.db, ctx, resource)
        elif adopted:
            resource.owner_user_id = ctx.user_id
        previous = resource.visibility
        resource.visibility = visibility.value
        self.db.add(resource)
        await self.db.flush()
        if adopted and guard is None:
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

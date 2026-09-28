"""Group service - named sets of an organization's members.

Any member may see the groups and who is in them, the way any member may list
the organization's members: a group is something they will be offered as a
sharing target, and a picker that hides who it reaches is a picker nobody can
use safely. Changing a group - creating, renaming, deleting, adding and removing
people - is `members:manage`, because deciding who reaches what a group was
granted is deciding membership, one level down.

A group carries no role and grants nothing by itself. Its whole effect is the
grants made to it, resolved in `resource_grant_repo`, so deleting one removes
exactly the access that was shared with it (the grants cascade with the row).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import Perm, assignable_roles, role_has
from app.db.models.group import Group, GroupMember
from app.db.models.organization import MembershipSource, OrganizationMember
from app.repositories import directory_mapping_repo, group_repo, member_repo
from app.schemas.group import GroupCreate, GroupUpdate


class GroupService:
    """List, create and change the groups of one organization."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _membership(self, organization_id: UUID, requester_id: UUID) -> OrganizationMember:
        """The requester's membership, or a refusal that reveals nothing.

        An outsider is told the organization does not exist, the same answer
        `MemberService.list_for_org` gives, so group routes cannot be used to
        learn which organization ids are real.
        """
        membership = await member_repo.get(
            self.db, organization_id=organization_id, user_id=requester_id
        )
        if membership is None:
            raise NotFoundError(
                message="Organization not found", details={"org_id": str(organization_id)}
            )
        return membership

    async def _require_manage(self, organization_id: UUID, requester_id: UUID) -> None:
        membership = await self._membership(organization_id, requester_id)
        if not role_has(membership.role, Perm.MEMBERS_MANAGE):
            raise AuthorizationError(message="You cannot manage groups in this organization")

    async def _group(self, organization_id: UUID, group_id: UUID) -> Group:
        group = await group_repo.get(self.db, organization_id=organization_id, group_id=group_id)
        if group is None:
            raise NotFoundError(message="Group not found", details={"group_id": str(group_id)})
        return group

    async def list_groups(
        self, organization_id: UUID, requester_id: UUID
    ) -> list[tuple[Group, int]]:
        """Every group in the organization with its member count. Any member may call this."""
        await self._membership(organization_id, requester_id)
        return await group_repo.list_for_org(self.db, organization_id)

    async def create(self, organization_id: UUID, requester_id: UUID, data: GroupCreate) -> Group:
        """Create a group.

        Raises:
            AlreadyExistsError: The organization already has a group of that name.
                Checked first for the common case and enforced by
                `uq_group_org_name` for the race, inside a savepoint so the loser
                gets this 409 rather than an `IntegrityError` as a 500.
        """
        await self._require_manage(organization_id, requester_id)
        await self._refuse_taken_name(organization_id, data.name)
        try:
            async with self.db.begin_nested():
                group = await group_repo.create(
                    self.db,
                    organization_id=organization_id,
                    name=data.name,
                    description=data.description,
                    created_by_user_id=requester_id,
                )
        except IntegrityError as exc:
            raise AlreadyExistsError(
                message="A group with this name already exists", details={"name": data.name}
            ) from exc
        await record_audit(
            self.db,
            actor_user_id=requester_id,
            organization_id=organization_id,
            action="group.created",
            target_type="group",
            target_id=str(group.id),
            details={"name": group.name},
        )
        return group

    async def update(
        self, organization_id: UUID, group_id: UUID, requester_id: UUID, data: GroupUpdate
    ) -> tuple[Group, int]:
        """Rename a group or change its description; returns it with its member count."""
        await self._require_manage(organization_id, requester_id)
        group = await self._group(organization_id, group_id)
        name = data.name if data.name is not None else group.name
        # A description sent as null clears it; one not sent at all is left alone.
        sent = data.model_fields_set
        description = data.description if "description" in sent else group.description
        if name != group.name:
            await self._refuse_taken_name(organization_id, name)
        try:
            async with self.db.begin_nested():
                updated = await group_repo.update(
                    self.db, group, name=name, description=description
                )
        except IntegrityError as exc:
            raise AlreadyExistsError(
                message="A group with this name already exists", details={"name": name}
            ) from exc
        await record_audit(
            self.db,
            actor_user_id=requester_id,
            organization_id=organization_id,
            action="group.updated",
            target_type="group",
            target_id=str(group.id),
            details={"fields": sorted(sent)},
        )
        return updated, await group_repo.count_members(self.db, updated.id)

    async def delete(self, organization_id: UUID, group_id: UUID, requester_id: UUID) -> None:
        """Delete a group, and with it every grant made to it and every mapping naming it.

        Raises:
            AuthorizationError: A directory mapping naming the group maps to a
                role the requester's does not outrank. The mapping cascades with
                the group, and deleting it demotes everybody it placed - which
                `DirectoryMappingService.delete` refuses this requester, so
                deleting the group must not do it by the back door.
        """
        membership = await self._membership(organization_id, requester_id)
        if not role_has(membership.role, Perm.MEMBERS_MANAGE):
            raise AuthorizationError(message="You cannot manage groups in this organization")
        group = await self._group(organization_id, group_id)
        ceiling = assignable_roles(membership.role)
        for mapping in await directory_mapping_repo.list_for_group(self.db, group_id=group.id):
            if mapping.role not in ceiling:
                raise AuthorizationError(
                    message=(
                        "A directory mapping to a role your own does not outrank places people "
                        "in this group; it has to be removed by someone who outranks it first"
                    ),
                    details={"role": mapping.role},
                )
        name = group.name
        await group_repo.delete_group(self.db, group)
        await record_audit(
            self.db,
            actor_user_id=requester_id,
            organization_id=organization_id,
            action="group.deleted",
            target_type="group",
            target_id=str(group_id),
            details={"name": name},
        )

    async def list_members(
        self, organization_id: UUID, group_id: UUID, requester_id: UUID
    ) -> list[tuple[GroupMember, str, str | None]]:
        """Who is in one group. Any member of the organization may call this."""
        await self._membership(organization_id, requester_id)
        group = await self._group(organization_id, group_id)
        return await group_repo.list_members(self.db, group.id)

    async def add_member(
        self, organization_id: UUID, group_id: UUID, user_id: UUID, requester_id: UUID
    ) -> tuple[GroupMember, str, str | None]:
        """Put a member of the organization in a group, by hand.

        Idempotent for someone already added by hand. Someone the directory put
        there becomes a manual member: an administrator adding them is a
        decision that should outlive the directory taking them out again.

        Raises:
            BadRequestError: The person is not a member of this organization. A
                group reaches what was shared with it, and an outsider in one
                would reach this organization's resources.
        """
        await self._require_manage(organization_id, requester_id)
        group = await self._group(organization_id, group_id)
        if await member_repo.get(self.db, organization_id=organization_id, user_id=user_id) is None:
            raise BadRequestError(
                message="Only members of this organization can be added to a group",
                details={"user_id": str(user_id)},
            )
        existing = await group_repo.get_member(self.db, group_id=group.id, user_id=user_id)
        if existing is not None:
            if existing.source != MembershipSource.MANUAL:
                previous = existing.source
                await group_repo.set_member_source(
                    self.db, existing, source=MembershipSource.MANUAL
                )
                # A takeover is a decision - the access now outlives the
                # directory taking the person out - so it is recorded as one.
                await record_audit(
                    self.db,
                    actor_user_id=requester_id,
                    organization_id=organization_id,
                    action="group.member_taken_over",
                    target_type="group",
                    target_id=str(group.id),
                    details={"user_id": str(user_id), "source_was": previous},
                )
            return await self._member_row(group.id, user_id)
        try:
            async with self.db.begin_nested():
                await group_repo.add_member(
                    self.db,
                    group_id=group.id,
                    user_id=user_id,
                    source=MembershipSource.MANUAL,
                    added_by_user_id=requester_id,
                )
        except IntegrityError as exc:
            raise AlreadyExistsError(
                message="Already a member of this group", details={"user_id": str(user_id)}
            ) from exc
        await record_audit(
            self.db,
            actor_user_id=requester_id,
            organization_id=organization_id,
            action="group.member_added",
            target_type="group",
            target_id=str(group.id),
            details={"user_id": str(user_id)},
        )
        return await self._member_row(group.id, user_id)

    async def remove_member(
        self, organization_id: UUID, group_id: UUID, user_id: UUID, requester_id: UUID
    ) -> None:
        """Take somebody out of a group, whoever put them there."""
        await self._require_manage(organization_id, requester_id)
        group = await self._group(organization_id, group_id)
        member = await group_repo.get_member(self.db, group_id=group.id, user_id=user_id)
        if member is None:
            raise NotFoundError(
                message="Not a member of this group", details={"user_id": str(user_id)}
            )
        await group_repo.remove_member(self.db, member)
        await record_audit(
            self.db,
            actor_user_id=requester_id,
            organization_id=organization_id,
            action="group.member_removed",
            target_type="group",
            target_id=str(group.id),
            details={"user_id": str(user_id)},
        )

    async def _refuse_taken_name(self, organization_id: UUID, name: str) -> None:
        if await group_repo.get_by_name(self.db, organization_id=organization_id, name=name):
            raise AlreadyExistsError(
                message="A group with this name already exists", details={"name": name}
            )

    async def _member_row(
        self, group_id: UUID, user_id: UUID
    ) -> tuple[GroupMember, str, str | None]:
        """The membership as a listing shows it, read back after a write."""
        row = await group_repo.get_member_row(self.db, group_id=group_id, user_id=user_id)
        if row is None:
            raise NotFoundError(
                message="Not a member of this group", details={"user_id": str(user_id)}
            )
        return row

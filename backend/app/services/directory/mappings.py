"""Directory group mappings - an organization deciding what a directory group means to it.

A mapping admits people and hands them a role, so it takes both authorities
that doing those things by hand takes: `members:manage` to add people and
`roles:manage` to give them a role. The role is bounded the way an invitation's
is - only one the requester's own strictly outranks (`assignable_roles`) - so a
mapping is never a way to hand out more than the person who wrote it could.

Reading the mappings takes `members:manage`: they say which directory groups
reach the organization, which is the membership policy, not something every
member needs.
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
from app.db.models.directory_mapping import DirectoryGroupMapping
from app.db.models.organization import OrganizationMember
from app.repositories import directory_mapping_repo, group_repo, member_repo, organization_repo
from app.schemas.directory import DirectoryMappingCreate


class DirectoryMappingService:
    """List, create and delete one organization's directory group mappings."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _requester(self, organization_id: UUID, requester_id: UUID) -> OrganizationMember:
        membership = await member_repo.get(
            self.db, organization_id=organization_id, user_id=requester_id
        )
        if membership is None:
            raise NotFoundError(
                message="Organization not found", details={"org_id": str(organization_id)}
            )
        if not role_has(membership.role, Perm.MEMBERS_MANAGE):
            raise AuthorizationError(message="You cannot manage directory mappings here")
        return membership

    async def list_mappings(
        self, organization_id: UUID, requester_id: UUID
    ) -> list[tuple[DirectoryGroupMapping, str | None]]:
        """Every mapping with the name of the group it places people in."""
        await self._requester(organization_id, requester_id)
        mappings = await directory_mapping_repo.list_for_org(self.db, organization_id)
        names = await group_repo.get_names(
            self.db,
            organization_id=organization_id,
            group_ids=[mapping.group_id for mapping in mappings if mapping.group_id],
        )
        return [
            (mapping, names.get(mapping.group_id) if mapping.group_id else None)
            for mapping in mappings
        ]

    async def create(
        self, organization_id: UUID, requester_id: UUID, data: DirectoryMappingCreate
    ) -> tuple[DirectoryGroupMapping, str | None]:
        """Map a directory group to a role, and optionally a group, here.

        Raises:
            AuthorizationError: The requester lacks `roles:manage`, or offered a
                role their own does not strictly outrank.
            BadRequestError: The organization is personal, or the group is not
                one of its own.
            AlreadyExistsError: The directory group is already mapped here.
        """
        requester = await self._requester(organization_id, requester_id)
        if not role_has(requester.role, Perm.ROLES_MANAGE):
            raise AuthorizationError(message="You cannot assign roles in this organization")
        if data.role not in assignable_roles(requester.role):
            raise AuthorizationError(
                message="You cannot map a directory group to a role your own does not outrank",
                details={"role": data.role},
            )
        organization = await organization_repo.get_by_id(self.db, organization_id)
        if organization is not None and organization.is_personal:
            raise BadRequestError(message="A personal organization cannot take directory members")
        group_name: str | None = None
        if data.group_id is not None:
            group = await group_repo.get(
                self.db, organization_id=organization_id, group_id=data.group_id
            )
            if group is None:
                raise BadRequestError(
                    message="That group is not one of this organization's",
                    details={"group_id": str(data.group_id)},
                )
            group_name = group.name
        if await directory_mapping_repo.get_by_external_group(
            self.db, organization_id=organization_id, external_group=data.external_group
        ):
            raise AlreadyExistsError(
                message="That directory group is already mapped here",
                details={"external_group": data.external_group},
            )
        try:
            async with self.db.begin_nested():
                mapping = await directory_mapping_repo.create(
                    self.db,
                    organization_id=organization_id,
                    external_group=data.external_group,
                    role=data.role,
                    group_id=data.group_id,
                    created_by_user_id=requester_id,
                )
        except IntegrityError as exc:
            raise AlreadyExistsError(
                message="That directory group is already mapped here",
                details={"external_group": data.external_group},
            ) from exc
        await record_audit(
            self.db,
            actor_user_id=requester_id,
            organization_id=organization_id,
            action="directory.mapping_created",
            target_type="directory_mapping",
            target_id=str(mapping.id),
            details={
                "external_group": mapping.external_group,
                "role": mapping.role,
                "group_id": str(mapping.group_id) if mapping.group_id else None,
            },
        )
        return mapping, group_name

    async def delete(self, organization_id: UUID, mapping_id: UUID, requester_id: UUID) -> None:
        """Delete a mapping.

        The people it placed keep their membership until their next sign-in,
        which removes the directory-managed ones no other mapping still names.
        """
        requester = await self._requester(organization_id, requester_id)
        if not role_has(requester.role, Perm.ROLES_MANAGE):
            raise AuthorizationError(message="You cannot assign roles in this organization")
        mapping = await directory_mapping_repo.get(
            self.db, organization_id=organization_id, mapping_id=mapping_id
        )
        if mapping is None:
            raise NotFoundError(
                message="Directory mapping not found", details={"mapping_id": str(mapping_id)}
            )
        # Deleting a mapping demotes everybody it placed, at their next sign-in,
        # so it takes the same ceiling as creating it: an Admin cannot remove the
        # mapping that makes their peers Admins, as they could not demote one.
        if mapping.role not in assignable_roles(requester.role):
            raise AuthorizationError(
                message="You cannot remove a mapping to a role your own does not outrank",
                details={"role": mapping.role},
            )
        external_group = mapping.external_group
        await directory_mapping_repo.delete_mapping(self.db, mapping)
        await record_audit(
            self.db,
            actor_user_id=requester_id,
            organization_id=organization_id,
            action="directory.mapping_deleted",
            target_type="directory_mapping",
            target_id=str(mapping_id),
            details={"external_group": external_group},
        )

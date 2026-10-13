"""Reconciling a person's memberships with what their directory says, at sign-in.

Every organization's directory group mappings are read against the groups the
identity provider reported, and the person's *directory-managed* memberships are
made to match: joined where a mapping names them, given the mapped role, put in
the mapped groups - and taken out again where no mapping names them any more.

Four rules keep that from undoing anybody's decision:

- **The sync touches only rows it made.** A membership an administrator created
  or took over (`source = manual`) keeps its role whatever the directory says;
  a group membership added by hand stays when the directory would remove it.
- **An owner is never demoted or removed by it.** Ownership moves through
  `transfer_ownership` and nothing else, and a directory that dropped the owner
  from a group must not leave an organization without one.
- **No mapping can make an owner.** The schema refuses `owner` as a mapped role.
- **A personal organization is never joined.** `list_matching` excludes them.

When several mappings match in one organization, the role is the first of
`ROLE_PRECEDENCE` among them. Roles are not totally ordered by authority -
`builder` and `operator` each hold something the other does not - so the order
is stated rather than derived, and it is written down in `docs/directory.md`.

The sync runs in the sign-in's own transaction: the memberships it writes commit
with the session they are for, or not at all.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.permissions import OrgRoleName
from app.db.models.directory_mapping import DirectoryGroupMapping
from app.db.models.organization import MembershipSource
from app.repositories import directory_mapping_repo, group_repo, member_repo

logger = logging.getLogger(__name__)

#: Which role wins when one person matches several mappings in one organization.
ROLE_PRECEDENCE: tuple[OrgRoleName, ...] = (
    OrgRoleName.ADMIN,
    OrgRoleName.BUILDER,
    OrgRoleName.OPERATOR,
    OrgRoleName.MEMBER,
    OrgRoleName.VIEWER,
)


def normalize_groups(groups: Iterable[str]) -> frozenset[str]:
    """Directory groups the way mappings store them: trimmed and case-folded."""
    return frozenset(folded for group in groups if (folded := group.strip().casefold()))


def winning_role(mappings: Iterable[DirectoryGroupMapping]) -> str:
    """The role several matching mappings resolve to, by `ROLE_PRECEDENCE`."""
    roles = {mapping.role for mapping in mappings}
    for role in ROLE_PRECEDENCE:
        if role.value in roles:
            return role.value
    # A mapping row holding a role outside the catalog - the schema forbids it,
    # so this is a row written some other way. The least a member can hold.
    logger.warning("directory_mapping_unknown_role", extra={"roles": sorted(roles)})
    return OrgRoleName.VIEWER.value


class DirectorySyncService:
    """Applies the organizations' directory group mappings to one person."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def admits(self, groups: Iterable[str]) -> bool:
        """Whether any organization maps one of these groups.

        A match is an invitation: somebody holding `members:manage` and
        `roles:manage` decided that everyone in that group belongs in their
        organization. `check_may_register` reads it the way it reads one.
        """
        return bool(
            await directory_mapping_repo.list_matching(
                self.db, external_groups=normalize_groups(groups)
            )
        )

    async def apply(self, user_id: UUID, groups: Iterable[str], *, provider: str) -> None:
        """Make the person's directory-managed memberships match `groups`.

        Args:
            user_id: Who signed in.
            groups: The groups the identity provider reported for them, verbatim.
            provider: Which sign-in reported them (`ldap`, `oidc`), for the audit trail.
        """
        matched = await directory_mapping_repo.list_matching(
            self.db, external_groups=normalize_groups(groups)
        )
        by_organization: dict[UUID, list[DirectoryGroupMapping]] = defaultdict(list)
        for mapping in matched:
            by_organization[mapping.organization_id].append(mapping)

        for organization_id, mappings in by_organization.items():
            await self._place(user_id, organization_id, winning_role(mappings), provider=provider)
            await self._sync_groups(
                user_id,
                organization_id,
                {mapping.group_id for mapping in mappings if mapping.group_id is not None},
                provider=provider,
            )

        for membership in await member_repo.list_for_user_by_source(
            self.db, user_id=user_id, source=MembershipSource.DIRECTORY
        ):
            if membership.organization_id in by_organization:
                continue
            if membership.role == OrgRoleName.OWNER:
                continue
            await group_repo.delete_memberships_in_org(
                self.db, organization_id=membership.organization_id, user_id=user_id
            )
            await member_repo.delete(self.db, membership)
            await self._audit(
                "directory.member_removed",
                user_id,
                membership.organization_id,
                {"role": membership.role, "provider": provider},
            )

        for organization_id in await group_repo.organizations_with_directory_groups(
            self.db, user_id=user_id
        ):
            if organization_id not in by_organization:
                await self._sync_groups(user_id, organization_id, set(), provider=provider)

    async def _place(
        self, user_id: UUID, organization_id: UUID, role: str, *, provider: str
    ) -> None:
        """Join the organization with `role`, or bring a directory-managed role up to date."""
        membership = await member_repo.get(
            self.db, organization_id=organization_id, user_id=user_id, for_update=True
        )
        if membership is None:
            try:
                async with self.db.begin_nested():
                    await member_repo.create(
                        self.db,
                        organization_id=organization_id,
                        user_id=user_id,
                        role=role,
                        source=MembershipSource.DIRECTORY,
                    )
            except IntegrityError:
                # A second sign-in by the same person got there first, and its
                # membership says what this one would have.
                logger.info("directory_member_created_concurrently")
                return
            await self._audit(
                "directory.member_added",
                user_id,
                organization_id,
                {"role": role, "provider": provider},
            )
            return
        if membership.source != MembershipSource.DIRECTORY:
            return
        if membership.role == OrgRoleName.OWNER or membership.role == role:
            return
        previous = membership.role
        await member_repo.update_role(self.db, membership, role=role)
        await self._audit(
            "directory.role_changed",
            user_id,
            organization_id,
            {"from": previous, "to": role, "provider": provider},
        )

    async def _sync_groups(
        self, user_id: UUID, organization_id: UUID, wanted: set[UUID], *, provider: str
    ) -> None:
        """Add the directory group memberships `wanted` names and drop the ones it does not."""
        current = await group_repo.list_memberships_in_org(
            self.db, organization_id=organization_id, user_id=user_id
        )
        held = {member.group_id for member in current}
        for member in current:
            if member.source == MembershipSource.DIRECTORY and member.group_id not in wanted:
                await group_repo.remove_member(self.db, member)
                await self._audit(
                    "directory.group_left",
                    user_id,
                    organization_id,
                    {"group_id": str(member.group_id), "provider": provider},
                )
        for group_id in sorted(wanted - held):
            try:
                async with self.db.begin_nested():
                    await group_repo.add_member(
                        self.db,
                        group_id=group_id,
                        user_id=user_id,
                        source=MembershipSource.DIRECTORY,
                        added_by_user_id=None,
                    )
            except IntegrityError:
                logger.info("directory_group_member_created_concurrently")
                continue
            await self._audit(
                "directory.group_joined",
                user_id,
                organization_id,
                {"group_id": str(group_id), "provider": provider},
            )

    async def _audit(
        self, action: str, user_id: UUID, organization_id: UUID, details: dict[str, str]
    ) -> None:
        """Record a change the sync made, attributed to the sign-in that caused it."""
        await record_audit(
            self.db,
            actor_user_id=user_id,
            organization_id=organization_id,
            action=action,
            target_type="member",
            target_id=str(user_id),
            details=details,
        )

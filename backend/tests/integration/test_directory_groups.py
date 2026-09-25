"""Groups, group grants and the directory sync, against a real database (#1773).

What only Postgres can say: that a grant has exactly one subject, that deleting
a group takes its grants and mappings with it, that a group grant reaches a
member through the subquery and stops reaching them the moment they leave - and
that the sync, run over real rows, joins, re-roles and removes exactly the
memberships it owns and nothing an administrator made.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AlreadyExistsError, AuthorizationError, BadRequestError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.directory_mapping import DirectoryGroupMapping
from app.db.models.group import Group, GroupMember
from app.db.models.organization import MembershipSource, Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.db.models.skill import Skill
from app.db.models.user import User
from app.repositories import group_repo, member_repo, resource_grant_repo
from app.schemas.directory import DirectoryMappingCreate
from app.schemas.group import GroupCreate
from app.services.access import SKILL, resolve_access
from app.services.directory import DirectoryMappingService, DirectorySyncService
from app.services.group import GroupService
from app.services.member import MemberService

pytestmark = pytest.mark.anyio

FINANCE = "CN=Finance,OU=Groups,DC=corp,DC=example"
ADMINS = "CN=Platform Admins,OU=Groups,DC=corp,DC=example"


async def _user(db, email: str | None = None) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email or f"{uuid.uuid4().hex}@example.com",
        hashed_password=None,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db, *, personal: bool = False) -> tuple[Organization, User]:
    owner = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
        is_personal=personal,
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"))
    await db.flush()
    return org, owner


async def _member(db, org: Organization, *, role: str = "member", source: str = "manual") -> User:
    user = await _user(db)
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role, source=source))
    await db.flush()
    return user


async def _group(db, org: Organization, name: str = "Finance") -> Group:
    group = Group(organization_id=org.id, name=name)
    db.add(group)
    await db.flush()
    return group


async def _mapping(
    db, org: Organization, external: str, role: str, group: Group | None = None
) -> DirectoryGroupMapping:
    mapping = DirectoryGroupMapping(
        organization_id=org.id,
        external_group=external.casefold(),
        role=role,
        group_id=group.id if group else None,
    )
    db.add(mapping)
    await db.flush()
    return mapping


async def _skill(db, org: Organization, owner: User) -> Skill:
    skill = Skill(
        organization_id=org.id,
        owner_user_id=owner.id,
        name=f"skill-{uuid.uuid4().hex[:6]}",
        description="d",
        content="c",
        visibility=Visibility.PRIVATE.value,
    )
    db.add(skill)
    await db.flush()
    return skill


async def _membership(db, org: Organization, user: User) -> OrganizationMember | None:
    return await member_repo.get(db, organization_id=org.id, user_id=user.id)


async def _group_rows(db, user: User) -> dict[uuid.UUID, str]:
    rows = (await db.execute(select(GroupMember).where(GroupMember.user_id == user.id))).scalars()
    return {row.group_id: row.source for row in rows}


class TestGrantSubjects:
    async def test_a_grant_with_no_subject_is_refused(self, db):
        org, owner = await _org(db)
        db.add(
            ResourceGrant(
                organization_id=org.id,
                resource_type="skill",
                resource_id=uuid.uuid4(),
                level="read",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_grant_naming_a_person_and_a_group_is_refused(self, db):
        org, owner = await _org(db)
        group = await _group(db, org)
        db.add(
            ResourceGrant(
                organization_id=org.id,
                subject_user_id=owner.id,
                subject_group_id=group.id,
                resource_type="skill",
                resource_id=uuid.uuid4(),
                level="read",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_one_group_holds_one_grant_per_resource(self, db):
        org, _ = await _org(db)
        group = await _group(db, org)
        resource_id = uuid.uuid4()
        for _ in range(2):
            db.add(
                ResourceGrant(
                    organization_id=org.id,
                    subject_group_id=group.id,
                    resource_type="skill",
                    resource_id=resource_id,
                    level="read",
                )
            )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_deleting_a_group_takes_its_grants_members_and_mappings(self, db):
        org, owner = await _org(db)
        group = await _group(db, org)
        db.add(GroupMember(group_id=group.id, user_id=owner.id))
        db.add(
            ResourceGrant(
                organization_id=org.id,
                subject_group_id=group.id,
                resource_type="skill",
                resource_id=uuid.uuid4(),
                level="edit",
            )
        )
        await _mapping(db, org, FINANCE, "member", group)
        await db.flush()

        await group_repo.delete_group(db, group)
        db.expunge_all()

        assert (await db.execute(select(ResourceGrant))).scalars().all() == []
        assert (await db.execute(select(GroupMember))).scalars().all() == []
        assert (await db.execute(select(DirectoryGroupMapping))).scalars().all() == []

    async def test_a_membership_source_outside_the_two_is_refused(self, db):
        org, owner = await _org(db)
        group = await _group(db, org)
        db.add(GroupMember(group_id=group.id, user_id=owner.id, source="scim"))
        with pytest.raises(IntegrityError):
            await db.flush()


class TestGroupGrantsReachMembers:
    async def test_a_member_reaches_a_private_resource_through_their_group(self, db):
        org, owner = await _org(db)
        member = await _member(db, org)
        skill = await _skill(db, org, owner)
        group = await _group(db, org)
        db.add(GroupMember(group_id=group.id, user_id=member.id))
        await resource_grant_repo.upsert_for_group(
            db,
            organization_id=org.id,
            subject_group_id=group.id,
            resource_type=SKILL.key,
            resource_id=skill.id,
            level=GrantLevel.EDIT,
        )
        ctx = AuthContext(user_id=member.id, organization_id=org.id, role="member")

        assert await resolve_access(db, ctx, skill, Perm.SKILLS_EDIT, resource_type=SKILL)

        (membership,) = (
            await db.execute(select(GroupMember).where(GroupMember.user_id == member.id))
        ).scalars()
        await group_repo.remove_member(db, membership)

        assert not await resolve_access(db, ctx, skill, Perm.SKILLS_VIEW, resource_type=SKILL)

    @pytest.mark.security
    async def test_a_group_of_another_organization_reaches_nothing_here(self, db):
        """A grant row naming a foreign group - however it got there - must not open a door."""
        org, owner = await _org(db)
        other, _ = await _org(db)
        member = await _member(db, org)
        skill = await _skill(db, org, owner)
        foreign = await _group(db, other, "Foreign")
        db.add(GroupMember(group_id=foreign.id, user_id=member.id))
        db.add(
            ResourceGrant(
                organization_id=org.id,
                subject_group_id=foreign.id,
                resource_type=SKILL.key,
                resource_id=skill.id,
                level="edit",
            )
        )
        await db.flush()

        level = await resource_grant_repo.get_level(
            db,
            organization_id=org.id,
            subject_user_id=member.id,
            resource_type=SKILL.key,
            resource_id=skill.id,
        )

        assert level is None

    async def test_the_best_grant_wins_and_a_twice_shared_row_lists_once(self, db):
        org, owner = await _org(db)
        member = await _member(db, org)
        skill = await _skill(db, org, owner)
        group = await _group(db, org)
        db.add(GroupMember(group_id=group.id, user_id=member.id))
        await resource_grant_repo.upsert(
            db,
            organization_id=org.id,
            subject_user_id=member.id,
            resource_type=SKILL.key,
            resource_id=skill.id,
            level=GrantLevel.READ,
        )
        await resource_grant_repo.upsert_for_group(
            db,
            organization_id=org.id,
            subject_group_id=group.id,
            resource_type=SKILL.key,
            resource_id=skill.id,
            level=GrantLevel.USE,
        )

        level = await resource_grant_repo.get_level(
            db,
            organization_id=org.id,
            subject_user_id=member.id,
            resource_type=SKILL.key,
            resource_id=skill.id,
        )
        listed = await resource_grant_repo.list_shared_ids(
            db, organization_id=org.id, subject_user_id=member.id, resource_type=SKILL.key
        )

        assert level is GrantLevel.USE
        assert listed == [skill.id]

    async def test_revoking_a_group_share_removes_exactly_that_grant(self, db):
        org, owner = await _org(db)
        group = await _group(db, org)
        skill = await _skill(db, org, owner)
        await resource_grant_repo.upsert_for_group(
            db,
            organization_id=org.id,
            subject_group_id=group.id,
            resource_type=SKILL.key,
            resource_id=skill.id,
            level=GrantLevel.READ,
        )
        upgraded = await resource_grant_repo.upsert_for_group(
            db,
            organization_id=org.id,
            subject_group_id=group.id,
            resource_type=SKILL.key,
            resource_id=skill.id,
            level=GrantLevel.EDIT,
        )

        assert upgraded.level == "edit"
        assert await resource_grant_repo.revoke_for_group(
            db,
            organization_id=org.id,
            subject_group_id=group.id,
            resource_type=SKILL.key,
            resource_id=skill.id,
        )
        assert not await resource_grant_repo.revoke_for_group(
            db,
            organization_id=org.id,
            subject_group_id=group.id,
            resource_type=SKILL.key,
            resource_id=skill.id,
        )


class TestGroupService:
    async def test_a_duplicate_name_is_a_conflict_not_a_500(self, db):
        org, owner = await _org(db)
        service = GroupService(db)
        await service.create(org.id, owner.id, GroupCreate(name="Finance"))

        with pytest.raises(AlreadyExistsError):
            await service.create(org.id, owner.id, GroupCreate(name="Finance"))

    async def test_listing_counts_members_and_orders_by_name(self, db):
        org, owner = await _org(db)
        member = await _member(db, org)
        service = GroupService(db)
        zeta = await service.create(org.id, owner.id, GroupCreate(name="Zeta"))
        await service.create(org.id, owner.id, GroupCreate(name="Alpha"))
        await service.add_member(org.id, zeta.id, member.id, owner.id)

        listed = await service.list_groups(org.id, member.id)

        assert [(group.name, count) for group, count in listed] == [("Alpha", 0), ("Zeta", 1)]

    @pytest.mark.security
    async def test_only_members_of_the_organization_join_its_groups(self, db):
        org, owner = await _org(db)
        outsider = await _user(db)
        group = await GroupService(db).create(org.id, owner.id, GroupCreate(name="Finance"))

        with pytest.raises(BadRequestError):
            await GroupService(db).add_member(org.id, group.id, outsider.id, owner.id)

    async def test_adding_by_hand_takes_over_a_directory_membership(self, db):
        org, owner = await _org(db)
        member = await _member(db, org)
        group = await _group(db, org)
        db.add(GroupMember(group_id=group.id, user_id=member.id, source="directory"))
        await db.flush()

        row, email, _ = await GroupService(db).add_member(org.id, group.id, member.id, owner.id)

        assert row.source == MembershipSource.MANUAL
        assert email == member.email

    async def test_renaming_to_a_taken_name_is_a_conflict(self, db):
        from app.schemas.group import GroupUpdate

        org, owner = await _org(db)
        service = GroupService(db)
        await service.create(org.id, owner.id, GroupCreate(name="Finance"))
        ops = await service.create(org.id, owner.id, GroupCreate(name="Ops"))

        with pytest.raises(AlreadyExistsError):
            await service.update(org.id, ops.id, owner.id, GroupUpdate(name="Finance"))

        renamed, count = await service.update(
            org.id, ops.id, owner.id, GroupUpdate(description="Runs things")
        )
        assert (renamed.name, renamed.description, count) == ("Ops", "Runs things", 0)

    async def test_members_are_listed_removed_and_the_group_deleted_with_an_audit_trail(self, db):
        org, owner = await _org(db)
        member = await _member(db, org)
        service = GroupService(db)
        group = await service.create(org.id, owner.id, GroupCreate(name="Finance"))
        await service.add_member(org.id, group.id, member.id, owner.id)

        listed = await service.list_members(org.id, group.id, member.id)
        assert [(row.user_id, email) for row, email, _ in listed] == [(member.id, member.email)]

        await service.remove_member(org.id, group.id, member.id, owner.id)
        assert await service.list_members(org.id, group.id, owner.id) == []

        await service.delete(org.id, group.id, owner.id)
        assert await group_repo.get(db, organization_id=org.id, group_id=group.id) is None
        actions = [
            entry.action
            for entry in (await db.execute(select(AppAdminAuditLog))).scalars()
            if entry.target_id == str(group.id)
        ]
        assert actions == [
            "group.created",
            "group.member_added",
            "group.member_removed",
            "group.deleted",
        ]


class TestMembershipsAnAdministratorOwns:
    async def test_changing_a_directory_members_role_takes_the_membership_over(self, db):
        org, owner = await _org(db)
        member = await _member(db, org, role="viewer", source="directory")

        await MemberService(db).change_role(org.id, member.id, "builder", owner.id)

        membership = await _membership(db, org, member)
        assert membership is not None
        assert (membership.role, membership.source) == ("builder", "manual")

    async def test_removing_a_member_takes_them_out_of_every_group_there(self, db):
        org, owner = await _org(db)
        member = await _member(db, org)
        group = await _group(db, org)
        other, _ = await _org(db)
        elsewhere = await _group(db, other, "Elsewhere")
        db.add(GroupMember(group_id=group.id, user_id=member.id))
        db.add(GroupMember(group_id=elsewhere.id, user_id=member.id))
        await db.flush()

        await MemberService(db).remove(org.id, member.id, owner.id)

        assert set(await _group_rows(db, member)) == {elsewhere.id}


class TestDirectorySync:
    async def test_a_matching_mapping_joins_the_organization_with_its_role_and_group(self, db):
        org, _ = await _org(db)
        group = await _group(db, org)
        await _mapping(db, org, FINANCE, "builder", group)
        person = await _user(db)

        await DirectorySyncService(db).apply(person.id, [FINANCE.upper()], provider="ldap")

        membership = await _membership(db, org, person)
        assert membership is not None
        assert (membership.role, membership.source) == ("builder", "directory")
        assert await _group_rows(db, person) == {group.id: "directory"}
        actions = {
            entry.action
            for entry in (await db.execute(select(AppAdminAuditLog))).scalars()
            if entry.target_id == str(person.id)
        }
        assert actions == {"directory.member_added", "directory.group_joined"}

    async def test_the_role_follows_the_stated_precedence(self, db):
        org, _ = await _org(db)
        await _mapping(db, org, FINANCE, "operator")
        await _mapping(db, org, ADMINS, "builder")
        person = await _user(db)

        await DirectorySyncService(db).apply(person.id, [FINANCE, ADMINS], provider="oidc")

        membership = await _membership(db, org, person)
        assert membership is not None
        assert membership.role == "builder"

    async def test_a_later_sign_in_re_roles_and_moves_groups(self, db):
        org, _ = await _org(db)
        finance = await _group(db, org, "Finance")
        admins = await _group(db, org, "Admins")
        await _mapping(db, org, FINANCE, "member", finance)
        await _mapping(db, org, ADMINS, "admin", admins)
        person = await _user(db)
        sync = DirectorySyncService(db)
        await sync.apply(person.id, [FINANCE], provider="ldap")

        await sync.apply(person.id, [ADMINS], provider="ldap")

        membership = await _membership(db, org, person)
        assert membership is not None
        assert membership.role == "admin"
        assert await _group_rows(db, person) == {admins.id: "directory"}

    async def test_leaving_every_mapped_group_removes_only_what_the_sync_made(self, db):
        org, owner = await _org(db)
        kept_org, _ = await _org(db)
        group = await _group(db, org)
        manual_group = await _group(db, org, "By hand")
        await _mapping(db, org, FINANCE, "member", group)
        person = await _user(db)
        # An administrator's decisions: a manual membership elsewhere, and a
        # group they added by hand.
        db.add(OrganizationMember(organization_id=kept_org.id, user_id=person.id, role="viewer"))
        await db.flush()
        sync = DirectorySyncService(db)
        await sync.apply(person.id, [FINANCE], provider="ldap")
        db.add(GroupMember(group_id=manual_group.id, user_id=person.id, source="manual"))
        await db.flush()

        await sync.apply(person.id, [], provider="ldap")

        assert await _membership(db, org, person) is None
        kept = await _membership(db, kept_org, person)
        assert kept is not None
        assert kept.role == "viewer"
        # The whole organization is gone, so its groups go with it - the manual
        # one included, because a group of an organization somebody is not in
        # reaches nothing.
        assert await _group_rows(db, person) == {}

    async def test_a_manual_membership_keeps_its_role_but_gains_the_mapped_group(self, db):
        org, _ = await _org(db)
        group = await _group(db, org)
        await _mapping(db, org, FINANCE, "admin", group)
        person = await _member(db, org, role="viewer")

        await DirectorySyncService(db).apply(person.id, [FINANCE], provider="ldap")

        membership = await _membership(db, org, person)
        assert membership is not None
        assert (membership.role, membership.source) == ("viewer", "manual")
        assert await _group_rows(db, person) == {group.id: "directory"}

        await DirectorySyncService(db).apply(person.id, [], provider="ldap")

        assert await _membership(db, org, person) is not None
        assert await _group_rows(db, person) == {}

    async def test_a_group_added_by_hand_survives_the_directory_moving_the_person_on(self, db):
        org, _ = await _org(db)
        mapped = await _group(db, org, "Mapped")
        by_hand = await _group(db, org, "By hand")
        await _mapping(db, org, FINANCE, "member", mapped)
        person = await _user(db)
        sync = DirectorySyncService(db)
        await sync.apply(person.id, [FINANCE], provider="ldap")
        db.add(GroupMember(group_id=by_hand.id, user_id=person.id, source="manual"))
        await db.flush()

        await sync.apply(person.id, [FINANCE], provider="ldap")

        assert await _group_rows(db, person) == {mapped.id: "directory", by_hand.id: "manual"}

    async def test_an_owner_is_never_demoted_or_removed(self, db):
        org, _ = await _org(db)
        await _mapping(db, org, FINANCE, "viewer")
        person = await _member(db, org, role="owner", source="directory")
        sync = DirectorySyncService(db)

        await sync.apply(person.id, [FINANCE], provider="ldap")
        await sync.apply(person.id, [], provider="ldap")

        membership = await _membership(db, org, person)
        assert membership is not None
        assert membership.role == "owner"

    @pytest.mark.security
    async def test_a_personal_organization_is_never_joined(self, db):
        personal, _ = await _org(db, personal=True)
        await _mapping(db, personal, FINANCE, "member")
        person = await _user(db)

        sync = DirectorySyncService(db)
        assert not await sync.admits([FINANCE])
        await sync.apply(person.id, [FINANCE], provider="ldap")

        assert await _membership(db, personal, person) is None

    async def test_a_mapped_group_admits_and_an_unmapped_one_does_not(self, db):
        org, _ = await _org(db)
        await _mapping(db, org, FINANCE, "member")
        sync = DirectorySyncService(db)

        assert await sync.admits([f"  {FINANCE.lower()} "])
        assert not await sync.admits(["CN=Nobody,DC=corp"])
        assert not await sync.admits([])


class TestDirectoryMappingService:
    async def test_an_owner_maps_a_group_and_sees_it_listed_with_the_group_name(self, db):
        org, owner = await _org(db)
        group = await _group(db, org)
        service = DirectoryMappingService(db)

        mapping, name = await service.create(
            org.id,
            owner.id,
            DirectoryMappingCreate(external_group=FINANCE, role="admin", group_id=group.id),
        )
        listed = await service.list_mappings(org.id, owner.id)

        assert name == "Finance"
        assert mapping.external_group == FINANCE.casefold()
        assert [(row.id, group_name) for row, group_name in listed] == [(mapping.id, "Finance")]

    async def test_mapping_the_same_group_twice_is_a_conflict(self, db):
        org, owner = await _org(db)
        service = DirectoryMappingService(db)
        await service.create(
            org.id, owner.id, DirectoryMappingCreate(external_group=FINANCE, role="member")
        )

        with pytest.raises(AlreadyExistsError):
            await service.create(
                org.id,
                owner.id,
                DirectoryMappingCreate(external_group=FINANCE.upper(), role="viewer"),
            )

    @pytest.mark.security
    async def test_an_admin_cannot_map_or_unmap_their_own_level(self, db):
        """A mapping hands a role to everyone in a group; it is bounded like an invitation."""
        org, owner = await _org(db)
        admin = await _member(db, org, role=OrgRoleName.ADMIN.value)
        service = DirectoryMappingService(db)

        with pytest.raises(AuthorizationError):
            await service.create(
                org.id, admin.id, DirectoryMappingCreate(external_group=ADMINS, role="admin")
            )

        owners_mapping, _ = await service.create(
            org.id, owner.id, DirectoryMappingCreate(external_group=ADMINS, role="admin")
        )
        with pytest.raises(AuthorizationError):
            await service.delete(org.id, owners_mapping.id, admin.id)

        mine, _ = await service.create(
            org.id, admin.id, DirectoryMappingCreate(external_group=FINANCE, role="builder")
        )
        await service.delete(org.id, mine.id, admin.id)
        remaining = [row.id for row, _ in await service.list_mappings(org.id, owner.id)]
        assert remaining == [owners_mapping.id]

    @pytest.mark.security
    async def test_a_group_of_another_organization_cannot_be_named(self, db):
        org, owner = await _org(db)
        other, _ = await _org(db)
        foreign = await _group(db, other, "Foreign")

        with pytest.raises(BadRequestError):
            await DirectoryMappingService(db).create(
                org.id,
                owner.id,
                DirectoryMappingCreate(external_group=FINANCE, role="member", group_id=foreign.id),
            )

    async def test_a_personal_organization_takes_no_mappings(self, db):
        personal, owner = await _org(db, personal=True)

        with pytest.raises(BadRequestError):
            await DirectoryMappingService(db).create(
                personal.id,
                owner.id,
                DirectoryMappingCreate(external_group=FINANCE, role="member"),
            )

"""Refusals of the group and directory-mapping services, and the small contracts beside them (#1773).

Most of what these services do is proven over a real database in
`tests/integration/test_directory_groups.py`. What is here is what that suite
would need contortions to reach: each refusal, asserted to happen before
anything is written, and the savepoint turning a lost race into a 409.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AlreadyExistsError, AuthorizationError, NotFoundError
from app.db.models.directory_mapping import DirectoryGroupMapping
from app.db.models.group import Group, GroupMember
from app.db.models.resource_grant import ResourceGrant
from app.schemas.directory import DirectoryLogin, DirectoryMappingCreate
from app.schemas.group import GroupCreate, GroupUpdate
from app.schemas.resource_grant import ResourceGrantUpsert
from app.services.directory import DirectoryMappingService
from app.services.directory.ldap_directory import _subject
from app.services.group import GroupService

pytestmark = pytest.mark.anyio

ORG, CALLER = uuid.uuid4(), uuid.uuid4()


class _Savepoint:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _db() -> MagicMock:
    db = MagicMock()
    db.begin_nested = MagicMock(return_value=_Savepoint())
    return db


def _membership(role: str) -> MagicMock:
    return MagicMock(role=role)


def _race() -> IntegrityError:
    return IntegrityError("insert", {}, Exception())


class TestGroupServiceRefusals:
    @pytest.mark.security
    async def test_an_outsider_is_told_the_organization_does_not_exist(self):
        with (
            patch("app.services.group.member_repo.get", new=AsyncMock(return_value=None)),
            patch("app.services.group.group_repo") as groups,
            pytest.raises(NotFoundError) as refused,
        ):
            await GroupService(_db()).list_groups(ORG, CALLER)

        assert refused.value.message == "Organization not found"
        groups.list_for_org.assert_not_called()

    @pytest.mark.security
    @pytest.mark.parametrize("role", ["member", "viewer", "builder", "operator"])
    async def test_a_role_without_members_manage_changes_no_group(self, role):
        with (
            patch(
                "app.services.group.member_repo.get", new=AsyncMock(return_value=_membership(role))
            ),
            patch("app.services.group.group_repo") as groups,
            pytest.raises(AuthorizationError),
        ):
            await GroupService(_db()).create(ORG, CALLER, GroupCreate(name="Finance"))

        groups.create.assert_not_called()

    async def test_a_group_of_another_organization_is_not_found(self):
        with (
            patch(
                "app.services.group.member_repo.get",
                new=AsyncMock(return_value=_membership("owner")),
            ),
            patch("app.services.group.group_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await GroupService(_db()).delete(ORG, uuid.uuid4(), CALLER)

    async def test_a_lost_create_race_is_a_conflict(self):
        with (
            patch(
                "app.services.group.member_repo.get",
                new=AsyncMock(return_value=_membership("owner")),
            ),
            patch("app.services.group.group_repo") as groups,
            pytest.raises(AlreadyExistsError),
        ):
            groups.get_by_name = AsyncMock(return_value=None)
            groups.create = AsyncMock(side_effect=_race())
            await GroupService(_db()).create(ORG, CALLER, GroupCreate(name="Finance"))

    async def test_a_lost_rename_race_is_a_conflict(self):
        group = MagicMock(id=uuid.uuid4(), name="Ops", description=None)
        with (
            patch(
                "app.services.group.member_repo.get",
                new=AsyncMock(return_value=_membership("owner")),
            ),
            patch("app.services.group.group_repo") as groups,
            pytest.raises(AlreadyExistsError),
        ):
            groups.get = AsyncMock(return_value=group)
            groups.get_by_name = AsyncMock(return_value=None)
            groups.update = AsyncMock(side_effect=_race())
            await GroupService(_db()).update(ORG, group.id, CALLER, GroupUpdate(name="Finance"))

    async def test_a_lost_add_race_is_a_conflict(self):
        group = MagicMock(id=uuid.uuid4())
        with (
            patch(
                "app.services.group.member_repo.get",
                new=AsyncMock(return_value=_membership("owner")),
            ),
            patch("app.services.group.group_repo") as groups,
            pytest.raises(AlreadyExistsError),
        ):
            groups.get = AsyncMock(return_value=group)
            groups.get_member = AsyncMock(return_value=None)
            groups.add_member = AsyncMock(side_effect=_race())
            await GroupService(_db()).add_member(ORG, group.id, uuid.uuid4(), CALLER)

    async def test_adding_someone_already_added_by_hand_changes_nothing(self):
        group = MagicMock(id=uuid.uuid4())
        row = (MagicMock(source="manual"), "a@x", None)
        with (
            patch(
                "app.services.group.member_repo.get",
                new=AsyncMock(return_value=_membership("owner")),
            ),
            patch("app.services.group.group_repo") as groups,
            patch("app.services.group.record_audit", new=AsyncMock()) as audit,
        ):
            groups.get = AsyncMock(return_value=group)
            groups.get_member = AsyncMock(return_value=row[0])
            groups.set_member_source = AsyncMock()
            groups.get_member_row = AsyncMock(return_value=row)
            assert await GroupService(_db()).add_member(ORG, group.id, uuid.uuid4(), CALLER) == row

        groups.set_member_source.assert_not_awaited()
        audit.assert_not_awaited()

    async def test_a_membership_that_vanished_before_it_was_read_back_is_not_found(self):
        group = MagicMock(id=uuid.uuid4())
        with (
            patch(
                "app.services.group.member_repo.get",
                new=AsyncMock(return_value=_membership("owner")),
            ),
            patch("app.services.group.group_repo") as groups,
            patch("app.services.group.record_audit", new=AsyncMock()),
            pytest.raises(NotFoundError),
        ):
            groups.get = AsyncMock(return_value=group)
            groups.get_member = AsyncMock(return_value=None)
            groups.add_member = AsyncMock()
            groups.get_member_row = AsyncMock(return_value=None)
            await GroupService(_db()).add_member(ORG, group.id, uuid.uuid4(), CALLER)

    async def test_removing_someone_who_is_not_in_the_group_is_not_found(self):
        with (
            patch(
                "app.services.group.member_repo.get",
                new=AsyncMock(return_value=_membership("owner")),
            ),
            patch("app.services.group.group_repo") as groups,
            pytest.raises(NotFoundError),
        ):
            groups.get = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            groups.get_member = AsyncMock(return_value=None)
            await GroupService(_db()).remove_member(ORG, uuid.uuid4(), uuid.uuid4(), CALLER)


class TestDirectoryMappingRefusals:
    @pytest.mark.security
    async def test_an_outsider_is_told_the_organization_does_not_exist(self):
        with (
            patch(
                "app.services.directory.mappings.member_repo.get", new=AsyncMock(return_value=None)
            ),
            pytest.raises(NotFoundError),
        ):
            await DirectoryMappingService(_db()).list_mappings(ORG, CALLER)

    @pytest.mark.security
    async def test_reading_the_mappings_takes_members_manage(self):
        with (
            patch(
                "app.services.directory.mappings.member_repo.get",
                new=AsyncMock(return_value=_membership("builder")),
            ),
            pytest.raises(AuthorizationError),
        ):
            await DirectoryMappingService(_db()).list_mappings(ORG, CALLER)

    @pytest.mark.security
    async def test_changing_them_takes_roles_manage_as_well(self, monkeypatch):
        """`members:manage` alone adds people; a mapping also hands them a role."""
        from app.core.permissions import ROLE_PERMS, Perm, Scope

        monkeypatch.setitem(ROLE_PERMS, "test:members-only", {Perm.MEMBERS_MANAGE: Scope.ALL})
        with (
            patch(
                "app.services.directory.mappings.member_repo.get",
                new=AsyncMock(return_value=_membership("test:members-only")),
            ),
            patch("app.services.directory.mappings.directory_mapping_repo") as mappings,
        ):
            with pytest.raises(AuthorizationError):
                await DirectoryMappingService(_db()).create(
                    ORG, CALLER, DirectoryMappingCreate(external_group="g", role="viewer")
                )
            with pytest.raises(AuthorizationError):
                await DirectoryMappingService(_db()).delete(ORG, uuid.uuid4(), CALLER)

        mappings.create.assert_not_called()
        mappings.delete_mapping.assert_not_called()

    async def test_deleting_a_mapping_that_is_not_here_is_not_found(self):
        with (
            patch(
                "app.services.directory.mappings.member_repo.get",
                new=AsyncMock(return_value=_membership("owner")),
            ),
            patch(
                "app.services.directory.mappings.directory_mapping_repo.get",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError),
        ):
            await DirectoryMappingService(_db()).delete(ORG, uuid.uuid4(), CALLER)

    async def test_a_lost_create_race_is_a_conflict(self):
        with (
            patch(
                "app.services.directory.mappings.member_repo.get",
                new=AsyncMock(return_value=_membership("owner")),
            ),
            patch(
                "app.services.directory.mappings.organization_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(is_personal=False)),
            ),
            patch("app.services.directory.mappings.directory_mapping_repo") as mappings,
            pytest.raises(AlreadyExistsError),
        ):
            mappings.get_by_external_group = AsyncMock(return_value=None)
            mappings.create = AsyncMock(side_effect=_race())
            await DirectoryMappingService(_db()).create(
                ORG, CALLER, DirectoryMappingCreate(external_group="g", role="viewer")
            )


class TestSmallContracts:
    def test_every_new_row_says_what_it_is(self):
        group_id, user_id = uuid.uuid4(), uuid.uuid4()

        assert "Finance" in repr(Group(id=group_id, organization_id=ORG, name="Finance"))
        assert "directory" in repr(
            GroupMember(group_id=group_id, user_id=user_id, source="directory")
        )
        assert "cn=g" in repr(
            DirectoryGroupMapping(organization_id=ORG, external_group="cn=g", role="member")
        )
        assert f"group:{group_id}" in repr(
            ResourceGrant(
                subject_group_id=group_id, resource_type="agent", resource_id=user_id, level="read"
            )
        )

    def test_a_username_of_only_spaces_is_refused(self):
        with pytest.raises(ValidationError):
            DirectoryLogin(username="   ", password="pw")

    @pytest.mark.parametrize(
        "body",
        [{}, {"subject_user_id": str(uuid.uuid4()), "subject_group_id": str(uuid.uuid4())}],
    )
    def test_a_share_names_exactly_one_subject(self, body):
        with pytest.raises(ValidationError):
            ResourceGrantUpsert(**body)

    @pytest.mark.parametrize("raw", [None, b"\xff\xfe\xfd", b"   "])
    def test_an_identifier_that_cannot_be_read_is_none(self, raw):
        assert _subject(raw) is None

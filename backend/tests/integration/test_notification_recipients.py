"""Who a notification write may reach, asked of Postgres rather than of a mock.

Two queries decide the recipients of every notification this platform writes
about a run, and each one is a security boundary the unit tests can only pin
the wiring of:

- `list_member_ids_for` - everything keyed on a *person*: the agent's owner,
  the run's initiator, and the ids an author typed into `AlertSpec.user_ids`.
  **Membership-scoped**, and that scoping is the whole point.
- `list_member_ids_by_role` - the organization's owners and admins.
- `list_app_admin_ids` - the deployment's superadmins, who hold no membership
  row anywhere and are therefore deliberately *not* scoped.

The failure this file exists for: `AlertSpec.user_ids` is written by whoever
may edit an agent. Resolved without the membership join, an author in one
organization could name a user id belonging to another and have them notified
of that organization's name, the agent's name, and what a run spent - every
one of which goes into `render_context`.

None of these take a preference argument (#1598): identity is resolved here,
independent of any channel's preference, which `NotificationCenterService`
applies afterward, per recipient, per channel - see
`tests/integration/test_notification_center.py` for that half.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.permissions import OrgRoleName
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import member as member_repo

pytestmark = pytest.mark.anyio


async def _user(
    db, *, email: str | None = None, is_active: bool = True, is_app_admin: bool = False
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email or f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=is_active,
        is_app_admin=is_app_admin,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db, *, name: str) -> Organization:
    """An organization with a founder, because `created_by_user_id` is NOT NULL.

    The founder holds no membership row, so it never appears in any result
    below - which is itself the point of the queries under test.
    """
    founder = await _user(db)
    organization = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _join(db, organization: Organization, user: User, role: str) -> None:
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=organization.id, user_id=user.id, role=role
        )
    )
    await db.flush()


class TestNamedRecipientsCannotCrossTenants:
    async def test_a_member_of_another_organization_resolves_to_no_id(self, db) -> None:
        """The regression. An id from another tenant must contribute nothing,
        and it must do so because the query cannot see them - not because
        something downstream filtered it out."""
        home = await _org(db, name="Home")
        other = await _org(db, name="Other")
        outsider = await _user(db)
        await _join(db, other, outsider, OrgRoleName.OWNER.value)

        ids = await member_repo.list_member_ids_for(
            db, organization_id=home.id, user_ids=[outsider.id]
        )

        assert ids == set()

    async def test_a_member_of_this_organization_does_resolve(self, db) -> None:
        """The other half: a scoping bug that refused everybody would pass the
        test above while silencing every notification on the platform."""
        home = await _org(db, name="Home")
        insider = await _user(db)
        await _join(db, home, insider, OrgRoleName.MEMBER.value)

        ids = await member_repo.list_member_ids_for(
            db, organization_id=home.id, user_ids=[insider.id]
        )

        assert ids == {insider.id}

    async def test_a_mixed_list_yields_only_the_members(self, db) -> None:
        """The realistic shape of the attack: one legitimate id to make the
        spec look ordinary, one foreign id alongside it."""
        home = await _org(db, name="Home")
        other = await _org(db, name="Other")
        insider = await _user(db)
        outsider = await _user(db)
        await _join(db, home, insider, OrgRoleName.MEMBER.value)
        await _join(db, other, outsider, OrgRoleName.OWNER.value)

        ids = await member_repo.list_member_ids_for(
            db, organization_id=home.id, user_ids=[insider.id, outsider.id]
        )

        assert ids == {insider.id}

    async def test_a_user_who_exists_but_belongs_to_no_organization_resolves_to_nothing(
        self, db
    ) -> None:
        """A registered account with no membership anywhere. The join, not the
        existence of the row, is what decides."""
        home = await _org(db, name="Home")
        stranger = await _user(db)

        ids = await member_repo.list_member_ids_for(
            db, organization_id=home.id, user_ids=[stranger.id]
        )

        assert ids == set()

    async def test_an_empty_list_asks_the_database_nothing(self, db) -> None:
        """`IN ()` is not valid SQL, and an audience naming nobody is the common case."""
        home = await _org(db, name="Home")

        assert (
            await member_repo.list_member_ids_for(db, organization_id=home.id, user_ids=[]) == set()
        )

    async def test_a_deactivated_member_is_not_resolved(self, db) -> None:
        """Deactivation is how an account is taken away; being notified is part
        of what it takes."""
        home = await _org(db, name="Home")
        gone = await _user(db, is_active=False)
        await _join(db, home, gone, OrgRoleName.MEMBER.value)

        ids = await member_repo.list_member_ids_for(db, organization_id=home.id, user_ids=[gone.id])

        assert ids == set()


class TestTheDeploymentsAppAdmins:
    """Deliberately not membership-scoped, which is why it needs its own tests.

    `get_auth_context` admits an app admin to an organization they are not a
    member of, so a query joined to `organization_members` would silently omit
    exactly the person who is supposed to hear when something runs out of
    money.
    """

    async def test_an_app_admin_with_no_membership_anywhere_is_still_found(self, db) -> None:
        await _org(db, name="Home")
        root = await _user(db, is_app_admin=True)

        ids = await member_repo.list_app_admin_ids(db)

        assert root.id in ids

    async def test_an_ordinary_member_is_not_an_app_admin(self, db) -> None:
        home = await _org(db, name="Home")
        member = await _user(db)
        await _join(db, home, member, OrgRoleName.OWNER.value)

        ids = await member_repo.list_app_admin_ids(db)

        assert member.id not in ids

    async def test_a_deactivated_app_admin_is_not_returned(self, db) -> None:
        gone = await _user(db, is_app_admin=True, is_active=False)

        ids = await member_repo.list_app_admin_ids(db)

        assert gone.id not in ids


class TestTheRoleQuery:
    async def test_only_owners_and_admins_answer_for_the_spend(self, db) -> None:
        """A builder can create an agent but is not who gets called when the
        organization's month runs out."""
        home = await _org(db, name="Home")
        owner = await _user(db)
        builder = await _user(db)
        await _join(db, home, owner, OrgRoleName.OWNER.value)
        await _join(db, home, builder, OrgRoleName.BUILDER.value)

        ids = await member_repo.list_member_ids_by_role(
            db, organization_id=home.id, roles=[OrgRoleName.OWNER.value, OrgRoleName.ADMIN.value]
        )

        assert ids == [owner.id]

    async def test_another_organizations_owner_is_not_this_organizations_admin(self, db) -> None:
        home = await _org(db, name="Home")
        other = await _org(db, name="Other")
        outsider = await _user(db)
        await _join(db, other, outsider, OrgRoleName.OWNER.value)

        ids = await member_repo.list_member_ids_by_role(
            db, organization_id=home.id, roles=[OrgRoleName.OWNER.value, OrgRoleName.ADMIN.value]
        )

        assert ids == []

    async def test_a_deactivated_member_does_not_answer_for_the_role(self, db) -> None:
        home = await _org(db, name="Home")
        gone = await _user(db, is_active=False)
        await _join(db, home, gone, OrgRoleName.OWNER.value)

        ids = await member_repo.list_member_ids_by_role(
            db, organization_id=home.id, roles=[OrgRoleName.OWNER.value]
        )

        assert ids == []

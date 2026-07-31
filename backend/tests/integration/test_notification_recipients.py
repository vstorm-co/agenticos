"""Who an alert may reach, asked of Postgres rather than of a mock.

Three queries decide the recipients of every email this platform sends about a
run, and each one is a security boundary the unit tests can only pin the wiring
of:

- `list_emails_for_members` - everything keyed on a *person*: the agent's owner,
  the run's initiator, and the ids an author typed into `AlertSpec.user_ids`.
  **Membership-scoped**, and that scoping is the whole point.
- `list_emails_by_role` - the organization's owners and admins.
- `list_app_admin_emails` - the deployment's superadmins, who hold no membership
  row anywhere and are therefore deliberately *not* scoped.

The failure this file exists for: `AlertSpec.user_ids` is written by whoever may
edit an agent. Resolved without the membership join, an author in one
organization could name a user id belonging to another and have them mailed that
organization's name, the agent's name, and what a run spent - every one of which
goes into the email body.
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
    db,
    *,
    email: str | None = None,
    is_active: bool = True,
    is_app_admin: bool = False,
    notify_budget_alerts: bool = True,
    notify_approval_requests: bool = True,
    notify_usage_reports: bool = True,
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email or f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=is_active,
        is_app_admin=is_app_admin,
        notify_budget_alerts=notify_budget_alerts,
        notify_approval_requests=notify_approval_requests,
        notify_usage_reports=notify_usage_reports,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db, *, name: str) -> Organization:
    """An organization with a founder, because `created_by_user_id` is NOT NULL.

    The founder holds no membership row, so it never appears in any result below -
    which is itself the point of the queries under test.
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
            id=uuid.uuid4(),
            organization_id=organization.id,
            user_id=user.id,
            role=role,
        )
    )
    await db.flush()


class TestNamedRecipientsCannotCrossTenants:
    async def test_a_member_of_another_organization_resolves_to_no_address(self, db) -> None:
        """The regression. An id from another tenant must contribute nothing, and
        it must do so because the query cannot see them - not because something
        downstream filtered the address out."""
        home = await _org(db, name="Home")
        other = await _org(db, name="Other")
        outsider = await _user(db, email="outsider@other.test")
        await _join(db, other, outsider, OrgRoleName.OWNER.value)

        addresses = await member_repo.list_emails_for_members(
            db,
            organization_id=home.id,
            user_ids=[outsider.id],
            preference="notify_approval_requests",
        )

        assert addresses == []

    async def test_a_member_of_this_organization_does_resolve(self, db) -> None:
        """The other half: a scoping bug that refused everybody would pass the test
        above while silencing every alert on the platform."""
        home = await _org(db, name="Home")
        insider = await _user(db, email="insider@home.test")
        await _join(db, home, insider, OrgRoleName.MEMBER.value)

        addresses = await member_repo.list_emails_for_members(
            db,
            organization_id=home.id,
            user_ids=[insider.id],
            preference="notify_approval_requests",
        )

        assert addresses == ["insider@home.test"]

    async def test_a_mixed_list_yields_only_the_members(self, db) -> None:
        """The realistic shape of the attack: one legitimate id to make the spec
        look ordinary, one foreign id alongside it."""
        home = await _org(db, name="Home")
        other = await _org(db, name="Other")
        insider = await _user(db, email="insider@home.test")
        outsider = await _user(db, email="outsider@other.test")
        await _join(db, home, insider, OrgRoleName.MEMBER.value)
        await _join(db, other, outsider, OrgRoleName.OWNER.value)

        addresses = await member_repo.list_emails_for_members(
            db,
            organization_id=home.id,
            user_ids=[insider.id, outsider.id],
            preference="notify_approval_requests",
        )

        assert addresses == ["insider@home.test"]

    async def test_a_user_who_exists_but_belongs_to_no_organization_resolves_to_nothing(
        self, db
    ) -> None:
        """A registered account with no membership anywhere. The join, not the
        existence of the row, is what decides."""
        home = await _org(db, name="Home")
        stranger = await _user(db, email="stranger@nowhere.test")

        addresses = await member_repo.list_emails_for_members(
            db,
            organization_id=home.id,
            user_ids=[stranger.id],
            preference="notify_approval_requests",
        )

        assert addresses == []

    async def test_an_empty_list_asks_the_database_nothing(self, db) -> None:
        """`IN ()` is not valid SQL, and an audience naming nobody is the common case."""
        home = await _org(db, name="Home")

        assert (
            await member_repo.list_emails_for_members(
                db, organization_id=home.id, user_ids=[], preference="notify_budget_alerts"
            )
            == []
        )


class TestNamedRecipientsHonourTheirOwnSwitches:
    async def test_a_deactivated_member_is_not_mailed(self, db) -> None:
        """Deactivation is how an account is taken away; mail is part of what it takes."""
        home = await _org(db, name="Home")
        gone = await _user(db, email="gone@home.test", is_active=False)
        await _join(db, home, gone, OrgRoleName.MEMBER.value)

        addresses = await member_repo.list_emails_for_members(
            db,
            organization_id=home.id,
            user_ids=[gone.id],
            preference="notify_budget_alerts",
        )

        assert addresses == []

    async def test_the_named_preference_is_the_one_consulted(self, db) -> None:
        """A member who declined budget mail but still wants approvals. Reading the
        wrong column would honour one opt-out by silencing a different email, and
        every address involved would still look plausible."""
        home = await _org(db, name="Home")
        picky = await _user(
            db,
            email="picky@home.test",
            notify_budget_alerts=False,
            notify_approval_requests=True,
        )
        await _join(db, home, picky, OrgRoleName.MEMBER.value)

        assert (
            await member_repo.list_emails_for_members(
                db,
                organization_id=home.id,
                user_ids=[picky.id],
                preference="notify_budget_alerts",
            )
            == []
        )
        assert await member_repo.list_emails_for_members(
            db,
            organization_id=home.id,
            user_ids=[picky.id],
            preference="notify_approval_requests",
        ) == ["picky@home.test"]

    async def test_without_a_preference_only_membership_and_activity_matter(self, db) -> None:
        """The argument is optional, and omitting it must not quietly drop the
        other two conditions."""
        home = await _org(db, name="Home")
        opted_out = await _user(db, email="opted-out@home.test", notify_budget_alerts=False)
        await _join(db, home, opted_out, OrgRoleName.MEMBER.value)

        addresses = await member_repo.list_emails_for_members(
            db, organization_id=home.id, user_ids=[opted_out.id]
        )

        assert addresses == ["opted-out@home.test"]


class TestTheDeploymentsAppAdmins:
    """Deliberately not membership-scoped, which is why it needs its own tests.

    `get_auth_context` admits an app admin to an organization they are not a
    member of, so a query joined to `organization_members` would silently omit
    exactly the person who is supposed to hear when something runs out of money.
    """

    async def test_an_app_admin_with_no_membership_anywhere_is_still_found(self, db) -> None:
        await _org(db, name="Home")
        root = await _user(db, email="root@platform.test", is_app_admin=True)

        addresses = await member_repo.list_app_admin_emails(db, preference="notify_budget_alerts")

        assert root.email in addresses

    async def test_an_ordinary_member_is_not_an_app_admin(self, db) -> None:
        home = await _org(db, name="Home")
        member = await _user(db, email="member@home.test")
        await _join(db, home, member, OrgRoleName.OWNER.value)

        addresses = await member_repo.list_app_admin_emails(db)

        assert member.email not in addresses

    async def test_a_deactivated_app_admin_is_not_mailed(self, db) -> None:
        gone = await _user(db, email="gone-root@platform.test", is_app_admin=True, is_active=False)

        addresses = await member_repo.list_app_admin_emails(db)

        assert gone.email not in addresses

    async def test_an_app_admin_who_declined_this_kind_of_mail_is_left_out(self, db) -> None:
        """Their flag reaches every organization; it does not override their inbox."""
        quiet = await _user(
            db,
            email="quiet-root@platform.test",
            is_app_admin=True,
            notify_usage_reports=False,
        )

        assert quiet.email not in await member_repo.list_app_admin_emails(
            db, preference="notify_usage_reports"
        )
        # Still reachable for the kinds they did not decline.
        assert quiet.email in await member_repo.list_app_admin_emails(
            db, preference="notify_budget_alerts"
        )


class TestTheRoleQuery:
    async def test_only_owners_and_admins_answer_for_the_spend(self, db) -> None:
        """A builder can create an agent but is not who gets called when the
        organization's month runs out."""
        home = await _org(db, name="Home")
        owner = await _user(db, email="owner@home.test")
        builder = await _user(db, email="builder@home.test")
        await _join(db, home, owner, OrgRoleName.OWNER.value)
        await _join(db, home, builder, OrgRoleName.BUILDER.value)

        addresses = await member_repo.list_emails_by_role(
            db,
            organization_id=home.id,
            roles=[OrgRoleName.OWNER.value, OrgRoleName.ADMIN.value],
            preference="notify_budget_alerts",
        )

        assert addresses == ["owner@home.test"]

    async def test_another_organizations_owner_is_not_this_organizations_admin(self, db) -> None:
        home = await _org(db, name="Home")
        other = await _org(db, name="Other")
        outsider = await _user(db, email="owner@other.test")
        await _join(db, other, outsider, OrgRoleName.OWNER.value)

        addresses = await member_repo.list_emails_by_role(
            db,
            organization_id=home.id,
            roles=[OrgRoleName.OWNER.value, OrgRoleName.ADMIN.value],
        )

        assert addresses == []

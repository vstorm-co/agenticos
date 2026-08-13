"""What role a public surface's turn takes, against real rows.

`publisher_context` is the one answer to "who does an anonymous turn run as", and
what it reads has to be a *join*: a membership row survives its user being
deactivated, so a role read off the membership alone is the authority of an account
that is refused everywhere a person signs in. That is a two-table fact, so a mocked
session cannot show it - `member_repo.get` and `member_repo.get_active` return the
same stand-in to a `MagicMock` whatever the SQL says.

Three rows, three answers, and the middle one is the defect: still a member, still
recorded, and no longer able to sign in.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.permissions import OrgRoleName
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services.access import publisher_context

pytestmark = pytest.mark.anyio


async def _user(db, *, is_active: bool) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db) -> Organization:
    founder = await _user(db, is_active=True)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _member(db, organization: Organization, user: User, role: str) -> None:
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=organization.id, user_id=user.id, role=role
        )
    )
    await db.flush()


class TestWhichRoleAnAnonymousTurnBorrows:
    async def test_a_publisher_who_can_still_sign_in_lends_their_role(self, db) -> None:
        organization = await _org(db)
        publisher = await _user(db, is_active=True)
        await _member(db, organization, publisher, OrgRoleName.OWNER.value)

        ctx = await publisher_context(
            db, organization_id=organization.id, publisher_user_id=publisher.id
        )

        assert ctx.role == OrgRoleName.OWNER.value

    async def test_a_deactivated_publisher_lends_nothing(self, db) -> None:
        """The row that made this worth an integration test. Deactivating a user
        leaves their membership exactly where it was, so their widget, hosted page
        and channel binding kept answering at Owner while the account itself was
        refused on every path a person signs in through.
        """
        organization = await _org(db)
        publisher = await _user(db, is_active=False)
        await _member(db, organization, publisher, OrgRoleName.OWNER.value)

        ctx = await publisher_context(
            db, organization_id=organization.id, publisher_user_id=publisher.id
        )

        assert ctx.role == OrgRoleName.VIEWER.value
        assert ctx.user_id == publisher.id, "still the honest record of who published"

    async def test_a_publisher_who_left_lends_nothing(self, db) -> None:
        organization = await _org(db)
        publisher = await _user(db, is_active=True)

        ctx = await publisher_context(
            db, organization_id=organization.id, publisher_user_id=publisher.id
        )

        assert ctx.role == OrgRoleName.VIEWER.value

    async def test_a_membership_in_another_organization_lends_nothing_here(self, db) -> None:
        """The join must not widen what the tenant check already decided."""
        theirs, ours = await _org(db), await _org(db)
        publisher = await _user(db, is_active=True)
        await _member(db, theirs, publisher, OrgRoleName.OWNER.value)

        ctx = await publisher_context(db, organization_id=ours.id, publisher_user_id=publisher.id)

        assert ctx.role == OrgRoleName.VIEWER.value

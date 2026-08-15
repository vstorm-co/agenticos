"""Which owner an admin's organization listing names, asked of a real Postgres.

The owner arrives through a `DISTINCT ON` subquery outer-joined onto the
listing, and three things about that only a database answers: that an
organization with several owners contributes one row rather than duplicating
itself, that the one it contributes is the earliest to have joined, and that an
organization with no owner at all still appears - with nulls - instead of being
dropped by the join. A listing that quietly loses a tenant is the worst of the
three, because the deployment admin is the only person able to see it at all.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.permissions import OrgRoleName
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services.admin import AdminService

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


async def _user(db, *, full_name: str | None = None) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        full_name=full_name,
        hashed_password="x",
        is_active=True,
        created_at=NOW,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db, name: str) -> Organization:
    creator = await _user(db)
    organization = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        is_personal=False,
        created_by_user_id=creator.id,
        created_at=NOW,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _join(db, organization: Organization, user: User, role: str, at: datetime) -> None:
    db.add(
        OrganizationMember(
            id=uuid.uuid4(),
            organization_id=organization.id,
            user_id=user.id,
            role=role,
            joined_at=at,
        )
    )
    await db.flush()


def _row(items: list[dict], organization: Organization) -> dict:
    match = [item for item in items if item["id"] == organization.id]
    assert len(match) == 1, f"expected one row for {organization.name}, got {len(match)}"
    return match[0]


class TestTheOwnerColumn:
    async def test_the_earliest_owner_is_named_once(self, db) -> None:
        organization = await _org(db, "Acme")
        founder = await _user(db, full_name="Ada Founder")
        second = await _user(db, full_name="Bo Later")
        await _join(db, organization, founder, OrgRoleName.OWNER.value, NOW)
        await _join(db, organization, second, OrgRoleName.OWNER.value, NOW + timedelta(days=30))

        result = await AdminService(db).list_organizations(limit=100)

        # One row, not two: the join must not multiply a tenant by its owners.
        row = _row(result["items"], organization)
        assert row["owner_user_id"] == founder.id
        assert row["owner_name"] == "Ada Founder"
        assert row["member_count"] == 2

    async def test_a_member_is_never_mistaken_for_the_owner(self, db) -> None:
        organization = await _org(db, "Beta")
        member = await _user(db, full_name="Early Member")
        owner = await _user(db, full_name="Late Owner")
        # The member joined first, so an owner picked by join order alone -
        # without the role condition - would be this one.
        await _join(db, organization, member, OrgRoleName.MEMBER.value, NOW)
        await _join(db, organization, owner, OrgRoleName.OWNER.value, NOW + timedelta(days=1))

        result = await AdminService(db).list_organizations(limit=100)

        assert _row(result["items"], organization)["owner_user_id"] == owner.id

    async def test_an_organization_with_no_owner_is_still_listed(self, db) -> None:
        organization = await _org(db, "Orphan")
        stray = await _user(db)
        await _join(db, organization, stray, OrgRoleName.MEMBER.value, NOW)

        result = await AdminService(db).list_organizations(limit=100)

        row = _row(result["items"], organization)
        assert (row["owner_user_id"], row["owner_email"], row["owner_name"]) == (None, None, None)
        assert row["member_count"] == 1

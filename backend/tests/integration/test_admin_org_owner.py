"""The admin's organization listing, asked of a real Postgres.

The owner arrives through a `DISTINCT ON` subquery outer-joined onto the
listing, and three things about that only a database answers: that an
organization with several owners contributes one row rather than duplicating
itself, that the one it contributes is the earliest to have joined, and that an
organization with no owner at all still appears - with nulls - instead of being
dropped by the join. A listing that quietly loses a tenant is the worst of the
three, because the deployment admin is the only person able to see it at all.

The narrowing and the ordering are here for the same reason: both happen in SQL
before `OFFSET`/`LIMIT` (#921), so what they do to a page is a question only a
database answers - a unit test over a mocked session sees the arguments and not
the rows they select.
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


async def _org(
    db,
    name: str,
    *,
    is_personal: bool = False,
    created_at: datetime = NOW,
    slug: str | None = None,
) -> Organization:
    creator = await _user(db)
    organization = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=slug or f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        is_personal=is_personal,
        created_by_user_id=creator.id,
        created_at=created_at,
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


async def _owned_by(db, organization: Organization, email: str) -> User:
    """Give an organization one owner with a known address."""
    owner = User(
        id=uuid.uuid4(),
        email=email,
        full_name=None,
        hashed_password="x",
        is_active=True,
        created_at=NOW,
    )
    db.add(owner)
    await db.flush()
    await _join(db, organization, owner, OrgRoleName.OWNER.value, NOW)
    return owner


def _names(result: dict) -> list[str]:
    """The names the listing came back with, in order.

    Every table is emptied between integration tests, so the page holds exactly
    what this test made and the order is the whole assertion.
    """
    return [item["name"] for item in result["items"]]


class TestNarrowingTheListing:
    async def test_search_matches_a_name_a_slug_and_an_owners_address(self, db) -> None:
        await _org(db, "Contoso")
        await _org(db, "Northwind", slug=f"contoso-supply-{uuid.uuid4().hex[:8]}")
        by_owner = await _org(db, "Initech")
        await _owned_by(db, by_owner, f"finance@contoso-{uuid.uuid4().hex[:6]}.test")
        # The one that matches on nothing, so a search that quietly matched
        # everything would fail here.
        await _org(db, "Umbrella")

        result = await AdminService(db).list_organizations(search="contoso", limit=100)

        assert set(_names(result)) == {"Contoso", "Northwind", "Initech"}

    async def test_a_search_term_is_text_rather_than_a_pattern(self, db) -> None:
        # A lone `%` matched every row before `contains_ci` (#372), and this
        # listing is the one a deployment admin uses to find a tenant.
        literal = await _org(db, f"100% Ltd {uuid.uuid4().hex[:6]}")
        await _org(db, "Plain Ltd")

        result = await AdminService(db).list_organizations(search="100%", limit=100)

        assert _names(result) == [literal.name]

    async def test_the_kind_filter_separates_personal_from_team(self, db) -> None:
        await _org(db, "Ada", is_personal=True)
        await _org(db, "Acme Team")

        service = AdminService(db)

        assert _names(await service.list_organizations(kind="personal", limit=100)) == ["Ada"]
        assert _names(await service.list_organizations(kind="team", limit=100)) == ["Acme Team"]
        assert set(_names(await service.list_organizations(limit=100))) == {
            "Ada",
            "Acme Team",
        }

    async def test_the_total_counts_what_was_narrowed_to(self, db) -> None:
        """Not the deployment's whole population - a pager reading the unfiltered
        count offers pages of rows the filter removed."""
        personal = await _org(db, f"Solo {uuid.uuid4().hex[:6]}", is_personal=True)
        await _org(db, "Acme")
        await _org(db, "Initech")

        narrowed = await AdminService(db).list_organizations(
            search=personal.name, kind="personal", limit=100
        )
        everything = await AdminService(db).list_organizations(limit=100)

        assert narrowed["total"] == 1
        assert everything["total"] == 3


class TestOrderingTheListing:
    async def test_sorting_by_name_orders_the_collection_not_the_page(self, db) -> None:
        stamp = uuid.uuid4().hex[:6]
        # Created newest-first in the order that would come back under the
        # default sort, so an ordering that quietly did nothing would fail here.
        zulu = await _org(db, f"Zulu {stamp}", created_at=NOW)
        alpha = await _org(db, f"Alpha {stamp}", created_at=NOW + timedelta(days=1))
        mike = await _org(db, f"Mike {stamp}", created_at=NOW + timedelta(days=2))

        result = await AdminService(db).list_organizations(
            search=stamp, sort_by="name", sort_dir="asc", limit=100
        )

        assert _names(result) == [alpha.name, mike.name, zulu.name]

    async def test_sorting_by_members_orders_on_the_joined_count(self, db) -> None:
        """The count is a subquery's column, not one of the table's - an order
        naming it has to reach the join rather than the model."""
        stamp = uuid.uuid4().hex[:6]
        crowded = await _org(db, f"Crowded {stamp}")
        quiet = await _org(db, f"Quiet {stamp}")
        for _ in range(3):
            await _join(db, crowded, await _user(db), OrgRoleName.MEMBER.value, NOW)
        await _join(db, quiet, await _user(db), OrgRoleName.MEMBER.value, NOW)

        result = await AdminService(db).list_organizations(
            search=stamp, sort_by="members", sort_dir="desc", limit=100
        )

        assert _names(result) == [crowded.name, quiet.name]

    async def test_paging_a_tie_lists_every_row_once(self, db) -> None:
        """Three organizations with the same member count and no tiebreak is an
        order the planner chooses, so a row can appear on two pages or on none."""
        stamp = uuid.uuid4().hex[:6]
        made = [await _org(db, f"Tied {stamp} {index}") for index in range(3)]
        service = AdminService(db)

        first = await service.list_organizations(search=stamp, sort_by="members", limit=2)
        second = await service.list_organizations(search=stamp, sort_by="members", skip=2, limit=2)

        seen = [item["id"] for item in first["items"] + second["items"]]
        assert sorted(seen, key=str) == sorted((org.id for org in made), key=str)

    async def test_an_unknown_column_falls_back_rather_than_reaching_the_database(self, db) -> None:
        # The route refuses one with a 422; the repository is the second line,
        # and what it must never do is interpolate the string into an ORDER BY.
        stamp = uuid.uuid4().hex[:6]
        organization = await _org(db, f"Fallback {stamp}")

        result = await AdminService(db).list_organizations(
            search=stamp, sort_by="; drop table organizations", limit=100
        )

        assert _names(result) == [organization.name]

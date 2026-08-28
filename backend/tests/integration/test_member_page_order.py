"""Paging through an organization's members cannot show one twice.

`useMembers` reads every page to fill the conversation share picker, so the order
the pages come back in has to be total. It was `joined_at` alone - and two people
invited in one request share it, Postgres is free to return tied rows in either
order, and a page boundary falling inside a tie shows one member twice and another
never: a colleague who cannot be shared with (#931).

Here rather than in the unit suite because what an unstable `ORDER BY` does is
Postgres's answer, not a mock's.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import member as member_repo

pytestmark = pytest.mark.anyio

# One instant for every row, which is the case the tie-breaker exists for.
JOINED = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


async def _org(db) -> Organization:
    founder = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(founder)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _member(db, organization: Organization, index: int) -> OrganizationMember:
    user = User(
        id=uuid.uuid4(),
        email=f"member-{index:03d}-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    row = OrganizationMember(
        id=uuid.uuid4(),
        organization_id=organization.id,
        user_id=user.id,
        role="member",
        joined_at=JOINED,
    )
    db.add(row)
    await db.flush()
    return row


async def test_every_member_appears_once_across_the_pages(db) -> None:
    organization = await _org(db)
    for index in range(25):
        await _member(db, organization, index)

    seen: list[uuid.UUID] = []
    for skip in range(0, 25, 5):
        page = await member_repo.list_for_org(db, organization.id, skip=skip, limit=5)
        seen.extend(row[0].user_id for row in page)

    assert len(seen) == 25
    assert len(set(seen)) == 25


async def test_the_same_page_comes_back_the_same_way_twice(db) -> None:
    """A tie is only unstable if the order is; asked twice, one page is one page."""
    organization = await _org(db)
    for index in range(10):
        await _member(db, organization, index)

    first = await member_repo.list_for_org(db, organization.id, skip=5, limit=5)
    again = await member_repo.list_for_org(db, organization.id, skip=5, limit=5)

    assert [row[0].id for row in first] == [row[0].id for row in again]

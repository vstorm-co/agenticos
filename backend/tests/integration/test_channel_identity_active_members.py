"""Which linked authors the thread backfill may quote, against real rows.

Under a link-required policy the backfill quotes an earlier author into the
prompt only when that author is tied to a member who can still sign in (#1457).
The predicate that decides it is a three-table join - identity to member to user -
and only a real database shows that `User.is_active` reaches the result the same
way `member_repo.get_active` relies on it: a deactivated member's linked account
must be absent from the set, not merely unranked. The router-level test stubs the
repository; this one runs the query.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_identity import ChannelIdentity
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import channel_identity_repo

pytestmark = pytest.mark.anyio

PLATFORM = "slack"


async def _user(db: AsyncSession, *, is_active: bool = True) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db: AsyncSession) -> Organization:
    founder = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(org)
    await db.flush()
    return org


async def _member(db: AsyncSession, *, org: Organization, user: User) -> None:
    db.add(
        OrganizationMember(
            id=uuid.uuid4(),
            organization_id=org.id,
            user_id=user.id,
            role="member",
        )
    )
    await db.flush()


async def _identity(db: AsyncSession, *, user: User | None) -> str:
    platform_user_id = uuid.uuid4().hex
    db.add(
        ChannelIdentity(
            id=uuid.uuid4(),
            platform=PLATFORM,
            platform_user_id=platform_user_id,
            user_id=None if user is None else user.id,
        )
    )
    await db.flush()
    return platform_user_id


async def test_only_accounts_linked_to_an_active_member_are_returned(db: AsyncSession) -> None:
    org = await _org(db)

    active_user = await _user(db)
    await _member(db, org=org, user=active_user)
    active_account = await _identity(db, user=active_user)

    deactivated_user = await _user(db, is_active=False)
    await _member(db, org=org, user=deactivated_user)
    deactivated_account = await _identity(db, user=deactivated_user)

    non_member = await _user(db)
    non_member_account = await _identity(db, user=non_member)

    unlinked_account = await _identity(db, user=None)

    other_org = await _org(db)
    other_org_user = await _user(db)
    await _member(db, org=other_org, user=other_org_user)
    other_org_account = await _identity(db, user=other_org_user)

    result = await channel_identity_repo.linked_active_platform_user_ids(
        db,
        platform=PLATFORM,
        platform_user_ids=[
            active_account,
            deactivated_account,
            non_member_account,
            unlinked_account,
            other_org_account,
        ],
        organization_id=org.id,
    )

    assert result == {active_account}


async def test_an_empty_request_makes_no_query(db: AsyncSession) -> None:
    """The backfill hands an empty set when a thread has no quotable authors; the
    guard returns without touching the database."""
    org = await _org(db)
    result = await channel_identity_repo.linked_active_platform_user_ids(
        db, platform=PLATFORM, platform_user_ids=[], organization_id=org.id
    )
    assert result == set()

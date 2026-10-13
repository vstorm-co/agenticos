"""The organization listing's role and member counts, in grouped queries (#953).

`list_for_user` returns each organization with the role off the same membership
row it joins on, and `member_counts_for` counts a whole page of organizations in
one grouped read - both replacing a query per row. Only a real database shows
the join carries the role and the `GROUP BY` keys the counts correctly.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.db.models.organization import Organization, OrganizationMember, OrgRole
from app.db.models.user import User
from app.repositories import organization as organization_repo

pytestmark = pytest.mark.anyio


async def _user(db: Any) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db: Any, creator: User, *, name: str, is_personal: bool = False) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        is_personal=is_personal,
        created_by_user_id=creator.id,
    )
    db.add(org)
    await db.flush()
    return org


async def _member(db: Any, org: Organization, user: User, role: str) -> None:
    db.add(OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role=role))
    await db.flush()


async def test_list_for_user_carries_the_membership_role(db: Any) -> None:
    user = await _user(db)
    owned = await _org(db, user, name="Owned")
    joined_creator = await _user(db)
    joined = await _org(db, joined_creator, name="Joined")
    await _member(db, owned, user, OrgRole.OWNER.value)
    await _member(db, joined, user, OrgRole.MEMBER.value)

    pairs = await organization_repo.list_for_user(db, user.id)

    by_name = {org.name: role for org, role in pairs}
    assert by_name == {"Owned": OrgRole.OWNER.value, "Joined": OrgRole.MEMBER.value}


async def test_member_counts_for_groups_by_organization(db: Any) -> None:
    founder = await _user(db)
    big = await _org(db, founder, name="Big")
    small = await _org(db, founder, name="Small")
    await _member(db, big, founder, OrgRole.OWNER.value)
    await _member(db, big, await _user(db), OrgRole.MEMBER.value)
    await _member(db, small, founder, OrgRole.OWNER.value)

    counts = await organization_repo.member_counts_for(db, [big.id, small.id])

    assert counts == {big.id: 2, small.id: 1}


async def test_member_counts_for_no_ids_asks_nothing(db: Any) -> None:
    assert await organization_repo.member_counts_for(db, []) == {}

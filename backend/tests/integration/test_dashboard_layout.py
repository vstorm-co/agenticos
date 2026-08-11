"""Guarantees the dashboard-layout table makes that only a database can.

The preference is keyed on `(user_id, organization_id)`, and the point of the
composite key is isolation: the same person is a steward in one organization and
a member in another, so their saved layout in one must never surface in the
other - and that is true even though they *own* the row, which is the case a
per-user check would wave through. Alongside that: one row per person per org,
and no orphan preference left behind when either side is deleted.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.dashboard_layout import DashboardLayout
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import dashboard_layout_repo

pytestmark = pytest.mark.anyio


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db, *, owner: User) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=owner.id, role="owner")
    )
    await db.flush()
    return org


async def test_the_same_person_gets_a_different_layout_in_each_organization(db) -> None:
    person = await _user(db)
    org_a = await _org(db, owner=person)
    org_b = await _org(db, owner=person)

    await dashboard_layout_repo.upsert(
        db, user_id=person.id, organization_id=org_a.id, entries=[{"widget": "runs", "span": "s8"}]
    )
    await dashboard_layout_repo.upsert(
        db, user_id=person.id, organization_id=org_b.id, entries=[{"widget": "spend", "span": "s6"}]
    )

    in_a = await dashboard_layout_repo.get(db, user_id=person.id, organization_id=org_a.id)
    in_b = await dashboard_layout_repo.get(db, user_id=person.id, organization_id=org_b.id)
    assert in_a is not None and in_a.entries == [{"widget": "runs", "span": "s8"}]
    assert in_b is not None and in_b.entries == [{"widget": "spend", "span": "s6"}]


async def test_a_second_save_replaces_the_row_rather_than_conflicting(db) -> None:
    # The write is `INSERT ... ON CONFLICT DO UPDATE`, so a second save for a
    # `(user, org)` that already has a row updates it in place. A read-then-insert
    # raced against itself here — two first saves both seeing no row, the second
    # hitting `uq_dashboard_layout_user_org` as an untranslated 500.
    person = await _user(db)
    org = await _org(db, owner=person)

    await dashboard_layout_repo.upsert(
        db, user_id=person.id, organization_id=org.id, entries=[{"widget": "runs", "span": "s8"}]
    )
    await dashboard_layout_repo.upsert(
        db, user_id=person.id, organization_id=org.id, entries=[{"widget": "spend", "span": "s6"}]
    )

    rows = (
        (
            await db.execute(
                select(DashboardLayout).where(
                    DashboardLayout.user_id == person.id,
                    DashboardLayout.organization_id == org.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].entries == [{"widget": "spend", "span": "s6"}]


async def test_a_layout_saved_in_one_org_is_invisible_in_another_even_to_its_owner(db) -> None:
    person = await _user(db)
    org_a = await _org(db, owner=person)
    org_b = await _org(db, owner=person)

    await dashboard_layout_repo.upsert(
        db, user_id=person.id, organization_id=org_a.id, entries=[{"widget": "runs", "span": "s8"}]
    )

    # Same caller, different active organization: the row they own in org_a must
    # not answer here.
    assert await dashboard_layout_repo.get(db, user_id=person.id, organization_id=org_b.id) is None


async def test_only_one_layout_may_exist_per_person_per_org(db) -> None:
    person = await _user(db)
    org = await _org(db, owner=person)
    db.add(DashboardLayout(user_id=person.id, organization_id=org.id, entries=[]))
    await db.flush()
    db.add(DashboardLayout(user_id=person.id, organization_id=org.id, entries=[]))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_deleting_the_member_removes_their_layout(db) -> None:
    owner = await _user(db)
    org = await _org(db, owner=owner)
    member = await _user(db)
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=org.id, user_id=member.id, role="member"
        )
    )
    await db.flush()
    await dashboard_layout_repo.upsert(
        db,
        user_id=member.id,
        organization_id=org.id,
        entries=[{"widget": "my-agents", "span": "s6"}],
    )

    await db.delete(member)
    await db.flush()

    remaining = (
        (await db.execute(select(DashboardLayout).where(DashboardLayout.user_id == member.id)))
        .scalars()
        .all()
    )
    assert remaining == []


async def test_deleting_the_organization_removes_the_layout(db) -> None:
    owner = await _user(db)
    org = await _org(db, owner=owner)
    await dashboard_layout_repo.upsert(
        db, user_id=owner.id, organization_id=org.id, entries=[{"widget": "runs", "span": "s8"}]
    )

    await db.delete(org)
    await db.flush()

    remaining = (
        (await db.execute(select(DashboardLayout).where(DashboardLayout.organization_id == org.id)))
        .scalars()
        .all()
    )
    assert remaining == []

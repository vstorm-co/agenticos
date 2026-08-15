"""Guarantees the dashboard-preset table makes that only a database can.

Presets share the layout's tenant boundary — `(user_id, organization_id)` —
plus a name unique inside that pair. What matters here: the same person can
keep a "Monday review" in each of their organizations without collision, a
preset saved in one organization never lists in another even for its owner,
the duplicate name is refused by the constraint and not only by the service,
and deleting either side of the key leaves no orphan preset behind.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.dashboard_preset import DashboardPreset
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import dashboard_preset_repo

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


async def test_the_same_name_may_exist_once_per_organization(db) -> None:
    person = await _user(db)
    org_a = await _org(db, owner=person)
    org_b = await _org(db, owner=person)

    await dashboard_preset_repo.create(
        db,
        user_id=person.id,
        organization_id=org_a.id,
        name="Monday review",
        entries=[{"widget": "runs", "span": "s8", "rows": "r3"}],
    )
    await dashboard_preset_repo.create(
        db,
        user_id=person.id,
        organization_id=org_b.id,
        name="Monday review",
        entries=[{"widget": "spend", "span": "s6", "rows": None}],
    )

    in_a = await dashboard_preset_repo.get_by_name(
        db, user_id=person.id, organization_id=org_a.id, name="Monday review"
    )
    in_b = await dashboard_preset_repo.get_by_name(
        db, user_id=person.id, organization_id=org_b.id, name="Monday review"
    )
    assert in_a is not None and in_a.entries == [{"widget": "runs", "span": "s8", "rows": "r3"}]
    assert in_b is not None and in_b.entries == [{"widget": "spend", "span": "s6", "rows": None}]


async def test_a_duplicate_name_in_one_organization_is_refused_by_the_database(db) -> None:
    person = await _user(db)
    org = await _org(db, owner=person)
    db.add(
        DashboardPreset(user_id=person.id, organization_id=org.id, name="Monday review", entries=[])
    )
    await db.flush()
    db.add(
        DashboardPreset(user_id=person.id, organization_id=org.id, name="Monday review", entries=[])
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_a_preset_saved_in_one_org_is_invisible_in_another_even_to_its_owner(db) -> None:
    person = await _user(db)
    org_a = await _org(db, owner=person)
    org_b = await _org(db, owner=person)

    preset = await dashboard_preset_repo.create(
        db,
        user_id=person.id,
        organization_id=org_a.id,
        name="Monday review",
        entries=[{"widget": "runs", "span": "s8"}],
    )

    # Same caller, different active organization: neither the list nor a
    # direct id lookup may answer with the row they own in org_a.
    assert (
        await dashboard_preset_repo.list_for_user(db, user_id=person.id, organization_id=org_b.id)
        == []
    )
    assert (
        await dashboard_preset_repo.get(
            db, preset_id=preset.id, user_id=person.id, organization_id=org_b.id
        )
        is None
    )


async def test_presets_list_ordered_by_name(db) -> None:
    person = await _user(db)
    org = await _org(db, owner=person)
    # Lowercase, single-word names so the order is the same under Python's
    # sort and Postgres' collation - the assertion is "ordered by name", not a
    # claim about how a given collation ranks mixed case.
    for name in ("watchlist", "incidents", "adoption"):
        await dashboard_preset_repo.create(
            db, user_id=person.id, organization_id=org.id, name=name, entries=[]
        )

    presets = await dashboard_preset_repo.list_for_user(
        db, user_id=person.id, organization_id=org.id
    )
    assert [preset.name for preset in presets] == ["adoption", "incidents", "watchlist"]


async def test_deleting_the_member_removes_their_presets(db) -> None:
    owner = await _user(db)
    org = await _org(db, owner=owner)
    member = await _user(db)
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=org.id, user_id=member.id, role="member"
        )
    )
    await db.flush()
    await dashboard_preset_repo.create(
        db,
        user_id=member.id,
        organization_id=org.id,
        name="mine",
        entries=[{"widget": "my-agents", "span": "s6"}],
    )

    await db.delete(member)
    await db.flush()

    remaining = (
        (await db.execute(select(DashboardPreset).where(DashboardPreset.user_id == member.id)))
        .scalars()
        .all()
    )
    assert remaining == []


async def test_deleting_the_organization_removes_the_presets(db) -> None:
    owner = await _user(db)
    org = await _org(db, owner=owner)
    await dashboard_preset_repo.create(
        db,
        user_id=owner.id,
        organization_id=org.id,
        name="Monday review",
        entries=[{"widget": "runs", "span": "s8"}],
    )

    await db.delete(org)
    await db.flush()

    remaining = (
        (await db.execute(select(DashboardPreset).where(DashboardPreset.organization_id == org.id)))
        .scalars()
        .all()
    )
    assert remaining == []

"""What only a database can guarantee about pinned sidebar items.

Pins are keyed on `(user_id, organization_id)`: the same person pins different
items in each organization, nobody reads anybody else's, a second save replaces
the first, and a deleted organization leaves no orphan row.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.nav_pins import NavPins
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.schemas.nav_pins import NavPinsUpdate
from app.services.nav_pins import NavPinsService

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


async def test_nothing_pinned_reads_as_empty(db) -> None:
    person = await _user(db)
    org = await _org(db, owner=person)
    assert await NavPinsService(db).get_for_user(user_id=person.id, organization_id=org.id) == []


async def test_pins_keep_the_order_they_were_saved_in(db) -> None:
    person = await _user(db)
    org = await _org(db, owner=person)
    service = NavPinsService(db)
    saved = await service.replace(
        user_id=person.id,
        organization_id=org.id,
        data=NavPinsUpdate(item_ids=["runs", "agents", "spend"]),
    )
    assert saved == ["runs", "agents", "spend"]
    assert await service.get_for_user(user_id=person.id, organization_id=org.id) == saved


async def test_a_second_save_replaces_the_first_in_one_row(db) -> None:
    person = await _user(db)
    org = await _org(db, owner=person)
    service = NavPinsService(db)
    await service.replace(
        user_id=person.id, organization_id=org.id, data=NavPinsUpdate(item_ids=["runs"])
    )
    await service.replace(
        user_id=person.id, organization_id=org.id, data=NavPinsUpdate(item_ids=[])
    )
    rows = (await db.execute(select(NavPins).where(NavPins.user_id == person.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].item_ids == []


async def test_pins_are_per_organization_even_for_their_owner(db) -> None:
    person = await _user(db)
    org_a = await _org(db, owner=person)
    org_b = await _org(db, owner=person)
    service = NavPinsService(db)
    await service.replace(
        user_id=person.id, organization_id=org_a.id, data=NavPinsUpdate(item_ids=["runs"])
    )
    assert await service.get_for_user(user_id=person.id, organization_id=org_b.id) == []


async def test_pins_are_per_user_within_one_organization(db) -> None:
    alice = await _user(db)
    bob = await _user(db)
    org = await _org(db, owner=alice)
    service = NavPinsService(db)
    await service.replace(
        user_id=alice.id, organization_id=org.id, data=NavPinsUpdate(item_ids=["runs"])
    )
    assert await service.get_for_user(user_id=bob.id, organization_id=org.id) == []


async def test_only_one_row_may_exist_per_person_per_org(db) -> None:
    person = await _user(db)
    org = await _org(db, owner=person)
    db.add(NavPins(user_id=person.id, organization_id=org.id, item_ids=[]))
    await db.flush()
    db.add(NavPins(user_id=person.id, organization_id=org.id, item_ids=[]))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_deleting_the_organization_removes_its_pins(db) -> None:
    person = await _user(db)
    org = await _org(db, owner=person)
    await NavPinsService(db).replace(
        user_id=person.id, organization_id=org.id, data=NavPinsUpdate(item_ids=["runs"])
    )
    await db.delete(org)
    await db.flush()
    rows = (await db.execute(select(NavPins).where(NavPins.user_id == person.id))).scalars().all()
    assert rows == []


def test_repr_names_the_owner_and_pin_count() -> None:
    row = NavPins(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), item_ids=["a", "b"])
    assert "n=2" in repr(row)

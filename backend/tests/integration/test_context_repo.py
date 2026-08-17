"""Guarantees the context-files table makes that only a database can.

Context files share the skills tenant boundary: owned by a member, carrying a
visibility, unique name per organization. What matters here — the same name may
exist once per organization and the duplicate is refused by the constraint (not
only the service), the `mode` CHECK refuses a value the capability cannot branch
on, `list_visible` scopes a private file to its owner while an org-visible one is
everybody's, and deleting the organization takes its files with it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.context import ContextFile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import context_repo

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

    await context_repo.create(
        db,
        organization_id=org_a.id,
        owner_user_id=person.id,
        name="glossary",
        description=None,
        content="a",
        content_format="md",
        mode="inject",
    )
    other = await context_repo.create(
        db,
        organization_id=org_b.id,
        owner_user_id=person.id,
        name="glossary",
        description=None,
        content="b",
        content_format="md",
        mode="inject",
    )
    assert other.name == "glossary"


async def test_a_duplicate_name_in_one_organization_is_refused_by_the_constraint(db) -> None:
    person = await _user(db)
    org = await _org(db, owner=person)
    await context_repo.create(
        db,
        organization_id=org.id,
        owner_user_id=person.id,
        name="glossary",
        description=None,
        content="a",
        content_format="md",
        mode="inject",
    )
    with pytest.raises(IntegrityError):
        await context_repo.create(
            db,
            organization_id=org.id,
            owner_user_id=person.id,
            name="glossary",
            description=None,
            content="b",
            content_format="md",
            mode="inject",
        )


async def test_an_unknown_mode_is_refused_by_the_check_constraint(db) -> None:
    person = await _user(db)
    org = await _org(db, owner=person)
    with pytest.raises(IntegrityError):
        await context_repo.create(
            db,
            organization_id=org.id,
            owner_user_id=person.id,
            name="glossary",
            description=None,
            content="a",
            content_format="md",
            mode="sometimes",
        )


async def test_get_and_get_by_name_are_scoped_to_the_organization(db) -> None:
    person = await _user(db)
    org = await _org(db, owner=person)
    other_org = await _org(db, owner=person)
    file = await context_repo.create(
        db,
        organization_id=org.id,
        owner_user_id=person.id,
        name="glossary",
        description=None,
        content="a",
        content_format="md",
        mode="inject",
    )
    assert (await context_repo.get(db, file.id, organization_id=org.id)) is not None
    assert (await context_repo.get(db, file.id, organization_id=other_org.id)) is None
    assert (await context_repo.get_by_name(db, "glossary", organization_id=org.id)) is not None
    assert (await context_repo.get_by_name(db, "nope", organization_id=org.id)) is None


async def test_get_many_returns_only_this_organizations_rows(db) -> None:
    person = await _user(db)
    org = await _org(db, owner=person)
    other_org = await _org(db, owner=person)
    mine = await context_repo.create(
        db,
        organization_id=org.id,
        owner_user_id=person.id,
        name="mine",
        description=None,
        content="a",
        content_format="md",
        mode="inject",
    )
    theirs = await context_repo.create(
        db,
        organization_id=other_org.id,
        owner_user_id=person.id,
        name="theirs",
        description=None,
        content="b",
        content_format="md",
        mode="inject",
    )
    found = await context_repo.get_many(db, [mine.id, theirs.id], organization_id=org.id)
    assert set(found) == {mine.id}
    assert await context_repo.get_many(db, [], organization_id=org.id) == {}


async def test_list_visible_scopes_a_private_file_to_its_owner(db) -> None:
    owner = await _user(db)
    other = await _user(db)
    org = await _org(db, owner=owner)
    private = await context_repo.create(
        db,
        organization_id=org.id,
        owner_user_id=owner.id,
        name="private",
        description="mine only",
        content="a",
        content_format="md",
        mode="inject",
        visibility=Visibility.PRIVATE.value,
    )
    shared = await context_repo.create(
        db,
        organization_id=org.id,
        owner_user_id=owner.id,
        name="shared",
        description="everybody",
        content="b",
        content_format="md",
        mode="link",
        visibility=Visibility.ORG.value,
    )

    owner_items, owner_total = await context_repo.list_visible(
        db, organization_id=org.id, user_id=owner.id, see_all=False, shared_ids=[]
    )
    assert {file.name for file in owner_items} == {"private", "shared"}
    assert owner_total == 2

    other_items, _ = await context_repo.list_visible(
        db, organization_id=org.id, user_id=other.id, see_all=False, shared_ids=[]
    )
    assert {file.name for file in other_items} == {"shared"}

    granted_items, _ = await context_repo.list_visible(
        db, organization_id=org.id, user_id=other.id, see_all=False, shared_ids=[private.id]
    )
    assert {file.name for file in granted_items} == {"private", "shared"}

    all_items, _ = await context_repo.list_visible(
        db, organization_id=org.id, user_id=other.id, see_all=True, shared_ids=[]
    )
    assert {file.name for file in all_items} == {"private", "shared"}

    assert shared.visibility == Visibility.ORG.value


async def test_list_visible_shared_with_me_excludes_the_callers_own(db) -> None:
    owner = await _user(db)
    org = await _org(db, owner=owner)
    await context_repo.create(
        db,
        organization_id=org.id,
        owner_user_id=owner.id,
        name="mine-org",
        description=None,
        content="a",
        content_format="md",
        mode="inject",
        visibility=Visibility.ORG.value,
    )
    items, total = await context_repo.list_visible(
        db,
        organization_id=org.id,
        user_id=owner.id,
        see_all=True,
        shared_ids=[],
        shared_with_me=True,
    )
    assert items == []
    assert total == 0


async def test_list_visible_searches_name_and_description_and_sorts_by_update(db) -> None:
    owner = await _user(db)
    org = await _org(db, owner=owner)
    for name, description in [("alpha", "the first"), ("beta", "mentions alpha too")]:
        await context_repo.create(
            db,
            organization_id=org.id,
            owner_user_id=owner.id,
            name=name,
            description=description,
            content="x",
            content_format="md",
            mode="inject",
            visibility=Visibility.ORG.value,
        )
    hits, total = await context_repo.list_visible(
        db, organization_id=org.id, user_id=owner.id, see_all=True, shared_ids=[], search="alpha"
    )
    assert {file.name for file in hits} == {"alpha", "beta"}
    assert total == 2

    by_update, _ = await context_repo.list_visible(
        db, organization_id=org.id, user_id=owner.id, see_all=True, shared_ids=[], sort="updated"
    )
    assert {file.name for file in by_update} == {"alpha", "beta"}


async def test_update_and_delete(db) -> None:
    owner = await _user(db)
    org = await _org(db, owner=owner)
    file = await context_repo.create(
        db,
        organization_id=org.id,
        owner_user_id=owner.id,
        name="glossary",
        description=None,
        content="a",
        content_format="md",
        mode="inject",
    )
    updated = await context_repo.update(db, file=file, update_data={"content": "b", "mode": "link"})
    assert updated.content == "b"
    assert updated.mode == "link"

    await context_repo.delete(db, file)
    assert (await context_repo.get(db, file.id, organization_id=org.id)) is None


async def test_deleting_the_organization_takes_its_files(db) -> None:
    owner = await _user(db)
    org = await _org(db, owner=owner)
    file = await context_repo.create(
        db,
        organization_id=org.id,
        owner_user_id=owner.id,
        name="glossary",
        description=None,
        content="a",
        content_format="md",
        mode="inject",
    )
    await db.delete(await db.get(Organization, org.id))
    await db.flush()
    remaining = await db.scalar(select(ContextFile).where(ContextFile.id == file.id))
    assert remaining is None


def test_repr_names_the_org_and_mode() -> None:
    file = ContextFile(organization_id=uuid.uuid4(), name="glossary", mode="inject")
    assert "glossary" in repr(file)
    assert "inject" in repr(file)

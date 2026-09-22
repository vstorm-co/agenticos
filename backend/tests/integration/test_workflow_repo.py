"""The workflow repository against a real Postgres.

Only a real database enforces the unique `(organization_id, slug)` and
`(workflow_id, version)` constraints and the `CHECK`s on `status`,
`visibility` and `draft_revision` - a mock would let a duplicate slug or a
negative revision through silently.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow import WorkflowStatus
from app.repositories import workflow as workflow_repo

pytestmark = pytest.mark.anyio


async def _user(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db: AsyncSession) -> tuple[Organization, User]:
    founder = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(org)
    await db.flush()
    return org, founder


async def test_create_and_get_round_trip(db: AsyncSession):
    org, owner = await _org(db)
    created = await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="import-orders",
        name="Import orders",
        description="Reads a CSV and writes rows",
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        visibility=Visibility.PRIVATE.value,
    )
    assert created.status == WorkflowStatus.DRAFT.value
    assert created.draft_revision == 0
    fetched = await workflow_repo.get(db, created.id, organization_id=org.id)
    assert fetched is not None
    assert fetched.slug == "import-orders"


async def test_get_is_scoped_to_the_organization(db: AsyncSession):
    org_a, owner_a = await _org(db)
    org_b, _ = await _org(db)
    created = await workflow_repo.create(
        db,
        organization_id=org_a.id,
        slug="cross-tenant",
        name="Cross tenant",
        description=None,
        owner_user_id=owner_a.id,
        created_by_user_id=owner_a.id,
        visibility=Visibility.PRIVATE.value,
    )
    assert await workflow_repo.get(db, created.id, organization_id=org_b.id) is None


async def test_get_by_slug_finds_the_row(db: AsyncSession):
    org, owner = await _org(db)
    await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="findable",
        name="Findable",
        description=None,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        visibility=Visibility.PRIVATE.value,
    )
    found = await workflow_repo.get_by_slug(db, "findable", organization_id=org.id)
    assert found is not None
    assert found.slug == "findable"
    assert await workflow_repo.get_by_slug(db, "nope", organization_id=org.id) is None


async def test_a_duplicate_slug_in_one_organization_is_refused(db: AsyncSession):
    org, owner = await _org(db)
    await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="dup",
        name="First",
        description=None,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        visibility=Visibility.PRIVATE.value,
    )
    await db.flush()
    with pytest.raises(IntegrityError):
        await workflow_repo.create(
            db,
            organization_id=org.id,
            slug="dup",
            name="Second",
            description=None,
            owner_user_id=owner.id,
            created_by_user_id=owner.id,
            visibility=Visibility.PRIVATE.value,
        )
    await db.rollback()


async def test_get_for_update_locks_and_returns_the_row(db: AsyncSession):
    org, owner = await _org(db)
    created = await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="locked",
        name="Locked",
        description=None,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        visibility=Visibility.PRIVATE.value,
    )
    locked = await workflow_repo.get_for_update(db, created.id, organization_id=org.id)
    assert locked is not None
    assert locked.id == created.id


async def test_update_changes_only_the_named_fields(db: AsyncSession):
    org, owner = await _org(db)
    created = await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="updatable",
        name="Before",
        description=None,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        visibility=Visibility.PRIVATE.value,
    )
    updated = await workflow_repo.update(
        db, workflow=created, update_data={"name": "After", "draft_revision": 1}
    )
    assert updated.name == "After"
    assert updated.draft_revision == 1
    assert updated.slug == "updatable"


async def test_list_visible_sees_all_when_the_role_reaches_everything(db: AsyncSession):
    org, owner = await _org(db)
    other = await _user(db)
    await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="mine",
        name="Mine",
        description=None,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        visibility=Visibility.PRIVATE.value,
    )
    await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="theirs",
        name="Theirs",
        description=None,
        owner_user_id=other.id,
        created_by_user_id=other.id,
        visibility=Visibility.PRIVATE.value,
    )
    items, total = await workflow_repo.list_visible(
        db, organization_id=org.id, user_id=owner.id, see_all=True, shared_ids=[], skip=0, limit=50
    )
    assert total == 2
    assert {item.slug for item in items} == {"mine", "theirs"}


async def test_list_visible_narrows_to_own_org_and_shared_when_the_role_does_not_reach_everything(
    db: AsyncSession,
):
    org, owner = await _org(db)
    other = await _user(db)
    mine = await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="own-workflow",
        name="Own",
        description=None,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        visibility=Visibility.PRIVATE.value,
    )
    org_visible = await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="org-visible",
        name="Org visible",
        description=None,
        owner_user_id=other.id,
        created_by_user_id=other.id,
        visibility=Visibility.ORG.value,
    )
    shared = await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="explicitly-shared",
        name="Shared",
        description=None,
        owner_user_id=other.id,
        created_by_user_id=other.id,
        visibility=Visibility.PRIVATE.value,
    )
    not_visible = await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="not-visible",
        name="Not visible",
        description=None,
        owner_user_id=other.id,
        created_by_user_id=other.id,
        visibility=Visibility.PRIVATE.value,
    )
    items, total = await workflow_repo.list_visible(
        db,
        organization_id=org.id,
        user_id=owner.id,
        see_all=False,
        shared_ids=[shared.id],
        skip=0,
        limit=50,
    )
    visible_ids = {item.id for item in items}
    assert visible_ids == {mine.id, org_visible.id, shared.id}
    assert not_visible.id not in visible_ids
    assert total == 3


async def test_list_visible_paginates(db: AsyncSession):
    org, owner = await _org(db)
    for index in range(3):
        await workflow_repo.create(
            db,
            organization_id=org.id,
            slug=f"page-{index}",
            name=f"Page {index}",
            description=None,
            owner_user_id=owner.id,
            created_by_user_id=owner.id,
            visibility=Visibility.PRIVATE.value,
        )
    page = await workflow_repo.list_visible(
        db, organization_id=org.id, user_id=owner.id, see_all=True, shared_ids=[], skip=0, limit=2
    )
    assert len(page[0]) == 2
    assert page[1] == 3


async def test_next_version_number_starts_at_one_and_increments(db: AsyncSession):
    org, owner = await _org(db)
    created = await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="versioned",
        name="Versioned",
        description=None,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        visibility=Visibility.PRIVATE.value,
    )
    assert await workflow_repo.next_version_number(db, workflow_id=created.id) == 1
    await workflow_repo.create_version(
        db,
        workflow_id=created.id,
        organization_id=org.id,
        version=1,
        graph={"entry_node_id": str(uuid.uuid4()), "nodes": []},
        note="first",
        published_by_user_id=owner.id,
        budget_limit=None,
    )
    assert await workflow_repo.next_version_number(db, workflow_id=created.id) == 2


async def test_create_version_and_get_version_round_trip(db: AsyncSession):
    org, owner = await _org(db)
    created = await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="frozen",
        name="Frozen",
        description=None,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        visibility=Visibility.PRIVATE.value,
    )
    version = await workflow_repo.create_version(
        db,
        workflow_id=created.id,
        organization_id=org.id,
        version=1,
        graph={"entry_node_id": str(uuid.uuid4()), "nodes": []},
        note="v1",
        published_by_user_id=owner.id,
        budget_limit=Decimal("25.5"),
    )
    fetched = await workflow_repo.get_version(db, version.id, organization_id=org.id)
    assert fetched is not None
    assert fetched.version == 1
    assert fetched.budget_limit == Decimal("25.5")
    assert await workflow_repo.get_version(db, uuid.uuid4(), organization_id=org.id) is None


async def test_list_versions_orders_newest_first(db: AsyncSession):
    org, owner = await _org(db)
    created = await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="multi-version",
        name="Multi version",
        description=None,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        visibility=Visibility.PRIVATE.value,
    )
    for version in (1, 2, 3):
        await workflow_repo.create_version(
            db,
            workflow_id=created.id,
            organization_id=org.id,
            version=version,
            graph={"entry_node_id": str(uuid.uuid4()), "nodes": []},
            note=None,
            published_by_user_id=owner.id,
            budget_limit=None,
        )
    versions = await workflow_repo.list_versions(db, workflow_id=created.id, organization_id=org.id)
    assert [v.version for v in versions] == [3, 2, 1]


async def test_a_second_version_at_the_same_number_is_refused(db: AsyncSession):
    org, owner = await _org(db)
    created = await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="conflict",
        name="Conflict",
        description=None,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        visibility=Visibility.PRIVATE.value,
    )
    await workflow_repo.create_version(
        db,
        workflow_id=created.id,
        organization_id=org.id,
        version=1,
        graph={"entry_node_id": str(uuid.uuid4()), "nodes": []},
        note=None,
        published_by_user_id=owner.id,
        budget_limit=None,
    )
    await db.flush()
    with pytest.raises(IntegrityError):
        await workflow_repo.create_version(
            db,
            workflow_id=created.id,
            organization_id=org.id,
            version=1,
            graph={"entry_node_id": str(uuid.uuid4()), "nodes": []},
            note=None,
            published_by_user_id=owner.id,
            budget_limit=None,
        )
    await db.rollback()


async def test_workflow_and_version_repr_name_their_identity(db: AsyncSession):
    org, owner = await _org(db)
    created = await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="reprable",
        name="Reprable",
        description=None,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        visibility=Visibility.PRIVATE.value,
    )
    assert "reprable" in repr(created)
    assert "draft" in repr(created)
    version = await workflow_repo.create_version(
        db,
        workflow_id=created.id,
        organization_id=org.id,
        version=1,
        graph={"entry_node_id": str(uuid.uuid4()), "nodes": []},
        note=None,
        published_by_user_id=owner.id,
        budget_limit=None,
    )
    assert str(created.id) in repr(version)
    assert "v1" in repr(version)


async def test_negative_draft_revision_is_refused(db: AsyncSession):
    org, owner = await _org(db)
    created = await workflow_repo.create(
        db,
        organization_id=org.id,
        slug="revision-check",
        name="Revision check",
        description=None,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        visibility=Visibility.PRIVATE.value,
    )
    await db.flush()
    with pytest.raises(IntegrityError):
        await workflow_repo.update(db, workflow=created, update_data={"draft_revision": -1})
    await db.rollback()

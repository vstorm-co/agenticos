"""Persisted role preferences preserve other roles and organizations."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import organization_repo

pytestmark = pytest.mark.anyio


@pytest.mark.security
async def test_saving_from_a_stale_session_preserves_other_roles_and_tenants(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    owner = User(email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(owner)
    await db.flush()
    organization = Organization(
        name="Workspace", slug=f"workspace-{uuid4().hex}", created_by_user_id=owner.id
    )
    other = Organization(
        name="Other",
        slug=f"other-{uuid4().hex}",
        created_by_user_id=owner.id,
        role_navigation={"member": ["skills"]},
    )
    db.add_all([organization, other])
    await db.commit()
    assert organization.role_navigation is None

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as stale_session:
        stale = await stale_session.get(Organization, organization.id)
        assert stale is not None and stale.role_navigation is None
        await organization_repo.set_role_navigation(
            db, organization_id=organization.id, role="member", hidden_items=["chat"]
        )
        await db.commit()
        # The identity map still holds the old row. The locked read must refresh
        # it before merging or this second write would erase the Member policy.
        await organization_repo.set_role_navigation(
            stale_session, organization_id=organization.id, role="viewer", hidden_items=["groups"]
        )
        await stale_session.commit()

    await db.refresh(organization)
    await db.refresh(other)
    assert organization.role_navigation == {"member": ["chat"], "viewer": ["groups"]}
    assert other.role_navigation == {"member": ["skills"]}

    await organization_repo.set_role_navigation(
        db, organization_id=organization.id, role="member", hidden_items=[]
    )
    await db.commit()
    await db.refresh(organization)
    assert organization.role_navigation == {"member": [], "viewer": ["groups"]}

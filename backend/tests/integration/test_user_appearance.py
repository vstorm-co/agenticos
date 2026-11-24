"""Saved appearance stays with its account when another member writes theirs."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import user_repo
from app.schemas.user_appearance import UserAppearance
from app.services.user_appearance import UserAppearanceService

pytestmark = pytest.mark.anyio


@pytest.mark.security
async def test_account_preferences_persist_without_changing_another_member(db):
    alice = User(email=f"{uuid4()}@example.com", hashed_password="x")
    bob = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add_all([alice, bob])
    await db.flush()
    org = Organization(name="Appearance", slug=f"appearance-{uuid4()}", created_by_user_id=alice.id)
    db.add(org)
    await db.flush()
    service = UserAppearanceService(db)
    alice_ctx = AuthContext(user_id=alice.id, organization_id=org.id, role="member")
    bob_ctx = AuthContext(user_id=bob.id, organization_id=org.id, role="owner")
    await service.update(alice_ctx, UserAppearance(theme="dark", accent="violet"))
    await service.update(bob_ctx, UserAppearance(look="paper"))
    await db.refresh(alice)
    await db.refresh(bob)
    assert alice.appearance["theme"] == "dark"
    assert bob.appearance["theme"] == "system"
    assert (await service.get(alice_ctx)).accent == "violet"
    await service.reset(alice_ctx)
    assert alice.appearance is None
    assert (await service.get(bob_ctx)).look == "paper"
    await db.commit()

    # Authentication can load the user before another request wins its write
    # lock. Merging must refresh that identity-map entry after acquiring it.
    async with AsyncSession(db.bind, expire_on_commit=False) as second:
        previously_loaded = await user_repo.get_by_id(second, alice.id)
        assert previously_loaded.appearance is None
        await service.update(alice_ctx, UserAppearance(theme="dark"))
        await db.commit()
        await UserAppearanceService(second).update(alice_ctx, UserAppearance(accent="green"))
        await second.commit()
    await db.refresh(alice)
    assert alice.appearance["theme"] == "dark"
    assert alice.appearance["accent"] == "green"

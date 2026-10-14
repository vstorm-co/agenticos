"""#2130: an organization's browser setting against a real database."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import browser_setting as browser_setting_repo

pytestmark = pytest.mark.anyio


async def _organization(db: AsyncSession) -> Organization:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id
    )
    db.add(organization)
    await db.flush()
    return organization


async def test_the_first_save_makes_the_row_and_the_next_changes_it(db: AsyncSession) -> None:
    organization = await _organization(db)
    assert await browser_setting_repo.get(db, organization_id=organization.id) is None

    first = await browser_setting_repo.save(
        db,
        organization_id=organization.id,
        values={"mode": "proxy", "proxy_url": "http://proxy.example.com:8080"},
    )
    assert first.remote_key_param == "apiKey"
    assert "mode=proxy" in repr(first)

    await browser_setting_repo.save(
        db,
        organization_id=organization.id,
        values={"mode": "built_in", "timezone": "Europe/Warsaw"},
    )
    again = await browser_setting_repo.get(db, organization_id=organization.id)

    assert again is not None
    assert (again.mode, again.timezone) == ("built_in", "Europe/Warsaw")
    # What the other mode held is kept, so switching back does not lose it.
    assert again.proxy_url == "http://proxy.example.com:8080"


async def test_each_organization_has_its_own(db: AsyncSession) -> None:
    acme, globex = await _organization(db), await _organization(db)
    await browser_setting_repo.save(db, organization_id=acme.id, values={"mode": "remote"})

    assert await browser_setting_repo.get(db, organization_id=globex.id) is None

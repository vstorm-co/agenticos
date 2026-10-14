"""The organization's voice limits, held by the schema (#54)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.models.organization import Organization
from app.db.models.user import User

pytestmark = pytest.mark.anyio


async def _org(db) -> Organization:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    return org


async def test_a_new_organization_starts_with_voice_off_and_ten_minute_calls(db):
    organization = await _org(db)
    await db.refresh(organization)

    assert organization.voice_conversations_enabled is False
    assert organization.voice_in_chat is True
    assert organization.voice_max_call_seconds == 600
    assert organization.voice_monthly_minutes == 600


@pytest.mark.parametrize("seconds", [59, 3001])
async def test_a_call_cap_outside_one_to_fifty_minutes_is_refused(db, seconds):
    organization = await _org(db)
    with pytest.raises(IntegrityError):
        await db.execute(
            text("UPDATE organizations SET voice_max_call_seconds = :s WHERE id = :id"),
            {"s": seconds, "id": organization.id},
        )


async def test_zero_monthly_minutes_is_refused(db):
    organization = await _org(db)
    with pytest.raises(IntegrityError):
        await db.execute(
            text("UPDATE organizations SET voice_monthly_minutes = 0 WHERE id = :id"),
            {"id": organization.id},
        )

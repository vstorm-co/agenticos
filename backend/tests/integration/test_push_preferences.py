"""Real JSONB merge, per-session isolation and ownership enforcement."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import session as sessions
from app.repositories import user as users

pytestmark = pytest.mark.anyio


async def test_preferences_merge_without_crossing_accounts_or_device_sessions(
    db: AsyncSession,
) -> None:
    user = await users.create(db, email=f"{uuid4()}@example.com", hashed_password="x")
    other = await users.create(db, email=f"{uuid4()}@example.com", hashed_password="x")
    first = await sessions.create(
        db,
        user_id=user.id,
        refresh_token_hash=uuid4().hex,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    second = await sessions.create(
        db,
        user_id=user.id,
        refresh_token_hash=uuid4().hex,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    assert await sessions.update_push_preferences(
        db, user_id=user.id, session_id=first.id, patch={"hide_previews": True}
    )
    assert await sessions.update_push_preferences(
        db, user_id=user.id, session_id=first.id, patch={"focused_conversation": str(uuid4())}
    )
    assert not await sessions.update_push_preferences(
        db, user_id=other.id, session_id=first.id, patch={"hide_previews": False}
    )
    rows = await sessions.push_preferences_for(
        db, user_id=user.id, session_ids=[first.id, second.id]
    )
    assert rows[first.id]["hide_previews"] is True
    assert "focused_conversation" in rows[first.id]
    assert second.id not in rows
    assert await sessions.push_preferences_for(db, user_id=other.id, session_ids=[first.id]) == {}
    first.is_active = False
    await db.flush()
    assert not await sessions.update_push_preferences(
        db, user_id=user.id, session_id=first.id, patch={"hide_previews": False}
    )
    assert await sessions.push_preferences_for(db, user_id=user.id, session_ids=[first.id]) == {}


async def test_concurrent_focus_and_privacy_updates_preserve_each_other(db: AsyncSession) -> None:
    import asyncio

    from pydantic import JsonValue
    from sqlalchemy.ext.asyncio import async_sessionmaker

    user = await users.create(db, email=f"{uuid4()}@example.com", hashed_password="x")
    session = await sessions.create(
        db,
        user_id=user.id,
        refresh_token_hash=uuid4().hex,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    await db.commit()
    factory = async_sessionmaker(db.bind, expire_on_commit=False)

    async def write(patch: dict[str, JsonValue]) -> None:
        async with factory.begin() as own:
            assert await sessions.update_push_preferences(
                own, user_id=user.id, session_id=session.id, patch=patch
            )

    await asyncio.gather(
        write({"hide_previews": True}), write({"focused_conversation": str(uuid4())})
    )
    rows = await sessions.push_preferences_for(db, user_id=user.id, session_ids=[session.id])
    assert rows[session.id]["hide_previews"] is True
    assert "focused_conversation" in rows[session.id]

"""When the admin drawer says somebody was last here, and what it calls open.

Both figures used to come off the same read - the user's *active* sessions - and
both were wrong for it. Somebody who has signed out has no active session row at
all, so "when were they last here" came back null and the drawer answered "Never
signed in" for most accounts most of the time: the one case the field exists to
tell apart from an account created and never used. And nothing sweeps a session
that simply ran out, so a row past `expires_at` stays `is_active` until the next
refresh declines it and was counted as open (#1256).

Here rather than in the unit suite because both halves are a `WHERE` clause: what
`is_active AND expires_at > now()` selects is Postgres's answer, not a mock's.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.session import Session
from app.db.models.user import User
from app.services.user import UserService

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
        created_at=NOW - timedelta(days=90),
    )
    db.add(user)
    await db.flush()
    return user


async def _session(
    db,
    user: User,
    *,
    last_used_at: datetime,
    is_active: bool = True,
    expires_at: datetime | None = None,
) -> Session:
    session = Session(
        id=uuid.uuid4(),
        user_id=user.id,
        refresh_token_hash=uuid.uuid4().hex,
        is_active=is_active,
        created_at=last_used_at,
        last_used_at=last_used_at,
        expires_at=expires_at or datetime.now(UTC) + timedelta(days=7),
    )
    db.add(session)
    await db.flush()
    return session


class TestLastSeenIsEverySession:
    async def test_somebody_who_signed_out_has_still_been_here(self, db) -> None:
        user = await _user(db)
        await _session(db, user, last_used_at=NOW - timedelta(days=30), is_active=False)
        last = NOW - timedelta(days=3)
        await _session(db, user, last_used_at=last, is_active=False)

        detail = await UserService(db).admin_detail(user.id)

        assert detail.last_seen_at == last
        assert detail.active_sessions == 0
        # No open session, so nothing to date - the drawer reads this beside the
        # count and "newest session August" under "0 open sessions" says nothing.
        assert detail.newest_session_at is None

    async def test_an_account_that_never_signed_in_is_still_null(self, db) -> None:
        """The distinction the field exists for, and the half that was already
        right: no session ever is not the same as none open now."""
        user = await _user(db)

        detail = await UserService(db).admin_detail(user.id)

        assert detail.last_seen_at is None
        assert detail.active_sessions == 0


class TestOpenMeansUsable:
    async def test_an_expired_row_is_not_an_open_session(self, db) -> None:
        """Nothing deactivates a session that lapses: the row stays `is_active`
        until a refresh finds it expired and declines it."""
        user = await _user(db)
        await _session(
            db,
            user,
            last_used_at=NOW - timedelta(days=40),
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )

        detail = await UserService(db).admin_detail(user.id)

        assert detail.active_sessions == 0
        assert detail.last_seen_at == NOW - timedelta(days=40)

    async def test_an_unexpired_row_is(self, db) -> None:
        user = await _user(db)
        await _session(db, user, last_used_at=NOW - timedelta(days=40), is_active=False)
        opened = NOW - timedelta(hours=2)
        await _session(db, user, last_used_at=opened)

        detail = await UserService(db).admin_detail(user.id)

        assert detail.active_sessions == 1
        assert detail.newest_session_at == opened
        assert detail.last_seen_at == opened

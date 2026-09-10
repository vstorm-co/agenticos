"""Signing out everywhere revokes an ordinary access token, against a real
database (#1501).

The unit suite proves the pieces with the database mocked: the token is bound to
a session row, and `verify_access_session` refuses one whose row is gone. What it
cannot prove is the two SQL facts the whole feature rests on - that creating a
session assigns a real id for the token's `sid`, and that `DELETE /sessions`
actually flips `is_active` on the row the token names, so the very next request
is refused. Both are asserted here through the real routes and the real
repositories.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.security import create_access_token
from app.main import app
from app.repositories import session_repo, user_repo
from app.services.session import SessionService, hash_token

pytestmark = pytest.mark.anyio


@pytest.fixture
async def api(db) -> AsyncIterator[AsyncClient]:
    """The real app over the test database, sharing the test's own session so a
    write in one request is visible to the next."""
    app.dependency_overrides[deps.get_db_session] = lambda: db
    app.dependency_overrides[deps.get_redis] = lambda: MagicMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def _user(db, email: str):
    return await user_repo.create(db, email=email, hashed_password="not-a-real-hash")


def _in_a_day() -> datetime:
    return datetime.now(UTC) + timedelta(days=1)


async def test_delete_sessions_revokes_an_ordinary_access_token_over_http(db, api: AsyncClient):
    user = await _user(db, "revoke-e2e@example.com")
    session = await session_repo.create(
        db, user_id=user.id, refresh_token_hash="h", expires_at=_in_a_day()
    )
    assert isinstance(session.id, UUID)  # a real flush assigned the id the token names

    token = create_access_token(str(user.id), sid=str(session.id))
    headers = {"Authorization": f"Bearer {token}"}

    live = await api.get(f"{settings.API_V1_STR}/auth/me", headers=headers)
    assert live.status_code == 200

    revoked = await api.delete(f"{settings.API_V1_STR}/sessions", headers=headers)
    assert revoked.status_code == 200
    assert revoked.json()["sessions_logged_out"] == 1

    # A real request would read the row in a fresh session; the shared one must be
    # told to re-read rather than trust the copy it loaded a request ago.
    db.expire_all()
    after = await api.get(f"{settings.API_V1_STR}/auth/me", headers=headers)
    assert after.status_code == 401


async def test_a_sid_less_token_survives_sign_out_everywhere(db, api: AsyncClient):
    """A pre-#1501 token names no row, so it is not revocable this way - the
    compatibility boundary, proven end to end rather than only in the unit."""
    user = await _user(db, "legacy-e2e@example.com")
    await session_repo.create(db, user_id=user.id, refresh_token_hash="h", expires_at=_in_a_day())
    token = create_access_token(str(user.id))  # no sid
    headers = {"Authorization": f"Bearer {token}"}

    assert (await api.delete(f"{settings.API_V1_STR}/sessions", headers=headers)).status_code == 200
    db.expire_all()

    still_ok = await api.get(f"{settings.API_V1_STR}/auth/me", headers=headers)
    assert still_ok.status_code == 200


async def test_rotate_keeps_the_id_and_re_keys_the_refresh_hash(db):
    """Refresh in place: the row's id (the token's `sid`) survives, the old
    refresh token stops validating, and the new one takes over - on real SQL.

    The security-sensitive properties of a refresh rotation, asserted explicitly
    because in-place rotation replaces deactivate-old-then-create-new: the spent
    token is refused (its hash no longer names a row), there is no window in which
    both tokens validate (one row holds exactly one hash), and no second row is
    left behind (the count stays one). The codebase has no rotation-chain reuse
    detection for in-place to break - `validate_refresh_token` keys on the hash,
    `is_active` and `expires_at` alone, and the session row carries no token
    lineage - so the guarantee is exactly this hash swap.
    """
    user = await _user(db, "rotate-e2e@example.com")
    user_id = user.id  # bound before expire_all, which would make a later read reload
    service = SessionService(db)
    session = await session_repo.create(
        db, user_id=user_id, refresh_token_hash=hash_token("old-refresh"), expires_at=_in_a_day()
    )
    original_id = session.id
    assert await session_repo.count_user_sessions(db, user_id, open_only=True) == 1

    rotated = await service.rotate_session(session, "new-refresh")

    assert rotated.id == original_id
    assert rotated.refresh_token_hash == hash_token("new-refresh")

    db.expire_all()
    # The spent token is refused, the new one works, and there is exactly one
    # active row - no parallel window, no orphaned second session.
    assert await service.validate_refresh_token("old-refresh") is None
    revalidated = await service.validate_refresh_token("new-refresh")
    assert revalidated is not None
    assert revalidated.id == original_id
    assert await session_repo.count_user_sessions(db, user_id, open_only=True) == 1

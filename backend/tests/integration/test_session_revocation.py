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
from sqlalchemy import func, select

from app.api import deps
from app.core.config import settings
from app.core.security import create_access_token
from app.db.models.audit_log import AppAdminAuditLog
from app.main import app
from app.repositories import session_repo, user_repo
from app.services.session import SessionService, hash_token

pytestmark = [pytest.mark.anyio, pytest.mark.security]


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
    left behind (the count stays one).

    Since #1519 the row also keeps the hash rotation replaced, which is what makes
    the spent token's *reuse* recognisable rather than merely ineffective. That is
    asserted below; here the guarantee is still exactly the hash swap.
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


class TestReusingASpentRefreshToken:
    """Rotation makes a spent refresh token useless. Reuse detection makes its
    use *visible*, which is the whole of #1519.

    A token the legitimate user rotated away, presented afterwards by somebody
    else, failed exactly like a typo: rotation re-keys the row in place, so the
    hash names no row and `validate_refresh_token` answers `None` for every
    invalid token alike. There was no signal, no audit entry, and the still-live
    session the thief was racing went on running.
    """

    async def test_the_spent_token_ends_the_chain_it_belonged_to(self, db):
        user = await _user(db, "reuse-chain@example.com")
        user_id = user.id
        service = SessionService(db)
        session = await session_repo.create(
            db, user_id=user_id, refresh_token_hash=hash_token("first"), expires_at=_in_a_day()
        )
        session_id = session.id
        await service.rotate_session(session, "second")
        db.expire_all()

        ended = await service.detect_refresh_reuse("first")

        assert ended is not None
        assert ended.id == session_id
        db.expire_all()
        # The chain is closed, so the token the thief was racing is dead too.
        assert await service.validate_refresh_token("second") is None
        assert await session_repo.count_user_sessions(db, user_id, open_only=True) == 0

    async def test_it_is_recorded_in_the_audit_trail(self, db):
        """A failed replay used to be indistinguishable from any other invalid
        token. The entry is what turns it into something somebody can act on -
        and it carries no token and no hash, because a credential has no business
        in a table people can export."""
        user = await _user(db, "reuse-audit@example.com")
        service = SessionService(db)
        session = await session_repo.create(
            db, user_id=user.id, refresh_token_hash=hash_token("first"), expires_at=_in_a_day()
        )
        await service.rotate_session(session, "second")
        db.expire_all()

        await service.detect_refresh_reuse("first")

        rows = (
            (
                await db.execute(
                    select(AppAdminAuditLog).where(
                        AppAdminAuditLog.action == "session.refresh_token_reused"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].target_id == str(session.id)
        body = str(rows[0].details)
        assert hash_token("first") not in body
        assert "first" not in body

    async def test_an_ordinary_invalid_token_is_not_a_replay(self, db):
        """A typo, an expired token, a revoked one - every one of them reaches
        this path, and answering "breach" for them would make the signal
        worthless."""
        service = SessionService(db)

        assert await service.detect_refresh_reuse("never-issued") is None

    async def test_a_second_replay_of_the_same_token_records_nothing_further(self, db):
        """One breach is one signal. The lookup is restricted to an *active* row,
        so a retry finds a chain already ended and says nothing - otherwise a
        client looping on a dead token would fill the trail."""
        user = await _user(db, "reuse-idempotent@example.com")
        service = SessionService(db)
        session = await session_repo.create(
            db, user_id=user.id, refresh_token_hash=hash_token("first"), expires_at=_in_a_day()
        )
        await service.rotate_session(session, "second")
        db.expire_all()

        assert await service.detect_refresh_reuse("first") is not None
        db.expire_all()

        assert await service.detect_refresh_reuse("first") is None
        count = (
            await db.execute(
                select(func.count())
                .select_from(AppAdminAuditLog)
                .where(AppAdminAuditLog.action == "session.refresh_token_reused")
            )
        ).scalar_one()
        assert count == 1

    async def test_the_person_s_other_sessions_are_left_alone(self, db):
        """A replay proves the one chain leaked. Logging somebody out of the
        laptop in front of them because a phone's token was replayed is a heavier
        default than the evidence supports - `DELETE /sessions` is there for an
        operator who reads the entry and wants it."""
        user = await _user(db, "reuse-other-devices@example.com")
        user_id = user.id
        service = SessionService(db)
        leaked = await session_repo.create(
            db, user_id=user_id, refresh_token_hash=hash_token("first"), expires_at=_in_a_day()
        )
        await session_repo.create(
            db, user_id=user_id, refresh_token_hash=hash_token("laptop"), expires_at=_in_a_day()
        )
        await service.rotate_session(leaked, "second")
        db.expire_all()

        await service.detect_refresh_reuse("first")
        db.expire_all()

        assert await service.validate_refresh_token("laptop") is not None
        assert await session_repo.count_user_sessions(db, user_id, open_only=True) == 1

    async def test_the_refresh_route_ends_the_chain_and_still_answers_401(
        self, db, api: AsyncClient
    ):
        """Through the real endpoint, because the detection is worth nothing if
        the route does not reach it - and because the answer to the caller must
        not change. A replay learns exactly what a typo learns."""
        user = await _user(db, "reuse-http@example.com")
        service = SessionService(db)
        session = await session_repo.create(
            db, user_id=user.id, refresh_token_hash=hash_token("first"), expires_at=_in_a_day()
        )
        await service.rotate_session(session, "second")
        db.expire_all()

        response = await api.post(
            f"{settings.API_V1_STR}/auth/refresh", json={"refresh_token": "first"}
        )

        assert response.status_code == 401
        db.expire_all()
        assert await service.validate_refresh_token("second") is None

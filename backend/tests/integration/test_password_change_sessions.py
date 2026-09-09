"""A password change revokes the account's other sessions against a real database.

The unit tests assert the service asks for the revocation; these assert the rows
actually flip, and that the caller's own session is the one spared (#1439). Only a
database shows a `WHERE id != :sid` sparing exactly one of several open rows.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError
from app.core.security import get_password_hash, verify_password
from app.repositories import session_repo, user_repo
from app.schemas.user import UserUpdate
from app.services.session import SessionService
from app.services.user import UserService

pytestmark = pytest.mark.anyio


async def _user(db: AsyncSession, email: str):
    return await user_repo.create(db, email=email, hashed_password="not-a-real-hash")


async def test_a_password_change_keeps_the_current_session_and_revokes_the_rest(
    db: AsyncSession,
) -> None:
    user = await _user(db, "pw-change@example.com")
    sessions = SessionService(db)
    current = await sessions.create_session(user_id=user.id, refresh_token="rt-current")
    other = await sessions.create_session(user_id=user.id, refresh_token="rt-other")

    await UserService(db).update(
        user.id, UserUpdate(password="a-brand-new-password"), current_session_id=current.id
    )

    kept = await session_repo.get_by_id(db, current.id)
    revoked = await session_repo.get_by_id(db, other.id)
    assert kept is not None and kept.is_active is True
    assert revoked is not None and revoked.is_active is False


async def test_a_password_change_with_no_current_session_revokes_every_one(
    db: AsyncSession,
) -> None:
    user = await _user(db, "pw-reset@example.com")
    sessions = SessionService(db)
    first = await sessions.create_session(user_id=user.id, refresh_token="rt-a")
    second = await sessions.create_session(user_id=user.id, refresh_token="rt-b")

    await UserService(db).update(user.id, UserUpdate(password="another-new-password"))

    for session_id in (first.id, second.id):
        row = await session_repo.get_by_id(db, session_id)
        assert row is not None and row.is_active is False


async def test_change_password_proves_the_old_bumps_the_version_and_revokes_all(
    db: AsyncSession,
) -> None:
    """The self-service change against a real row: the current password is proved
    under the lock, the hash and credential version move, and every session is
    revoked so the route can open a fresh one (#1517)."""
    user = await user_repo.create(
        db, email="selfchange@example.com", hashed_password=get_password_hash("old-password")
    )
    sessions = SessionService(db)
    one = await sessions.create_session(user_id=user.id, refresh_token="rt-1")
    two = await sessions.create_session(user_id=user.id, refresh_token="rt-2")

    updated = await UserService(db).change_password(
        user, current_password="old-password", new_password="a-brand-new-password"
    )

    assert verify_password("a-brand-new-password", updated.hashed_password) is True
    assert updated.credential_version == 1
    for session_id in (one.id, two.id):
        row = await session_repo.get_by_id(db, session_id)
        assert row is not None and row.is_active is False


async def test_change_password_refuses_a_wrong_current_password_and_changes_nothing(
    db: AsyncSession,
) -> None:
    user = await user_repo.create(
        db, email="wrongpw@example.com", hashed_password=get_password_hash("real-password")
    )
    sessions = SessionService(db)
    live = await sessions.create_session(user_id=user.id, refresh_token="rt-live")

    with pytest.raises(AuthenticationError):
        await UserService(db).change_password(
            user, current_password="not-the-password", new_password="a-brand-new-password"
        )

    assert verify_password("real-password", user.hashed_password) is True
    assert user.credential_version == 0
    row = await session_repo.get_by_id(db, live.id)
    assert row is not None and row.is_active is True


async def test_another_accounts_sessions_are_untouched(db: AsyncSession) -> None:
    """The revocation is scoped to the account whose password changed."""
    changer = await _user(db, "changer@example.com")
    bystander = await _user(db, "bystander@example.com")
    sessions = SessionService(db)
    bystander_session = await sessions.create_session(
        user_id=bystander.id, refresh_token="rt-bystander"
    )
    await sessions.create_session(user_id=changer.id, refresh_token="rt-changer")

    await UserService(db).update(changer.id, UserUpdate(password="yet-another-password"))

    row = await session_repo.get_by_id(db, bystander_session.id)
    assert row is not None and row.is_active is True

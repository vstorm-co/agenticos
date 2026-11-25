"""Magic-link redemption is a one-transaction, one-session operation in PostgreSQL."""

import asyncio
import hashlib
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import AuthenticationError
from app.core.security import verify_special_token
from app.db.models.session import MagicLinkClaim, Session
from app.db.models.user import User
from app.services.session import SessionService
from app.services.user import UserService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _account(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    async with sessions() as db:
        user = User(email=f"magic-{uuid4().hex}@example.com", hashed_password="not-a-hash")
        db.add(user)
        await db.flush()
        user_id = user.id
        await db.commit()
    return user_id


async def _issue(
    sessions: async_sessionmaker[AsyncSession], user_id: UUID, *, return_to: str | None = None
) -> str:
    async with sessions() as db:
        user = await db.get(User, user_id)
        assert user is not None
        issued = await UserService(db).issue_magic_link_token(user.email, return_to=return_to)
        assert issued is not None
        await db.commit()
        return issued[1]


async def _redeem(
    sessions: async_sessionmaker[AsyncSession], token: str
) -> tuple[bool, str | None]:
    async with sessions() as db:
        try:
            user, return_to = await UserService(db).consume_magic_link_token(token)
            await SessionService(db).issue_tokens(
                user_id=user.id, credential_version=user.credential_version
            )
            await db.commit()
        except AuthenticationError:
            await db.rollback()
            return False, None
        return True, return_to


async def _session_count(sessions: async_sessionmaker[AsyncSession], user_id: UUID) -> int:
    async with sessions() as db:
        return (
            await db.scalar(select(func.count(Session.id)).where(Session.user_id == user_id)) or 0
        )


async def test_first_redemption_creates_one_session_and_sequential_replay_is_refused(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = await _account(sessions)
    token = await _issue(sessions, user_id, return_to="/agents/a-1")
    payload = verify_special_token(token, expected_type="magic_link")
    assert payload is not None and isinstance(payload.get("jti"), str)

    async with sessions() as db:
        claim = await db.scalar(select(MagicLinkClaim).where(MagicLinkClaim.user_id == user_id))
        assert claim is not None
        assert claim.token_hash == hashlib.sha256(payload["jti"].encode()).hexdigest()
        assert claim.credential_version == payload["cv"]

    first = await _redeem(sessions, token)
    replay = await _redeem(sessions, token)

    assert first == (True, "/agents/a-1")
    assert replay == (False, None)
    assert await _session_count(sessions, user_id) == 1
    async with sessions() as db:
        assert (
            await db.scalar(
                select(func.count(MagicLinkClaim.token_hash)).where(
                    MagicLinkClaim.user_id == user_id
                )
            )
            == 0
        )


async def test_concurrent_redemptions_create_exactly_one_session(engine: AsyncEngine) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = await _account(sessions)
    token = await _issue(sessions, user_id)

    outcomes = await asyncio.gather(_redeem(sessions, token), _redeem(sessions, token))

    assert [accepted for accepted, _return_to in outcomes].count(True) == 1
    assert await _session_count(sessions, user_id) == 1


async def test_a_failed_session_transaction_does_not_burn_the_link(engine: AsyncEngine) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = await _account(sessions)
    token = await _issue(sessions, user_id)

    async with sessions() as db:
        await UserService(db).consume_magic_link_token(token)
        await db.rollback()

    assert await _redeem(sessions, token) == (True, None)
    assert await _session_count(sessions, user_id) == 1


@pytest.mark.parametrize("change", ["password", "email"])
async def test_account_recovery_changes_invalidate_an_outstanding_link(
    engine: AsyncEngine, change: str
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = await _account(sessions)
    token = await _issue(sessions, user_id)

    async with sessions() as db:
        user = await db.get(User, user_id)
        assert user is not None
        if change == "password":
            user.credential_version += 1
        else:
            user.email = f"moved-{uuid4().hex}@example.com"
        await db.commit()

    assert await _redeem(sessions, token) == (False, None)
    assert await _session_count(sessions, user_id) == 0

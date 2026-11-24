"""Postgres guarantees that one TOTP counter can be accepted only once."""

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.totp import code_now, generate_secret
from app.db.models.user import User
from app.services.mfa import MfaService

pytestmark = pytest.mark.anyio


async def test_concurrent_challenges_accept_a_totp_counter_once(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    secret = generate_secret()
    async with sessions() as setup:
        user = User(
            email=f"mfa-replay-{uuid.uuid4().hex}@example.com",
            totp_enabled=True,
            totp_secret_encrypted="sealed",
            totp_key_version=1,
        )
        setup.add(user)
        await setup.flush()
        user_id = user.id
        await setup.commit()

    async def verify() -> bool:
        async with sessions() as db:
            user = await db.get(User, user_id)
            assert user is not None
            with (
                patch("app.services.mfa.unseal", return_value=secret),
                patch("app.services.mfa.record_audit", new=AsyncMock()),
            ):
                result = await MfaService(db).verify_challenge(user, code_now(secret))
            await db.commit()
            return result

    outcomes = await asyncio.gather(verify(), verify())

    assert sorted(outcomes) == [False, True]

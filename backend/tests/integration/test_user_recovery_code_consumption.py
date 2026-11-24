"""Postgres guarantees for single-use MFA recovery codes."""

import uuid

import pytest

from app.db.models.user import User
from app.repositories import user as user_repo

pytestmark = pytest.mark.anyio


async def test_a_recovery_hash_can_only_be_consumed_once(db) -> None:
    digests = ["first-digest", "remaining-digest"]
    user = User(email=f"mfa-{uuid.uuid4().hex}@example.com", totp_recovery_hashes=digests)
    db.add(user)
    await db.flush()

    remaining = await user_repo.consume_totp_recovery_hash(db, user.id, digests[0])
    repeated = await user_repo.consume_totp_recovery_hash(db, user.id, digests[0])

    assert remaining == [digests[1]]
    assert repeated is None

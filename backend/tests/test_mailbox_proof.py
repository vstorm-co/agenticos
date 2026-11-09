"""An invitation inbox requires mailbox proof in this session, not in another device."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.security import create_magic_link_token, verify_special_token
from app.services import session as module
from app.services.session import SessionService

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "case",
    [
        "proved",
        "password",
        "other_address",
        "other_user",
        "revoked",
        "expired",
        "impersonated",
        "missing",
        "no_session",
    ],
)
async def test_mailbox_proof_is_bound_to_current_address_account_and_live_session(
    monkeypatch, case
):
    user_id, session_id = uuid4(), uuid4()
    row = SimpleNamespace(
        user_id=user_id,
        proved_email="Owner@example.com",
        is_active=True,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        impersonator_user_id=None,
    )
    if case == "password":
        row.proved_email = None
    if case == "other_address":
        row.proved_email = "previous@example.com"
    if case == "other_user":
        row.user_id = uuid4()
    if case == "revoked":
        row.is_active = False
    if case == "expired":
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    if case == "impersonated":
        row.impersonator_user_id = uuid4()
    read = AsyncMock(return_value=None if case == "missing" else row)
    monkeypatch.setattr(module.session_repo, "get_by_id", read)
    result = await SessionService(MagicMock()).has_mailbox_proof(
        user_id, "owner@example.com", None if case == "no_session" else session_id
    )
    assert result is (case == "proved")
    if case == "no_session":
        read.assert_not_awaited()


async def test_proof_does_not_cross_to_a_password_session_of_the_same_account(monkeypatch):
    user_id, proved_id, password_id = uuid4(), uuid4(), uuid4()

    def row(proof):
        return SimpleNamespace(
            user_id=user_id,
            proved_email=proof,
            is_active=True,
            expires_at=datetime.now(UTC) + timedelta(days=1),
            impersonator_user_id=None,
        )

    sessions = {proved_id: row("owner@example.com"), password_id: row(None)}
    read = AsyncMock(side_effect=lambda _db, sid: sessions[sid])
    monkeypatch.setattr(module.session_repo, "get_by_id", read)
    service = SessionService(MagicMock())
    assert await service.has_mailbox_proof(user_id, "owner@example.com", proved_id)
    assert not await service.has_mailbox_proof(user_id, "owner@example.com", password_id)


def test_new_mail_links_bind_the_address_without_granting_proof_to_legacy_links():
    bound = verify_special_token(
        create_magic_link_token("person", email="owner@example.com"), expected_type="magic_link"
    )
    legacy = verify_special_token(create_magic_link_token("person"), expected_type="magic_link")
    assert bound is not None and bound["email"] == "owner@example.com"
    assert legacy is not None and "email" not in legacy

"""The server-side exchange that keeps an invitation token off the sign-in trip (#1414).

Two halves. `InvitationStagingService` is the Redis exchange - opaque handle in,
token out, exactly once. `InvitationService.ensure_stageable` is the gate in front
of it: a forged or dead token is turned away before a handle is ever minted, with
one refusal that names nothing, because the endpoint it guards is public.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import NotFoundError
from app.repositories import invitation_repo
from app.services.invitation import InvitationService
from app.services.invitation_staging import InvitationStagingService

pytestmark = pytest.mark.anyio


def _pending(**over: object) -> SimpleNamespace:
    base = {
        "status": "pending",
        "email": "invitee@example.com",
        "max_uses": None,
        "used_count": 0,
        "reserved_emails": [],
        "expires_at": datetime.now(UTC) + timedelta(days=7),
    }
    base.update(over)
    return SimpleNamespace(**base)


class TestTheRedisExchange:
    async def test_stage_stores_the_token_under_a_fresh_handle_with_a_ttl(self) -> None:
        redis = MagicMock()
        redis.set = AsyncMock(return_value=True)

        handle = await InvitationStagingService(redis).stage("a-live-token")

        key, value = redis.set.await_args.args
        assert key == f"invitation:stage:{handle}"
        assert value == "a-live-token"
        assert redis.set.await_args.kwargs["ttl"] == 1800

    async def test_each_stage_mints_a_different_handle(self) -> None:
        redis = MagicMock()
        redis.set = AsyncMock(return_value=True)
        service = InvitationStagingService(redis)

        assert await service.stage("t") != await service.stage("t")

    async def test_peek_reads_the_token_without_consuming_it(self) -> None:
        redis = MagicMock()
        redis.get = AsyncMock(return_value="a-live-token")
        redis.getdel = AsyncMock()

        token = await InvitationStagingService(redis).peek("handle-1")

        assert token == "a-live-token"
        assert redis.get.await_args.args[0] == "invitation:stage:handle-1"
        redis.getdel.assert_not_awaited()

    async def test_redeem_consumes_the_handle_and_a_replay_gets_nothing(self) -> None:
        redis = MagicMock()
        # getdel deletes on read, so the second call sees an absent key - which is
        # also what a forged or expired handle looks like.
        redis.getdel = AsyncMock(side_effect=["a-live-token", None])
        service = InvitationStagingService(redis)

        assert await service.redeem("handle-1") == "a-live-token"
        assert await service.redeem("handle-1") is None


class TestTheStagingGate:
    async def test_a_live_invitation_is_stageable(self, monkeypatch, mock_db_session) -> None:
        monkeypatch.setattr(invitation_repo, "get_by_token", AsyncMock(return_value=_pending()))
        await InvitationService(mock_db_session).ensure_stageable("tok")  # no raise

    async def test_an_unknown_token_is_refused(self, monkeypatch, mock_db_session) -> None:
        monkeypatch.setattr(invitation_repo, "get_by_token", AsyncMock(return_value=None))
        with pytest.raises(NotFoundError):
            await InvitationService(mock_db_session).ensure_stageable("tok")

    async def test_an_expired_invitation_is_refused(self, monkeypatch, mock_db_session) -> None:
        expired = _pending(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        monkeypatch.setattr(invitation_repo, "get_by_token", AsyncMock(return_value=expired))
        with pytest.raises(NotFoundError):
            await InvitationService(mock_db_session).ensure_stageable("tok")

    async def test_a_revoked_invitation_is_refused(self, monkeypatch, mock_db_session) -> None:
        monkeypatch.setattr(
            invitation_repo, "get_by_token", AsyncMock(return_value=_pending(status="revoked"))
        )
        with pytest.raises(NotFoundError):
            await InvitationService(mock_db_session).ensure_stageable("tok")

    async def test_a_used_up_link_is_refused(self, monkeypatch, mock_db_session) -> None:
        spent = _pending(email=None, max_uses=1, used_count=1)
        monkeypatch.setattr(invitation_repo, "get_by_token", AsyncMock(return_value=spent))
        with pytest.raises(NotFoundError):
            await InvitationService(mock_db_session).ensure_stageable("tok")

    async def test_the_refusal_names_nothing_about_the_token(
        self, monkeypatch, mock_db_session
    ) -> None:
        """A public endpoint: "expired" versus "never existed" would let a stranger
        probe which tokens are real, so every failure reads the same."""
        monkeypatch.setattr(invitation_repo, "get_by_token", AsyncMock(return_value=None))
        with pytest.raises(NotFoundError) as unknown:
            await InvitationService(mock_db_session).ensure_stageable("forged")

        monkeypatch.setattr(
            invitation_repo,
            "get_by_token",
            AsyncMock(return_value=_pending(expires_at=datetime.now(UTC) - timedelta(days=1))),
        )
        with pytest.raises(NotFoundError) as expired:
            await InvitationService(mock_db_session).ensure_stageable("real-but-expired")

        assert str(unknown.value) == str(expired.value)

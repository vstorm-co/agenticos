"""Tests for expiring an invitation nobody accepted in time.

An invitation times out by clock, and the ordinary way it does is that nobody
ever clicks it - so no request path can be relied on to write `EXPIRED`, and
the ceiling has to be a schedule, the same reasoning as the approval sweep.
The one request-path case, a click arriving past the expiry, must record a
timeout rather than a withdrawal: `revoked` says somebody took the invitation
back, which is a different fact from the one that happened (#456).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BadRequestError
from app.db.models.organization import InvitationStatus, OrgRole
from app.services.invitation import InvitationService
from app.worker.tasks.invitation_tasks import invitation_expiry_sweep_flow

pytestmark = pytest.mark.anyio

MODULE = "app.services.invitation"


def _stale_invite() -> MagicMock:
    invite = MagicMock()
    invite.id = uuid.uuid4()
    invite.organization_id = uuid.uuid4()
    invite.email = "invited@acme.test"
    invite.role = OrgRole.MEMBER.value
    invite.status = InvitationStatus.PENDING.value
    invite.expires_at = datetime.now(UTC) - timedelta(days=1)
    return invite


class TestAClickPastExpiry:
    async def test_a_timed_out_invitation_is_marked_expired_not_revoked(self):
        """What an admin reads off the members list. `revoked` claims somebody
        withdrew the invitation; the row timed out, and the status must say so."""
        invite = _stale_invite()
        with (
            patch(f"{MODULE}.invitation_repo.get_by_token", new=AsyncMock(return_value=invite)),
            patch(f"{MODULE}.invitation_repo.expire", new=AsyncMock()) as expire,
            patch(f"{MODULE}.invitation_repo.revoke", new=AsyncMock()) as revoke,
            pytest.raises(BadRequestError, match="expired"),
        ):
            await InvitationService(MagicMock()).accept("tok", uuid.uuid4())

        expire.assert_awaited_once()
        assert expire.await_args.args[1] is invite
        revoke.assert_not_awaited()


class TestTheScheduledSweep:
    """The flow around the service. Thin on purpose - what it must not do is
    swallow the count, since that is all a Prefect run reports."""

    async def test_the_flow_answers_with_what_it_expired(self):
        with (
            patch("app.worker.tasks.invitation_tasks.get_db_context") as db_context,
            patch(
                "app.worker.tasks.invitation_tasks.InvitationService",
                return_value=MagicMock(expire_stale=AsyncMock(return_value=2)),
            ),
        ):
            db_context.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            db_context.return_value.__aexit__ = AsyncMock(return_value=False)

            assert await invitation_expiry_sweep_flow() == 2

    async def test_the_service_sweep_is_the_repository_sweep(self):
        """One UPDATE, cross-tenant by construction - a schedule has no tenant
        to be scoped to. The service adds nothing on purpose, and this pins
        that the count is handed through rather than swallowed."""
        with patch(
            f"{MODULE}.invitation_repo.expire_stale", new=AsyncMock(return_value=3)
        ) as sweep:
            assert await InvitationService(MagicMock()).expire_stale() == 3

        sweep.assert_awaited_once()

"""Who may file and decide a request to bind an agent to a public line, without a database.

The refusals that must hold before anything is read: only a holder of `channels:manage`
lists or decides requests, and filing counts against the hourly allowance of requests.
`tests/integration/test_channel_binding_requests.py` drives the same service on real rows.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, RateLimitError
from app.core.permissions import ROLE_PERMS, AuthContext, OrgRoleName, Perm
from app.db.models.channel_binding_request import BindingRequestKind
from app.services import channel_binding_requests as requests_module
from app.services.channel_binding_requests import (
    CHANNELS_MANAGE_ROLES,
    ChannelBindingRequestService,
    file_request,
)
from app.services.rate_limit import Decision

pytestmark = pytest.mark.anyio


def _ctx(role: OrgRoleName) -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=role.value)


def _untouched_db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    return db


class TestWhoDecides:
    @pytest.mark.security
    def test_the_roles_are_the_ones_that_hold_the_permission(self) -> None:
        assert set(CHANNELS_MANAGE_ROLES) == {
            role for role, perms in ROLE_PERMS.items() if Perm.CHANNELS_MANAGE in perms
        }
        assert OrgRoleName.OWNER.value in CHANNELS_MANAGE_ROLES
        assert OrgRoleName.BUILDER.value not in CHANNELS_MANAGE_ROLES

    @pytest.mark.security
    @pytest.mark.parametrize("role", [OrgRoleName.BUILDER, OrgRoleName.VIEWER])
    async def test_only_a_channels_manager_decides(self, role: OrgRoleName) -> None:
        db = _untouched_db()
        service = ChannelBindingRequestService(db)
        ctx = _ctx(role)

        with pytest.raises(AuthorizationError):
            await service.approve(ctx, uuid4())
        with pytest.raises(AuthorizationError):
            await service.decline(ctx, uuid4())
        with pytest.raises(AuthorizationError):
            await service.list_pending(ctx, 0, 50)

        db.execute.assert_not_called()


class TestTheHourlyAllowance:
    @pytest.mark.security
    async def test_filing_past_the_allowance_is_refused_before_anything_is_read(self) -> None:
        db = _untouched_db()
        refused = Decision(allowed=False, retry_after_seconds=120)
        with (
            patch.object(
                requests_module.rate_limit,
                "consume_with_local_floor",
                AsyncMock(return_value=refused),
            ) as consume,
            pytest.raises(RateLimitError) as error,
        ):
            await file_request(
                db,
                _ctx(OrgRoleName.BUILDER),
                bot_id=uuid4(),
                agent_id=uuid4(),
                kind=BindingRequestKind.BIND,
            )

        assert error.value.details == {"retry_after_seconds": 120}
        assert consume.await_args.kwargs["surface"] == "channel_binding_request"
        db.execute.assert_not_called()

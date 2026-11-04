"""The context a continuation runs as: the decider's own request, rebuilt (#2656)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.permissions import Perm
from app.services import access
from app.services.access import decider_context

pytestmark = pytest.mark.anyio

_ORG = uuid4()
_USER = uuid4()


def _rebuilt(*, user, membership):
    return (
        patch.object(access.user_repo, "get_by_id", AsyncMock(return_value=user)),
        patch.object(access.member_repo, "get", AsyncMock(return_value=membership)),
    )


async def _context(*, user, membership):
    users, members = _rebuilt(user=user, membership=membership)
    with users, members:
        return await decider_context(AsyncMock(), organization_id=_ORG, user_id=_USER)


async def test_a_member_decider_is_rebuilt_with_their_role() -> None:
    user = SimpleNamespace(is_active=True, is_app_admin=False)

    ctx = await _context(user=user, membership=SimpleNamespace(role="admin"))

    assert ctx is not None
    assert (ctx.user_id, ctx.organization_id, ctx.role, ctx.is_app_admin) == (
        _USER,
        _ORG,
        "admin",
        False,
    )
    assert ctx.has(Perm.APPROVALS_DECIDE) is True


async def test_an_app_admin_outside_the_organization_is_rebuilt_as_their_request_was() -> None:
    user = SimpleNamespace(is_active=True, is_app_admin=True)

    ctx = await _context(user=user, membership=None)

    assert ctx is not None
    assert ctx.role == "" and ctx.is_app_admin is True
    assert ctx.has(Perm.APPROVALS_DECIDE) is True


@pytest.mark.parametrize("user", [None, SimpleNamespace(is_active=False, is_app_admin=True)])
async def test_a_deactivated_or_deleted_decider_is_nobody(user: object) -> None:
    assert await _context(user=user, membership=SimpleNamespace(role="owner")) is None


async def test_somebody_neither_a_member_nor_an_app_admin_is_nobody() -> None:
    user = SimpleNamespace(is_active=True, is_app_admin=False)

    assert await _context(user=user, membership=None) is None

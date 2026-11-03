"""A parked expectation cannot borrow a replacement organization mailbox grant."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.permissions import AuthContext
from app.db.models.mcp_connection import McpConnection
from app.services.mcp_connection import McpConnectionService

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "variant", ["first", "same", "missing", "replacement", "disabled", "renewed_consent", "expired"]
)
async def test_mailbox_token_is_bound_to_account_and_generation(variant: str):
    generation = uuid4()
    grant = McpConnection(
        id=uuid4(), authorization_generation=generation, is_enabled=variant != "disabled"
    )
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    service = McpConnectionService(AsyncMock())
    with (
        patch.object(
            service, "get_org_portal_connection", AsyncMock(return_value=grant)
        ) as selected,
        patch.object(
            service,
            "get_org_portal_grant",
            AsyncMock(
                return_value=None
                if variant == "missing"
                else (McpConnection(id=uuid4()) if variant == "replacement" else grant)
            ),
        ),
        patch(
            "app.services.mcp_connection._oauth_access_token",
            AsyncMock(return_value=None if variant == "expired" else "token"),
        ) as renew,
    ):
        result = await service.reply_mailbox_token(
            ctx,
            portal_key="google",
            connection_id=grant.id,
            authorization_generation=None
            if variant == "first"
            else uuid4()
            if variant == "renewed_consent"
            else generation,
        )
        selected.assert_awaited_once_with(ctx, grant.id)
        if variant in ("first", "same"):
            assert (
                result is not None
                and result[0] == generation
                and result[1].get_secret_value() == "token"
            )
        else:
            assert result is None
            if variant != "expired":
                renew.assert_not_awaited()

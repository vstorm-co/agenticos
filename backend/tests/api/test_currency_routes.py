"""The currency read uses the path tenant's membership rather than an admin gate."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.currency import CurrencyContext

pytestmark = pytest.mark.anyio


async def test_a_member_can_read_the_currency_for_the_organization_in_the_path(
    client: AsyncClient,
) -> None:
    org_id, user_id = uuid4(), uuid4()
    ctx = AuthContext(user_id=user_id, organization_id=org_id, role=OrgRoleName.MEMBER)
    context = CurrencyContext(
        currency="PLN", default_currency="PLN", inherited=True, rates={"USD": "1", "PLN": "4"}
    )
    read = AsyncMock(return_value=context)
    app.dependency_overrides[deps.get_path_org_context] = lambda: ctx
    app.dependency_overrides[deps.get_organization_service] = lambda: MagicMock(
        currency_context=read
    )
    response = await client.get(f"{settings.API_V1_STR}/orgs/{org_id}/currency")
    assert response.status_code == 200
    assert response.json()["currency"] == "PLN"
    read.assert_awaited_once_with(org_id, user_id)

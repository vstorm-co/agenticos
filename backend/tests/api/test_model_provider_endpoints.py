"""Regional listings keep connection authority and never forward a vault key."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.api.routes.v1.model_providers import list_provider_models
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.services.model_catalog import CatalogModel
from app.services.organization_secret import OrganizationSecretService

pytestmark = pytest.mark.anyio


def context(role: str = "owner") -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=role, is_app_admin=False)


async def test_custom_listing_uses_the_endpoint_without_opening_a_vault_key():
    secrets = MagicMock(spec=OrganizationSecretService)
    with patch(
        "app.api.routes.v1.model_providers.models_for",
        new=AsyncMock(return_value=([CatalogModel(id="vendor/chat", name="Chat")], "live")),
    ) as listing:
        response = await list_provider_models(
            "openrouter", secrets, context(), base_url="https://eu.openrouter.ai/api/v1"
        )
    listing.assert_awaited_once_with(
        "openrouter", api_key=None, base_url="https://eu.openrouter.ai/api/v1"
    )
    secrets.listing_key.assert_not_called()
    assert response.items[0].id == "vendor/chat"


async def test_custom_listing_requires_connection_management_before_fetching():
    with (
        patch("app.api.routes.v1.model_providers.models_for", new=AsyncMock()) as listing,
        pytest.raises(AuthorizationError),
    ):
        await list_provider_models(
            "openrouter",
            MagicMock(spec=OrganizationSecretService),
            context("member"),
            base_url="http://internal/v1",
        )
    listing.assert_not_called()


@pytest.mark.parametrize(
    ("provider", "endpoint"),
    [
        ("openai", "https://example.com/v1"),
        ("openrouter", "file:///etc/passwd"),
        ("openrouter", "https://user:password@example.com/v1"),
    ],
)
async def test_custom_listing_refuses_unsupported_provider_or_unsafe_url(
    provider: str, endpoint: str
):
    with pytest.raises(BadRequestError):
        await list_provider_models(
            provider, MagicMock(spec=OrganizationSecretService), context(), base_url=endpoint
        )

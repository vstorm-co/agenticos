"""Regional listings keep connection authority and never forward a vault key."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.api.routes.v1.model_providers import list_provider_models
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.services.model_catalog import CatalogModel
from app.services.organization_secret import OrganizationSecretService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


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


async def test_a_custom_stav_listing_sends_the_key_the_profile_will_send():
    secrets = MagicMock(spec=OrganizationSecretService)
    secrets.listing_key = AsyncMock(return_value="sk_stav_test")
    ctx, secret_id = context(), uuid4()
    with (
        patch(
            "app.api.routes.v1.model_providers.validate_endpoint_url",
            new=AsyncMock(side_effect=lambda url: url),
        ),
        patch(
            "app.api.routes.v1.model_providers.models_for",
            new=AsyncMock(return_value=([CatalogModel(id="mistralai/m", name="M")], "live")),
        ) as listing,
    ):
        await list_provider_models(
            "stav", secrets, ctx, base_url="https://staging-api.stav.ai/v1", secret_id=secret_id
        )
    listing.assert_awaited_once_with(
        "stav", api_key="sk_stav_test", base_url="https://staging-api.stav.ai/v1"
    )
    secrets.listing_key.assert_awaited_once_with(ctx, "stav", secret_id=secret_id)


async def test_a_stav_listing_says_which_apis_each_model_is_served_on():
    secrets = MagicMock(spec=OrganizationSecretService)
    secrets.listing_key = AsyncMock(return_value="sk_stav_test")
    models = [
        CatalogModel(id="a/chat", name="A", surfaces=("chat", "messages", "responses")),
        CatalogModel(id="openai/o3-pro", name="B", surfaces=("responses",)),
        CatalogModel(id="c/unstated", name="C"),
    ]
    with patch(
        "app.api.routes.v1.model_providers.models_for",
        new=AsyncMock(return_value=(models, "live")),
    ):
        response = await list_provider_models("stav", secrets, context())
    assert [item.apis for item in response.items] == [["chat", "responses"], ["responses"], []]


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


async def test_custom_stav_listing_cannot_use_an_implicit_organization_key() -> None:
    secrets = MagicMock(spec=OrganizationSecretService)
    with (
        patch(
            "app.api.routes.v1.model_providers.validate_endpoint_url",
            new=AsyncMock(side_effect=lambda url: url),
        ),
        patch("app.api.routes.v1.model_providers.models_for", new=AsyncMock()) as listing,
        pytest.raises(BadRequestError),
    ):
        await list_provider_models(
            "stav", secrets, context(), base_url="https://attacker.example/v1"
        )
    secrets.listing_key.assert_not_called()
    listing.assert_not_called()

"""Regional listings keep connection authority and never forward a vault key."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.api.routes.v1.model_providers import list_provider_models
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.services.model_catalog import CatalogModel
from app.services.organization_secret import OrganizationSecretService
from app.services.subscription_accounts import SubscriptionAccountService

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
            "openrouter",
            secrets,
            context(),
            base_url="https://eu.openrouter.ai/api/v1",
            accounts=MagicMock(spec=SubscriptionAccountService),
        )
    listing.assert_awaited_once_with(
        "openrouter",
        api_key=None,
        base_url="https://eu.openrouter.ai/api/v1",
        api=None,
        refresh=False,
    )
    secrets.listing_key.assert_not_called()
    assert response.items[0].id == "vendor/chat"


@pytest.mark.parametrize("provider", ["stav", "otari", "zai"])
async def test_a_custom_authenticated_listing_sends_the_selected_key(provider: str):
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
            provider,
            secrets,
            ctx,
            base_url="https://staging-api.stav.ai/v1",
            secret_id=secret_id,
            accounts=MagicMock(spec=SubscriptionAccountService),
        )
    listing.assert_awaited_once_with(
        provider,
        api_key="sk_stav_test",
        base_url="https://staging-api.stav.ai/v1",
        api=None,
        refresh=False,
    )
    secrets.listing_key.assert_awaited_once_with(ctx, provider, secret_id=secret_id)


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
        response = await list_provider_models(
            "stav", secrets, context(), accounts=MagicMock(spec=SubscriptionAccountService)
        )
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
            accounts=MagicMock(spec=SubscriptionAccountService),
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
            provider,
            MagicMock(spec=OrganizationSecretService),
            context(),
            base_url=endpoint,
            accounts=MagicMock(spec=SubscriptionAccountService),
        )


@pytest.mark.parametrize("provider", ["stav", "otari", "zai"])
async def test_custom_listing_cannot_use_an_implicit_organization_key(provider: str) -> None:
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
            provider,
            secrets,
            context(),
            base_url="https://attacker.example/v1",
            accounts=MagicMock(spec=SubscriptionAccountService),
        )
    secrets.listing_key.assert_not_called()
    listing.assert_not_called()


async def test_otari_listing_without_a_destination_does_not_open_a_key() -> None:
    secrets = MagicMock(spec=OrganizationSecretService)
    with patch("app.api.routes.v1.model_providers.models_for", new=AsyncMock()) as listing:
        response = await list_provider_models(
            "otari",
            secrets,
            context("builder"),
            secret_id=uuid4(),
            accounts=MagicMock(spec=SubscriptionAccountService),
        )
    assert response.items == []
    assert response.source == "unlisted"
    secrets.listing_key.assert_not_called()
    listing.assert_not_called()


@pytest.mark.parametrize("provider", ["openai_compatible", "anthropic_compatible"])
async def test_a_custom_provider_lists_the_endpoint_it_is_given(provider: str) -> None:
    """The endpoint the organization runs, read with the key stored for it.

    The listing reaches no host the profile does not, so it is asked with the
    same key the runs send.
    """
    secrets = MagicMock(spec=OrganizationSecretService)
    secrets.listing_key = AsyncMock(return_value="sk_custom_test")
    ctx, secret_id = context(), uuid4()
    with (
        patch(
            "app.api.routes.v1.model_providers.validate_endpoint_url",
            new=AsyncMock(side_effect=lambda url: url),
        ),
        patch(
            "app.api.routes.v1.model_providers.models_for",
            new=AsyncMock(return_value=([CatalogModel(id="our-model", name="Ours")], "live")),
        ) as listing,
    ):
        await list_provider_models(
            provider,
            secrets,
            ctx,
            base_url="https://models.example",
            secret_id=secret_id,
            accounts=MagicMock(spec=SubscriptionAccountService),
        )
    listing.assert_awaited_once_with(
        provider,
        api_key="sk_custom_test",
        base_url="https://models.example",
        api=None,
        refresh=False,
    )
    secrets.listing_key.assert_awaited_once_with(ctx, provider, secret_id=secret_id)


async def test_a_custom_listing_is_asked_where_the_sdk_reaches_it() -> None:
    """An endpoint that already carries the path the SDK adds is trimmed.

    Anthropic's SDK posts to `<endpoint>/v1/messages`, so an endpoint written
    as `https://models.example/v1` would ask for `/v1/v1/messages` - and the
    listing would fail with a 404 that names the path rather than the cause.
    """
    secrets = MagicMock(spec=OrganizationSecretService)
    secrets.listing_key = AsyncMock(return_value="sk_custom_test")
    ctx, secret_id = context(), uuid4()
    with (
        patch(
            "app.api.routes.v1.model_providers.validate_endpoint_url",
            new=AsyncMock(side_effect=lambda url: url),
        ),
        patch(
            "app.api.routes.v1.model_providers.models_for",
            new=AsyncMock(return_value=([], "live")),
        ) as listing,
    ):
        await list_provider_models(
            "anthropic_compatible",
            secrets,
            ctx,
            base_url="https://models.example/v1",
            secret_id=secret_id,
            accounts=MagicMock(spec=SubscriptionAccountService),
        )
    assert listing.await_args.kwargs["base_url"] == "https://models.example"


@pytest.mark.parametrize("provider", ["openai_compatible", "anthropic_compatible"])
async def test_a_custom_provider_without_an_endpoint_lists_nothing(provider: str) -> None:
    """It exists only at an endpoint somebody names, so there is nothing to ask
    before one is named."""
    secrets = MagicMock(spec=OrganizationSecretService)
    with patch("app.api.routes.v1.model_providers.models_for", new=AsyncMock()) as listing:
        response = await list_provider_models(
            provider,
            secrets,
            context("builder"),
            accounts=MagicMock(spec=SubscriptionAccountService),
        )
    assert response.items == []
    assert response.source == "unlisted"
    secrets.listing_key.assert_not_called()
    listing.assert_not_called()


async def test_explicit_refresh_preserves_endpoint_and_key_authorization() -> None:
    secrets = MagicMock(spec=OrganizationSecretService)
    with patch(
        "app.api.routes.v1.model_providers.models_for",
        new=AsyncMock(return_value=([CatalogModel(id="a/chat", name="Chat")], "live")),
    ) as listing:
        await list_provider_models(
            "openrouter",
            secrets,
            context(),
            accounts=MagicMock(spec=SubscriptionAccountService),
            base_url="https://eu.openrouter.ai/api/v1",
            refresh=True,
        )
        listing.assert_awaited_once_with(
            "openrouter",
            api_key=None,
            base_url="https://eu.openrouter.ai/api/v1",
            api=None,
            refresh=True,
        )
        with pytest.raises(AuthorizationError):
            await list_provider_models(
                "openrouter",
                secrets,
                context("member"),
                accounts=MagicMock(spec=SubscriptionAccountService),
                base_url="https://eu.openrouter.ai/api/v1",
                refresh=True,
            )
    secrets.listing_key.assert_not_called()

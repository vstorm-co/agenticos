"""Currency settings and profile rates persist without reinterpreting old money."""

from decimal import Decimal

import pytest
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import SpendLedger
from app.agents.profile_pricing import ProfilePricingModel
from app.agents.stav_cost import _Capture
from app.core.currency import CurrencySettings
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.secret_kinds import ApiKeySecret, seal_secret
from app.core.vault import VaultScope
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.organization import Organization, OrganizationMember
from app.repositories import credential_repo, personal_model_key
from app.schemas.organization import OrganizationUpdate
from app.schemas.token_pricing import TokenPricing
from app.services.currency import CurrencyService
from app.services.model_profile import ModelProfileService
from app.services.organization import OrganizationService
from app.services.personal_model_key import PersonalModelKeyService
from tests.integration._keys import provider_key
from tests.integration.test_profile_pricing import tenant
from tests.test_profile_pricing import answer

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_profile_currency_is_independent_of_organization_and_retains_its_conversion_snapshot(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = await tenant(db)
    settings = CurrencySettings(
        default_currency="PLN", rates={"USD": "1", "EUR": "0.9", "PLN": "4"}
    )
    deployment = DeploymentSettings(currency_settings=settings.model_dump(mode="json"))
    db.add(deployment)
    await db.flush()
    profile = await credential_repo.create_profile(
        db,
        organization_id=ctx.organization_id,
        label="Enterprise EUR",
        provider="ollama",
        model="alias",
        secret_id=None,
        base_url="http://localhost:11434/v1",
        runs_without_key=True,
        custom_pricing=TokenPricing(currency="EUR", input="9", output="0").model_dump(mode="json"),
    )
    service = ModelProfileService(db)
    original = await service.resolve(ctx, profile_id=profile.id)
    assert (await service.currency_context(ctx)).currency == "PLN"
    monkeypatch.setattr(
        "app.agents.model_resolver._build_model", lambda *args: FunctionModel(answer)
    )
    first = original.build()
    assert isinstance(first, ProfilePricingModel)
    usage = RequestUsage(input_tokens=1_000_000)
    first.apply(usage)
    ledger = SpendLedger()
    ledger.record("alias", usage, "ollama")
    assert ledger.total_usd == Decimal(10)
    deployment.currency_settings = CurrencySettings(
        default_currency="USD", rates={"USD": "1", "EUR": "0.5"}
    ).model_dump(mode="json")
    await db.flush()
    later = await service.resolve(ctx, profile_id=profile.id)
    second = later.build()
    assert isinstance(second, ProfilePricingModel)
    new_usage = RequestUsage(input_tokens=1_000_000)
    second.apply(new_usage)
    assert new_usage.cost == Decimal(18)
    assert usage.cost == ledger.total_usd == Decimal(10)
    assert original.credential.exchange_rates["EUR"] == Decimal("0.9")
    assert profile.custom_pricing["currency"] == "EUR"


async def test_organization_overrides_inherit_and_do_not_modify_the_existing_usd_budget(
    db: AsyncSession,
) -> None:
    ctx = await tenant(db)
    db.add(
        OrganizationMember(organization_id=ctx.organization_id, user_id=ctx.user_id, role="owner")
    )
    db.add(
        DeploymentSettings(
            currency_settings={
                "default_currency": "PLN",
                "rates": {"USD": "1", "PLN": "4", "EUR": "0.9"},
            }
        )
    )
    organization = await db.get(Organization, ctx.organization_id)
    assert organization is not None
    organization.monthly_budget_usd = Decimal(100)
    await db.flush()
    service = OrganizationService(db)
    inherited = await service.currency_context(ctx.organization_id, ctx.user_id)
    assert inherited.inherited and inherited.currency == "PLN"
    await service.update(
        ctx.organization_id, OrganizationUpdate(currency="EUR"), requester_id=ctx.user_id
    )
    assert (await service.currency_context(ctx.organization_id, ctx.user_id)).currency == "EUR"
    assert organization.monthly_budget_usd == Decimal(100)
    with pytest.raises(BadRequestError):
        await service.update(
            ctx.organization_id, OrganizationUpdate(currency="ZZZ"), requester_id=ctx.user_id
        )
    await service.update(
        ctx.organization_id, OrganizationUpdate(currency=None), requester_id=ctx.user_id
    )
    assert organization.currency is None
    assert (await CurrencyService(db).context(ctx.organization_id)).currency == "PLN"
    assert organization.monthly_budget_usd == Decimal(100)


@pytest.mark.parametrize("personal", [False, True], ids=["vault", "personal"])
async def test_stav_preserves_provider_bills_with_custom_usd_pricing(
    db: AsyncSession, personal: bool
) -> None:
    ctx = await tenant(db)
    assert ctx.user_id is not None
    db.add(
        OrganizationMember(organization_id=ctx.organization_id, user_id=ctx.user_id, role="owner")
    )
    db.add(DeploymentSettings(currency_settings={"rates": {"USD": "1", "EUR": "0.9"}}))
    pricing = TokenPricing(input=2, output=0)
    profile = await credential_repo.create_profile(
        db,
        organization_id=ctx.organization_id,
        label="Stav",
        provider="stav",
        model="test-model",
        secret_id=await provider_key(db, ctx.organization_id, purpose="stav"),
        custom_pricing=pricing.model_dump(mode="json"),
    )
    if personal:
        sealed = seal_secret(
            ApiKeySecret(api_key="sk-test-personal"), scope=VaultScope.user(ctx.user_id)
        )
        await personal_model_key.save(
            db,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            provider="stav",
            endpoint="",
            sealed_secret=sealed.ciphertext,
            key_version=sealed.key_version,
        )
        resolved = await PersonalModelKeyService(db).resolve(ctx, profile)
    else:
        resolved = await ModelProfileService(db).resolve(ctx, profile_id=profile.id)

    rates = resolved.credential.exchange_rates
    assert rates["EUR"] == Decimal("0.9")
    usage = RequestUsage(input_tokens=1_000_000)
    _Capture(cost=Decimal(9), currency="EUR", exchange_rates=rates).apply(usage)
    assert usage.cost == Decimal(10)
    model = resolved.build()
    assert isinstance(model, ProfilePricingModel)
    model.apply(usage)
    assert usage.cost == Decimal(2)
    assert usage.__dict__["provider_reported_cost"]["currency"] == "EUR"


async def test_currency_context_is_not_readable_outside_the_tenant(db: AsyncSession) -> None:
    first, second = await tenant(db), await tenant(db)
    service = OrganizationService(db)
    with pytest.raises(NotFoundError):
        await service.currency_context(first.organization_id, second.user_id)

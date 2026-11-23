"""Currency settings and profile rates persist without reinterpreting old money."""

from decimal import Decimal

import pytest
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import SpendLedger
from app.agents.profile_pricing import ProfilePricingModel
from app.core.currency import CurrencySettings
from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.organization import Organization, OrganizationMember
from app.repositories import credential_repo
from app.schemas.organization import OrganizationUpdate
from app.schemas.token_pricing import TokenPricing
from app.services.currency import CurrencyService
from app.services.model_profile import ModelProfileService
from app.services.organization import OrganizationService
from tests.integration.test_profile_pricing import tenant
from tests.test_profile_pricing import answer

pytestmark = pytest.mark.anyio


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


async def test_currency_context_is_not_readable_outside_the_tenant(db: AsyncSession) -> None:
    first, second = await tenant(db), await tenant(db)
    service = OrganizationService(db)
    with pytest.raises(NotFoundError):
        await service.currency_context(first.organization_id, second.user_id)

"""Currencies are independent of UI language, model identity and accounting USD."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities.budget import (
    BudgetGuard,
    BudgetScope,
    SpendLedger,
    SpendLimit,
    price_request,
)
from app.agents.profile_pricing import ProfilePricingModel
from app.agents.stav_cost import _Capture
from app.core.currency import CurrencySettings, to_usd
from app.core.exceptions import BadRequestError, NotFoundError
from app.schemas.token_pricing import TokenPricing
from app.services.currency import CurrencyService
from tests.test_profile_pricing import answer

pytestmark = [pytest.mark.anyio, pytest.mark.security]
RATES = {"USD": Decimal(1), "EUR": Decimal("0.9"), "PLN": Decimal("4"), "NOK": Decimal("10.5")}


@pytest.mark.parametrize(
    "rates,default",
    [
        ({"USD": "1", "EUR": "0"}, "USD"),
        ({"USD": "1", "EUR": "NaN"}, "USD"),
        ({"USD": "2"}, "USD"),
        ({"EUR": "0.9"}, "EUR"),
        ({"USD": "1"}, "PLN"),
        ({"USD": "1", "INVALID": "2"}, "USD"),
    ],
)
def test_invalid_deployment_currency_settings_are_refused(rates, default):
    with pytest.raises(ValidationError):
        CurrencySettings(default_currency=default, rates=rates)


def test_cross_currency_pricing_is_correct_even_when_the_organization_uses_usd():
    pricing = TokenPricing(input="9", output="0", currency="EUR")
    usage = RequestUsage(input_tokens=1_000_000)
    assert pricing.cost(usage) == Decimal(9)
    assert price_request(
        usage, "private-alias", "ollama", custom_pricing=pricing, exchange_rates=RATES
    ) == Decimal(10)
    assert to_usd(Decimal("21"), "NOK", RATES) == 2
    assert TokenPricing(input="1", output="2").currency == "USD"


@pytest.mark.parametrize(
    "rates", [{}, {"EUR": Decimal(0)}, {"EUR": Decimal(-1)}, {"EUR": Decimal("NaN")}]
)
def test_a_missing_or_invalid_exchange_rate_leaves_only_nonzero_amounts_unknown(rates):
    assert to_usd(Decimal("9"), "EUR", rates) is None
    assert to_usd(Decimal(0), "EUR", rates) == 0


async def test_an_explicitly_free_profile_can_run_under_a_cap_without_its_exchange_rate() -> None:
    model = ProfilePricingModel(
        FunctionModel(answer), TokenPricing(input=0, output=0, currency="EUR"), uuid4()
    )
    ledger = SpendLedger()
    guard = BudgetGuard(
        ledger=ledger, limits=[SpendLimit(scope=BudgetScope.RUN, limit_usd=Decimal("10"))]
    )
    await Agent(model, capabilities=[guard]).run("hello")
    (entry,) = ledger.entries
    assert entry.priced and entry.cost_usd == 0


@pytest.mark.parametrize(
    "pricing",
    [
        TokenPricing(input=9, output=0, currency="EUR"),
        TokenPricing(input=0, output=0, cache_read=9, currency="EUR"),
        TokenPricing(input=0, output=0, cache_write=9, currency="EUR"),
    ],
)
async def test_a_capped_request_is_refused_before_inference_when_its_currency_cannot_be_converted(
    pricing: TokenPricing,
) -> None:
    calls = []

    def respond(messages, info):
        calls.append(True)
        return answer(messages, info)

    model = ProfilePricingModel(FunctionModel(respond), pricing, uuid4())
    guard = BudgetGuard(limits=[SpendLimit(scope=BudgetScope.RUN, limit_usd=Decimal("10"))])
    with pytest.raises(BadRequestError, match="price is unknown"):
        await Agent(model, capabilities=[guard]).run("hello")
    assert calls == []
    ledger = SpendLedger()
    await Agent(model, capabilities=[BudgetGuard(ledger=ledger)]).run("uncapped")
    assert calls == [True] and ledger.has_unpriced_models


def test_recorded_cost_and_rate_do_not_change_when_operator_rates_change():
    rates = dict(RATES)
    pricing = TokenPricing(input="9", output="0", currency="EUR")
    before = ProfilePricingModel(FunctionModel(answer), pricing, uuid4(), rates)
    rates["EUR"] = Decimal("0.5")
    first = RequestUsage(input_tokens=1_000_000)
    before.apply(first)
    after = ProfilePricingModel(FunctionModel(answer), pricing, uuid4(), rates)
    second = RequestUsage(input_tokens=1_000_000)
    after.apply(second)
    assert first.cost == Decimal(10) and second.cost == Decimal(18)
    provenance = first.__dict__["profile_pricing"]
    assert provenance["currency"] == "EUR" and provenance["amount"] == "9"
    assert provenance["units_per_usd"] == "0.9"


async def test_organization_currency_inherits_overrides_and_does_not_change_model_prices(
    monkeypatch,
):
    org = SimpleNamespace(currency=None)
    row = SimpleNamespace(
        currency_settings=CurrencySettings(default_currency="PLN", rates=RATES).model_dump(
            mode="json"
        )
    )
    with (
        patch("app.services.currency.organization_repo.get_by_id", AsyncMock(return_value=org)),
        patch("app.services.currency.deployment_settings_repo.get", AsyncMock(return_value=row)),
    ):
        service = CurrencyService(AsyncMock())
        context = await service.context(uuid4())
        assert context.currency == "PLN" and context.inherited
        org.currency = "EUR"
        context = await service.context(uuid4())
        assert context.currency == "EUR" and not context.inherited
        assert context.rates["PLN"] == 4
        assert await service.rates_for(None) == {"USD": 1}
        assert await service.rates_for(TokenPricing(input=1, output=1, currency="EUR")) == RATES
    with (
        patch("app.services.currency.organization_repo.get_by_id", AsyncMock(return_value=None)),
        pytest.raises(NotFoundError),
    ):
        await service.context(uuid4())


async def test_environment_defaults_are_used_only_without_a_deployment_override(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEFAULT_ORG_CURRENCY", "PLN")
    monkeypatch.setattr(settings, "CURRENCY_RATES", RATES)
    with patch("app.services.currency.deployment_settings_repo.get", AsyncMock(return_value=None)):
        config = await CurrencyService(AsyncMock()).settings()
        assert config.default_currency == "PLN" and config.rates == RATES


def test_stav_uses_generic_rates_and_keeps_the_actual_billed_currency():
    usage = RequestUsage()
    _Capture(cost=Decimal(9), currency="EUR", exchange_rates=RATES).apply(usage)
    assert usage.cost == Decimal(10)
    assert usage.__dict__["provider_reported_cost"]["units_per_usd"] == "0.9"


@pytest.mark.parametrize("rate", [Decimal(0), Decimal(-1), Decimal("NaN"), Decimal("Infinity")])
def test_an_invalid_stav_conversion_rate_never_becomes_a_bill(rate):
    usage = RequestUsage()
    _Capture(cost=Decimal(9), currency="EUR", exchange_rates={"EUR": rate}).apply(usage)
    assert usage.cost is None

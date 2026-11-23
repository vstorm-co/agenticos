"""Negotiated rates follow actual profiles through SDK request accounting."""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage, RunUsage

from app.agents.capabilities.budget import (
    BudgetExceeded,
    BudgetGuard,
    BudgetScope,
    SpendLedger,
    SpendLimit,
    booked_to,
    price_request,
    usage_counts,
    usage_delta,
)
from app.agents.model_resolver import ResolvedCredential, build_model
from app.agents.profile_pricing import ProfilePricingModel, catalog_token_pricing
from app.core.secret_kinds import NoSecret
from app.schemas.model_profile import ModelProfileCreate, ModelProfileUpdate
from app.schemas.token_pricing import TokenPricing

pytestmark = pytest.mark.anyio
RATES = TokenPricing(
    input=Decimal("2"), output=Decimal("8"), cache_read=Decimal("0.5"), cache_write=Decimal("3")
)


def answer(messages, info):
    return ModelResponse(
        parts=[TextPart("done")],
        model_name="same-alias",
        usage=RequestUsage(
            input_tokens=1_000_000,
            output_tokens=500_000,
            cache_read_tokens=200_000,
            cache_write_tokens=100_000,
        ),
    )


def priced(rates=RATES, profile_id=None):
    return ProfilePricingModel(FunctionModel(answer, model_name="same-alias"), rates, profile_id)


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, "5.8"),
        ({"cache_read": None, "cache_write": None}, "6"),
        ({"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}, "0"),
    ],
)
def test_cache_tokens_are_not_charged_twice_and_zero_is_a_price(changes, expected):
    rates = TokenPricing.model_validate({**RATES.model_dump(), **changes})
    assert rates.cost(answer([], None).usage) == Decimal(expected)


@pytest.mark.parametrize("field", ["input", "output", "cache_read", "cache_write"])
@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "1000001"])
def test_invalid_rates_are_refused(field, value):
    with pytest.raises(ValidationError):
        TokenPricing.model_validate({**RATES.model_dump(), field: value})


def test_creation_requires_both_base_prices_and_updates_distinguish_omission_from_null():
    with pytest.raises(ValidationError):
        ModelProfileCreate(label="x", provider="ollama", model="alias", custom_pricing={"input": 0})
    assert "custom_pricing" not in ModelProfileUpdate().model_fields_set
    assert ModelProfileUpdate(custom_pricing=None).model_fields_set == {"custom_pricing"}
    assert ModelProfileCreate(label="x", provider="ollama", model="alias").custom_pricing is None


@pytest.mark.parametrize(
    "usage",
    [
        RequestUsage(input_tokens=-1),
        RequestUsage(output_tokens=-1),
        RequestUsage(input_tokens=1, cache_read_tokens=2),
        RequestUsage(cache_write_tokens=-1),
    ],
)
def test_inconsistent_usage_never_falls_back_to_an_unrelated_catalog_price(usage):
    priced().apply(usage)
    entry = SpendLedger().record("gpt-4.1", usage, "openai")
    assert not entry.priced
    assert entry.cost_usd == 0


async def test_keyless_profiles_get_their_own_rates_even_for_equal_model_ids():
    ledger = SpendLedger()
    for profile_id, rates in [(uuid4(), RATES), (uuid4(), TokenPricing(input=0, output=0))]:
        response = await priced(rates, profile_id).request([], None, ModelRequestParameters())
        ledger.record(response.model_name, response.usage, "ollama")
        assert response.usage.__dict__["profile_pricing"]["profile_id"] == str(profile_id)
    assert [entry.cost_usd for entry in ledger.entries] == [Decimal("5.8"), 0]
    assert not ledger.has_unpriced_models
    assert not any(entry.provider_reported for entry in ledger.entries)


async def test_fallback_uses_the_responding_profiles_price_and_delegate_attribution():
    def fail(messages, info):
        raise ModelHTTPError(429, "same-alias")

    model = FallbackModel(
        ProfilePricingModel(FunctionModel(fail), TokenPricing(input=100, output=100), uuid4()),
        priced(),
    )
    ledger = SpendLedger()
    guard = BudgetGuard(ledger=ledger, provider="openai")
    with booked_to("child", has_own_row=True):
        await Agent(model, capabilities=[guard.for_delegate(provider="ollama")]).run("hi")
    assert ledger.total_usd == Decimal("5.8")
    assert ledger.share_of("child").cost_usd == ledger.total_usd


async def test_custom_cost_is_the_amount_that_exhausts_the_budget():
    ledger = SpendLedger()
    guard = BudgetGuard(
        ledger=ledger,
        provider="ollama",
        limits=[SpendLimit(scope=BudgetScope.ORGANIZATION, limit_usd=Decimal("5"))],
    )
    agent = Agent(priced(), capabilities=[guard])
    await agent.run("hi")
    with pytest.raises(BudgetExceeded):
        await agent.run("again")
    assert len(ledger.entries) == 1


async def test_streamed_usage_is_priced_before_it_reaches_the_guard():
    async def stream(messages, info):
        yield "hello world"

    model = ProfilePricingModel(
        FunctionModel(stream_function=stream, model_name="unknown"), RATES, uuid4()
    )
    ledger = SpendLedger()
    async with Agent(model, capabilities=[BudgetGuard(ledger=ledger)]).run_stream("hi") as result:
        await result.get_output()
    assert ledger.total_usd > 0
    assert not ledger.has_unpriced_models


@pytest.mark.parametrize("rates", [RATES, TokenPricing(input=0, output=0)])
def test_aggregate_and_nested_deltas_preserve_profile_costs_including_free_requests(rates):
    total = RunUsage()
    before = usage_counts(total)
    request = answer([], None).usage
    priced(rates).apply(request)
    total.incr(request)
    total.requests += 1
    delta = usage_delta(before, total)
    assert delta is not None
    ledger = SpendLedger()
    entry = ledger.record("unknown", delta, "ollama")
    assert entry.cost_usd == rates.cost(request)
    assert entry.priced
    total.incr(RequestUsage(input_tokens=30))
    total.requests += 1
    assert not ledger.record("unknown", total, "ollama").priced


def test_provider_bill_is_overridden_but_preserved_as_request_provenance():
    usage = answer([], None).usage
    usage.cost = Decimal(99)
    usage.provider_reported_cost_usd = Decimal(99)
    usage.provider_reported_requests = 1
    priced().apply(usage)
    assert price_request(usage, "known", "stav") == Decimal("5.8")
    assert not SpendLedger().record("known", usage, "stav").provider_reported


def test_catalog_rates_and_estimates_do_not_depend_on_a_saved_override():
    auto = catalog_token_pricing("openai", "gpt-4.1")
    assert auto is not None and auto.input > 0
    assert catalog_token_pricing("ollama", "unknown") is None
    assert catalog_token_pricing("github_copilot", "gpt-4.1") is None
    assert (
        price_request(
            RequestUsage(input_tokens=1_000_000), "gpt-4.1", "openai", custom_pricing=RATES
        )
        == 2
    )


def test_client_construction_keeps_pricing_on_keyless_profiles(monkeypatch):
    monkeypatch.setattr(
        "app.agents.model_resolver._build_model", lambda *args: FunctionModel(answer)
    )
    credential = ResolvedCredential(
        provider="ollama", secret=NoSecret(), custom_pricing=RATES, profile_id=uuid4()
    )
    assert isinstance(build_model(credential, "same-alias"), ProfilePricingModel)


def test_case_generation_estimate_uses_custom_rates_for_an_unknown_alias():
    from app.services.case_generation.estimate import estimate_cost

    assert estimate_cost(
        "abcd",
        1,
        model_name="unknown",
        provider="ollama",
        custom_pricing=TokenPricing(input="2", output="5"),
    ) == Decimal("0.005002")


async def test_incomplete_custom_usage_refuses_further_spending_under_a_budget():
    from app.core.exceptions import BadRequestError

    usage = RequestUsage(input_tokens=1, cache_read_tokens=2)
    priced().apply(usage)
    ledger = SpendLedger()
    ledger.record("alias", usage, "ollama")
    guard = BudgetGuard(
        ledger=ledger, limits=[SpendLimit(scope=BudgetScope.RUN, limit_usd=Decimal("1"))]
    )
    with pytest.raises(BadRequestError, match="incomplete"):
        await guard.assert_within_budget()
    assert not await guard.can_afford_next_request()
    guard.limits = []
    await guard.assert_within_budget()
    assert await guard.can_afford_next_request()


def test_invalid_custom_usage_survives_aggregate_and_nested_accounting():
    total = RunUsage()
    before = usage_counts(total)
    request = RequestUsage(input_tokens=1, cache_read_tokens=2)
    priced().apply(request)
    total.incr(request)
    total.requests += 1
    delta = usage_delta(before, total)
    assert delta is not None
    entry = SpendLedger().record("gpt-4.1", delta, "openai")
    assert not entry.priced and entry.custom_pricing


@pytest.mark.parametrize("cost", [None, Decimal("-1"), Decimal("NaN"), Decimal("Infinity")])
def test_invalid_tagged_costs_cannot_reduce_spending_or_become_a_catalog_price(cost):
    usage = RequestUsage(input_tokens=10, cost=cost, profile_priced_requests=1)
    entry = SpendLedger().record("gpt-4.1", usage, "openai")
    assert entry.cost_usd == 0 and not entry.priced

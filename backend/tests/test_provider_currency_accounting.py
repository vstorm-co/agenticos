"""A reported foreign bill cannot silently become a different catalog charge."""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage, RunUsage

from app.agents.capabilities.budget import SpendLedger, usage_counts, usage_delta
from app.agents.profile_pricing import ProfilePricingModel
from app.agents.stav_cost import _Capture
from app.schemas.token_pricing import TokenPricing
from tests.test_profile_pricing import answer

pytestmark = pytest.mark.security


def test_a_bill_without_its_exchange_rate_keeps_its_origin_and_cannot_use_catalog_pricing() -> None:
    usage = RequestUsage(input_tokens=1_000_000)
    _Capture(cost=Decimal(9), currency="EUR", exchange_rates={}).apply(usage)

    entry = SpendLedger().record("gpt-4o-mini", usage, "stav")

    assert not entry.priced and entry.cost_usd == 0
    assert usage.__dict__["provider_reported_cost"] == {
        "provider": "stav",
        "amount": "9",
        "currency": "EUR",
        "cost_usd": None,
        "nok_per_usd": None,
        "units_per_usd": None,
    }


def test_aggregated_bills_retain_known_subtotal_but_remain_partial() -> None:
    known, unknown = RequestUsage(input_tokens=1_000_000), RequestUsage(input_tokens=1_000_000)
    _Capture(cost=Decimal(2), currency="USD", exchange_rates={}).apply(known)
    _Capture(cost=Decimal(9), currency="EUR", exchange_rates={}).apply(unknown)
    total = RunUsage()
    total.incr(known)
    total.incr(unknown)

    entry = SpendLedger().record("gpt-4o-mini", total, "stav")

    assert not entry.priced and entry.cost_usd == 2


def test_a_nested_unconvertible_bill_retains_its_refusal_in_the_usage_delta() -> None:
    total = RunUsage()
    before = usage_counts(total)
    unknown = RequestUsage(input_tokens=1_000_000)
    _Capture(cost=Decimal(9), currency="EUR", exchange_rates={}).apply(unknown)
    total.incr(unknown)
    delta = usage_delta(before, total)
    assert delta is not None
    assert not SpendLedger().record("gpt-4o-mini", delta, "stav").priced


def test_a_custom_override_remains_authoritative_without_losing_the_original_foreign_bill() -> None:
    usage = RequestUsage(input_tokens=1_000_000)
    _Capture(cost=Decimal(9), currency="EUR", exchange_rates={}).apply(usage)
    ProfilePricingModel(FunctionModel(answer), TokenPricing(input=2, output=0), uuid4()).apply(
        usage
    )

    entry = SpendLedger().record("gpt-4o-mini", usage, "stav")

    assert entry.priced and entry.cost_usd == 2
    assert usage.__dict__["provider_reported_cost"]["amount"] == "9"

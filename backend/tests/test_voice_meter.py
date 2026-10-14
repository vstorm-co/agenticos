"""Booking a call's spend as it happens (#54)."""

from decimal import Decimal

from pydantic_ai.usage import RunUsage

from app.agents.capabilities.budget import SpendLedger
from app.services import realtime_models
from app.services.voice.meter import UsageMeter


def test_each_response_books_only_what_it_added():
    ledger = SpendLedger()
    meter = UsageMeter(
        ledger, entry=realtime_models.offered("openai", "gpt-realtime"), model_name="gpt-realtime"
    )

    meter.book_response(RunUsage(input_tokens=100, output_tokens=50, cost=Decimal("0.02")))
    meter.book_response(RunUsage(input_tokens=250, output_tokens=90, cost=Decimal("0.05")))

    assert ledger.total_usd == Decimal("0.05")
    assert [e.cost_usd for e in ledger.entries] == [Decimal("0.02"), Decimal("0.03")]
    assert ledger.input_tokens == 250 and ledger.output_tokens == 90


def test_a_response_with_no_new_cost_books_nothing():
    ledger = SpendLedger()
    meter = UsageMeter(
        ledger, entry=realtime_models.offered("openai", "gpt-realtime"), model_name="gpt-realtime"
    )
    meter.book_response(RunUsage(cost=Decimal("0.02")))
    meter.book_response(RunUsage(cost=Decimal("0.02")))
    assert len(ledger.entries) == 1


def test_a_per_minute_model_is_billed_by_duration_not_tokens():
    ledger = SpendLedger()
    meter = UsageMeter(
        ledger,
        entry=realtime_models.offered("xai", "grok-voice-latest"),
        model_name="grok-voice-latest",
    )

    meter.book_response(RunUsage(input_tokens=500, output_tokens=500, cost=Decimal(0)))
    meter.book_elapsed(90)
    meter.book_elapsed(150)

    assert meter.total_usd == Decimal("0.20")  # 150 s at $0.08/min
    assert all(entry.priced for entry in ledger.entries)


def test_elapsed_time_books_nothing_on_a_token_priced_model():
    ledger = SpendLedger()
    UsageMeter(
        ledger, entry=realtime_models.offered("openai", "gpt-realtime"), model_name="gpt-realtime"
    ).book_elapsed(600)
    assert ledger.entries == []


def _azure_meter(ledger: SpendLedger) -> UsageMeter:
    return UsageMeter(
        ledger,
        entry=realtime_models.offered("azure", "gpt-realtime"),
        model_name="gpt-realtime",
        price_as="openai",
    )


def test_an_azure_deployment_is_priced_as_its_base_model_and_the_session_sees_it():
    """The session cannot price `rt-prod`, so its `cost_limit` would never trip. Not verified live."""
    from app.agents.capabilities.budget import price_request

    ledger = SpendLedger()
    meter = _azure_meter(ledger)
    usage = RunUsage(input_tokens=1000, output_tokens=500)  # the session's cost: None

    first = meter.book_response(usage)
    usage.input_tokens, usage.output_tokens = 1500, 900
    second = meter.book_response(usage)

    assert first == price_request(
        RunUsage(input_tokens=1000, output_tokens=500), "gpt-realtime", "openai"
    )
    assert second == price_request(
        RunUsage(input_tokens=500, output_tokens=400), "gpt-realtime", "openai"
    )
    assert usage.cost == ledger.total_usd == first + second
    assert all(entry.priced for entry in ledger.entries)


def test_an_azure_response_that_added_no_tokens_books_nothing():
    ledger = SpendLedger()
    meter = _azure_meter(ledger)
    usage = RunUsage(input_tokens=10, output_tokens=10)
    meter.book_response(usage)
    meter.book_response(usage)
    assert len(ledger.entries) == 1


def test_an_azure_base_model_the_price_list_lost_is_booked_as_unpriced(monkeypatch):
    monkeypatch.setattr("app.services.voice.meter.price_request", lambda *a: None)
    ledger = SpendLedger()
    _azure_meter(ledger).book_response(RunUsage(input_tokens=10, output_tokens=10))
    assert ledger.has_unpriced_models and ledger.total_usd == 0


def test_an_azure_session_starts_from_a_known_cost_so_its_limit_is_not_reported_unenforced():
    meter = _azure_meter(SpendLedger())
    usage = RunUsage()
    meter.attach(usage)
    assert usage.cost == Decimal(0)


def test_a_session_priced_by_the_library_is_left_as_it_is():
    meter = UsageMeter(
        SpendLedger(),
        entry=realtime_models.offered("openai", "gpt-realtime"),
        model_name="gpt-realtime",
    )
    usage = RunUsage()
    meter.attach(usage)
    assert usage.cost is None

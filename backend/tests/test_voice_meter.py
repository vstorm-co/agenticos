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


def test_a_per_minute_model_is_billed_by_duration_not_tokens(monkeypatch):
    monkeypatch.setattr(realtime_models, "RELAY_READY", True)
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

"""Booking a call's spend on its run's ledger as it happens (#54).

`session.usage` is a running total whose cost genai-prices computes at each
response boundary. Each booking takes the difference from the last one, through
`ledger.book()` - not `record()`, which would reprice with the chat provider
(spec amendment 6). Per-minute models (xAI) report $0 in tokens and are billed
by connected time at the catalog's rate instead. Input transcription is reported
in `usage.details` and is unpriced: a documented undercount.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic_ai.usage import RunUsage

from app.agents.capabilities.budget import SpendEntry, SpendLedger
from app.services.realtime_models import RealtimeModelEntry


class UsageMeter:
    """One call's running spend, booked onto its run's ledger per response or per minute."""

    def __init__(self, ledger: SpendLedger, *, entry: RealtimeModelEntry, model_name: str) -> None:
        self._ledger = ledger
        self._entry = entry
        self._model_name = model_name
        self._cost = Decimal(0)
        self._input = 0
        self._output = 0
        self._seconds = 0.0
        self._per_minute = entry.pricing.kind == "per_minute"

    @property
    def total_usd(self) -> Decimal:
        return self._ledger.total_usd

    def book_response(self, usage: RunUsage) -> Decimal:
        """Book what the session added since the last booking; returns that cost."""
        cost = Decimal(0) if self._per_minute else (usage.cost or Decimal(0)) - self._cost
        input_tokens = (usage.input_tokens or 0) - self._input
        output_tokens = (usage.output_tokens or 0) - self._output
        if cost <= 0 and input_tokens <= 0 and output_tokens <= 0:
            return Decimal(0)
        self._cost = usage.cost or Decimal(0)
        self._input = usage.input_tokens or 0
        self._output = usage.output_tokens or 0
        self._ledger.book(
            SpendEntry(
                model_name=self._model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=max(cost, Decimal(0)),
                priced=True,
            )
        )
        return max(cost, Decimal(0))

    def book_elapsed(self, seconds: float) -> Decimal:
        """For a per-minute model, book the connected time since the last booking."""
        if not self._per_minute or seconds <= self._seconds:
            return Decimal(0)
        rate = self._entry.pricing.usd_per_minute or self._entry.pricing.worst_case_usd_per_minute
        cost = (Decimal(str(seconds - self._seconds)) / Decimal(60) * rate).quantize(
            Decimal("0.000001")
        )
        self._seconds = seconds
        self._ledger.book(
            SpendEntry(
                model_name=self._model_name,
                input_tokens=0,
                output_tokens=0,
                cost_usd=cost,
                priced=True,
            )
        )
        return cost

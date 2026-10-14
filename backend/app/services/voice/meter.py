"""Booking a call's spend on its run's ledger as it happens (#54).

`session.usage` is a running total whose cost genai-prices computes at each
response boundary. Each booking takes the difference from the last one, through
`ledger.book()` - not `record()`, which would reprice with the chat provider
(spec amendment 6). Per-minute models (xAI) report $0 in tokens and are billed
by connected time at the catalog's rate instead. Input transcription is reported
in `usage.details` and is unpriced: a documented undercount.

An Azure deployment is named by its owner, so the session cannot price it:
its tokens are priced here as the base model on OpenAI, and the running total
is written back to the session's usage, so the session's own `cost_limit`
stops an Azure call too. It does so one response later than on other
providers: the session checks the limit at a response's boundary, before the
pump books that response - so an Azure call can overshoot by up to two
responses where another overshoots by one. The per-response budget check in
the pump is unaffected. Not verified live.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from pydantic_ai.usage import RunUsage

from app.agents.capabilities.budget import SpendEntry, SpendLedger, price_request
from app.services.realtime_models import RealtimeModelEntry


class UsageMeter:
    """One call's running spend, booked onto its run's ledger per response or per minute."""

    def __init__(
        self,
        ledger: SpendLedger,
        *,
        entry: RealtimeModelEntry,
        model_name: str,
        price_as: str | None = None,
    ) -> None:
        """`price_as` names the provider whose price list prices `model_name` when the
        session cannot (an Azure deployment: `"openai"`)."""
        self._ledger = ledger
        self._entry = entry
        self._model_name = model_name
        self._price_as = price_as
        self._last = RunUsage()
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
        if self._price_as is not None:
            return self._book_priced_here(usage)
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

    def attach(self, usage: RunUsage) -> None:
        """Start a session's cost at what this meter has booked, when it prices here.

        Before its first response an Azure session's cost is unknown (`None`),
        and the library warns that a `cost_limit` it cannot compute is not
        enforced. It is - from the first booking on - so the session starts
        from a known zero instead.
        """
        if self._price_as is not None and usage.cost is None:
            usage.cost = self._cost

    def _book_priced_here(self, usage: RunUsage) -> Decimal:
        added = usage - self._last
        if added.input_tokens <= 0 and added.output_tokens <= 0:
            return Decimal(0)
        price = price_request(added, self._model_name, self._price_as)
        # The starter refuses a model it cannot price; a price list that lost it
        # since is booked as unpriced, which marks the run's total as a floor.
        cost = price or Decimal(0)
        self._last = deepcopy(usage)
        self._cost += cost
        # The session priced the deployment at nothing (or by a name it guessed);
        # the total priced here is what its `cost_limit` must see.
        usage.cost = self._cost
        self._last.cost = self._cost
        self._ledger.book(
            SpendEntry(
                model_name=self._model_name,
                input_tokens=added.input_tokens,
                output_tokens=added.output_tokens,
                cost_usd=cost,
                priced=price is not None,
            )
        )
        return cost

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

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
        provider: str,
        price_here: bool = False,
    ) -> None:
        """`provider` names the price list that prices `model_name` (`"openai"` for an
        Azure deployment). `price_here` prices every response here rather than by the
        session, which cannot price a deployment named by its owner."""
        self._ledger = ledger
        self._entry = entry
        self._model_name = model_name
        self._provider = provider
        self._price_here = price_here
        self._last = RunUsage()
        self._cost = Decimal(0)
        self._seconds = 0.0
        self._per_minute = entry.pricing.kind == "per_minute"

    @property
    def total_usd(self) -> Decimal:
        return self._ledger.total_usd

    def book_response(self, usage: RunUsage) -> Decimal:
        """Book what the session added since the last booking; returns that cost.

        A token-priced response the session left unpriced - the server can report
        serving a model by a name the price list lacks - is priced here, and the
        price written back to the session's usage so its `cost_limit` sees it; one
        neither can price is booked as unpriced, which marks the run's total as a
        floor. Tokens are never booked as a priced $0.
        """
        added = usage - self._last
        if added.input_tokens <= 0 and added.output_tokens <= 0 and not added.cost:
            return Decimal(0)
        priced = True
        if self._per_minute:
            cost = Decimal(0)
        elif not self._price_here and added.cost is not None and added.cost > 0:
            cost = added.cost
        else:
            price = price_request(added, self._model_name, self._provider)
            cost = price or Decimal(0)
            priced = price is not None
            # What was priced here is what the session's `cost_limit` must see. An
            # Azure session priced the deployment at nothing (or by a name it
            # guessed), so its total is replaced; another's misses only this response.
            if self._price_here:
                self._cost += cost
                usage.cost = self._cost
            else:
                usage.cost = (usage.cost or Decimal(0)) + cost
        self._last = deepcopy(usage)
        self._ledger.book(
            SpendEntry(
                model_name=self._model_name,
                input_tokens=max(added.input_tokens, 0),
                output_tokens=max(added.output_tokens, 0),
                cost_usd=cost,
                priced=priced,
            )
        )
        return cost

    def attach(self, usage: RunUsage) -> None:
        """Start a session's cost at what this meter has booked, when it prices here.

        Before its first response an Azure session's cost is unknown (`None`),
        and the library warns that a `cost_limit` it cannot compute is not
        enforced. It is - from the first booking on - so the session starts
        from a known zero instead.
        """
        if self._price_here and usage.cost is None:
            usage.cost = self._cost

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

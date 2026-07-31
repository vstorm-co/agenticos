"""Cost tracking and budget enforcement.

An agent platform without a hard spending limit is a platform nobody puts a
credit card behind. Two mechanisms, deliberately separate:

*Accounting* - :class:`SpendLedger` records what a run consumed, in tokens and
in dollars, so the cost dashboard has something to read and a monthly total has
something to sum.

*Enforcement* - :class:`BudgetGuard` is a capability that refuses to issue a
model request once a limit is reached. It stops the run rather than warning
about it, because a warning nobody reads is how a runaway loop spends a month's
budget in an afternoon.

Enforcement happens *before* each request, not after. Checking afterwards means
the request that broke the budget was already paid for, and a loop can overshoot
by one expensive call every time.

Prices come from `genai-prices`, not from a table in this repository. A
hand-maintained table cannot express tiered pricing and goes stale silently,
which is worse than reporting nothing - so a model the package does not know is
recorded at zero with a warning and flags the run's total as a floor, rather
than being guessed at.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from genai_prices import calc_price
from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability, WrapModelRequestHandler
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.usage import RequestUsage, RunUsage

logger = logging.getLogger(__name__)


class BudgetScope(StrEnum):
    """Which cap bound, as something other than a sentence.

    The two are answerable by different people and the alert for each goes to a
    different audience: an agent's cap is its author's to raise, the
    organization's is not and stops every agent in it. That distinction used to
    exist only inside the human-readable message, so telling them apart meant
    matching a prefix on the string a person reads - which is a decision about
    who gets mailed, resting on the wording of an error.
    """

    AGENT = "agent"
    ORGANIZATION = "organization"

    @property
    def label(self) -> str:
        """How the refusal names it to the person reading it."""
        return "Agent monthly" if self is BudgetScope.AGENT else "Organization monthly"


class BudgetExceeded(Exception):
    """Raised when a run would spend past its limit.

    Not an `AppException`: it is raised inside a model request, propagates out
    of the agent run, and the surface decides how to present it - an error event
    on a WebSocket, a failed row in run history, a message in Slack.
    """

    def __init__(self, *, limit_usd: Decimal, spent_usd: Decimal, scope: BudgetScope) -> None:
        self.limit_usd = limit_usd
        self.spent_usd = spent_usd
        self.scope = scope
        super().__init__(
            f"{scope.label} budget exhausted: ${spent_usd:.4f} spent of ${limit_usd:.2f} limit"
        )


def price_request(
    usage: RequestUsage | RunUsage, model_name: str, provider: str | None
) -> Decimal | None:
    """What one model request cost, or `None` if the model is not priced.

    Delegates to `genai-prices`, which Pydantic maintains and which the
    Pydantic AI stack already depends on. This used to be a hand-written table
    of nine models, and the table was wrong: Gemini 2.5 Pro charges
    $1.25/1M below a 200k-token context and $2.50 above it, so every
    long-context run was reported at half what it cost - and the budget that is
    supposed to stop a runaway loop let it run twice as far. A flat
    dollars-per-million table cannot express that at all, and no amount of care
    in maintaining it would have.

    The same applies to cached and audio tokens, which the table ignored:
    cache reads are a fraction of the input price and were being billed at full
    rate. `RunUsage` is accepted alongside `RequestUsage` because it carries
    the same counts summed over a whole run, which is the granularity a caller
    without a per-request hook - the image describer - can report at.
    `RequestUsage` is handed over as-is - Pydantic AI declares it an
    implementation of `genai_prices.types.AbstractUsage` for exactly this, and
    copying the counts into a second object would only create somewhere for the
    two conventions to disagree about whether `input_tokens` includes the
    cached ones. It does.

    Prices come from the snapshot bundled with the package. Nothing here
    reaches the network - a self-hosted deployment should not phone home
    because somebody ran an agent. Refreshing the snapshot is a dependency
    bump, which is a change someone reviews.

    Args:
        usage: Token counts for the request, as the provider reported them.
        model_name: The model as the *response* named it, which is what was
            actually billed - not what the profile asked for.
        provider: The resolved profile's provider, as a hint. A run that fell
            back to another provider reports a model this hint does not match,
            so resolution is retried without it rather than mispricing.
    """
    for provider_id in (provider, None) if provider else (None,):
        try:
            return calc_price(usage, model_name, provider_id=provider_id).total_price
        except LookupError:
            continue
        except ValueError:
            logger.warning("Refused to price %s from usage %r", model_name, usage)
            return None
    return None


@dataclass
class SpendEntry:
    """What one model request consumed."""

    model_name: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    priced: bool


@dataclass
class SpendLedger:
    """Accumulated cost for a single run.

    Held per run rather than per agent: a run is the unit a user waits on, the
    unit that can be cancelled, and the unit whose cost is worth showing next to
    its transcript.
    """

    run_id: UUID | None = None
    agent_id: UUID | None = None
    organization_id: UUID | None = None
    entries: list[SpendEntry] = field(default_factory=list)

    @property
    def total_usd(self) -> Decimal:
        return sum((entry.cost_usd for entry in self.entries), Decimal(0))

    @property
    def input_tokens(self) -> int:
        return sum(entry.input_tokens for entry in self.entries)

    @property
    def output_tokens(self) -> int:
        return sum(entry.output_tokens for entry in self.entries)

    @property
    def has_unpriced_models(self) -> bool:
        """Whether any request could not be priced - the total is then a floor."""
        return any(not entry.priced for entry in self.entries)

    def record(
        self, model_name: str, usage: RequestUsage | RunUsage, provider: str | None = None
    ) -> SpendEntry:
        cost = price_request(usage, model_name, provider)
        if cost is None:
            logger.warning("No price for model %s - run cost will be under-reported", model_name)
        entry = SpendEntry(
            model_name=model_name,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cost_usd=cost if cost is not None else Decimal(0),
            priced=cost is not None,
        )
        self.entries.append(entry)
        return entry


_active_ledger: ContextVar[SpendLedger | None] = ContextVar("active_spend_ledger", default=None)


@contextmanager
def metered_by(ledger: SpendLedger) -> Iterator[None]:
    """Attribute ambient model usage inside this block to `ledger`.

    Exists for spend the request wrapper cannot see. Embedding calls go through
    a process-global service that serves every run and every ingestion job at
    once - it cannot take a ledger as a parameter without threading a billing
    argument through the whole retrieval stack, and it cannot hold one as state
    without concurrent callers writing into each other's totals. A context
    variable is the mechanism built for exactly this: it travels with the task
    (and into `to_thread`, which copies the context), so whatever the block
    embeds is booked to the run - or the ingestion job - that asked for it.
    """
    token = _active_ledger.set(ledger)
    try:
        yield
    finally:
        _active_ledger.reset(token)


def record_ambient_usage(
    model_name: str, usage: RequestUsage | RunUsage, provider: str | None = None
) -> None:
    """Book one model call to whichever ledger is active, if any is.

    Callers that meter (an agent run, an ingestion job) open a
    :func:`metered_by` block; callers that have nothing to bill - the CLI, a
    warmup - simply have no active ledger, and the call is a no-op rather than
    an error. Silence is deliberate: an embedding provider should not refuse to
    embed because nobody is counting.
    """
    ledger = _active_ledger.get()
    if ledger is not None:
        ledger.record(model_name, usage, provider)


PeriodSpendLookup = Callable[[], Awaitable[Decimal]]


@dataclass(frozen=True)
class SpendLimit:
    """One cap, what it is called when it stops a run, and the spend it meters.

    A run can be under several caps at once - the agent's own and the
    organization's - and they are not variations on one number. **Each meters
    its own spend.** An agent's cap measured against the organization's total
    would be exhausted by its neighbours' runs, which is precisely what makes
    it not a cap; and an organization's cap measured against one agent's spend
    would never bind. That is why the lookup travels with the limit instead of
    being shared.

    It follows that two caps cannot be collapsed with `min()`. Taking the
    tighter of two numbers is only meaningful when both are measured against the
    same quantity, and these are not - so every cap is its own entry, the first
    one to bind stops the run, and `scope` is how the person reading the
    refusal learns which.

    `period_spend` is `None` where there is no database to ask - a preview -
    in which case the cap meters only what this run's ledger has booked.
    """

    scope: BudgetScope
    limit_usd: Decimal
    period_spend: PeriodSpendLookup | None = None


@dataclass
class BudgetGuard(AbstractCapability[Any]):
    """Stops a run from issuing a model request it cannot afford.

    Wraps the model request rather than the whole run so the check happens at
    every step of an agent loop - the place where cost is actually incurred and
    where a runaway loop must be caught.

    Every ceiling a run is under is one entry in `limits`: the agent's month
    and the organization's month. There is deliberately no second spelling for
    either of them. A cap that meters a database period and one that meters
    this run's ledger differ only in whether their :class:`SpendLimit` carries
    a lookup, and a field of their own for the ledger kind is what let the
    agent's monthly cap sit next to the organization's, sharing one
    organization-wide number, for as long as it did.

    Limits are checked in order and the first to bind stops the run, naming
    itself in the refusal. Callers order them narrowest first, so an operator is
    told about the ceiling closest to them - the one they can act on - before one
    they may not be allowed to move.
    """

    ledger: SpendLedger = field(default_factory=SpendLedger)
    provider: str | None = None
    limits: list[SpendLimit] = field(default_factory=list)
    _baselines: dict[str, Decimal] = field(default_factory=dict, init=False, repr=False)

    async def _baseline_for(self, limit: SpendLimit) -> Decimal:
        """What this limit's period had already booked when the run started.

        Fetched once per run: re-querying per request would put a database round
        trip in the hot path of every agent step, and the ledger covers what this
        run adds. Cached *per limit* rather than once for the guard, because the
        limits measure different quantities - sharing one cached number is how an
        agent's own cap silently starts reading the organization's total again.
        """
        if limit.period_spend is None:
            return Decimal(0)
        if limit.scope not in self._baselines:
            self._baselines[limit.scope] = await limit.period_spend()
        return self._baselines[limit.scope]

    async def _assert_within_budget(self) -> None:
        run_total = self.ledger.total_usd
        for limit in self.limits:
            spent = await self._baseline_for(limit) + run_total
            if spent >= limit.limit_usd:
                raise BudgetExceeded(limit_usd=limit.limit_usd, spent_usd=spent, scope=limit.scope)

    async def wrap_model_request(
        self,
        ctx: RunContext[Any],
        *,
        request_context: ModelRequestContext,
        handler: WrapModelRequestHandler,
    ) -> ModelResponse:
        """Check the budget, make the request, then record what it cost."""
        await self._assert_within_budget()

        response = await handler(request_context)

        model_name = getattr(response, "model_name", None) or "unknown"
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.ledger.record(model_name, usage, self.provider)
        return response

"""Cost tracking and budget enforcement.

An agent platform without a hard spending limit is a platform nobody puts a
credit card behind. Two mechanisms, deliberately separate:

*Accounting* - :class:`SpendLedger` records what a run consumed, in tokens and
in dollars, so the cost dashboard has something to read and a monthly total has
something to sum. One ledger per run, whatever the run built: a delegate records
into the ledger of the run that started it, which is what makes the parent's cap
see a delegate's spend before the parent's next request. Each entry is stamped
with the delegation that made it (:func:`booked_to`), so "what did the run cost"
and "what did this delegate cost" are both answerable off one set of prices.

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

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
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
    """What one model request consumed, and which agent in the run consumed it."""

    model_name: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    priced: bool

    delegation: str | None = None
    """The delegation whose agent issued this request, or `None` for the run's own.

    Stamped from :func:`booked_to` at the moment the entry is recorded, which is
    the only moment the answer is available: a run has one ledger and every agent
    in the tree records into it, so by the time anyone reads the ledger back there
    is nothing on an entry to say who made it.

    The innermost delegation, not the outermost - a delegate's own delegate sets
    the attribution again, so a grandchild's requests are stamped with the
    grandchild. That is what keeps a mid-tree delegate's share from containing its
    own delegates' spend, which is the same money its delegates' rows already
    record (agenticos#180).

    This is the *panel* attribution: :meth:`SpendLedger.share_of` reads it, and a
    delegation panel shows an agent only what its own requests cost. It is not what
    a monthly total is summed off - see :attr:`billed_to`.
    """

    billed_to: str | None = None
    """Which agent-row this request bills to, or `None` for the run's own agent.

    A *second* attribution beside :attr:`delegation`, because the two answer
    different questions and diverge for exactly one shape. `delegation` is the
    innermost delegation - what the panel shows. `billed_to` is the nearest
    delegation with an `agent_runs` row of its own, which is the nearest *published*
    delegate: an inline specialist has no row, so its spend has to land in some
    row's month, and the honest one is its published ancestor's (agenticos#228).

    They are equal for every request a published delegate makes on its own account,
    and they differ only under an inline specialist: its entry is stamped
    `delegation=<the specialist>` so its panel keeps its own share, and
    `billed_to=<the published ancestor>` so its spend still reaches a month. Stamped
    from :func:`booked_to`, which advances `billed_to` only across a delegation that
    has its own row and leaves an inline one inheriting its ancestor's.

    `None` - the run's own agent - is what the top-level run row already sums as the
    whole ledger, so an inline specialist directly under the run's own agent needs
    no delegated row: :meth:`SpendLedger.billed_share_of` never reads `None`.
    """


@dataclass(frozen=True)
class SpendShare:
    """What one agent in a run booked into the run's single ledger.

    A share rather than a delta. The obvious way to describe a delegation's cost is
    what the shared total grew by while it ran, and it is wrong twice over: a
    background delegation is settled when it is next polled, so everything the
    parent spent in between lands on the child, and a mid-tree delegate's window
    contains what its own delegates spent, which their rows record again.

    The defaults are the honest answer where nothing is metering - a preview, or a
    unit test - rather than a cost nobody measured.
    """

    cost_usd: Decimal = Decimal(0)
    input_tokens: int = 0
    output_tokens: int = 0
    has_unpriced_models: bool = False
    """Whether any request in this share went unpriced - the cost is then a floor.

    Named as :attr:`SpendLedger.has_unpriced_models` is, because it is the same
    question asked of part of the ledger rather than all of it. What differs is the
    answer: an unpriced parent makes the *run's* total a floor and says nothing
    about a delegate that ran on a priced model.
    """


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

    def share_of(self, delegation: str) -> SpendShare:
        """What one delegation booked into this ledger, and nothing else.

        The same numbers the run's own total is made of, filtered rather than
        recomputed: one price per request, looked up once, so a delegation's cost
        and the run's cost cannot disagree about what a request cost. That is the
        property a second pricing path - `TaskHandle.usage` priced again on the way
        past - would give up, and `BudgetGuard.for_delegate` exists because pricing
        the same request twice through two catalogs is exactly how a run gets
        under-reported.

        Exact in every mode and at every depth, because attribution is stamped when
        the request is recorded rather than inferred from when the delegation was
        looked at. Zero for a delegation that made no request of its own - a
        delegate the library refused, or one whose whole job was to delegate
        further.

        Filtered on :attr:`SpendEntry.delegation`, the innermost stamp - so this is
        the *panel* number, an agent's own requests and not its inline specialists'.
        What a monthly total is summed off is :meth:`billed_share_of`.
        """
        return self._share_where(lambda entry: entry.delegation == delegation)

    def billed_share_of(self, billed_to: str) -> SpendShare:
        """What bills to one published delegate's row: its own spend and its inline
        specialists'.

        Filtered on :attr:`SpendEntry.billed_to` rather than
        :attr:`SpendEntry.delegation`, which is the whole of the difference. An
        inline specialist's entry is stamped to the specialist for the panel and to
        its nearest published ancestor for the row, so this share is the one that
        makes the ancestor's month whole again without inventing a row for the
        specialist (agenticos#228). For a published delegate with no inline
        specialist below it the two shares are identical.

        Only ever asked of a delegation that has a row - a published delegate - so
        `None` (the run's own agent) is not a key here: its spend is the whole
        ledger the top-level run row already carries.
        """
        return self._share_where(lambda entry: entry.billed_to == billed_to)

    def _share_where(self, matches: Callable[[SpendEntry], bool]) -> SpendShare:
        """The share of the ledger the matching entries make up.

        One summation for both attributions, so the panel number and the row number
        are the same arithmetic over a different filter and cannot drift in how they
        add tokens or decide `has_unpriced_models`.
        """
        mine = [entry for entry in self.entries if matches(entry)]
        return SpendShare(
            cost_usd=sum((entry.cost_usd for entry in mine), Decimal(0)),
            input_tokens=sum(entry.input_tokens for entry in mine),
            output_tokens=sum(entry.output_tokens for entry in mine),
            has_unpriced_models=any(not entry.priced for entry in mine),
        )

    def book(self, entry: SpendEntry) -> SpendEntry:
        """Add one entry to the ledger, attributed to whatever is spending here.

        The only way in, so there is exactly one place attribution is stamped. An
        entry appended around this is an entry that belongs to the run's own agent
        whoever made it - which is how a delegate's requests came to be counted as
        the parent's, and how they would be again.

        A copy rather than the caller's object: `record` builds a fresh entry, but a
        caller with an entry of its own - a resumed run's opening balance - would
        otherwise have that object mutated by being booked.

        Both attributions are stamped here, from the two context variables
        :func:`booked_to` sets together: `delegation` for the panel and `billed_to`
        for the row. Stamping them anywhere but the one way in is how a delegate's
        spend came to be counted as the parent's, and how it would be again.
        """
        booked = replace(entry, delegation=_booked_to.get(), billed_to=_billed_to.get())
        self.entries.append(booked)
        return booked

    def record(
        self, model_name: str, usage: RequestUsage | RunUsage, provider: str | None = None
    ) -> SpendEntry:
        cost = price_request(usage, model_name, provider)
        if cost is None:
            logger.warning("No price for model %s - run cost will be under-reported", model_name)
        return self.book(
            SpendEntry(
                model_name=model_name,
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cost_usd=cost if cost is not None else Decimal(0),
                priced=cost is not None,
            )
        )


_booked_to: ContextVar[str | None] = ContextVar("spend_booked_to", default=None)
"""Which delegation the spend in this task belongs to, if it belongs to one.

Read by :meth:`SpendLedger.record` rather than passed to it, for the reason
:func:`metered_by` is a context variable too: the guard that records a request is
built per agent, while the delegation that is running is per *task* - a fan-out of
three runs three delegations in three asyncio tasks against one guard.

The *innermost* delegation, and what the panel is read off (:meth:`share_of`).
"""

_billed_to: ContextVar[str | None] = ContextVar("spend_billed_to", default=None)
"""Which agent-row the spend in this task bills to, if it bills to a delegate's.

The companion to :data:`_booked_to`, and it advances only across a delegation with
a row of its own - a published delegate. An inline specialist leaves it pointing at
whatever it was, which is its nearest published ancestor, so the specialist's spend
lands in that ancestor's month while `_booked_to` still names the specialist for its
panel (agenticos#228). `None` is the run's own agent, whose row is the whole ledger.
"""


@contextmanager
def booked_to(delegation: str, *, has_own_row: bool) -> Iterator[None]:
    """Attribute what is metered inside this block to one delegation.

    Opened around the tool call that starts a delegation, which is what makes it
    reach both kinds. A `sync` delegation runs inside the block. A background one
    is an `asyncio.Task` created inside it, and `asyncio` copies the current
    context into every task - so the whole of that delegation, including its own
    nested delegations and whatever their tools embed, is booked to it long after
    the block has closed in the caller.

    Nested rather than exclusive: a delegate's own delegation sets this again, so
    the innermost one wins and each level is attributed only what it spent itself.

    Two attributions are set together, because a request has to answer two
    questions at once - which panel, and which month. `delegation` is always the
    innermost, for the panel. `has_own_row` says whether this delegation is a
    published delegate (one with its own `agent_runs` row): if it is, its spend
    bills to itself; if it is an inline specialist, it has no row, so what is
    metered here bills to its nearest published ancestor - whatever was billed here
    already. Setting them together is the point - any window in which only one held
    would attribute a request to a panel and a month that disagree.
    """
    billed = delegation if has_own_row else _billed_to.get()
    booked_token = _booked_to.set(delegation)
    billed_token = _billed_to.set(billed)
    try:
        yield
    finally:
        _billed_to.reset(billed_token)
        _booked_to.reset(booked_token)


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


def usage_counts(usage: RunUsage) -> tuple[int, int, int, int]:
    """The four counters a price is computed from, read off the run's usage.

    A tuple rather than the object: `RunUsage` is accumulated in place, so keeping
    a reference and comparing later compares it with itself. Cached tokens are
    carried alongside the plain ones because they are priced differently and
    `input_tokens` already includes them; dropping them would bill a cache read at
    the full input rate, the defect :func:`price_request` exists to avoid.
    """
    return (
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_tokens,
        usage.cache_write_tokens,
    )


def usage_delta(before: tuple[int, int, int, int], usage: RunUsage) -> RequestUsage | None:
    """What a step added to the run's usage, or `None` when it called no model.

    A capability that runs its own `Agent` - a compaction summary, a tool-output
    summary - spends against `ctx.usage` and nowhere the request wrapper can see,
    so each meters itself by snapshotting :func:`usage_counts` before the step and
    diffing after. One helper so the two meters cannot drift on how the diff is
    taken.
    """
    after = usage_counts(usage)
    if after == before:
        return None
    return RequestUsage(
        input_tokens=after[0] - before[0],
        output_tokens=after[1] - before[1],
        cache_read_tokens=after[2] - before[2],
        cache_write_tokens=after[3] - before[3],
    )


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
class RunSpendState:
    """The part of a budget check that every agent in one run must share.

    One run can build more than one agent: a delegation runs a second agent's
    whole conversation inside a turn of the first. Those agents share a ledger,
    which is what makes a delegate's cost count against the cap somebody set -
    but two things beside the ledger have to be shared too, and both for reasons
    that are invisible until they break.

    `baselines` is what the month had already booked before this run started,
    read once from the database. Per guard it would be read once *per agent*, and
    a fan-out reads it concurrently - on the request's `AsyncSession`, which is
    not concurrency-safe, so the failure is not a slow query but a corrupted
    session shared by everything else in the request.

    `check` is what stops that. It serialises the *check*, never the request:
    holding a lock across a model call would put every delegate's requests in a
    queue behind the parent's, which is most of what a fan-out is for. It cannot
    prevent an overshoot - no check knows what a request will cost before it is
    made, which is what `max_fanout` bounds instead - and it does not try to.
    """

    baselines: dict[str, Decimal] = field(default_factory=dict)
    check: asyncio.Lock = field(default_factory=asyncio.Lock)


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
    run_state: RunSpendState = field(default_factory=RunSpendState, repr=False)

    def for_delegate(self, *, provider: str | None) -> BudgetGuard:
        """A guard for a second agent spending against this same run.

        Shares the ledger, the limits and the read baselines, so the delegate's
        requests are checked against a total the parent is also adding to and the
        parent's caps are the ones that bind. What it does *not* share is
        `provider`, and that is the whole reason this is a method rather than
        passing the same instance around: the guard prices what it records, so a
        delegate on Anthropic metered through a guard built for OpenAI is priced
        against the wrong catalog - silently, and usually as unpriced, which
        under-reports the run and sets `cost_is_partial` on a run that was
        perfectly priceable.
        """
        return BudgetGuard(
            ledger=self.ledger,
            provider=provider,
            limits=self.limits,
            run_state=self.run_state,
        )

    async def _baseline_for(self, limit: SpendLimit) -> Decimal:
        """What this limit's period had already booked when the run started.

        Fetched once per run: re-querying per request would put a database round
        trip in the hot path of every agent step, and the ledger covers what this
        run adds. Cached *per limit* rather than once for the guard, because the
        limits measure different quantities - sharing one cached number is how an
        agent's own cap silently starts reading the organization's total again.

        Cached on `run_state` rather than on the guard, so a delegation reads it
        once for the whole run instead of once per delegate.
        """
        if limit.period_spend is None:
            return Decimal(0)
        if limit.scope not in self.run_state.baselines:
            self.run_state.baselines[limit.scope] = await limit.period_spend()
        return self.run_state.baselines[limit.scope]

    async def _assert_within_budget(self) -> None:
        """Refuse the next request if the run has already reached a ceiling.

        Under `run_state.check`, because `_baseline_for` may query the database on
        a session that several concurrent delegations are sharing. The lock is
        released before the model request itself - see :class:`RunSpendState`.
        """
        async with self.run_state.check:
            run_total = self.ledger.total_usd
            for limit in self.limits:
                spent = await self._baseline_for(limit) + run_total
                if spent >= limit.limit_usd:
                    raise BudgetExceeded(
                        limit_usd=limit.limit_usd, spent_usd=spent, scope=limit.scope
                    )

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

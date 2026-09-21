"""Tests for cost tracking and budget enforcement.

The behaviour that matters: a limit stops the *next* request rather than
reporting the one that already broke it, and an unpriced model is visibly
unpriced rather than silently free.
"""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.usage import RequestUsage, RunUsage, UsageLimits

from app.agents.capabilities.budget import (
    BudgetExceeded,
    BudgetGuard,
    BudgetScope,
    SpendLedger,
    SpendLimit,
    can_afford_ambient_call,
    guarding,
    metered_by,
    metered_nested_run,
    price_request,
    record_ambient_usage,
    reserved_limits,
    usage_counts,
    usage_delta,
)

pytestmark = pytest.mark.security

MILLION = 1_000_000


def _usage(input_tokens: int = 0, output_tokens: int = 0, **rest: int) -> RequestUsage:
    """The real usage type, not a stand-in.

    A hand-rolled double used to be enough here, and that was the problem: it
    carried two of the seven counts a request actually reports, so cached and
    audio tokens were invisible to every test on this page.
    """
    return RequestUsage(input_tokens=input_tokens, output_tokens=output_tokens, **rest)


def _response(model_name: str, input_tokens: int = 1000, output_tokens: int = 1000):
    response = MagicMock()
    response.model_name = model_name
    response.usage = _usage(input_tokens, output_tokens)
    return response


class TestPricing:
    """Prices come from `genai-prices`; what is tested is our use of it.

    Not the prices themselves - restating a published rate card in assertions
    only pins today's number and fails on the next dependency bump. What is
    worth pinning is the behaviour a table could not give us at all.
    """

    def test_a_flat_rate_model_costs_what_the_provider_charges(self):
        assert price_request(_usage(input_tokens=MILLION), "gpt-4.1", "openai") == Decimal("2.0")

    def test_the_context_tier_is_applied(self):
        """The bug that motivated this: Gemini 2.5 Pro doubles past 200k tokens.

        A dollars-per-million table can hold one of these two numbers. It held
        the cheaper one, so every long-context run was reported at half its
        cost - and the budget meant to stop a runaway loop let it run twice as
        far.
        """
        below = price_request(_usage(input_tokens=100_000), "gemini-2.5-pro", "google")
        above = price_request(_usage(input_tokens=MILLION), "gemini-2.5-pro", "google")

        assert below is not None and above is not None
        assert above / Decimal(10) > below

    def test_cached_input_is_cheaper_than_fresh_input(self):
        """Cache reads were being billed at the full input rate."""
        fresh = price_request(_usage(input_tokens=MILLION), "claude-sonnet-4-6", "anthropic")
        half_cached = price_request(
            _usage(input_tokens=MILLION, cache_read_tokens=MILLION // 2),
            "claude-sonnet-4-6",
            "anthropic",
        )

        assert fresh is not None and half_cached is not None
        assert half_cached < fresh

    @pytest.mark.parametrize(
        ("model_id", "provider"),
        [
            ("claude-sonnet-4-6", "anthropic"),
            ("gpt-4.1", "openai"),
            ("gpt-4.1-mini", "openai"),
        ],
    )
    def test_the_model_names_our_providers_return_all_resolve(self, model_id, provider):
        assert price_request(_usage(input_tokens=1000), model_id, provider) is not None

    def test_a_model_from_a_provider_we_did_not_expect_still_resolves(self):
        """A run that fell back reports a model the profile's provider does not
        serve. Retrying without the hint is what keeps that run priced."""
        assert price_request(_usage(input_tokens=1000), "claude-sonnet-4-6", "openai") is not None

    def test_an_unknown_model_has_no_price(self):
        assert price_request(_usage(input_tokens=1000), "some-experimental-model", "openai") is None

    def test_counts_the_package_refuses_are_reported_as_unpriced_not_raised(self):
        """More cached tokens than input tokens is a provider bug, not ours -
        and it must not kill the run the guard is metering."""
        broken = _usage(input_tokens=10, cache_read_tokens=MILLION)

        assert price_request(broken, "claude-sonnet-4-6", "anthropic") is None


class TestLedger:
    def test_records_tokens_and_cost(self):
        ledger = SpendLedger()
        ledger.record("gpt-4.1", _usage(MILLION, MILLION), "openai")
        assert ledger.input_tokens == MILLION
        assert ledger.total_usd == Decimal("10.00")  # 2.00 in + 8.00 out

    def test_accumulates_across_requests(self):
        ledger = SpendLedger()
        for _ in range(3):
            ledger.record("gpt-4.1", _usage(MILLION, 0), "openai")
        assert ledger.total_usd == Decimal("6.00")

    def test_unpriced_models_are_flagged_not_silently_free(self):
        """A total that quietly under-reports is worse than one marked incomplete."""
        ledger = SpendLedger()
        ledger.record("mystery-model", _usage(MILLION, MILLION), "openai")
        assert ledger.total_usd == Decimal(0)
        assert ledger.has_unpriced_models


class TestBudgetGuard:
    async def _run(self, guard: BudgetGuard, response) -> None:
        handler = AsyncMock(return_value=response)
        await guard.wrap_model_request(MagicMock(), request_context=MagicMock(), handler=handler)

    @pytest.mark.anyio
    async def test_allows_a_request_within_budget(self):
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[SpendLimit(scope=BudgetScope.AGENT, limit_usd=Decimal("1.00"))],
        )
        await self._run(guard, _response("gpt-4.1"))
        assert guard.ledger.total_usd > 0

    @pytest.mark.anyio
    async def test_stops_the_next_request_once_the_run_cap_is_reached(self):
        """Checked before the call: the request that breaks a budget is never paid for."""
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[SpendLimit(scope=BudgetScope.AGENT, limit_usd=Decimal("0.005"))],
        )
        await self._run(guard, _response("gpt-4.1", 1000, 1000))

        with pytest.raises(BudgetExceeded) as exc:
            await self._run(guard, _response("gpt-4.1"))
        assert exc.value.scope is BudgetScope.AGENT

    @pytest.mark.anyio
    async def test_a_period_cap_counts_spend_from_earlier_runs(self):
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[
                SpendLimit(
                    scope=BudgetScope.AGENT,
                    limit_usd=Decimal("10"),
                    period_spend=AsyncMock(return_value=Decimal("9.999")),
                )
            ],
        )
        await self._run(guard, _response("gpt-4.1", 1000, 1000))

        with pytest.raises(BudgetExceeded) as exc:
            await self._run(guard, _response("gpt-4.1"))
        assert exc.value.scope is BudgetScope.AGENT

    @pytest.mark.anyio
    async def test_period_spend_is_read_once_per_run(self):
        """A database round trip per agent step would sit in the hot path."""
        lookup = AsyncMock(return_value=Decimal("0"))
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[
                SpendLimit(scope=BudgetScope.AGENT, limit_usd=Decimal("100"), period_spend=lookup)
            ],
        )
        for _ in range(3):
            await self._run(guard, _response("gpt-4o-mini"))
        assert lookup.await_count == 1

    @pytest.mark.anyio
    async def test_no_limits_means_no_enforcement(self):
        guard = BudgetGuard(ledger=SpendLedger())
        for _ in range(5):
            await self._run(guard, _response("claude-opus-4", 1_000_000, 1_000_000))
        assert guard.ledger.total_usd == Decimal("450.00")

    @pytest.mark.anyio
    async def test_the_error_states_both_numbers(self):
        """An operator needs to see what was spent against what limit."""
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[SpendLimit(scope=BudgetScope.AGENT, limit_usd=Decimal("0.001"))],
        )
        await self._run(guard, _response("gpt-4.1", 1000, 1000))
        with pytest.raises(BudgetExceeded) as exc:
            await self._run(guard, _response("gpt-4.1"))
        assert "0.001" in str(exc.value) or "0.00" in str(exc.value)
        assert exc.value.limit_usd == Decimal("0.001")


class TestSeveralCapsAtOnce:
    """A run is under both ceilings at once, and each is its own.

    The agent's spec sets one, the organization sets the other. They are not
    variations on one number: each measures a different quantity, so the
    tighter of two is not a meaningful thing to compute and the refusal has to
    say which one bound.
    """

    async def _run(self, guard: BudgetGuard, response) -> None:
        handler = AsyncMock(return_value=response)
        await guard.wrap_model_request(MagicMock(), request_context=MagicMock(), handler=handler)

    @pytest.mark.anyio
    async def test_a_narrower_cap_stops_a_run_the_others_would_have_allowed(self):
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[
                SpendLimit(
                    scope=BudgetScope.ORGANIZATION,
                    limit_usd=Decimal("1000"),
                    period_spend=AsyncMock(return_value=Decimal("0")),
                ),
                SpendLimit(
                    scope=BudgetScope.AGENT,
                    limit_usd=Decimal("10"),
                    period_spend=AsyncMock(return_value=Decimal("9.999")),
                ),
            ],
        )
        await self._run(guard, _response("gpt-4.1", 1000, 1000))

        with pytest.raises(BudgetExceeded) as exc:
            await self._run(guard, _response("gpt-4.1"))

        assert exc.value.scope is BudgetScope.AGENT

    @pytest.mark.anyio
    async def test_the_refusal_names_the_cap_that_bound(self):
        """Two possible causes and one message is a message nobody can act on."""
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[
                SpendLimit(scope=BudgetScope.AGENT, limit_usd=Decimal("0.005")),
                SpendLimit(
                    scope=BudgetScope.ORGANIZATION,
                    limit_usd=Decimal("1000"),
                    period_spend=AsyncMock(return_value=Decimal("0")),
                ),
            ],
        )
        await self._run(guard, _response("gpt-4.1", 1000, 1000))

        with pytest.raises(BudgetExceeded) as exc:
            await self._run(guard, _response("gpt-4.1"))

        assert exc.value.scope is BudgetScope.AGENT
        assert "Agent monthly budget exhausted" in str(exc.value)

    @pytest.mark.anyio
    async def test_the_organizations_cap_binding_says_so(self):
        """The other half, and it decides more than the wording.

        `BudgetScope` is what the notifier reads to choose an audience: the
        agent's cap goes to whoever its spec names, the organization's always goes
        to the administrators because no agent's author can raise it. A guard that
        reported the wrong scope would mail the wrong people about a limit they
        could not act on - and every address involved would still look plausible.
        """
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[
                SpendLimit(
                    scope=BudgetScope.AGENT,
                    limit_usd=Decimal("1000"),
                    period_spend=AsyncMock(return_value=Decimal("0")),
                ),
                SpendLimit(
                    scope=BudgetScope.ORGANIZATION,
                    limit_usd=Decimal("10"),
                    period_spend=AsyncMock(return_value=Decimal("10")),
                ),
            ],
        )

        with pytest.raises(BudgetExceeded) as exc:
            await self._run(guard, _response("gpt-4.1"))

        assert exc.value.scope is BudgetScope.ORGANIZATION
        assert "Organization monthly budget exhausted" in str(exc.value)

    @pytest.mark.anyio
    async def test_a_cap_with_no_lookup_meters_only_this_run(self):
        """The preview case: no database to ask, so the cap binds on what this
        run alone has booked - and a first conversation that has spent nothing
        must not be stopped by it."""
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[SpendLimit(scope=BudgetScope.AGENT, limit_usd=Decimal("1000"))],
        )
        for _ in range(3):
            await self._run(guard, _response("gpt-4o-mini"))

        assert guard.ledger.total_usd > 0

    @pytest.mark.anyio
    async def test_each_cap_reads_its_own_spend_and_reads_it_once(self):
        """Sharing one cached number is how an agent's cap starts reading the org's.

        Which is not hypothetical: the agent's monthly cap spent its life reading
        the organization's total, and one baseline for the whole guard is exactly
        the shape that made it possible. Separately cached as well as separately
        fetched - one round trip per cap per run, never one per model request.
        """
        agent_spend = AsyncMock(return_value=Decimal("0"))
        org_spend = AsyncMock(return_value=Decimal("0"))
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[
                SpendLimit(
                    scope=BudgetScope.AGENT,
                    limit_usd=Decimal("1000"),
                    period_spend=agent_spend,
                ),
                SpendLimit(
                    scope=BudgetScope.ORGANIZATION,
                    limit_usd=Decimal("1000"),
                    period_spend=org_spend,
                ),
            ],
        )
        for _ in range(3):
            await self._run(guard, _response("gpt-4o-mini"))

        assert (agent_spend.await_count, org_spend.await_count) == (1, 1)

    @pytest.mark.anyio
    async def test_no_caps_is_the_ordinary_case_and_costs_nothing(self):
        guard = BudgetGuard(ledger=SpendLedger())

        for _ in range(3):
            await self._run(guard, _response("gpt-4o-mini"))

        assert guard.limits == []


class TestAmbientMetering:
    """Spend the request wrapper cannot see - embeddings - is booked ambiently.

    The embedding service is process-global and serves every run and every
    ingestion job at once, so whoever wants its calls billed opens a
    `metered_by` block and the usage lands on that ledger and nobody else's.
    """

    def test_usage_inside_a_metered_block_lands_on_that_ledger(self):
        """Also pins that `genai-prices` prices our embedding model under the
        "openai" hint the provider sends - it cannot resolve the name without
        one, and a zero here would mean every knowledge search embeds for free
        again."""
        ledger = SpendLedger()

        with metered_by(ledger):
            record_ambient_usage(
                "text-embedding-3-large", _usage(input_tokens=MILLION), provider="openai"
            )

        assert ledger.input_tokens == MILLION
        assert ledger.total_usd > 0
        assert not ledger.has_unpriced_models

    def test_usage_with_nobody_metering_is_dropped_not_raised(self):
        """The CLI and a warmup have nothing to bill; the provider must not
        refuse to embed because nobody is counting."""
        record_ambient_usage("text-embedding-3-large", _usage(input_tokens=1000))

    def test_metering_ends_with_the_block(self):
        ledger = SpendLedger()

        with metered_by(ledger):
            pass
        record_ambient_usage("text-embedding-3-large", _usage(input_tokens=1000))

        assert ledger.entries == []

    def test_nested_blocks_restore_the_outer_ledger(self):
        """Two jobs metering in one task must not write into each other."""
        outer, inner = SpendLedger(), SpendLedger()

        with metered_by(outer):
            with metered_by(inner):
                record_ambient_usage("text-embedding-3-large", _usage(input_tokens=1))
            record_ambient_usage("text-embedding-3-large", _usage(input_tokens=2))

        assert [entry.input_tokens for entry in inner.entries] == [1]
        assert [entry.input_tokens for entry in outer.entries] == [2]


class TestUsageDelta:
    """What a nested call added to a shared `RunUsage`, used by any capability
    that runs its own agent on `ctx.usage` - compaction, the LLM reminder."""

    def test_no_change_is_no_spend(self):
        usage = RunUsage(input_tokens=10)
        assert usage_delta(usage_counts(usage), usage) is None

    def test_a_change_carries_all_four_priced_counts(self):
        before = usage_counts(RunUsage())
        usage = RunUsage(input_tokens=8, output_tokens=2, cache_read_tokens=1, cache_write_tokens=3)
        assert usage_delta(before, usage) == RequestUsage(
            input_tokens=8, output_tokens=2, cache_read_tokens=1, cache_write_tokens=3
        )


class TestCanAffordNextRequest:
    """The non-raising predicate `can_afford_next_request` agrees with the
    refusing check `_assert_within_budget`, so an ambient call and a real request
    decide the same way about the same cap (agenticos#1808)."""

    @pytest.mark.anyio
    async def test_true_below_the_cap_and_no_raise(self):
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[SpendLimit(scope=BudgetScope.AGENT, limit_usd=Decimal("1.00"))],
        )
        assert await guard.can_afford_next_request() is True
        await guard._assert_within_budget()

    @pytest.mark.anyio
    async def test_false_at_the_cap_where_the_check_would_raise(self):
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[
                SpendLimit(
                    scope=BudgetScope.AGENT,
                    limit_usd=Decimal("10"),
                    period_spend=AsyncMock(return_value=Decimal("10")),
                )
            ],
        )
        assert await guard.can_afford_next_request() is False
        with pytest.raises(BudgetExceeded):
            await guard._assert_within_budget()

    @pytest.mark.anyio
    async def test_no_limits_can_always_afford(self):
        assert await BudgetGuard(ledger=SpendLedger()).can_afford_next_request() is True


class TestCanAffordAmbientCall:
    """An ambient call consults the active guard; outside a run there is none and
    the call proceeds, which keeps a preview, the CLI and ingestion unchanged."""

    @pytest.mark.anyio
    async def test_no_active_guard_allows_the_call(self):
        assert await can_afford_ambient_call() is True

    @pytest.mark.anyio
    async def test_an_active_guard_below_its_cap_allows_the_call(self):
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[SpendLimit(scope=BudgetScope.AGENT, limit_usd=Decimal("1.00"))],
        )
        with guarding(guard):
            assert await can_afford_ambient_call() is True

    @pytest.mark.anyio
    async def test_an_active_guard_at_its_cap_refuses_the_call(self):
        guard = BudgetGuard(
            ledger=SpendLedger(),
            limits=[SpendLimit(scope=BudgetScope.ORGANIZATION, limit_usd=Decimal(0))],
        )
        with guarding(guard):
            assert await can_afford_ambient_call() is False
        # The guard is cleared on block exit, so an ambient call outside it proceeds.
        assert await can_afford_ambient_call() is True


class TestReservedLimits:
    def test_none_limits_stay_none(self):
        assert reserved_limits(None) is None

    def test_an_unset_request_limit_is_left_alone(self):
        limits = UsageLimits(request_limit=None)
        assert reserved_limits(limits) is limits

    def test_one_request_is_held_back(self):
        result = reserved_limits(UsageLimits(request_limit=4))
        assert result is not None
        assert result.request_limit == 3

    def test_it_never_goes_below_zero(self):
        result = reserved_limits(UsageLimits(request_limit=0))
        assert result is not None
        assert result.request_limit == 0


class TestMeteredNestedRun:
    """Concurrency-safe metering for an ambient run that shares `ctx.usage`.

    The regression is agenticos#1811: two ambient runs under one `metered_by`
    block that each snapshot and diff the *shared* usage book the sum twice,
    because each reads the other's increments inside its own window. Spending into
    a private copy and folding only the own-delta back fixes it.
    """

    @pytest.mark.anyio
    async def test_the_old_delta_over_shared_usage_double_books(self):
        """Documents the defect the new helper removes: the snapshot/delta pattern
        over one shared `ctx.usage` counts each concurrent run's spend twice."""
        usage = RunUsage()
        ledger = SpendLedger()

        async def old_nested() -> None:
            before = usage_counts(usage)
            await asyncio.sleep(0)  # both snapshot the same start before either spends
            usage.incr(RunUsage(requests=1, input_tokens=10, output_tokens=5))
            await asyncio.sleep(0)  # both spend before either diffs
            spent = usage_delta(before, usage)
            with metered_by(ledger):
                if spent is not None:
                    record_ambient_usage("gpt-4.1", spent)

        await asyncio.gather(old_nested(), old_nested())
        # Two runs spent 10 input tokens each; the shared-usage diff books 40.
        assert usage.input_tokens == 20
        assert ledger.input_tokens == 40

    @pytest.mark.anyio
    async def test_it_books_each_concurrent_run_exactly_once(self):
        usage = RunUsage()
        ledger = SpendLedger()

        async def nested(model_name: str) -> None:
            with metered_by(ledger), metered_nested_run(usage, model_name) as private:
                await asyncio.sleep(0)
                private.incr(RunUsage(requests=1, input_tokens=10, output_tokens=5))
                await asyncio.sleep(0)

        await asyncio.gather(nested("gpt-4.1"), nested("gpt-4.1"))
        # Each nested run's own spend is folded back once: no double-count, and the
        # shared usage ends at start + 2 requests.
        assert usage.requests == 2
        assert usage.input_tokens == 20
        assert ledger.input_tokens == 20
        assert ledger.output_tokens == 10
        assert len(ledger.entries) == 2

    @pytest.mark.anyio
    async def test_the_running_totals_travel_into_the_private_copy(self):
        """The private copy starts from the shared usage, so a reserved limit still
        meters the nested run against where the run already is, not from zero."""
        usage = RunUsage(requests=3, input_tokens=100)
        with metered_nested_run(usage, "gpt-4.1") as private:
            assert private.requests == 3
            assert private.input_tokens == 100

    @pytest.mark.anyio
    async def test_a_run_that_spends_nothing_books_nothing(self):
        usage = RunUsage(requests=2)
        ledger = SpendLedger()
        with metered_by(ledger), metered_nested_run(usage, "gpt-4.1"):
            pass
        assert usage.requests == 2
        assert ledger.entries == []

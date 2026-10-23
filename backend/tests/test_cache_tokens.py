"""A run keeps the cache split its cost was computed from (#2170).

`input_tokens` includes cache reads and writes, by Pydantic AI's convention, and
the three are priced apart. A run that kept only the total could not be
reconciled with a provider's console - "998k input" read as 998k full-price
tokens when most of them were cache reads.
"""

from datetime import UTC, datetime
from decimal import Decimal

from pydantic_ai.messages import ModelResponse
from pydantic_ai.usage import RequestUsage

from app.agents.capabilities.budget import SpendLedger
from app.agents.capabilities.budget._capability import price_request
from app.agents.manifest import RunRecorder, as_payload
from app.services.usage_report import UsageReport, usage_frame

WARM = RequestUsage(
    input_tokens=100_000, output_tokens=2_000, cache_read_tokens=80_000, cache_write_tokens=15_000
)


class TestTheLedger:
    def test_a_request_keeps_its_split_and_its_cost_is_priced_from_it(self) -> None:
        ledger = SpendLedger()

        entry = ledger.record("claude-sonnet-5-5", WARM, "anthropic")

        assert (entry.cache_read_tokens, entry.cache_write_tokens) == (80_000, 15_000)
        assert entry.cost_usd == price_request(WARM, "claude-sonnet-5-5", "anthropic")
        # Read at 5% of input and written at 125%: well under the full-rate price.
        full_rate = price_request(
            RequestUsage(input_tokens=100_000, output_tokens=2_000),
            "claude-sonnet-5-5",
            "anthropic",
        )
        assert full_rate is not None and entry.cost_usd < full_rate

    def test_the_run_and_a_delegations_share_add_the_split_up(self) -> None:
        ledger = SpendLedger()
        ledger.record("claude-sonnet-5-5", WARM, "anthropic")
        ledger.record("claude-sonnet-5-5", RequestUsage(input_tokens=10, cache_read_tokens=4))

        assert (ledger.cache_read_tokens, ledger.cache_write_tokens) == (80_004, 15_000)
        share = ledger.share_of("nobody")
        assert (share.cache_read_tokens, share.cache_write_tokens) == (0, 0)


class TestWhereItIsShown:
    def test_the_manifest_records_each_requests_cache_writes(self) -> None:
        recorder = RunRecorder()
        recorder.observe_response(
            ModelResponse(parts=[], usage=WARM),
            started=datetime.now(UTC),
            elapsed_ms=10,
            messages=3,
        )

        (request,) = as_payload(recorder)["requests"]
        assert (request["cache_read_tokens"], request["cache_write_tokens"]) == (80_000, 15_000)

    def test_the_turns_usage_frame_carries_the_split(self) -> None:
        frame = usage_frame(
            UsageReport(
                input_tokens=100_000,
                output_tokens=2_000,
                cache_read_tokens=80_000,
                cache_write_tokens=15_000,
                cost_usd=Decimal("0.05"),
            )
        )

        assert frame is not None
        assert (frame["cache_read_tokens"], frame["cache_write_tokens"]) == (80_000, 15_000)

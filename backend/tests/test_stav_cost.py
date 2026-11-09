"""Stav's billed cost must reach budget enforcement even for unknown models."""

from decimal import Decimal

from pydantic_ai.usage import RequestUsage

from app.agents.capabilities.budget import SpendLedger


def test_provider_reported_cost_prices_an_unknown_model() -> None:
    usage = RequestUsage(
        input_tokens=43, output_tokens=3, provider_reported_cost_usd=Decimal("0.05")
    )
    ledger = SpendLedger()
    entry = ledger.record("deepseek-ai/deepseek-v4-1-flash-1017", usage, "stav")
    assert entry.cost_usd == Decimal("0.05")
    assert not ledger.has_unpriced_models


import asyncio
import json
from typing import Literal
from unittest.mock import patch

import httpx2
import pytest
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

from app.agents.capabilities.budget import BudgetExceeded, BudgetGuard, BudgetScope, SpendLimit
from app.agents.model_resolver import ResolvedCredential, _StavProvider, build_model
from app.agents.stav_cost import _active, capture_stav_cost
from app.core.config import Settings, settings
from app.core.secret_kinds import ApiKeySecret

pytestmark = pytest.mark.security

MODEL = "deepseek-ai/deepseek-v4-1-flash-1017"


def _chat(usage: dict[str, object]) -> dict[str, object]:
    return {
        "id": "chat-test",
        "object": "chat.completion",
        "created": 1,
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hello"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 43, "completion_tokens": 3, "total_tokens": 46, **usage},
    }


def _responses(usage: dict[str, object]) -> dict[str, object]:
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "model": MODEL,
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "hello", "annotations": []}],
            }
        ],
        "usage": {"input_tokens": 43, "output_tokens": 3, "total_tokens": 46, **usage},
    }


def _wire(api: str, stream: bool, usage: dict[str, object]) -> httpx2.Response:
    if not stream:
        return httpx2.Response(200, json=_chat(usage) if api == "chat" else _responses(usage))
    if api == "chat":
        events = [
            {
                "id": "chat-test",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": MODEL,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "hello"},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "chat-test",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": MODEL,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": _chat(usage)["usage"],
            },
        ]
    else:
        response = _responses(usage)
        events = [
            {
                "type": "response.created",
                "response": {**response, "status": "in_progress", "output": [], "usage": None},
            },
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "id": "msg_test",
                    "type": "message",
                    "status": "in_progress",
                    "role": "assistant",
                    "content": [],
                },
            },
            {
                "type": "response.content_part.added",
                "output_index": 0,
                "content_index": 0,
                "item_id": "msg_test",
                "part": {"type": "output_text", "text": "", "annotations": []},
            },
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "content_index": 0,
                "item_id": "msg_test",
                "delta": "hello",
            },
            {"type": "response.completed", "response": response},
        ]
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
    return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})


@pytest.mark.anyio
@pytest.mark.parametrize("api", ["chat", "responses"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("headers_only", [False, True])
async def test_stav_billed_cost_stops_the_next_request(
    monkeypatch: pytest.MonkeyPatch,
    api: Literal["chat", "responses"],
    stream: bool,
    headers_only: bool,
) -> None:
    monkeypatch.setattr(settings, "STAV_NOK_PER_USD", Decimal("10"))
    sent: list[httpx2.Request] = []
    billed = {"cost": "0.5", "cost_currency": "NOK"}

    def respond(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        response = _wire(api, stream, {} if headers_only else billed)
        response.headers.update({"x-stav-cost": "0.5", "x-stav-cost-currency": "NOK"})
        return response

    ledger = SpendLedger()
    guard = BudgetGuard(
        ledger=ledger, provider="stav", limits=[SpendLimit(BudgetScope.AGENT, Decimal("0.04"))]
    )
    credential = ResolvedCredential(
        provider="stav", secret=ApiKeySecret(api_key="sk_stav_test"), api=api
    )
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as transport:
        with patch.object(_StavProvider, "_get_http_client", return_value=transport):
            model = build_model(credential, MODEL)
        async with Agent(model, capabilities=[guard]) as agent:
            if stream:
                async with agent.run_stream("hello") as run:
                    await run.get_output()
                final_response = run.all_messages()[-1]
                assert final_response.usage.provider_reported_cost["currency"] == "NOK"
            else:
                result = await agent.run("hello")
                assert result.response.usage.provider_reported_cost["currency"] == "NOK"
            assert ledger.total_usd == Decimal("0.05")
            assert ledger.entries[0].provider_reported
            assert not ledger.has_unpriced_models
            with pytest.raises(BudgetExceeded):
                await agent.run("again")
    assert len(sent) == 1
    assert _active.get() is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    "reported",
    [
        {"cost": "0", "cost_currency": "USD"},
        {"cost": "0.5", "cost_currency": "NOK"},
        {"cost": "0.5", "cost_currency": "EUR"},
        {"cost": "NaN", "cost_currency": "USD"},
        {"cost": "-1", "cost_currency": "USD"},
        {"cost": True, "cost_currency": "USD"},
        {"cost": "garbage", "cost_currency": "USD"},
        {"cost": {}, "cost_currency": "USD"},
        {"cost": "0.5"},
        {},
    ],
)
async def test_only_convertible_valid_costs_are_treated_as_priced(
    monkeypatch: pytest.MonkeyPatch, reported: dict[str, object], caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "STAV_NOK_PER_USD", None)
    credential = ResolvedCredential(
        provider="stav", secret=ApiKeySecret(api_key="sk_stav_test"), api="chat"
    )
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _: _wire("chat", False, reported))
    ) as transport:
        with patch.object(_StavProvider, "_get_http_client", return_value=transport):
            model = build_model(credential, MODEL)
        async with model:
            response = await model.request(
                [ModelRequest(parts=[UserPromptPart("hello")])], None, ModelRequestParameters()
            )
    ledger = SpendLedger()
    entry = ledger.record(MODEL, response.usage, "stav")
    if reported == {"cost": "0", "cost_currency": "USD"}:
        assert entry.priced and entry.provider_reported and entry.cost_usd == 0
    else:
        assert not entry.priced and ledger.has_unpriced_models
        assert "No price for model" in caplog.text
    assert _active.get() is None


@pytest.mark.parametrize("rate", ["0", "-1", "NaN", "Infinity"])
def test_stav_conversion_rate_must_be_finite_and_positive(rate: str) -> None:
    with pytest.raises(ValidationError):
        Settings(STAV_NOK_PER_USD=rate)


def test_an_unused_sdk_client_does_not_capture_cost() -> None:
    capture_stav_cost({"usage": {"cost": 1, "cost_currency": "USD"}}, {})
    assert _active.get() is None


@pytest.mark.anyio
async def test_concurrent_requests_keep_their_own_billed_amounts() -> None:
    ready = asyncio.Event()
    arrived = 0

    async def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            ready.set()
        await ready.wait()
        amount = "0.1" if b"alpha" in request.content else "0.2"
        return _wire("chat", False, {"cost": amount, "cost_currency": "USD"})

    credential = ResolvedCredential(
        provider="stav", secret=ApiKeySecret(api_key="sk_stav_test"), api="chat"
    )
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as transport:
        with patch.object(_StavProvider, "_get_http_client", return_value=transport):
            model = build_model(credential, MODEL)
        async with model:
            first, second = await asyncio.gather(
                *(
                    model.request(
                        [ModelRequest(parts=[UserPromptPart(prompt)])],
                        None,
                        ModelRequestParameters(),
                    )
                    for prompt in ("alpha", "beta")
                )
            )
    assert SpendLedger().record(MODEL, first.usage).cost_usd == Decimal("0.1")
    assert SpendLedger().record(MODEL, second.usage).cost_usd == Decimal("0.2")
    assert _active.get() is None


@pytest.mark.anyio
@pytest.mark.parametrize("stream", [False, True])
async def test_a_cancelled_request_always_clears_its_cost_capture(stream: bool) -> None:
    async def respond(request: httpx2.Request) -> httpx2.Response:
        raise asyncio.CancelledError

    credential = ResolvedCredential(
        provider="stav", secret=ApiKeySecret(api_key="sk_stav_test"), api="chat"
    )
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as transport:
        with patch.object(_StavProvider, "_get_http_client", return_value=transport):
            model = build_model(credential, MODEL)
        async with model:
            with pytest.raises(asyncio.CancelledError):
                messages = [ModelRequest(parts=[UserPromptPart("hello")])]
                if stream:
                    async with model.request_stream(messages, None, ModelRequestParameters()):
                        pytest.fail("Cancelled before the stream opens")
                else:
                    await model.request(messages, None, ModelRequestParameters())
    assert _active.get() is None


@pytest.mark.parametrize("reported", [Decimal("NaN"), Decimal("-1"), "0.5", None])
def test_invalid_reported_cost_never_reduces_the_ledger(reported: object) -> None:
    usage = RequestUsage(provider_reported_cost_usd=reported)
    entry = SpendLedger().record(MODEL, usage, "stav")
    assert not entry.priced
    assert entry.cost_usd == 0


def test_capture_handles_non_json_data_and_body_totals_override_headers() -> None:
    from app.agents.stav_cost import _Capture

    capture = _Capture()
    token = _active.set(capture)
    try:
        capture_stav_cost(None, {"x-stav-cost": "1", "x-stav-cost-currency": "USD"})
        assert capture.cost == 1
        capture_stav_cost(
            {"usage": {"cost": "0", "cost_currency": "USD"}},
            {"x-stav-cost": "1", "x-stav-cost-currency": "USD"},
        )
        assert capture.cost == 0
        capture_stav_cost({"response": {"usage": {"cost": "0.1", "cost_currency": "USD"}}}, {})
        assert capture.cost == Decimal("0.1")
        capture_stav_cost({"response": {"usage": {"cost": "0.2", "cost_currency": "USD"}}}, {})
        assert capture.cost == Decimal("0.2")
    finally:
        _active.reset(token)


@pytest.mark.anyio
async def test_an_auxiliary_request_books_the_same_stav_billed_cost() -> None:
    from pydantic_ai.tools import RunContext
    from pydantic_ai.usage import RunUsage

    from app.agents.capabilities._ambient import run_ambient_agent
    from app.agents.capabilities.budget import metered_by

    credential = ResolvedCredential(
        provider="stav", secret=ApiKeySecret(api_key="sk_stav_test"), api="chat"
    )
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda _: _wire("chat", False, {"cost": "0.5", "cost_currency": "USD"})
        )
    ) as transport:
        with patch.object(_StavProvider, "_get_http_client", return_value=transport):
            model = build_model(credential, MODEL)
        ledger = SpendLedger()
        async with model:
            ctx = RunContext(deps=None, model=model, usage=RunUsage())
            with metered_by(ledger):
                assert await run_ambient_agent(ctx, output_type=str, user_prompt="hello") == "hello"
        assert ledger.total_usd == Decimal("0.5")
        assert ledger.entries[0].provider_reported
        assert not ledger.has_unpriced_models


@pytest.mark.anyio
async def test_auxiliary_response_costs_survive_output_validation_failure() -> None:
    from pydantic_ai.exceptions import UnexpectedModelBehavior
    from pydantic_ai.tools import RunContext
    from pydantic_ai.usage import RunUsage

    from app.agents.capabilities._ambient import run_ambient_agent
    from app.agents.capabilities.budget import metered_by

    credential = ResolvedCredential(
        provider="stav", secret=ApiKeySecret(api_key="sk_stav_test"), api="chat"
    )
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda _: _wire("chat", False, {"cost": "0.5", "cost_currency": "USD"})
        )
    ) as transport:
        with patch.object(_StavProvider, "_get_http_client", return_value=transport):
            model = build_model(credential, MODEL)
        ledger = SpendLedger()
        async with model:
            ctx = RunContext(deps=None, model=model, usage=RunUsage())
            with metered_by(ledger), pytest.raises(UnexpectedModelBehavior):
                await run_ambient_agent(ctx, output_type=int, user_prompt="an integer, please")
        assert len(ledger.entries) == 2
        assert ledger.total_usd == Decimal("1")
        assert all(entry.provider_reported for entry in ledger.entries)
        assert not ledger.has_unpriced_models


@pytest.mark.anyio
async def test_image_description_keeps_billed_cost_after_run_usage_aggregation() -> None:
    from app.agents.capabilities.budget import metered_by
    from app.services.rag.image_describer import PydanticAIImageDescriber

    credential = ResolvedCredential(
        provider="stav", secret=ApiKeySecret(api_key="sk_stav_test"), api="chat"
    )
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda _: _wire("chat", False, {"cost": "0.5", "cost_currency": "USD"})
        )
    ) as transport:
        with patch.object(_StavProvider, "_get_http_client", return_value=transport):
            model = build_model(credential, MODEL)
        ledger = SpendLedger()
        async with model:
            with metered_by(ledger):
                assert (
                    await PydanticAIImageDescriber(model).describe(b"image", "image/png") == "hello"
                )
        assert ledger.total_usd == Decimal("0.5")
        assert ledger.entries[0].provider_reported
        assert not ledger.has_unpriced_models


@pytest.mark.parametrize("cost", [Decimal("0"), Decimal("0.5")])
def test_snapshot_delta_preserves_billed_usd_and_request_provenance(cost: Decimal) -> None:
    from pydantic_ai.usage import RunUsage

    from app.agents.capabilities.budget import usage_counts, usage_delta

    usage = RunUsage(requests=1)
    usage.incr(RequestUsage(cost=Decimal("0.7"), provider_reported_requests=1))
    before = usage_counts(usage)
    usage.requests += 1
    usage.incr(
        RequestUsage(cost=cost, provider_reported_requests=1, input_tokens=43, output_tokens=3)
    )
    delta = usage_delta(before, usage)
    assert delta is not None
    assert delta.cost == cost
    assert delta.requests == 1
    ledger = SpendLedger()
    entry = ledger.record(MODEL, delta, "stav")
    assert ledger.total_usd == cost
    assert entry.provider_reported
    assert not ledger.has_unpriced_models


@pytest.mark.anyio
async def test_mixed_aggregate_counts_known_spend_without_claiming_its_total_is_complete() -> None:
    from pydantic_ai.usage import RunUsage

    usage = RunUsage(requests=2)
    usage.incr(RequestUsage(cost=Decimal("0.5"), provider_reported_requests=1, input_tokens=43))
    usage.incr(RequestUsage(input_tokens=43))
    ledger = SpendLedger()
    entry = ledger.record(MODEL, usage, "stav")
    assert ledger.total_usd == Decimal("0.5")
    assert entry.provider_reported
    assert ledger.has_unpriced_models
    guard = BudgetGuard(ledger=ledger, limits=[SpendLimit(BudgetScope.AGENT, Decimal("0.4"))])
    with pytest.raises(BudgetExceeded):
        await guard.assert_within_budget()


@pytest.mark.parametrize("count", [True, "1", None, -1])
def test_invalid_reported_request_counts_do_not_claim_a_priced_total(count: object) -> None:
    usage = RequestUsage(cost=Decimal("0.5"), provider_reported_requests=count)
    ledger = SpendLedger()
    ledger.record(MODEL, usage)
    assert ledger.has_unpriced_models


@pytest.mark.parametrize("cost", [Decimal("NaN"), Decimal("Infinity"), Decimal("-1"), None])
def test_invalid_native_cost_cannot_reduce_the_aggregate_ledger(cost: Decimal | None) -> None:
    usage = RequestUsage(cost=cost, provider_reported_requests=1)
    ledger = SpendLedger()
    ledger.record(MODEL, usage)
    assert ledger.total_usd == 0
    assert ledger.has_unpriced_models


def test_snapshot_delta_does_not_reuse_an_earlier_requests_bill_for_an_unknown_call() -> None:
    from pydantic_ai.usage import RunUsage

    from app.agents.capabilities.budget import usage_counts, usage_delta

    usage = RunUsage(requests=1)
    usage.incr(RequestUsage(cost=Decimal("0.7"), provider_reported_requests=1))
    before = usage_counts(usage)
    usage.requests += 1
    usage.incr(RequestUsage(input_tokens=43))
    delta = usage_delta(before, usage)
    assert delta is not None and delta.cost is None
    ledger = SpendLedger()
    ledger.record(MODEL, delta)
    assert ledger.total_usd == 0
    assert ledger.has_unpriced_models

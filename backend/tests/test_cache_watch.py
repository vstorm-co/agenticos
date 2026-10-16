"""Prompt-cache busts are noted on the request they happened at (#2109).

The model is scripted with the cache figures a provider reports, so whether the
cached prefix collapsed - and whether the provider should still have held it -
is exactly what the run's responses say.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.usage import RequestUsage

from app.agents.cache_watch import CacheWatch
from app.agents.deps import AgentDeps
from app.agents.manifest import RecordingModel, RunRecorder, as_payload

pytestmark = pytest.mark.anyio


def _scripted(usages: list[RequestUsage]):
    """A model that calls `look` until its scripted usages run out, then answers."""

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        step = sum(isinstance(message, ModelResponse) for message in messages)
        usage = usages[step]
        if step == len(usages) - 1:
            return ModelResponse(parts=[TextPart("done")], usage=usage)
        return ModelResponse(parts=[ToolCallPart("look", {"n": step})], usage=usage)

    return respond


async def _run(
    usages: list[RequestUsage],
    *,
    conversation_id: uuid.UUID,
    profile: Any = None,
    agent_id: uuid.UUID | None = None,
) -> RunRecorder:
    recorder = RunRecorder()
    model = FunctionModel(_scripted(usages), profile=profile)
    agent = Agent[AgentDeps, str](
        RecordingModel(model, recorder),
        capabilities=[
            CacheWatch(recorder=recorder, conversation_id=conversation_id, agent_id=agent_id)
        ],
    )

    @agent.tool_plain
    def look(n: int) -> str:
        return str(n)

    await agent.run("go", deps=AgentDeps())
    return recorder


def _caches(recorder: RunRecorder) -> list[tuple[str | None, int]]:
    return [
        (request["cache"], request["cache_missed_tokens"])
        for request in as_payload(recorder)["requests"]
    ]


async def test_a_prefix_that_moved_mid_run_is_one_bust_on_the_request_it_hit(caplog) -> None:
    """The third request reads nothing back of the 10,500 tokens the second had
    cached: something before them moved, and the whole prefix was re-sent."""
    with caplog.at_level(logging.WARNING, logger="app.agents.cache_watch"):
        recorder = await _run(
            [
                RequestUsage(input_tokens=10_000, cache_write_tokens=10_000),
                RequestUsage(input_tokens=10_500, cache_read_tokens=10_000, cache_write_tokens=500),
                RequestUsage(input_tokens=11_000, cache_write_tokens=11_000),
                RequestUsage(input_tokens=11_500, cache_read_tokens=11_000),
            ],
            conversation_id=uuid.uuid4(),
            agent_id=(agent := uuid.uuid4()),
        )

    assert _caches(recorder) == [(None, 0), (None, 0), ("bust", 10_500), (None, 0)]
    (record,) = [r for r in caplog.records if r.getMessage() == "prompt_cache_bust"]
    assert record.model == "function:respond:"
    assert record.missed_tokens == 10_500
    assert record.agent_id == str(agent)


async def test_a_cache_that_held_records_nothing() -> None:
    recorder = await _run(
        [
            RequestUsage(input_tokens=10_000, cache_write_tokens=10_000),
            RequestUsage(input_tokens=10_400, cache_read_tokens=10_000, cache_write_tokens=400),
        ],
        conversation_id=uuid.uuid4(),
    )

    assert _caches(recorder) == [(None, 0), (None, 0)]


async def test_the_next_turn_is_judged_against_what_the_last_one_cached() -> None:
    """Where a moved prefix most often hides: the first request of a new turn."""
    conversation = uuid.uuid4()
    await _run(
        [
            RequestUsage(input_tokens=10_000, cache_write_tokens=10_000),
            RequestUsage(input_tokens=10_400, cache_read_tokens=10_000, cache_write_tokens=400),
        ],
        conversation_id=conversation,
    )

    next_turn = await _run(
        [RequestUsage(input_tokens=10_900, cache_write_tokens=10_900)],
        conversation_id=conversation,
    )

    assert _caches(next_turn) == [("bust", 10_400)]


async def test_a_conversation_resumed_after_the_cache_expired_is_an_expiry(monkeypatch) -> None:
    """Past the provider's retention window the cache is gone by design, not moved."""
    conversation = uuid.uuid4()
    five_minutes = ModelProfile(default_cache_retention=timedelta(minutes=5))
    clock = {"now": datetime(2026, 10, 16, 12, 0, tzinfo=UTC)}
    monkeypatch.setattr("pydantic_ai._cache_health._utils.now_utc", lambda: clock["now"])
    await _run(
        [
            RequestUsage(input_tokens=10_000, cache_write_tokens=10_000),
            RequestUsage(input_tokens=10_400, cache_read_tokens=10_000, cache_write_tokens=400),
        ],
        conversation_id=conversation,
        profile=five_minutes,
    )
    clock["now"] += timedelta(hours=1)

    an_hour_later = await _run(
        [RequestUsage(input_tokens=10_900, cache_write_tokens=10_900)],
        conversation_id=conversation,
        profile=five_minutes,
    )

    assert _caches(an_hour_later) == [("expired", 10_400)]

"""A run reviewer reads a run while it goes, and steers it (#2106).

Both models are scripted: the run's model keeps making a claim, the reviewer's
answers with a correction, so whether the correction arrived - and whether the
run carried on when the reviewer could not review - is what the run did.
"""

import asyncio
import logging
from typing import Any
from unittest.mock import patch

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai_harness.guardrails import GuardrailResult

from app.agents.capabilities.budget import SpendLedger, metered_by
from app.agents.capabilities.guardrails import GuardrailBlocked
from app.agents.deps import AgentDeps
from app.agents.manifest import MAX_RECORDED_REVIEWS, RunRecorder, as_payload
from app.agents.run_reviewer import MAX_STEER_CHARS, RunReviewer

pytestmark = pytest.mark.anyio

MAX_STEPS = 12


def _steered(messages: list[ModelMessage]) -> list[str]:
    return [
        str(part.content)
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart) and "Steering from run reviewer" in str(part.content)
    ]


def _working(seen: list[list[ModelMessage]]):
    """The run's model: looks something up until a correction reaches it, then answers.

    Waiting on the correction rather than counting requests is what keeps this
    from depending on how fast a review started beside the run comes back.
    """

    async def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        seen.append(messages)
        await asyncio.sleep(0.01)
        step = sum(isinstance(message, ModelResponse) for message in messages)
        if _steered(messages) or step >= MAX_STEPS:
            return ModelResponse(parts=[TextPart("The market grew 40%.")])
        return ModelResponse(parts=[ToolCallPart("lookup", {"q": f"market {step}"})])

    return respond


def _reviewing(asked: list[str], *, on_track: bool = False, fails: bool = False):
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        asked.append(str(messages[0]))
        if fails:
            raise RuntimeError("reviewer provider down")
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"on_track": on_track, "steer": None if on_track else "Cite a source for 40%."},
                )
            ]
        )

    return respond


async def _run(
    reviewer_model: FunctionModel, *, screen: Any = None
) -> tuple[Any, RunRecorder, list[list[ModelMessage]]]:
    recorder = RunRecorder()
    seen: list[list[ModelMessage]] = []
    agent = Agent[AgentDeps, str](
        FunctionModel(_working(seen)),
        capabilities=[
            RunReviewer(
                name="sources",
                model=reviewer_model,
                instructions="Flag claims without a source.",
                every=3,
                recorder=recorder,
                screen=screen,
            )
        ],
    )

    @agent.tool_plain
    def lookup(q: str) -> str:
        return "no figures found"

    result = await agent.run("How fast did the market grow?", deps=AgentDeps())
    return result, recorder, seen


async def test_a_reviewer_steers_a_drifting_run_and_says_who_sent_it() -> None:
    asked: list[str] = []
    result, recorder, seen = await _run(FunctionModel(_reviewing(asked)))

    steered = _steered(seen[-1])
    assert steered and steered[0].startswith("Steering from run reviewer 'sources': Cite a source")
    assert asked, "the reviewer was asked"
    (review, *_) = as_payload(recorder)["reviews"]
    assert review["reviewer"] == "sources"
    assert review["steer"] == "Cite a source for 40%."
    assert review["after_request"] % 3 == 0
    assert result.output == "The market grew 40%."


async def test_a_run_on_track_is_left_alone() -> None:
    asked: list[str] = []
    _, recorder, seen = await _run(FunctionModel(_reviewing(asked, on_track=True)))

    assert asked
    assert _steered(seen[-1]) == []
    assert recorder.reviews == []


@pytest.mark.security
async def test_a_review_refused_for_budget_is_skipped_and_the_run_goes_on() -> None:
    """Its call is checked against the caps like any other, before it is made."""
    asked: list[str] = []
    with patch("app.agents.capabilities._ambient.can_afford_ambient_call", return_value=False):
        result, recorder, _ = await _run(FunctionModel(_reviewing(asked)))

    assert asked == []
    assert recorder.reviews == []
    assert result.output == "The market grew 40%."


async def test_a_reviewer_that_fails_never_fails_the_run(caplog) -> None:
    asked: list[str] = []
    with caplog.at_level(logging.ERROR, logger="app.agents.run_reviewer"):
        result, recorder, _ = await _run(FunctionModel(_reviewing(asked, fails=True)))

    assert result.output == "The market grew 40%."
    assert recorder.reviews == []
    assert "could not review the run" in caplog.text


async def test_a_review_still_going_when_the_run_ends_is_cancelled() -> None:
    started = asyncio.Event()

    async def slow(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        started.set()
        await asyncio.sleep(10)
        raise AssertionError("never reached")

    recorder = RunRecorder()
    agent = Agent[AgentDeps, str](
        FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart("done")])),
        capabilities=[
            RunReviewer(
                name="slow",
                model=FunctionModel(slow),
                instructions="x",
                every=1,
                recorder=recorder,
            )
        ],
    )

    result = await asyncio.wait_for(agent.run("hi", deps=AgentDeps()), timeout=5)

    assert result.output == "done"
    assert recorder.reviews == []


async def test_the_reviewers_spend_is_booked_on_the_run_as_its_own_model() -> None:
    """Counted against the budget like any of the run's requests, priced as the
    reviewer's model rather than the run's."""
    asked: list[str] = []
    ledger = SpendLedger()
    with metered_by(ledger):
        await _run(FunctionModel(_reviewing(asked), model_name="claude-haiku-5-5"))

    assert asked
    assert {entry.model_name for entry in ledger.entries} == {"claude-haiku-5-5"}


async def test_a_correction_passes_the_agents_input_guardrail_first() -> None:
    """Past the first request the input edge no longer looks, and a reviewer quotes
    the run it read - so its words are screened like a person's mid-run steer."""
    asked: list[str] = []

    def redact(text: str) -> Any:
        return GuardrailResult.replace(text.replace("40%", "[REDACTED]"))

    _, recorder, seen = await _run(FunctionModel(_reviewing(asked)), screen=redact)

    assert _steered(seen[-1])[0].endswith("Cite a source for [REDACTED].")
    assert recorder.reviews[0]["steer"] == "Cite a source for [REDACTED]."


async def test_a_correction_the_guardrail_passes_goes_in_unchanged() -> None:
    asked: list[str] = []

    _, recorder, seen = await _run(
        FunctionModel(_reviewing(asked)), screen=lambda _text: GuardrailResult.allow()
    )

    assert _steered(seen[-1])[0].endswith("Cite a source for 40%.")
    assert recorder.reviews[0]["steer"] == "Cite a source for 40%."


async def test_a_correction_the_guardrail_refuses_is_dropped_not_the_run() -> None:
    asked: list[str] = []

    def block(_text: str) -> Any:
        raise GuardrailBlocked(edge="input", message="blocked")

    result, recorder, seen = await _run(FunctionModel(_reviewing(asked)), screen=block)

    assert result.output == "The market grew 40%."
    assert recorder.reviews == []
    assert _steered(seen[-1]) == []


async def test_a_run_past_the_kept_corrections_is_still_steered() -> None:
    asked: list[str] = []
    recorder = RunRecorder()
    earlier = [
        {"reviewer": "sources", "after_request": n, "steer": "x"}
        for n in range(MAX_RECORDED_REVIEWS)
    ]
    recorder.reviews.extend(earlier)
    seen: list[list[ModelMessage]] = []
    agent = Agent[AgentDeps, str](
        FunctionModel(_working(seen)),
        capabilities=[
            RunReviewer(
                name="sources",
                model=FunctionModel(_reviewing(asked)),
                instructions="Flag claims without a source.",
                every=3,
                recorder=recorder,
            )
        ],
    )

    @agent.tool_plain
    def lookup(q: str) -> str:
        return "no figures found"

    await agent.run("How fast did the market grow?", deps=AgentDeps())

    assert _steered(seen[-1])
    assert recorder.reviews == earlier


async def test_a_long_correction_is_cut() -> None:
    def verbose(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(info.output_tools[0].name, {"on_track": False, "steer": "x" * 5000})
            ]
        )

    _, recorder, _ = await _run(FunctionModel(verbose))

    assert len(recorder.reviews[0]["steer"]) == MAX_STEER_CHARS


async def test_a_reviewer_behind_fallbacks_is_priced_as_the_model_that_answered() -> None:
    """A fallback model's composite name is in no price list; booked under it, a
    review would cost nothing against the budget."""
    asked: list[str] = []
    ledger = SpendLedger()
    reviewer = FallbackModel(FunctionModel(_reviewing(asked), model_name="claude-haiku-5-5"))
    with metered_by(ledger):
        await _run(reviewer)

    assert {entry.model_name for entry in ledger.entries} == {"claude-haiku-5-5"}

"""A call's text twin: the `hand_off` tool and what it runs (#54)."""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError, ToolFailed, UsageLimitExceeded
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.tools import DeferredToolRequests
from pydantic_ai.usage import UsageLimits

from app.agents.capabilities.budget import BudgetExceeded, BudgetScope
from app.agents.deps import AgentDeps
from app.agents.hand_off import HAND_OFF_TOOL, WORKER_STYLE, CallWorker

pytestmark = pytest.mark.anyio


def _twin(respond) -> SimpleNamespace:
    """A twin on a scripted model; streamed, because a hand-off watches its events."""

    async def stream(messages: list[ModelMessage], info: AgentInfo):
        for part in respond(messages, info).parts:
            if isinstance(part, TextPart):
                yield part.content
            else:
                yield {0: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args))}

    agent = Agent(
        FunctionModel(respond, stream_function=stream),
        deps_type=AgentDeps,
        output_type=[str, DeferredToolRequests],
    )

    @agent.tool_plain
    def note(text: str) -> str:
        return f"noted {text}"

    return SimpleNamespace(
        agent=agent, deps=AgentDeps(organization_id=uuid4()), usage_limits=UsageLimits()
    )


def _call(ask_questions=None, generated_files=None) -> SimpleNamespace:
    return SimpleNamespace(
        deps=SimpleNamespace(ask_questions=ask_questions, generated_files=generated_files or set())
    )


def _notes_then_answers(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    noted = any(isinstance(part, ToolReturnPart) for m in messages for part in m.parts)
    if noted:
        return ModelResponse(parts=[TextPart("Wrote the draft.")])
    return ModelResponse(parts=[ToolCallPart("note", {"text": "draft"})])


async def test_a_hand_off_runs_the_twin_and_answers_with_what_it_said():
    twin = _twin(_notes_then_answers)
    seen: list[object] = []
    worker = CallWorker(lambda: twin, workspace=None, capability_names=["Sandbox"])

    async def watch(event: object) -> None:
        seen.append(event)

    worker.watch = watch

    answer = await worker.hand_off(_call(), "Write the draft")

    assert answer == "Wrote the draft."
    calls = [e.part.tool_name for e in seen if isinstance(e, FunctionToolCallEvent)]
    results = [e.part.content for e in seen if isinstance(e, FunctionToolResultEvent)]
    assert calls == ["note"] and results == ["noted draft"]


async def test_the_next_hand_off_continues_from_the_last_and_the_twin_is_built_once():
    asked: list[list[ModelMessage]] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        asked.append(messages)
        return ModelResponse(parts=[TextPart("ok")])

    twin = _twin(respond)
    build = MagicMock(return_value=twin)
    worker = CallWorker(build, workspace=None, capability_names=["Sandbox"])

    await worker.hand_off(_call(), "Write it up")
    await worker.hand_off(_call(), "Now shorten it")

    build.assert_called_once()
    assert len(asked[1]) == 3  # the first task and its answer, then the second task
    assert "Write it up" in str(asked[1][0])


async def test_the_twin_asks_its_questions_on_the_calls_card():
    twin = _twin(lambda messages, info: ModelResponse(parts=[TextPart("ok")]))
    worker = CallWorker(lambda: twin, workspace=None, capability_names=["Sandbox"])
    card = AsyncMock()

    await worker.hand_off(_call(card), "Ask me")

    assert twin.deps.ask_questions is card


async def test_the_twin_shares_the_calls_generated_files():
    """A clip the twin makes may start from an image the call drew, and is the call's."""

    def draws(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("ok")])

    twin = _twin(draws)
    worker = CallWorker(lambda: twin, workspace=None, capability_names=["Sandbox"])
    drawn = {"call-drew-this.png"}

    await worker.hand_off(_call(generated_files=drawn), "Animate it")
    twin.deps.generated_files.add("twin-made-this.mp4")

    assert drawn == {"call-drew-this.png", "twin-made-this.mp4"}


async def test_the_twin_works_in_the_calls_workspace_with_its_own_instructions():
    workspace = MagicMock()
    run = AsyncMock(return_value=SimpleNamespace(output="done", all_messages=list))
    twin = SimpleNamespace(
        agent=SimpleNamespace(run=run), deps=SimpleNamespace(), usage_limits=UsageLimits()
    )
    worker = CallWorker(lambda: twin, workspace=workspace, capability_names=["Sandbox"])

    await worker.hand_off(_call(), "Do it")

    kwargs = run.await_args.kwargs
    assert kwargs["workspace"] is workspace and kwargs["instructions"] == WORKER_STYLE


@pytest.mark.parametrize(
    ("failure", "said"),
    [
        (
            BudgetExceeded(limit_usd=Decimal("1"), spent_usd=Decimal("1"), scope=BudgetScope.AGENT),
            "there is no budget left for it",
        ),
        (UsageLimitExceeded("too many requests"), "it took more steps than this agent is allowed"),
        (ModelHTTPError(status_code=500, model_name="gpt-4.1"), "it failed partway"),
    ],
)
async def test_a_twin_that_cannot_finish_is_told_to_the_call_rather_than_ending_it(failure, said):
    twin = SimpleNamespace(
        agent=SimpleNamespace(run=AsyncMock(side_effect=failure)),
        deps=SimpleNamespace(),
        usage_limits=UsageLimits(),
    )
    worker = CallWorker(lambda: twin, workspace=None, capability_names=["Sandbox"])

    with pytest.raises(ToolFailed, match=said):
        await worker.hand_off(_call(), "Do it")


async def test_a_twin_left_waiting_on_something_a_call_cannot_give_says_so():
    deferred = SimpleNamespace(output=DeferredToolRequests(), all_messages=list)
    twin = SimpleNamespace(
        agent=SimpleNamespace(run=AsyncMock(return_value=deferred)),
        deps=SimpleNamespace(),
        usage_limits=UsageLimits(),
        budget=SimpleNamespace(ledger=MagicMock(billed_share_of=MagicMock())),
    )
    reports: list[object] = []
    worker = CallWorker(
        lambda: twin, workspace=None, capability_names=["Sandbox"], report=reports.append
    )

    with pytest.raises(ToolFailed, match="a call cannot give it"):
        await worker.hand_off(_call(), "Do it")

    # Codex on #2204: its row was written as completed before this was noticed.
    (spent,) = reports
    assert spent.error == "it stopped to wait for something a call cannot give it"


async def test_the_tool_names_what_the_call_hands_off():
    worker = CallWorker(MagicMock(), workspace=None, capability_names=["Sandbox", "Browser"])

    tool = worker.toolset().tools[HAND_OFF_TOOL]

    assert "Sandbox, Browser" in (tool.description or "")


async def test_each_hand_off_is_booked_to_a_share_of_its_own_and_reported():
    """Codex on #2204: the twin's text-model spend went onto the call's row, under the
    realtime provider and key. Booked to a share of its own, it gets a row as a
    delegation does, and the call's row keeps only what the call spent."""
    from app.agents.capabilities.budget import SpendShare
    from app.agents.capabilities.budget._capability import _billed_to

    booked: list[str | None] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        booked.append(_billed_to.get())
        return ModelResponse(parts=[TextPart("Done.")])

    twin = _twin(respond)
    share = SpendShare(cost_usd=Decimal("0.02"), input_tokens=120, output_tokens=30)
    ledger = MagicMock(billed_share_of=MagicMock(return_value=share))
    twin.budget = SimpleNamespace(ledger=ledger)
    reports: list[object] = []
    worker = CallWorker(
        lambda: twin, workspace=None, capability_names=["Sandbox"], report=reports.append
    )

    await worker.hand_off(_call(), "Write the draft")

    (spent,) = reports
    assert booked and booked[0] == spent.task_id
    ledger.billed_share_of.assert_called_once_with(spent.task_id)
    assert spent.share is share and spent.error is None
    assert spent.started_at <= spent.ended_at


async def test_a_failed_hand_off_is_reported_with_its_reason():
    def fails(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise ModelHTTPError(status_code=500, model_name="m", body="boom")

    twin = _twin(fails)
    twin.budget = SimpleNamespace(ledger=MagicMock(billed_share_of=MagicMock()))
    reports: list[object] = []
    worker = CallWorker(
        lambda: twin, workspace=None, capability_names=["Sandbox"], report=reports.append
    )

    with pytest.raises(ToolFailed):
        await worker.hand_off(_call(), "Write the draft")

    (spent,) = reports
    assert spent.error

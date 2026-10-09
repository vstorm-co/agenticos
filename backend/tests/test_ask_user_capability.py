"""The `ask_user` capability through a real agent run (#2064).

The harness owns the tool; what is ours is reaching the run's own question
channel from inside the call, and answering as a decline where there is none.
"""

from __future__ import annotations

import json

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai_harness.ask_user import (
    DECLINED,
    AskUserAnswer,
    AskUserRequest,
    AskUserResponse,
)

from app.agents.capabilities._registry import CapabilityBinding, build, load_builtins
from app.agents.capabilities.ask_user import ASK_USER_CAPABILITY_ID
from app.agents.capabilities.ask_user._capability import through_the_surface
from app.agents.deps import AgentDeps

pytestmark = pytest.mark.anyio

QUESTIONS = [
    {
        "header": "Audience",
        "question": "Who will use it?",
        "options": [{"label": "Everyone"}, {"label": "My team"}],
    }
]


def _asks_then_reports(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    returns = [
        part
        for message in messages
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart)
    ]
    if not returns:
        return ModelResponse(
            parts=[ToolCallPart("ask_user_question", {"questions": QUESTIONS}, tool_call_id="q1")]
        )
    return ModelResponse(parts=[TextPart(json.dumps(returns[0].content))])


def _agent() -> Agent[AgentDeps, str]:
    load_builtins()
    capabilities = build([CapabilityBinding(capability_id=ASK_USER_CAPABILITY_ID)])
    return Agent(FunctionModel(_asks_then_reports), deps_type=AgentDeps, capabilities=capabilities)


async def test_the_question_reaches_the_runs_channel_and_the_picks_reach_the_model() -> None:
    asked: list[AskUserRequest] = []

    async def channel(request: AskUserRequest) -> AskUserResponse:
        asked.append(request)
        return AskUserResponse(answers=(AskUserAnswer(header="Audience", selected=("My team",)),))

    result = await _agent().run("Build me a helper", deps=AgentDeps(ask_questions=channel))

    assert [question.header for question in asked[0].questions] == ["Audience"]
    assert json.loads(result.output) == {"Audience": ["My team"]}


async def test_with_nobody_to_ask_the_model_is_told_the_user_declined() -> None:
    result = await _agent().run("Build me a helper", deps=AgentDeps())

    assert json.loads(result.output) == DECLINED


async def test_the_answerer_outside_a_call_has_no_channel() -> None:
    response = await through_the_surface(AskUserRequest(questions=()))

    assert response == AskUserResponse(cancelled=True)

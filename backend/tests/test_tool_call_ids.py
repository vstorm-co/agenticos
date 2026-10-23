"""Tool call ids that name one call per conversation (#2171).

Some OpenAI-compatible servers number calls from zero on every response, so the
second turn's call is `call_0` again; a model scripted to do exactly that shows
the later call renamed and the earlier one untouched.
"""

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents.deps import AgentDeps
from app.agents.tool_call_ids import UniqueToolCallIds, fresh_call_id, used_call_ids

pytestmark = pytest.mark.anyio


def test_an_unused_id_is_kept_and_a_used_one_gets_the_first_free_suffix() -> None:
    used = {"call_0", "call_0~2"}
    assert fresh_call_id("call_1", used) == "call_1"
    assert fresh_call_id("call_0", used) == "call_0~3"
    # Recorded, so a second call reusing it in the same response differs again.
    assert fresh_call_id("call_0", used) == "call_0~4"


def _numbering_from_zero(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
    """A provider that names every response's first call `call_0`."""
    if isinstance(messages[-1].parts[-1], ToolCallPart) or any(
        part.part_kind == "tool-return" for part in messages[-1].parts
    ):
        return ModelResponse(parts=[TextPart("done")])
    return ModelResponse(parts=[ToolCallPart("lookup", {}, tool_call_id="call_0")])


async def test_a_later_turn_s_call_is_renamed_and_the_earlier_one_kept() -> None:
    agent = Agent[AgentDeps, str](
        FunctionModel(_numbering_from_zero), capabilities=[UniqueToolCallIds()]
    )

    @agent.tool_plain
    def lookup() -> str:
        return "found"

    first = await agent.run("one", deps=AgentDeps())
    second = await agent.run("two", deps=AgentDeps(), message_history=first.all_messages())

    ids = [
        part.tool_call_id
        for message in second.all_messages()
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]
    assert ids == ["call_0", "call_0~2"]
    assert used_call_ids(second.all_messages()) == {"call_0", "call_0~2"}

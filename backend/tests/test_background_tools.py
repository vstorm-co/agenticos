"""`background_tools`: a slow tool runs on, and its result is screened all the same (#2108)."""

from typing import Any

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities import all_capabilities, load_builtins
from app.agents.capabilities.background_tools import (
    BACKGROUND,
    BACKGROUND_TOOLS_CAPABILITY_ID,
    BackgroundTools,
)

pytestmark = pytest.mark.anyio

SECRET = "hunter2"


class _Redact(AbstractCapability[Any]):
    """A tool-result hook, as the guardrails and the output limits are."""

    def __init__(self) -> None:
        self.calls = 0

    async def after_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: Any,
        result: Any,
    ) -> Any:
        self.calls += 1
        return str(result).replace(SECRET, "[redacted]")


def _slow_tools() -> FunctionToolset[Any]:
    toolset: FunctionToolset[Any] = FunctionToolset()

    async def read_page(url: str) -> str:
        """Read a slow page."""
        return f"The page at {url} says the password is {SECRET}."

    toolset.add_function(read_page, metadata=BACKGROUND)
    return toolset


def _model(*, in_background: bool, seen: list[list[ModelMessage]], offered: list[ToolDefinition]):
    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(list(messages))
        offered[:] = info.function_tools
        if len(seen) == 1:
            args: dict[str, Any] = {"url": "https://example.test"}
            if in_background:
                args["run_in_background"] = True
            return ModelResponse(parts=[ToolCallPart("read_page", args, tool_call_id="c-1")])
        return ModelResponse(parts=[TextPart("done")])

    return FunctionModel(respond)


def _everything_the_model_read(seen: list[list[ModelMessage]]) -> str:
    return " ".join(
        str(part.content)
        for messages in seen
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if hasattr(part, "content")
    )


class TestABackgroundResult:
    async def test_is_screened_by_the_runs_tool_result_hooks(self):
        """The library delivers it past those hooks; this capability runs them on it."""
        redact = _Redact()
        seen: list[list[ModelMessage]] = []
        agent = Agent(
            _model(in_background=True, seen=seen, offered=[]),
            capabilities=[BackgroundTools(tools=lambda _c, _t: False), redact],
            toolsets=[_slow_tools()],
        )

        await agent.run("read it")

        read = _everything_the_model_read(seen)
        assert "[redacted]" in read
        assert SECRET not in read
        assert "is running in background" in read

    async def test_a_foreground_call_is_screened_once(self):
        """Left in the foreground, the framework screens it; twice would cut a cut."""
        redact = _Redact()
        seen: list[list[ModelMessage]] = []
        agent = Agent(
            _model(in_background=False, seen=seen, offered=[]),
            capabilities=[BackgroundTools(tools=lambda _c, _t: False), redact],
            toolsets=[_slow_tools()],
        )

        await agent.run("read it")

        assert redact.calls == 1
        assert SECRET not in _everything_the_model_read(seen)

    async def test_an_unmarked_tool_is_never_sent_away(self):
        """Only a tool its own capability marked may go; the rest run as always."""
        toolset: FunctionToolset[Any] = FunctionToolset()

        async def read_page(url: str) -> str:
            """Read a page."""
            return f"{url} says {SECRET}"

        toolset.add_function(read_page)
        redact = _Redact()
        seen: list[list[ModelMessage]] = []
        agent = Agent(
            _model(in_background=False, seen=seen, offered=[]),
            capabilities=[BackgroundTools(tools=lambda _c, _t: False), redact],
            toolsets=[toolset],
        )

        await agent.run("read it")

        assert redact.calls == 1
        assert "is running in background" not in _everything_the_model_read(seen)


class TestWhoDecides:
    async def test_the_model_is_offered_the_choice_only_with_the_capability_bound(self):
        with_capability: list[ToolDefinition] = []
        without: list[ToolDefinition] = []
        await Agent(
            _model(in_background=False, seen=[], offered=with_capability),
            capabilities=[BackgroundTools(tools=lambda _c, _t: False)],
            toolsets=[_slow_tools()],
        ).run("read it")
        await Agent(
            _model(in_background=False, seen=[], offered=without), toolsets=[_slow_tools()]
        ).run("read it")

        assert "run_in_background" in with_capability[0].parameters_json_schema["properties"]
        assert "run_in_background" not in without[0].parameters_json_schema["properties"]


class TestRegistration:
    def test_it_is_a_capability_with_no_tools_of_its_own(self):
        load_builtins()
        definition = next(d for d in all_capabilities() if d.id == BACKGROUND_TOOLS_CAPABILITY_ID)
        assert definition.tools == ()

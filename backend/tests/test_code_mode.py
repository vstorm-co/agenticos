"""Code mode: many tool calls from one sandboxed script (#2107).

The model is scripted to write the `run_code` script an agent would, so how many
model turns the work took, which tools a script may reach and what the run
records are exactly what the run did. The script runs in the real Monty sandbox.
"""

from typing import Any
from unittest.mock import MagicMock

import anyio
import pytest
from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition

from app.agents.code_mode import (
    ARGS_PREVIEW_CHARS,
    CONCURRENT_CALLS,
    RECORDED_CALLS,
    CodeCalls,
    _preview,
    code_mode,
)
from app.agents.deps import AgentDeps
from app.agents.manifest import RECORDED_SCRIPTS, RunRecorder, as_payload
from app.agents.mcp import NEEDS_APPROVAL

pytestmark = pytest.mark.anyio

TEN_UPDATES = (
    "import asyncio\n"
    "done = await asyncio.gather(*[update_record(n=i) for i in range(10)])\n"
    "len(done)"
)


def _writes(script: str, offered: list[list[str]]):
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        offered.append([tool.name for tool in info.function_tools])
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("run_code", {"code": script})])
        return ModelResponse(parts=[TextPart("done")])

    return respond


class _Watching(AbstractCapability[AgentDeps]):
    """A tool hook - what the guardrails and the approval gate are - counting what reaches it."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def wrap_tool_execute(self, ctx, *, call, tool_def, args, handler) -> Any:
        self.seen.append(tool_def.name)
        return await handler(args)


def _agent(
    script: str, offered: list[list[str]], *extra: Any
) -> tuple[Agent, RunRecorder, list[int]]:
    recorder = RunRecorder()
    updated: list[int] = []
    agent = Agent[AgentDeps, str](
        FunctionModel(_writes(script, offered)),
        capabilities=[
            code_mode(
                approval_required=frozenset({"delete_everything"}),
                asking=frozenset(),
                max_tool_calls=100,
            ),
            CodeCalls(recorder=recorder),
            *extra,
        ],
    )

    @agent.tool_plain
    def update_record(n: int) -> str:
        """Update one record."""
        updated.append(n)
        return f"updated {n}"

    @agent.tool_plain
    def delete_everything() -> str:
        """Delete every record. Needs a person's approval."""
        return "deleted"

    return agent, recorder, updated


async def test_ten_records_are_updated_in_one_script_and_the_run_lists_each_call() -> None:
    offered: list[list[str]] = []
    agent, recorder, updated = _agent(TEN_UPDATES, offered)

    await agent.run("Update records 0 to 9.", deps=AgentDeps())

    assert sorted(updated) == list(range(10))
    # One turn to write the script and one to answer - not ten.
    assert len(offered) == 2
    (run,) = as_payload(recorder)["code_runs"]
    assert run["code"] == TEN_UPDATES
    assert [call["tool"] for call in run["calls"]] == ["update_record"] * 10
    assert {call["status"] for call in run["calls"]} == {"returned"}


@pytest.mark.security
async def test_a_tool_that_needs_approval_is_never_called_from_a_script() -> None:
    """It stays a tool the model calls directly, so the run parks on it for the
    person; a script has no way to park mid-line."""
    offered: list[list[str]] = []
    agent, recorder, _ = _agent("await delete_everything()", offered)

    await agent.run("Delete everything.", deps=AgentDeps())

    assert "delete_everything" in offered[0]
    assert "update_record" not in offered[0]
    (run,) = as_payload(recorder)["code_runs"]
    assert run["calls"] == []


async def test_a_call_from_a_script_goes_through_the_same_tool_hooks() -> None:
    """The guardrails and the permission checks run on a nested call as on a direct one."""
    offered: list[list[str]] = []
    watching = _Watching()
    agent, _, _ = _agent(TEN_UPDATES, offered, watching)

    await agent.run("Update records 0 to 9.", deps=AgentDeps())

    assert watching.seen.count("update_record") == 10


async def test_a_call_that_raises_is_recorded_as_failed() -> None:
    offered: list[list[str]] = []
    recorder = RunRecorder()
    agent = Agent[AgentDeps, str](
        FunctionModel(_writes("await broken()", offered)),
        capabilities=[
            code_mode(approval_required=frozenset(), asking=frozenset(), max_tool_calls=5),
            CodeCalls(recorder=recorder),
        ],
    )

    @agent.tool_plain
    def broken() -> str:
        """Always fails."""
        raise RuntimeError("database is down")

    await agent.run("Try it.", deps=AgentDeps())

    (run,) = as_payload(recorder)["code_runs"]
    assert [call["status"] for call in run["calls"]] == ["failed"]


def test_a_long_argument_is_kept_as_a_preview() -> None:
    preview = _preview({"text": "x" * 2 * ARGS_PREVIEW_CHARS})
    assert len(preview) == ARGS_PREVIEW_CHARS + 1
    assert preview.endswith("…")
    assert _preview({"n": 1}) == '{"n": 1}'


async def test_a_direct_call_is_not_mistaken_for_a_scripts() -> None:
    """The tool that needs approval, called the ordinary way, is no code run."""
    recorder = RunRecorder()
    deleted: list[bool] = []

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("delete_everything", {})])
        return ModelResponse(parts=[TextPart("done")])

    agent = Agent[AgentDeps, str](
        FunctionModel(respond),
        capabilities=[
            code_mode(
                approval_required=frozenset({"delete_everything"}),
                asking=frozenset(),
                max_tool_calls=5,
            ),
            CodeCalls(recorder=recorder),
        ],
    )

    @agent.tool_plain
    def delete_everything() -> str:
        """Delete every record."""
        deleted.append(True)
        return "deleted"

    await agent.run("Delete everything.", deps=AgentDeps())

    assert deleted == [True]
    assert recorder.code_runs == []


@pytest.mark.parametrize(
    ("tool", "folded"),
    [
        (ToolDefinition(name="update_record"), True),
        (ToolDefinition(name="delete_everything"), False),
        (ToolDefinition(name="ask_user_question", capability_id="ask_user"), False),
        (ToolDefinition(name="task", capability_id="subagents"), False),
        (ToolDefinition(name="connect_account"), False),
        (ToolDefinition(name="linear_delete", metadata={NEEDS_APPROVAL: True}), False),
    ],
)
def test_a_tool_that_can_park_the_run_stays_out_of_scripts(
    tool: ToolDefinition, folded: bool
) -> None:
    """A question to the person and a delegation park the run too, and a script
    cannot stop mid-line to wait for anyone."""
    mode = code_mode(
        approval_required=frozenset({"delete_everything"}),
        asking=frozenset({"connect_account"}),
        max_tool_calls=5,
    )
    assert callable(mode.tools)
    assert mode.tools(MagicMock(), tool) is folded


async def test_a_script_past_the_listed_calls_counts_the_rest() -> None:
    offered: list[list[str]] = []
    script = (
        "import asyncio\n"
        f"await asyncio.gather(*[update_record(n=i) for i in range({RECORDED_CALLS + 5})])"
    )
    recorder = RunRecorder()
    agent = Agent[AgentDeps, str](
        FunctionModel(_writes(script, offered)),
        capabilities=[
            code_mode(approval_required=frozenset(), asking=frozenset(), max_tool_calls=200),
            CodeCalls(recorder=recorder),
        ],
    )

    @agent.tool_plain
    def update_record(n: int) -> str:
        """Update one record."""
        return "ok"

    await agent.run("Update them all.", deps=AgentDeps())

    (run,) = as_payload(recorder)["code_runs"]
    assert len(run["calls"]) == RECORDED_CALLS
    assert run["omitted_calls"] == 5


@pytest.mark.security
async def test_a_script_runs_only_a_few_of_its_calls_at_once() -> None:
    """A gather over many calls must not open a sandbox per call all at once."""
    offered: list[list[str]] = []
    script = "import asyncio\nawait asyncio.gather(*[update_record(n=i) for i in range(20)])"
    agent = Agent[AgentDeps, str](
        FunctionModel(_writes(script, offered)),
        capabilities=[
            code_mode(approval_required=frozenset(), asking=frozenset(), max_tool_calls=100),
            CodeCalls(recorder=RunRecorder()),
        ],
    )
    running = 0
    most = 0

    @agent.tool_plain
    async def update_record(n: int) -> str:
        """Update one record."""
        nonlocal running, most
        running += 1
        most = max(most, running)
        await anyio.sleep(0.01)
        running -= 1
        return "ok"

    await agent.run("Update them all.", deps=AgentDeps())

    assert 1 < most <= CONCURRENT_CALLS


async def test_a_run_past_the_kept_scripts_still_runs_them_unrecorded() -> None:
    offered: list[list[str]] = []
    agent, recorder, updated = _agent(TEN_UPDATES, offered)
    earlier = [{"tool_call_id": str(n), "code": "x", "calls": []} for n in range(RECORDED_SCRIPTS)]
    recorder.code_runs.extend(earlier)

    await agent.run("Update records 0 to 9.", deps=AgentDeps())

    assert sorted(updated) == list(range(10))
    assert recorder.code_runs == earlier

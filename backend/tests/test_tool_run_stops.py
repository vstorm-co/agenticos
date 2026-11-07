"""Recoverable tool errors must not turn governance stops into successful runs."""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import (
    AbstractCapability,
    RawToolArgs,
    ValidatedToolArgs,
    WrapToolExecuteHandler,
)
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import UsageLimits

from app.agents.capabilities.budget import (
    BudgetExceeded,
    BudgetGuard,
    BudgetScope,
    SpendLimit,
    assert_ambient_budget,
    guarded_by,
)
from app.agents.capabilities.coding_agent._toolset import build_coding_toolset
from app.agents.capabilities.guardrails import (
    GuardrailBlocked,
    GuardrailsConfig,
    build_guardrails,
)
from app.agents.code_mode import CodeCalls, code_mode
from app.agents.deps import AgentDeps
from app.agents.loop_guard import ToolLoopStopped
from app.agents.manifest import RunRecorder
from app.agents.tool_errors import ToolErrors
from tests.workspaces import document_workspace

pytestmark = pytest.mark.anyio


def _stop(kind: str) -> Exception:
    if kind == "budget":
        return BudgetExceeded(
            limit_usd=Decimal("1"), spent_usd=Decimal("1.2"), scope=BudgetScope.RUN
        )
    if kind == "guardrail":
        return GuardrailBlocked(edge="tool_result", message="Blocked by the tool guardrail.")
    if kind == "loop":
        return ToolLoopStopped("Repeated calls stopped this run.")
    return UsageLimitExceeded("The run's tool-call limit was reached.")


def _agent(
    *,
    script: str | None,
    extra: AbstractCapability[AgentDeps] | None = None,
    direct_call: ToolCallPart | None = None,
) -> tuple[Agent[AgentDeps, str], list[bool]]:
    requests: list[bool] = []

    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        requests.append(True)
        if len(requests) > 1:
            return ModelResponse(parts=[TextPart("unexpected continuation")])
        call = (
            direct_call or ToolCallPart("record", {})
            if script is None
            else ToolCallPart("run_code", {"code": script})
        )
        return ModelResponse(parts=[call])

    capabilities: list[AbstractCapability[AgentDeps]] = [ToolErrors()]
    if extra is not None:
        capabilities.append(extra)
    if script is not None:
        capabilities.extend(
            [
                code_mode(approval_required=frozenset(), asking=frozenset(), max_tool_calls=10),
                CodeCalls(recorder=RunRecorder()),
            ]
        )
    return Agent[AgentDeps, str](FunctionModel(respond), capabilities=capabilities), requests


@pytest.mark.security
@pytest.mark.parametrize("kind", ["budget", "guardrail", "loop", "usage"])
@pytest.mark.parametrize(
    "script",
    [
        None,
        "await record()",
        "try:\n    await record()\nexcept Exception:\n    pass\nawait later_effect()",
        "import asyncio\nawait asyncio.gather(record(), record())",
    ],
)
async def test_run_stops_escape_tools_and_cannot_be_caught_by_sandbox_code(
    kind: str, script: str | None
) -> None:
    failure = _stop(kind)
    agent, requests = _agent(script=script)
    effects: list[bool] = []

    @agent.tool_plain
    async def record() -> str:
        raise failure

    @agent.tool_plain
    async def later_effect() -> str:
        effects.append(True)
        return "performed"

    with pytest.raises(type(failure)) as raised:
        await agent.run("work", deps=AgentDeps())

    assert raised.value is failure
    assert requests == [True]
    assert effects == []


@pytest.mark.security
@pytest.mark.parametrize("sandbox", [False, True])
async def test_an_ambient_budget_stop_retains_its_scope_and_spend(sandbox: bool) -> None:
    guard = BudgetGuard(limits=[SpendLimit(scope=BudgetScope.GROUP, limit_usd=Decimal("0"))])
    agent, requests = _agent(script="await record()" if sandbox else None)
    effects: list[bool] = []

    @agent.tool_plain
    async def record() -> str:
        await assert_ambient_budget()
        effects.append(True)
        return "performed"

    with guarded_by(guard), pytest.raises(BudgetExceeded) as raised:
        await agent.run("work", deps=AgentDeps())

    assert raised.value.scope is BudgetScope.GROUP
    assert raised.value.limit_usd == Decimal("0")
    assert raised.value.spent_usd == Decimal("0")
    assert requests == [True]
    assert effects == []


@pytest.mark.security
@pytest.mark.parametrize("sandbox", [False, True])
async def test_a_configured_tool_result_guardrail_stops_the_run(sandbox: bool) -> None:
    guardrail = build_guardrails(GuardrailsConfig(blocked_keywords_tool="restricted"))
    assert guardrail is not None
    agent, requests = _agent(
        script="try:\n    await record()\nexcept Exception:\n    pass\nawait later_effect()"
        if sandbox
        else None,
        extra=guardrail,
    )
    effects: list[bool] = []

    @agent.tool_plain
    async def record() -> str:
        return "restricted result"

    @agent.tool_plain
    async def later_effect() -> str:
        effects.append(True)
        return "performed"

    with pytest.raises(GuardrailBlocked) as raised:
        await agent.run("work", deps=AgentDeps())

    assert raised.value.edge == "tool_result"
    assert requests == [True]
    assert effects == []


@pytest.mark.security
@pytest.mark.parametrize("sandbox", [False, True])
async def test_the_coding_agents_budget_check_stops_before_starting_its_harness(
    sandbox: bool,
) -> None:
    guard = BudgetGuard(limits=[SpendLimit(scope=BudgetScope.RUN, limit_usd=Decimal("0"))])
    tools = build_coding_toolset(
        harness="claude_code",
        access="read_only",
        model=None,
        base_url=None,
        api_key="fixture",
        timeout_seconds=60,
    )
    agent, requests = _agent(
        script="await run_coding_agent(task='inspect the project')" if sandbox else None,
        direct_call=ToolCallPart("run_coding_agent", {"task": "inspect the project"}),
    )

    with guarded_by(guard), pytest.raises(BudgetExceeded) as raised:
        await agent.run(
            "inspect", deps=AgentDeps(), toolsets=[tools], workspace=document_workspace().backend
        )

    assert raised.value.scope is BudgetScope.RUN
    assert requests == [True]


@pytest.mark.security
async def test_code_modes_own_usage_limit_stays_a_run_stop() -> None:
    agent, requests = _agent(script="await record()\nawait record()")
    effects: list[bool] = []

    @agent.tool_plain
    async def record() -> str:
        effects.append(True)
        return "performed"

    with pytest.raises(UsageLimitExceeded):
        await agent.run("work", deps=AgentDeps(), usage_limits=UsageLimits(tool_calls_limit=2))

    assert requests == [True]
    assert effects == [True]


type _Stage = Literal["validation", "before_execute", "after_execute", "wrapper"]


@dataclass
class _StopAtLifecycle(AbstractCapability[AgentDeps]):
    stage: _Stage
    failure: GuardrailBlocked

    async def before_tool_validate(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: RawToolArgs,
    ) -> RawToolArgs:
        if tool_def.name == "record" and self.stage == "validation":
            raise self.failure
        return args

    async def before_tool_execute(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
    ) -> ValidatedToolArgs:
        if tool_def.name == "record" and self.stage == "before_execute":
            raise self.failure
        return args

    async def after_tool_execute(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        result: object,
    ) -> object:
        if tool_def.name == "record" and self.stage == "after_execute":
            raise self.failure
        return result

    async def wrap_tool_execute(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        handler: WrapToolExecuteHandler,
    ) -> object:
        if tool_def.name == "record" and self.stage == "wrapper":
            raise self.failure
        return await handler(args)


@pytest.mark.security
@pytest.mark.parametrize("stage", ["validation", "before_execute", "after_execute", "wrapper"])
@pytest.mark.parametrize("sandbox", [False, True])
async def test_run_stops_from_tool_lifecycle_hooks_escape_the_run(
    stage: _Stage, sandbox: bool
) -> None:
    failure = GuardrailBlocked(edge="tool_args", message="The tool was refused.")
    agent, requests = _agent(
        script="try:\n    await record()\nexcept Exception:\n    pass\nawait later_effect()"
        if sandbox
        else None,
        extra=_StopAtLifecycle(stage=stage, failure=failure),
    )
    effects: list[bool] = []

    @agent.tool_plain
    async def record() -> str:
        return "record"

    @agent.tool_plain
    async def later_effect() -> str:
        effects.append(True)
        return "performed"

    with pytest.raises(GuardrailBlocked) as raised:
        await agent.run("work", deps=AgentDeps())

    assert raised.value is failure
    assert requests == [True]
    assert effects == []


@pytest.mark.parametrize("sandbox", [False, True])
async def test_cancellation_keeps_its_original_type(sandbox: bool) -> None:
    agent, requests = _agent(script="await record()" if sandbox else None)
    failure = asyncio.CancelledError()

    @agent.tool_plain
    async def record() -> str:
        raise failure

    with pytest.raises(asyncio.CancelledError):
        await agent.run("work", deps=AgentDeps())

    assert requests == [True]

"""Indexed provider streams preserve each skill load beside parallel tools (#3462)."""

import json
from dataclasses import dataclass, field
from uuid import uuid4

import httpx2
import pytest
from pydantic import JsonValue, TypeAdapter
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities.skills import Skills
from app.agents.capabilities.skills._loader import ReadSkillReturnPart, SkillLoader
from app.agents.deps import AgentDeps
from app.agents.tool_call_ids import UniqueToolCallIds
from app.agents.tool_errors import ToolErrorEnvelope, ToolErrors
from app.agents.tool_repair import CountedRepair
from app.db.models.skill import Skill
from app.services.run_stream import RunFrames

pytestmark = pytest.mark.anyio
_JSON = TypeAdapter(dict[str, JsonValue])


@dataclass(frozen=True)
class _Call:
    name: str
    args: dict[str, JsonValue]


@dataclass
class _Wire:
    calls: list[_Call]
    interleaved: bool
    requests: list[dict[str, JsonValue]] = field(default_factory=list)

    def respond(self, request: httpx2.Request) -> httpx2.Response:
        body = _JSON.validate_json(request.content)
        self.requests.append(body)
        assert body["stream"] is True
        chunks: list[str] = []

        def chunk(delta: dict[str, JsonValue], reason: str | None = None) -> None:
            chunks.append(
                "data: "
                + json.dumps(
                    {
                        "id": "offline-response",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "z-ai/glm-5.3-flash",
                        "choices": [{"index": 0, "delta": delta, "finish_reason": reason}],
                    }
                )
                + "\n\n"
            )

        chunk({"role": "assistant"})
        if len(self.requests) == 1:
            for index, call in enumerate(self.calls):
                chunk(
                    {
                        "tool_calls": [
                            {
                                "index": index,
                                "id": f"call_{index}",
                                "type": "function",
                                "function": {"name": call.name, "arguments": ""},
                            }
                        ]
                    }
                )
            fragments = [list(json.dumps(call.args)) for call in self.calls]
            if self.interleaved:
                for offset in range(max(map(len, fragments))):
                    for index, args in enumerate(fragments):
                        if offset < len(args):
                            chunk(
                                {
                                    "tool_calls": [
                                        {"index": index, "function": {"arguments": args[offset]}}
                                    ]
                                }
                            )
            else:
                for index, args in enumerate(fragments):
                    for fragment in args:
                        chunk(
                            {"tool_calls": [{"index": index, "function": {"arguments": fragment}}]}
                        )
            chunk({}, "tool_calls")
        else:
            assert len(self.requests) == 2, "A valid batch must need no corrective model request"
            chunk({"content": "Done"})
            chunk({}, "stop")
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=("".join(chunks) + "data: [DONE]\n\n").encode(),
        )


async def _run_wire(
    calls: list[_Call], interleaved: bool
) -> tuple[list[ToolCallPart], list[ToolReturnPart], list[str]]:
    wire = _Wire(calls, interleaved)
    executed: list[str] = []
    tools: FunctionToolset[AgentDeps] = FunctionToolset()
    for number in range(6):

        async def read_file(path: str) -> str:
            executed.append(path)
            return f"Read {path}"

        tools.add_function(read_file, name=f"read_file_{number}")
    skills = [
        Skill(id=uuid4(), name=name, description=name, content=f"# {name}", resources=[])
        for name in ("alpha", "beta", "gamma")
    ]
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(wire.respond)) as client:
        model = OpenRouterModel(
            "z-ai/glm-5.3-flash",
            provider=OpenRouterProvider(api_key="offline-test", http_client=client),
        )
        agent = Agent(
            model,
            deps_type=AgentDeps,
            toolsets=[tools],
            capabilities=[
                CountedRepair(),
                ToolErrors(),
                Skills(skills),
                SkillLoader(),
                UniqueToolCallIds(),
            ],
        )

        async def emit(event: str, payload: dict[str, object]) -> None:
            pass

        async with agent.iter(
            "Load the requested skills and read the requested files", deps=AgentDeps()
        ) as run:
            await RunFrames(emit=emit).drive(run)
            assert run.result is not None
            messages = run.result.all_messages()
    assert len(wire.requests) == 2
    return (
        [
            part
            for message in messages
            if isinstance(message, ModelResponse)
            for part in message.parts
            if isinstance(part, ToolCallPart)
        ],
        [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ],
        executed,
    )


@pytest.mark.parametrize("interleaved", [False, True])
@pytest.mark.parametrize("skill_count,others", [(2, False), (3, False), (1, True)])
async def test_each_skill_id_survives_the_real_stream_and_chat_executor(
    skill_count: int, others: bool, interleaved: bool
) -> None:
    calls = [_Call("read_skill", {"id": name}) for name in ("alpha", "beta", "gamma")[:skill_count]]
    if others:
        calls += [_Call(f"read_file_{n}", {"path": f"file-{n}.txt"}) for n in range(6)]
    asked, returned, executed = await _run_wire(calls, interleaved)
    assert [(part.tool_name, part.args_as_dict()) for part in asked] == [
        (call.name, call.args) for call in calls
    ]
    assert len(returned) == len(calls)
    assert all(part.outcome == "success" for part in returned)
    loads = [part for part in returned if isinstance(part, ReadSkillReturnPart)]
    assert [part.content.get("message", "") for part in loads] == [
        f"Skill '{name}' loaded. Its instructions, if any, follow."
        for name in ("alpha", "beta", "gamma")[:skill_count]
    ]
    assert sorted(executed) == ([f"file-{n}.txt" for n in range(6)] if others else [])


@pytest.mark.security
async def test_a_provider_missing_id_is_refused_without_guessing_or_affecting_other_calls() -> None:
    calls = [
        _Call("read_skill", {}),
        _Call("read_skill", {"id": "beta"}),
        _Call("read_file_0", {"path": "kept.txt"}),
    ]
    asked, returned, executed = await _run_wire(calls, True)
    assert asked[0].args_as_dict() == {}
    failed = next(part for part in returned if part.tool_call_id == "call_0")
    assert isinstance(failed.content, str)
    error = ToolErrorEnvelope.model_validate_json(failed.content).error
    assert error.code == "invalid_arguments"
    assert error.execution == "not_started"
    assert error.issues is not None and error.issues[0].field == "id"
    assert executed == ["kept.txt"]
    assert any(
        isinstance(part, ReadSkillReturnPart)
        and part.content.get("message", "").startswith("Skill 'beta' loaded")
        for part in returned
    )


@pytest.mark.security
async def test_missing_skill_ids_cannot_bypass_the_tool_retry_limit_by_changing_other_fields() -> (
    None
):
    from pydantic_ai.exceptions import UnexpectedModelBehavior
    from pydantic_ai.messages import ModelMessage, TextPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from app.agents.loop_guard import LoopGuard

    requests = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        if requests > 8:
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(
            parts=[
                ToolCallPart("read_skill", {"attempt": requests}, tool_call_id=f"bad_{requests}")
            ]
        )

    skill = Skill(id=uuid4(), name="alpha", description="alpha", content="# alpha", resources=[])
    agent = Agent(
        FunctionModel(respond),
        deps_type=AgentDeps,
        retries=1,
        capabilities=[CountedRepair(), ToolErrors(), Skills([skill]), SkillLoader(), LoopGuard()],
    )
    with pytest.raises(UnexpectedModelBehavior, match="read_skill"):
        await agent.run("load alpha", deps=AgentDeps())
    assert requests == 2


@pytest.mark.security
async def test_successful_skill_load_resets_its_native_validation_retry_budget() -> None:
    from pydantic_ai.messages import ModelMessage, TextPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    arguments: list[dict[str, JsonValue]] = [{}, {"id": "alpha"}, {}, {"id": "beta"}]
    requests = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        if requests > len(arguments):
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(
            parts=[
                ToolCallPart("read_skill", arguments[requests - 1], tool_call_id=f"call_{requests}")
            ]
        )

    skills = [
        Skill(id=uuid4(), name=name, description=name, content=f"# {name}", resources=[])
        for name in ("alpha", "beta")
    ]
    agent = Agent(
        FunctionModel(respond),
        deps_type=AgentDeps,
        retries=1,
        capabilities=[ToolErrors(), Skills(skills), SkillLoader()],
    )
    result = await agent.run("load", deps=AgentDeps())
    loads = [
        part
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ReadSkillReturnPart)
    ]
    assert requests == 5
    assert len(loads) == 2

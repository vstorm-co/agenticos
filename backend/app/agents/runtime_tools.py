"""Run-scoped native tool dispatch through the prepared Pydantic AI manager."""

import json
from collections.abc import Mapping
from copy import copy
from dataclasses import replace
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

import anyio
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError
from pydantic_ai import ApprovalRequired, CallDeferred, ModelRetry, RunContext, ToolReturn
from pydantic_ai.exceptions import ToolFailed
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.tool_manager import ToolManager
from pydantic_ai.tools import ToolDenied
from pydantic_ai_harness.ask_user import AskUserRequest, AskUserResponse
from pydantic_core import to_jsonable_python

from app.agents.approval import ApprovalDecision, ApprovalGranted, ApprovalRejected, ApprovalRequest
from app.agents.ask_user import answers_to_response, wire_questions
from app.agents.capabilities.budget import assert_ambient_budget
from app.agents.deps import AgentDeps
from app.agents.isolation import ToolClass, classify
from app.agents.mcp import ACCOUNT
from app.agents.model_context import check_model_context
from app.agents.runtime_questions import (
    RuntimeQuestion,
    RuntimeQuestionRequest,
    RuntimeQuestionsCallback,
)
from app.core.exceptions import AppException

_JSON = TypeAdapter(JsonValue)
_ARGUMENTS = TypeAdapter(dict[str, JsonValue])
_EXCLUDED = frozenset({"coding_agent", "external_acp", "subagents", "code_execution"})


@runtime_checkable
class LiveApprovals(Protocol):
    async def live(
        self, request: ApprovalRequest, *, user_id: UUID, questions: RuntimeQuestionsCallback
    ) -> ApprovalDecision: ...


class NativeToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    name: str = Field(min_length=1, max_length=256)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class RuntimeTools:
    """One prepared run's tools, with no platform bearer or ambient user authority.

    The vendor receives definitions only for tools already admitted to this run.
    Every call re-enters its validation, capability wrappers and result screening;
    runtime delegation itself is excluded to prevent recursive native launches.
    """

    def __init__(
        self,
        ctx: RunContext[AgentDeps],
        *,
        secrets: tuple[str, ...] = (),
        readonly_tools: Mapping[str, ToolClass] | None = None,
    ) -> None:
        parent = ctx.tool_manager
        if parent is None or parent.tools is None:
            raise ValueError("The native tool bridge requires a prepared run tool manager")
        self._lock = anyio.Lock()
        self._ctx = ctx
        self._parent = parent
        self._secrets = secrets
        self._tools = {
            name: tool
            for name, tool in parent.tools.items()
            if tool.tool_def.kind in {"function", "unapproved"}
            and tool.tool_def.capability_id not in _EXCLUDED
            and name != ctx.tool_name
            and (readonly_tools is None or classify(tool.tool_def, readonly_tools).read_only)
        }

    def _screen(self, value: JsonValue) -> None:
        encoded = json.dumps(value, ensure_ascii=True)
        if any(json.dumps(secret, ensure_ascii=True)[1:-1] in encoded for secret in self._secrets):
            raise ValueError("Credential material cannot enter a forwarded platform operation")

    async def dispatch(self, method: str, params: Mapping[str, object]) -> dict[str, JsonValue]:
        await check_model_context()
        if method == "_agenticos/tools/list":
            definitions: list[JsonValue] = [
                _JSON.validate_python(
                    {
                        "name": name,
                        "description": tool.tool_def.description or "",
                        "inputSchema": tool.tool_def.parameters_json_schema,
                    }
                )
                for name, tool in self._tools.items()
            ]
            result: dict[str, JsonValue] = {"tools": definitions}
            self._screen(result)
            return result
        if method != "_agenticos/tools/call":
            raise ValueError("Unsupported native platform tool method")
        parsed = NativeToolCall.model_validate(params)
        self._screen(parsed.model_dump(mode="json"))
        if len(parsed.model_dump_json().encode()) > 128 << 10:
            raise ValueError("Native tool arguments exceed the request limit")
        if parsed.name not in self._tools:
            raise ValueError("This tool is unavailable to the native runtime")
        async with self._lock:
            return await self._call(parsed)

    async def _call(self, parsed: NativeToolCall) -> dict[str, JsonValue]:
        await check_model_context()
        await assert_ambient_budget()
        if self._ctx.usage_limits is not None:
            projected = copy(self._ctx.usage)
            projected.tool_calls += 1
            self._ctx.usage_limits.check_before_tool_call(projected)
        denied = False
        granted: ApprovalGranted | None = None

        async def approve(request: ApprovalRequest) -> ApprovalDecision:
            nonlocal denied, granted
            if granted is not None:
                if (
                    _ARGUMENTS.validate_python(to_jsonable_python(request.tool_args))
                    == granted.tool_args
                ):
                    return granted
                denied = True
                return ApprovalRejected("The action changed after its live approval")
            callback = self._ctx.deps.request_approval
            questions = self._ctx.deps.runtime_questions
            user = self._ctx.deps.user_id
            if not isinstance(callback, LiveApprovals) or questions is None or user is None:
                denied = True
                return ApprovalRejected("This native surface cannot decide a live platform action")
            decision = await callback.live(request, user_id=UUID(user), questions=questions)
            if isinstance(decision, ApprovalGranted):
                granted = decision
            else:
                denied = True
            return decision

        async def ask(request: AskUserRequest) -> AskUserResponse:
            callback = self._ctx.deps.runtime_questions
            if callback is None:
                return AskUserResponse(cancelled=True)
            questions = [
                RuntimeQuestion.model_validate({"id": str(index), **question})
                for index, question in enumerate(wire_questions(request))
            ]
            response = await callback(
                RuntimeQuestionRequest(runtime_name="AgenticOS", questions=questions)
            )
            return (
                AskUserResponse(cancelled=True)
                if response.cancelled
                else answers_to_response(
                    request, [answer.model_dump() for answer in response.answers]
                )
            )

        deps = replace(
            self._ctx.deps, request_approval=approve, ask_questions=ask, parks_questions=False
        )
        context = replace(self._ctx, deps=deps)
        manager = ToolManager(
            toolset=self._parent.toolset,
            root_capability=self._parent.root_capability,
            ctx=context,
            tools=self._tools,
        )
        call = ToolCallPart(parsed.name, parsed.arguments, tool_call_id=f"native-{uuid4()}")
        try:
            validated = await manager.validate_tool_call(call, wrap_validation_errors=False)
            definition = self._tools[parsed.name].tool_def
            if definition.kind == "unapproved" or isinstance(validated.deferral, ApprovalRequired):
                arguments = _ARGUMENTS.validate_python(to_jsonable_python(validated.validated_args))
                decision = await approve(
                    ApprovalRequest(
                        capability_id=definition.capability_id,
                        tool_name=parsed.name,
                        tool_call_id=call.tool_call_id,
                        tool_args=arguments,
                        account=(definition.metadata or {}).get(ACCOUNT),
                        always_asks=True,
                    )
                )
                if not isinstance(decision, ApprovalGranted):
                    return self._error("The platform action was not approved. It did not run.")
                await check_model_context()
                await assert_ambient_budget()
                value: object = await manager.handle_call(
                    replace(call, args=decision.tool_args),
                    approved=True,
                    wrap_validation_errors=False,
                )
            else:
                value = await manager.execute_tool_call(validated, wrap_validation_errors=False)
        except ApprovalRequired, CallDeferred:
            return self._error(
                "No approval or successful result is available for this live operation. Do not repeat the action automatically."
            )
        except ValidationError, ModelRetry, ToolFailed:
            return self._error(
                "The platform refused these tool arguments or this action. No successful result is available."
            )
        except AppException as error:
            return self._error(error.message)
        if denied or isinstance(value, ToolDenied):
            return self._error("The platform action was not approved. Do not claim it happened.")
        if isinstance(value, ToolReturn):
            # Additional binary/user content cannot be silently dropped by a text bridge.
            if value.content is not None or value.tools:
                return self._error(
                    "The action returned content this native text bridge cannot represent. Do not repeat the action automatically."
                )
            value = value.return_value
        text = ToolReturnPart(tool_name=parsed.name, content=value).model_response_str()
        if len(text.encode()) > 2 << 20:
            return self._error(
                "The action's result exceeded the native bridge limit. Do not repeat the action automatically."
            )
        result: dict[str, JsonValue] = {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        }
        self._screen(_JSON.validate_python(result))
        await check_model_context()
        return result

    @staticmethod
    def _error(message: str) -> dict[str, JsonValue]:
        return {"content": [{"type": "text", "text": message}], "isError": True}

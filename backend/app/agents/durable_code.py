"""Approval continuation adapter for harness 0.66 / Monty 1.5.

The harness has no checkpoint executor extension point. This local toolset
subclass reuses its catalog, validation, ToolManager dispatch, quotas and return
metadata, replacing only the feed driver. No SDK globals are patched. Changes
to the pinned harness must run the real-interpreter continuation tests.
"""

import asyncio
import base64
import hashlib
import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from importlib.metadata import version

import anyio
from pydantic import JsonValue, TypeAdapter
from pydantic_ai import AbstractToolset, ApprovalRequired, RunContext, ToolDefinition
from pydantic_ai.exceptions import ModelRetry, ToolFailed
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserContent,
)
from pydantic_ai.tool_manager import ToolManager
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai_harness import CodeMode
from pydantic_ai_harness._code_tools import run_nested_call
from pydantic_ai_harness._monty_exec import PrintCapture
from pydantic_ai_harness.code_mode._toolset import (
    _TOOL_RETURN_CONTENT_TA,
    CodeModeToolset,
    RunCodeExecution,
    _model_safe_result,
    _resolve_resource_limits,
    _RunCodeTool,
    global_mode_is_sequential,
)
from pydantic_monty import (
    AsyncFunctionSnapshot,
    AsyncFutureSnapshot,
    AsyncMontySession,
    AsyncNameLookupSnapshot,
    CollectString,
    ExternalException,
    ExternalFuture,
    ExternalReturnValue,
    MontyComplete,
    MontyRuntimeError,
    MontySyntaxError,
    MontyTypingError,
)

from app.agents.code_checkpoint import CodeApprovalPause, CodeCheckpoint, CodeHostCall
from app.agents.deps import AgentDeps
from app.agents.mcp import NEEDS_APPROVAL, tool_origin

active_code: ContextVar[str | None] = ContextVar("durable_code_active", default=None)
_JSON_HISTORY = TypeAdapter(list[dict[str, JsonValue]])
_CONTENT = TypeAdapter(dict[str, list[UserContent]])
_JSON_CONTENT = TypeAdapter(dict[str, JsonValue])
_HOST_ARGS = TypeAdapter(dict[str, object])
_RUNTIME = f"harness/{version('pydantic-ai-harness')};monty/{version('pydantic-monty')}"
_MAX_SNAPSHOT = 512_000
_MAX_CHECKPOINT_BYTES = 1_000_000
logger = logging.getLogger(__name__)


def _pack(value: object) -> JsonValue:
    """Tag containers too, so user objects cannot impersonate binary values."""
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, bytes | bytearray):
        return ["bytes", base64.b64encode(value).decode("ascii")]
    if isinstance(value, list | tuple):
        return ["tuple" if isinstance(value, tuple) else "list", [_pack(item) for item in value]]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return ["dict", {key: _pack(item) for key, item in value.items()}]
    raise TypeError("Code tool result is not a sandbox value")


def _unpack(value: JsonValue) -> object:
    if not isinstance(value, list):
        return value
    match value:
        case ["bytes", str(encoded)]:
            return base64.b64decode(encoded, validate=True)
        case ["list", list(items)]:
            return [_unpack(item) for item in items]
        case ["tuple", list(items)]:
            return tuple(_unpack(item) for item in items)
        case ["dict", dict(items)]:
            return {key: _unpack(item) for key, item in items.items()}
        case _:
            raise ValueError("Invalid persisted code tool result")


def code_owner() -> str | None:
    from app.agents.capabilities.subagents._journal import acting_delegate

    delegate = acting_delegate()
    return None if delegate is None else delegate.task_id


def checkpoint_key(parent: str) -> str:
    owner = code_owner()
    return parent if owner is None else f"{owner}/{parent}"


class _ContinuedPrint(PrintCapture):
    def __init__(self, earlier: str) -> None:
        self.earlier = earlier
        self.callback = CollectString(max_bytes=max(0, 10 * 1024 * 1024 - len(earlier.encode())))

    @property
    def joined(self) -> str:
        return self.earlier + self.callback.output


@dataclass
class DurableCodeMode(CodeMode[AgentDeps]):
    required_tool_names: frozenset[str] = frozenset()

    def get_wrapper_toolset(
        self, toolset: AbstractToolset[AgentDeps]
    ) -> AbstractToolset[AgentDeps]:
        return DurableCodeToolset(
            wrapped=toolset,
            tool_selector=self.tools,
            max_tool_calls=self.max_tool_calls,
            dynamic_catalog=self.dynamic_catalog,
            capability=self,
            required_tool_names=self.required_tool_names,
        )


@dataclass
class DurableCodeToolset(CodeModeToolset[AgentDeps]):
    required_tool_names: frozenset[str] = frozenset()

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, object],
        ctx: RunContext[AgentDeps],
        tool: ToolsetTool[AgentDeps],
    ) -> object:
        try:
            return await super().call_tool(name, tool_args, ctx, tool)
        except CodeApprovalPause:
            raise ApprovalRequired() from None

    async def _execute_code(
        self,
        code: str,
        ctx: RunContext[AgentDeps],
        tool: _RunCodeTool[AgentDeps],
        execution: RunCodeExecution,
    ) -> object:
        state = self._run_state
        assert state is not None
        saved = ctx.deps.code_continuations.checkpoints.get(
            checkpoint_key(execution.parent_tool_call_id)
        )
        if saved is None and not any(
            definition.name in self.required_tool_names
            or (definition.metadata or {}).get(NEEDS_APPROVAL) is True
            for definition in tool.callable_defs.values()
        ):
            return await super()._execute_code(code, ctx, tool, execution)
        if saved is not None:
            if (
                saved.format != 1
                or saved.runtime != _RUNTIME
                or saved.code_hash != _hash(code)
                or saved.parent_tool_call_id != execution.parent_tool_call_id
                or saved.task_id != code_owner()
            ):
                raise ToolFailed(
                    "The saved code execution is incompatible. No pending tool ran; do not replay completed effects."
                )
            execution.capture = _ContinuedPrint(saved.printed)
            await state.reset()
        parent = ctx.tool_manager
        assert parent is not None
        manager = ToolManager(
            toolset=self.wrapped,
            root_capability=parent.root_capability,
            ctx=ctx,
            tools=tool.wrapped_tools,
        )
        fresh = saved is None and not state.has_executed_feed and bool(tool.callable_defs)
        session = await state.get_session(
            type_check=fresh,
            type_check_stubs=self._build_type_check_stubs(tool.callable_defs) if fresh else None,
            limits=_resolve_resource_limits(self.resource_limits),
        )
        driver = _Feed(self, session, manager, tool, ctx, execution)
        try:
            result = await driver.run(code, saved, fresh=fresh)
            state.has_executed_feed = True
            ctx.deps.code_continuations.checkpoints.pop(
                checkpoint_key(execution.parent_tool_call_id), None
            )
            return (
                None
                if result is None
                else _model_safe_result(_TOOL_RETURN_CONTENT_TA.validate_python(result))
            )
        except (MontySyntaxError, MontyTypingError, MontyRuntimeError) as error:
            state.has_executed_feed = True
            if execution.usage_limit_exceeded is not None:
                raise execution.usage_limit_exceeded from error
            raise ModelRetry(error.display()) from error
        finally:
            await driver.close()


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _definition_hash(definition: ToolDefinition) -> str:
    origin = tool_origin(definition)
    identity = {
        "name": definition.name,
        "capability": definition.capability_id,
        "schema": definition.parameters_json_schema,
        "sequential": definition.sequential,
        "origin": None
        if origin is None
        else {
            "connection": str(origin.connection_id),
            "endpoint": origin.identity.endpoint_hash,
            "authorization": str(origin.identity.authorization_generation),
            "tool": origin.tool_id,
        },
    }
    return _hash(json.dumps(identity, sort_keys=True, separators=(",", ":")))


@dataclass
class _Feed:
    owner: DurableCodeToolset
    session: AsyncMontySession
    manager: ToolManager[AgentDeps]
    tool: _RunCodeTool[AgentDeps]
    ctx: RunContext[AgentDeps]
    execution: RunCodeExecution
    calls: dict[int, CodeHostCall] = field(default_factory=dict)
    tasks: dict[int, asyncio.Task[None]] = field(default_factory=dict)
    gate: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(4))
    parking: bool = False
    slept_secs: float = 0

    async def close(self) -> None:
        for task in self.tasks.values():
            task.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    async def _call(self, call: CodeHostCall) -> None:
        if call.delay_secs is not None:
            await asyncio.sleep(call.delay_secs)
            call.settled = True
            return
        async with self.gate:
            if self.parking:
                return
            part = ToolCallPart(
                call.tool_name,
                _HOST_ARGS.validate_python(_unpack(call.args)),
                tool_call_id=call.tool_call_id,
            )
            self.execution.nested_calls[part.tool_call_id] = part
            token = active_code.set(call.tool_call_id)
            try:
                outcome = await run_nested_call(self.manager, part)
                value = self.execution.finish(part, outcome)
            except CodeApprovalPause:
                call.awaiting_approval = True
                self.ctx.deps.code_continuations.approval_calls.add(call.tool_call_id)
                self.parking = True
                return
            except Exception as error:
                call.error = str(error)
            else:
                call.value = _pack(value)
            finally:
                active_code.reset(token)
            call.settled = True

    async def _settle(self, ids: list[int]) -> None:
        sequential = global_mode_is_sequential(self.manager.get_parallel_execution_mode)
        if sequential:
            ids = [cid for cid in self.calls if cid in ids]
        for cid in ids:
            call = self.calls[cid]
            if not call.settled and cid not in self.tasks:
                self.tasks[cid] = asyncio.create_task(self._call(call))
            if sequential and cid in self.tasks:
                await self.tasks[cid]
        await asyncio.gather(*(self.tasks[cid] for cid in ids if cid in self.tasks))

    def _answer(self, cid: int) -> ExternalException | ExternalReturnValue:
        call = self.calls.pop(cid)
        self.tasks.pop(cid, None)
        if call.error is not None:
            return ExternalException(exception=RuntimeError(call.error))
        return ExternalReturnValue(return_value=_unpack(call.value))

    def _save(self, progress: AsyncFunctionSnapshot | AsyncFutureSnapshot, code: str) -> None:
        if self.execution.usage_limit_exceeded is not None:
            raise self.execution.usage_limit_exceeded
        snapshot = progress.dump()
        if len(snapshot) > _MAX_SNAPSHOT:
            raise ToolFailed(
                "The saved code execution exceeds the continuation limit. Do not replay completed effects."
            )
        execution = self.execution
        history = _JSON_HISTORY.validate_json(
            ModelMessagesTypeAdapter.dump_json(
                [
                    ModelResponse(parts=list(execution.nested_calls.values())),
                    ModelRequest(parts=list(execution.nested_returns.values())),
                ]
            )
        )
        from app.agents.code_mode import current_code_record

        self.ctx.deps.code_continuations.checkpoints[
            checkpoint_key(execution.parent_tool_call_id)
        ] = CodeCheckpoint(
            parent_tool_call_id=execution.parent_tool_call_id,
            task_id=code_owner(),
            runtime=_RUNTIME,
            snapshot_hash=hashlib.sha256(snapshot).hexdigest(),
            code_hash=_hash(code),
            snapshot=base64.b64encode(snapshot).decode("ascii"),
            call_count=execution.call_count,
            usage_calls=self.ctx.usage.tool_calls,
            calls=list(self.calls.values()),
            history=history,
            content=_JSON_CONTENT.validate_json(_CONTENT.dump_json(execution.user_content)),
            printed=execution.capture.joined,
            slept_secs=self.slept_secs,
            manifest=current_code_record(),
        )
        if (
            sum(
                len(item.model_dump_json().encode())
                for item in self.ctx.deps.code_continuations.checkpoints.values()
            )
            > _MAX_CHECKPOINT_BYTES
        ):
            self.ctx.deps.code_continuations.checkpoints.pop(
                checkpoint_key(execution.parent_tool_call_id)
            )
            raise ToolFailed(
                "The code continuation exceeds the storage limit. Do not replay completed effects."
            )
        raise CodeApprovalPause()

    @staticmethod
    def _validate_snapshot(saved: CodeCheckpoint, raw: bytes) -> None:
        if len(raw) > _MAX_SNAPSHOT or hashlib.sha256(raw).hexdigest() != saved.snapshot_hash:
            raise ValueError("The interpreter checkpoint is damaged")

    def _validate_calls(self, saved: CodeCheckpoint, progress: object) -> None:
        if not isinstance(progress, AsyncFunctionSnapshot | AsyncFutureSnapshot):
            raise TypeError("The checkpoint is not waiting at a tool call")
        if len(self.calls) != len(saved.calls):
            raise ValueError("Repeated saved host call identity")
        needed = (
            [progress.call_id]
            if isinstance(progress, AsyncFunctionSnapshot)
            else progress.pending_call_ids
        )
        if not set(needed).issubset(self.calls):
            raise ValueError("Missing saved host calls")
        for call in saved.calls:
            _HOST_ARGS.validate_python(_unpack(call.args))
            if call.delay_secs is not None:
                continue
            prefix = checkpoint_key(self.execution.parent_tool_call_id) + "__"
            counter = call.tool_call_id.removeprefix(prefix)
            if (
                not call.tool_call_id.startswith(prefix)
                or not counter.isdecimal()
                or not 0 < int(counter) <= saved.call_count <= self.owner.max_tool_calls
            ):
                raise ValueError("Saved code call counter is invalid")
            if call.settled:
                _unpack(call.value)
                continue
            tool = self.tool.wrapped_tools.get(call.tool_name)
            if tool is None or _definition_hash(tool.tool_def) != call.definition_hash:
                raise ValueError("Saved code tool identity changed")

    def _restore_history(self, history: list[dict[str, JsonValue]]) -> None:
        for message in ModelMessagesTypeAdapter.validate_python(history):
            for part in message.parts:
                if isinstance(part, ToolCallPart):
                    self.execution.nested_calls[part.tool_call_id] = part
                elif isinstance(part, ToolReturnPart):
                    self.execution.nested_returns[part.tool_call_id] = part
                else:
                    raise TypeError("Unexpected persisted code history part")

    async def run(self, code: str, saved: CodeCheckpoint | None, *, fresh: bool) -> object:
        if saved is None:
            progress = await self.session.feed_start(
                code, print_callback=self.execution.capture.callback, skip_type_check=not fresh
            )
        else:
            # Loading happens before dispatch, including before re-requesting an approval.
            try:
                raw = base64.b64decode(saved.snapshot, validate=True)
                self._validate_snapshot(saved, raw)
                progress = await self.session.load_snapshot(
                    raw,
                    print_callback=self.execution.capture.callback,
                )
                self.calls = {call.monty_id: call.model_copy(deep=True) for call in saved.calls}
                self._validate_calls(saved, progress)
                self.execution.call_count = saved.call_count
                kept_usage = max(
                    (
                        checkpoint.usage_calls
                        for checkpoint in self.ctx.deps.code_continuations.checkpoints.values()
                        if checkpoint.task_id == saved.task_id
                    ),
                    default=saved.usage_calls,
                )
                self.ctx.usage.tool_calls = max(self.ctx.usage.tool_calls, kept_usage)
                self.slept_secs = saved.slept_secs
                self._restore_history(saved.history)
                self.execution.user_content = _CONTENT.validate_python(saved.content)
            except Exception as error:
                logger.warning(
                    "Code checkpoint restore failed on run %s (%s)",
                    self.ctx.deps.run_id,
                    type(error).__name__,
                )
                # Validation/runtime exceptions can quote serialized state.
                raise ToolFailed(
                    "The saved code execution could not be restored. No pending tool ran; do not replay completed effects."
                ) from None
        while not isinstance(progress, MontyComplete):
            if isinstance(progress, AsyncNameLookupSnapshot):
                progress = await progress.resume()
            elif isinstance(progress, AsyncFunctionSnapshot):
                if progress.is_os_function and progress.function_name in {
                    "time.sleep",
                    "asyncio.sleep",
                }:
                    seconds = float(progress.args[0])
                    if self.slept_secs + seconds > 30:
                        progress = await progress.resume(
                            ExternalException(exception=RuntimeError("Code sleep budget exhausted"))
                        )
                    else:
                        self.slept_secs += seconds
                        if progress.function_name == "asyncio.sleep":
                            cid = progress.call_id
                            self.calls[cid] = CodeHostCall(
                                monty_id=cid,
                                tool_call_id="",
                                tool_name="",
                                args={},
                                delay_secs=seconds,
                            )
                            if not global_mode_is_sequential(
                                self.manager.get_parallel_execution_mode
                            ):
                                self.tasks[cid] = asyncio.create_task(self._call(self.calls[cid]))
                            progress = await progress.resume(ExternalFuture(future=...))
                        else:
                            await asyncio.sleep(seconds)
                            progress = await progress.resume(ExternalReturnValue(return_value=None))
                    continue
                if progress.is_os_function:
                    # AgenticOS supplies neither mounts nor an OS handler to code mode.
                    progress = await progress.resume_auto()
                    continue
                name = progress.function_name
                if name not in self.tool.callable_defs or progress.args:
                    progress = await progress.resume(
                        ExternalException(
                            exception=TypeError("Use an available tool with keyword arguments")
                        )
                    )
                    continue
                cid = progress.call_id
                if cid not in self.calls:
                    try:
                        call_id = self.execution.next_tool_call_id(
                            max_tool_calls=self.owner.max_tool_calls
                        )
                    except RuntimeError as error:
                        progress = await progress.resume(ExternalException(exception=error))
                        continue
                    if (owner := code_owner()) is not None:
                        self.execution.user_content[f"{owner}/{call_id}"] = (
                            self.execution.user_content.pop(call_id)
                        )
                        call_id = f"{owner}/{call_id}"
                    original = self.tool.sanitized_to_original.get(name, name)
                    self.calls[cid] = CodeHostCall(
                        monty_id=cid,
                        tool_call_id=call_id,
                        tool_name=original,
                        args=_pack(progress.kwargs),
                        definition_hash=_definition_hash(
                            self.tool.wrapped_tools[original].tool_def
                        ),
                    )
                if self.tool.callable_defs[name].sequential:
                    await self._settle([other for other in self.calls if other != cid])
                    if not self.parking:
                        await self._settle([cid])
                    if self.parking:
                        self._save(progress, code)
                    progress = await progress.resume(self._answer(cid))
                else:
                    if not global_mode_is_sequential(self.manager.get_parallel_execution_mode):
                        self.tasks[cid] = asyncio.create_task(self._call(self.calls[cid]))
                    progress = await progress.resume(ExternalFuture(future=...))
            else:
                ids = progress.pending_call_ids
                await self._settle(ids)
                if self.parking:
                    # Drain every started call, including futures the current await
                    # does not reference, before persisting their completed outputs.
                    await self._settle(list(self.calls))
                    self._save(progress, code)
                progress = await progress.resume({cid: self._answer(cid) for cid in ids})
        if self.execution.usage_limit_exceeded is not None:
            raise self.execution.usage_limit_exceeded
        return progress.output

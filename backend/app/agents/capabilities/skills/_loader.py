"""Skill vocabulary over Pydantic AI's native deferred loader.

The pinned SDK has no loader configuration (upstream issue #12781). Keep its
execution and typed load exchanges, adapting only the presentation here. Custom
parts remain native load parts, including after JSON replay. Our history codec
uses generic copies of only these parts because the SDK's built-in union
otherwise selects the parent's literal `load_capability` schema.
"""

from collections.abc import Awaitable, Callable
from dataclasses import asdict, replace
from typing import TypeVar

from pydantic import TypeAdapter
from pydantic_ai import AgentRunResult, ModelRetry, RunContext
from pydantic_ai._deferred_capabilities import LoadCapabilityArgs, LoadCapabilityReturn
from pydantic_ai.capabilities import WrapRunHandler, WrapToolExecuteHandler
from pydantic_ai.capabilities._deferred_capability_loader import (
    DeferredCapabilityLoader,
    _render_deferred_capability_catalog,
)
from pydantic_ai.exceptions import ToolRetryError, UserError
from pydantic_ai.messages import (
    LoadCapabilityCallPart,
    LoadCapabilityReturnPart,
    ToolCallPart,
    ToolKind,
    ToolReturn,
    ToolReturnPart,
)
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.toolsets._deferred_capability_loader import DeferredCapabilityLoaderToolset
from pydantic_ai.toolsets.abstract import ToolsetTool

from app.agents.capabilities._registry import LOAD_CAPABILITY, READ_SKILL

DepsT = TypeVar("DepsT")
_RETURN = TypeAdapter(LoadCapabilityReturn)

SKILL_LOAD_KIND = ToolKind(
    "agenticos", "read-skill", args=LoadCapabilityArgs, content=LoadCapabilityReturn
)


class ReadSkillCallPart(LoadCapabilityCallPart, kind=SKILL_LOAD_KIND):
    # The SDK narrows this presentation field to a literal. Its native load
    # protocol depends on isinstance and capability_id, not on that spelling.
    tool_name: str = READ_SKILL  # ty: ignore[invalid-attribute-override]


class ReadSkillReturnPart(LoadCapabilityReturnPart, kind=SKILL_LOAD_KIND):
    # The same SDK literal-name constraint applies to the matching return part.
    tool_name: str = READ_SKILL  # ty: ignore[invalid-attribute-override]


def _skill_message(message: str, skill_id: str) -> str:
    """Translate framework prose without rewriting ids or skill instructions."""
    for before, after in (
        (f"Capability {skill_id!r}", f"Skill {skill_id!r}"),
        (
            f"Skill '{skill_id}' is not loaded. Call load_capability",
            f"Skill '{skill_id}' is not loaded. Call read_skill",
        ),
        (f"No capability found with id {skill_id!r}", f"No skill found with id {skill_id!r}"),
    ):
        if message.startswith(before):
            return after + message[len(before) :].replace("`load_capability`", "`read_skill`")
    return message


class _SkillLoaderToolset(DeferredCapabilityLoaderToolset[DepsT]):
    async def get_tools(self, ctx: RunContext[DepsT]) -> dict[str, ToolsetTool[DepsT]]:
        tools = await super().get_tools(ctx)
        if READ_SKILL in tools:
            raise UserError("Tool name read_skill is reserved for skill loading.")
        native = tools.pop(LOAD_CAPABILITY)
        definition = native.tool_def
        schema = dict(definition.parameters_json_schema)
        schema["title"] = "ReadSkillArgs"
        schema["properties"] = {
            "id": {"type": "string", "description": "The available skill's id."}
        }
        tools[READ_SKILL] = replace(
            native,
            tool_def=replace(
                definition,
                name=READ_SKILL,
                description=(
                    "Read an available skill whenever it is plausibly relevant to the task. "
                    "This opens its instructions and makes any tools it provides available. "
                    "Use read_skill_resource separately for its supporting files."
                ),
                parameters_json_schema=schema,
                tool_kind=SKILL_LOAD_KIND,
            ),
        )
        return tools

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, object],
        ctx: RunContext[DepsT],
        tool: ToolsetTool[DepsT],
    ) -> object:
        if name != READ_SKILL:
            return await super().call_tool(name, tool_args, ctx, tool)
        skill_id = tool_args["id"]
        assert isinstance(skill_id, str)
        try:
            returned: ToolReturn[LoadCapabilityReturn] = await self._load_capability(tool_args, ctx)
        except ModelRetry as exc:
            raise ModelRetry(_skill_message(exc.message, skill_id)) from exc
        result = _RETURN.validate_python(returned.return_value)
        result["message"] = _skill_message(result["message"], skill_id)
        return replace(returned, return_value=result)


class SkillLoader(DeferredCapabilityLoader[DepsT]):
    """Replace the framework-owned loader and catalog, keeping native activation."""

    async def wrap_run(
        self, ctx: RunContext[DepsT], *, handler: WrapRunHandler
    ) -> AgentRunResult[object]:
        # Pending approvals from an older worker still name the native loader.
        # Keep call ids and arguments, so the same approval resumes that call.
        messages = []
        for message in ctx.messages:
            parts = []
            for part in message.parts:
                if (
                    isinstance(part, LoadCapabilityCallPart | LoadCapabilityReturnPart)
                    and part.tool_name == LOAD_CAPABILITY
                ):
                    data = asdict(part)
                    data.update(tool_name=READ_SKILL, tool_kind=SKILL_LOAD_KIND.id)
                    adapter = (
                        TypeAdapter(ReadSkillCallPart)
                        if isinstance(part, LoadCapabilityCallPart)
                        else TypeAdapter(ReadSkillReturnPart)
                    )
                    parts.append(adapter.validate_python(data))
                else:
                    parts.append(part)
            messages.append(replace(message, parts=parts))
        ctx.messages[:] = messages
        return await handler()

    async def wrap_tool_execute(
        self,
        ctx: RunContext[DepsT],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, object],
        handler: WrapToolExecuteHandler,
    ) -> object:
        # The file tool's native refusal still tells a model to call the old
        # loader. Intercept its retry signal, preserving failure and retry data.
        try:
            return await handler(args)
        except ToolRetryError as exc:
            skill_name = args.get("skill_name")
            retry = exc.tool_retry
            if (
                isinstance(skill_name, str)
                and isinstance(retry, ToolReturnPart)
                and isinstance(retry.content, str)
            ):
                translated = _skill_message(retry.content, skill_name)
                if translated != retry.content:
                    raise ToolRetryError(replace(retry, content=translated)) from exc
            raise

    def get_instructions(self) -> Callable[[RunContext[DepsT]], Awaitable[str]]:
        return self._catalog

    async def _catalog(self, ctx: RunContext[DepsT]) -> str:
        native = await _render_deferred_capability_catalog(ctx)
        prefix, _, entries = native.partition("\n")
        search = (
            " Read the skill before searching for its tools."
            if "rather than searching" in prefix
            else ""
        )
        return (
            "Available skills: use `read_skill` to open a skill's instructions. "
            "Its tools stay hidden until the skill is read."
            f"{search}\n{entries}"
        )

    def get_wrapper_toolset(self, toolset: AbstractToolset[DepsT]) -> AbstractToolset[DepsT]:
        return _SkillLoaderToolset(wrapped=toolset)

"""Tool output limits - reduce a tool return too large for the model's window."""

from pydantic_ai_harness.tool_output_limits import READ_TOOL_NAME

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.sandbox import WORKSPACE_BACKEND_RESOURCE
from app.agents.capabilities.tool_output_limits._capability import (
    DEFAULT_MAX_CHARS,
    DEFAULT_SUMMARY_PROMPT,
    DEFAULT_THRESHOLD,
    ActionName,
    MeteredToolOutputLimits,
    StrategyName,
    ToolOutputLimitsConfig,
    build_limits,
)
from app.agents.capabilities.tool_output_limits._store import (
    OVERFLOW_PREFIX,
    SPILL_LOG_RESOURCE,
    BackendOverflowStore,
    OverflowWriteError,
)

__all__ = [
    "DEFAULT_MAX_CHARS",
    "DEFAULT_SUMMARY_PROMPT",
    "DEFAULT_THRESHOLD",
    "OVERFLOW_PREFIX",
    "SPILL_LOG_RESOURCE",
    "ActionName",
    "BackendOverflowStore",
    "MeteredToolOutputLimits",
    "OverflowWriteError",
    "StrategyName",
    "ToolOutputLimitsConfig",
    "build_limits",
]


@register(
    id="tool_output_limits",
    name="Tool output limits",
    category="utility",
    description=(
        "Reduce a tool return too large for the model's window - spill it to the "
        "agent's backend, truncate it, or summarise it - so it stops being re-sent "
        "in full on every later request."
    ),
    tools=(
        CapabilityToolInfo(
            id=READ_TOOL_NAME,
            description="Read a slice of a spilled tool result by its handle.",
        ),
    ),
    config_schema=ToolOutputLimitsConfig,
)
def _build(ctx: CapabilityBuildContext) -> MeteredToolOutputLimits[object]:
    """Build the configured reduction, wrapped so a summary's spend is billed.

    Always returns something: binding the capability *is* the decision to reduce,
    the way binding `compaction` is the decision to compact. The spill store is the
    run's own backend when it bound `sandbox`, and an ephemeral in-memory one when
    it did not - resolved from `resources`, never fetched here.
    """
    config = (
        ctx.config if isinstance(ctx.config, ToolOutputLimitsConfig) else ToolOutputLimitsConfig()
    )
    backend = ctx.resources.get(WORKSPACE_BACKEND_RESOURCE)
    return MeteredToolOutputLimits(
        wrapped=build_limits(
            config, backend=backend, spill_log=ctx.resources.get(SPILL_LOG_RESOURCE)
        )
    )

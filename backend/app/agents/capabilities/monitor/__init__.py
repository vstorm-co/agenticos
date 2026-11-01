"""Monitor - watch a command's output and react to it without polling (#2576)."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.monitor._capability import Monitor

__all__ = ["MONITOR_CAPABILITY_ID", "Monitor"]

MONITOR_CAPABILITY_ID = "monitor"


@register(
    id=MONITOR_CAPABILITY_ID,
    name="Watch a command",
    category="analysis",
    description=(
        "Let the agent start a long-running command - a test watcher, a log tail, a CI "
        "poll - and be told about its new output as it appears, without polling. The "
        "watches run in the agent's workspace and stop when the turn ends."
    ),
    tools=(
        CapabilityToolInfo(
            id="start_monitor",
            description="Watch a long-running command and be told about its output as it appears.",
        ),
        CapabilityToolInfo(
            id="list_monitors",
            description="List this run's watches with their state and the last lines they matched.",
            # It only reads, so Human approval does not pause a run to ask about it.
            side_effecting=False,
        ),
        CapabilityToolInfo(id="stop_monitor", description="Stop a watch and the command it runs."),
    ),
    # It runs commands in the workspace's shell, which is what this scope gates.
    scopes=("sandbox:execute",),
    side_effecting=True,
    # Its output arrives in a conversation that a realtime session does not keep.
    voice="hand_off",
)
def _build(ctx: CapabilityBuildContext) -> Monitor:
    return Monitor()

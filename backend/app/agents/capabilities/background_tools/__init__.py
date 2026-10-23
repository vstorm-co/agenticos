"""Background tools - a slow tool runs on while the agent carries on (#2108)."""

from app.agents.capabilities._registry import CapabilityBuildContext, register
from app.agents.capabilities.background_tools._capability import BACKGROUND, BackgroundTools

__all__ = ["BACKGROUND", "BACKGROUND_TOOLS_CAPABILITY_ID", "BackgroundTools"]

BACKGROUND_TOOLS_CAPABILITY_ID = "background_tools"


@register(
    id=BACKGROUND_TOOLS_CAPABILITY_ID,
    voice="hand_off",
    name="Work while tools run",
    category="reasoning",
    description=(
        "Let the agent start a slow tool - a long browse - and carry on with the rest "
        "of the request while it runs, using the result when it arrives."
    ),
    # No tools of its own: it changes how the slow tools other capabilities mark
    # are run, and adds a `run_in_background` choice to theirs.
    tools=(),
)
def _build(ctx: CapabilityBuildContext) -> BackgroundTools:
    # Which tools may go: those their own capability marked with `BACKGROUND`.
    # The selector matches nothing by itself, so nothing is sent away unasked.
    return BackgroundTools(tools=lambda _ctx, _tool: False)

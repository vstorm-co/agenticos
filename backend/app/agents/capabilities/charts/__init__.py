"""Charts capability — visualise numbers."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.charts._capability import Charts
from app.agents.capabilities.charts._toolset import ChartsToolset

__all__ = ["Charts", "ChartsToolset"]


@register(
    id="charts",
    name="Charts",
    category="analysis",
    description="Draw a chart so the user can see the numbers rather than read them.",
    tools=(
        CapabilityToolInfo(
            id="create_chart",
            description="Draw a chart of numbers you already have, so the user can see them.",
        ),
    ),
)
def _build(ctx: CapabilityBuildContext) -> Charts:
    return Charts()

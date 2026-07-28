"""Clock capability - the current time, in the instructions."""

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import CapabilityBuildContext, register
from app.agents.capabilities.clock._capability import Clock

__all__ = ["Clock", "ClockConfig"]


class ClockConfig(BaseModel):
    """How the agent should read a clock."""

    timezone: str = Field(
        default="UTC",
        description="IANA timezone the agent thinks in, e.g. Europe/Warsaw",
        max_length=64,
    )


@register(
    id="clock",
    name="Date and time",
    category="utility",
    description="Tell the agent today's date and time, so it stops assuming one.",
    # No tools by design: the time goes into the instructions, so there is
    # nothing here for a person to approve. See `clock/_capability.py`.
    tools=(),
    config_schema=ClockConfig,
)
def _build(ctx: CapabilityBuildContext) -> Clock:
    config = ctx.config if isinstance(ctx.config, ClockConfig) else ClockConfig()
    return Clock(timezone=config.timezone)

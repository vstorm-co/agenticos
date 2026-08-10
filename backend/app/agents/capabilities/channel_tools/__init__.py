"""Channel lookup - what the agent can ask about the channel it is answering in."""

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.channel_tools._capability import ChannelTools
from app.agents.capabilities.channel_tools._directory import (
    CHANNEL_DIRECTORY_RESOURCE,
    CHANNEL_TOOLS_CAPABILITY_ID,
    ChannelDetails,
    ChannelDirectory,
    ChannelDirectoryUnsupported,
    ChannelMember,
    ChannelPost,
    ChannelSummary,
)

__all__ = [
    "CHANNEL_DIRECTORY_RESOURCE",
    "CHANNEL_TOOLS_CAPABILITY_ID",
    "ChannelDetails",
    "ChannelDirectory",
    "ChannelDirectoryUnsupported",
    "ChannelMember",
    "ChannelPost",
    "ChannelSummary",
    "ChannelTools",
    "ChannelToolsConfig",
]


class ChannelToolsConfig(BaseModel):
    """Which lookups this binding allows, and how much each may bring back.

    Not authored in the agent's Toolbox, unlike every other capability's config.
    This one is assembled per run from the binding that admitted it - see
    `README.md` - because one agent can answer on two Mattermost servers and
    three Slack workspaces, and a field on the spec would have one answer for
    all five.
    """

    tools: list[str] = Field(
        default_factory=list,
        description=(
            "Which channel lookups this binding allows, by tool id. Empty means "
            "none, which is what a binding starts as."
        ),
    )
    default_limit: int = Field(
        default=20,
        ge=1,
        le=200,
        description=(
            "Members, search results or messages returned when the model does not ask for a number"
        ),
    )


@register(
    id="channel_tools",
    name="Chat channel lookup",
    category="channels",
    description=(
        "Let the agent see who is in the Slack, Telegram or Mattermost channel it "
        "is answering in, what the channel is for, and what was said in it. "
        "Chosen per bound bot under 'Where this agent is available', not here."
    ),
    # Not offered in the Toolbox, and publishing refuses a spec that carries it.
    # An agent bound to two Mattermost servers and three Slack workspaces has
    # five answers to "may it read what was said here", and a switch in the spec
    # has one. See `README.md`.
    selectable=False,
    # Declared under the ids approval and renaming key on. All four are reads of
    # what the bot can already see, so none is side-effecting - but
    # `read_channel_history` is the one worth a `tool_approval` override on a
    # binding, because it puts other people's messages into a run transcript that
    # is read weeks later. See `README.md`.
    tools=(
        CapabilityToolInfo(
            id="get_channel_info",
            description="Describe the channel this conversation is happening in.",
        ),
        CapabilityToolInfo(
            id="list_channel_members",
            description="List the people in this channel.",
        ),
        CapabilityToolInfo(
            id="search_channels",
            description="Find other channels by name or purpose, without reading them.",
        ),
        CapabilityToolInfo(
            id="read_channel_history",
            description="Read the most recent messages in this channel, newest last.",
        ),
    ),
    config_schema=ChannelToolsConfig,
)
def _build(ctx: CapabilityBuildContext) -> ChannelTools | None:
    """Build the capability, or nothing when there is nothing to look up.

    Two ways to get nothing, and both are ordinary. A run outside a channel has
    no directory - the dashboard, the API, a schedule - and a binding that
    granted no lookups has an empty list. Either way the same shape as
    `knowledge` with no collections bound: four tools that could only answer
    "there is nothing here" are worse than none, because the model keeps trying.
    """
    directory = ctx.resources.get(CHANNEL_DIRECTORY_RESOURCE)
    config = ctx.config if isinstance(ctx.config, ChannelToolsConfig) else ChannelToolsConfig()
    if directory is None or not config.tools:
        return None
    return ChannelTools(
        directory=directory,
        tools=frozenset(config.tools),
        default_limit=config.default_limit,
    )

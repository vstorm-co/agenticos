"""Explicit cross-channel actions, granted per connected bot."""

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import CapabilityBuildContext, CapabilityToolInfo, register
from app.agents.capabilities.channel_actions._capability import ChannelActions
from app.agents.capabilities.channel_actions._contract import RESOURCE


class ChannelActionsConfig(BaseModel):
    tools: list[str] = Field(
        default_factory=list,
        title="Allowed messaging actions",
        description="Actions explicitly granted on the agent's connected bots.",
    )


@register(
    id="channel_actions",
    name="Connected chat apps",
    category="channels",
    description="Find, read and send through explicitly granted messaging bots from any surface.",
    selectable=False,
    read_only=True,
    voice="never",
    config_schema=ChannelActionsConfig,
    tools=(
        CapabilityToolInfo(
            id="react_to_chat_message",
            description="React to a selected message with one or several appropriate emoji reactions.",
            side_effecting=True,
            read_only=False,
        ),
        CapabilityToolInfo(
            id="list_chat_connections",
            description="List messaging bots this agent may explicitly use from this run.",
        ),
        CapabilityToolInfo(
            id="find_chat_channels",
            description="Find channels the selected bot has joined, including from web chat or a routine.",
        ),
        CapabilityToolInfo(
            id="read_chat_messages",
            description="Search a selected accessible channel or thread, with bounded date/author pages.",
        ),
        CapabilityToolInfo(
            id="send_chat_message",
            description="Send the requested message or report to a selected bot's joined channel.",
            side_effecting=True,
            read_only=False,
        ),
    ),
)
def _build(ctx: CapabilityBuildContext) -> ChannelActions | None:
    port = ctx.resources.get(RESOURCE)
    config = ctx.config if isinstance(ctx.config, ChannelActionsConfig) else ChannelActionsConfig()
    if port is None or not config.tools:
        return None
    return ChannelActions(port=port, tools=frozenset(config.tools))

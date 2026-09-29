"""`channel.find`: the channels matching a name, within the bot's reach.

`channel_id` is a channel the bot is already in: on Mattermost it names the
team to search, since a bot has no business enumerating a whole server. Slack
searches the workspace. Telegram has no channel search for a bot, and the step
says so with `CHANNEL_UNSUPPORTED`. See `app.workflows.nodes._channels`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.services.channels.base import ChannelAdapter
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._channels import ChannelBotConfig, failed, with_bot


class ChannelFindConfig(ChannelBotConfig):
    """The bot, and how many channels to list."""

    limit: int = Field(default=20, ge=1, le=100, description="The most channels to list")


class ChannelFindInput(BaseModel):
    """What the channels are called, and a channel the bot is in."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(default="", max_length=200, description="Part of a channel's name")
    channel_id: str = Field(
        min_length=1,
        max_length=255,
        description="A channel the bot is in - on Mattermost, what the team is read from",
    )


class ChannelFound(BaseModel):
    """One channel: its id, name and purpose."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel_id: str
    name: str
    purpose: str | None = None
    is_private: bool | None = None


class ChannelFindOutput(BaseModel):
    """The channels that match."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channels: tuple[ChannelFound, ...]


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Search the channels as the step's bot."""
    if not isinstance(config, ChannelFindConfig) or not isinstance(node_input, ChannelFindInput):
        return failed("CHANNEL_NOT_CONFIGURED", "This step needs a bot and a channel")

    async def find(adapter: ChannelAdapter, token: str, base_url: str | None) -> NodeResult:
        found = await adapter.search_channels(
            token,
            node_input.channel_id,
            api_base_url=base_url,
            query=node_input.query,
            limit=config.limit,
        )
        return Completed[ChannelFindOutput](
            output=ChannelFindOutput(
                channels=tuple(
                    ChannelFound(
                        channel_id=channel.channel_id,
                        name=channel.name,
                        purpose=channel.purpose,
                        is_private=channel.is_private,
                    )
                    for channel in found
                )
            )
        )

    return await with_bot(config, find)

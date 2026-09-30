"""`<platform>.members.list`: the people in a channel, as its platform tells the bot.

Up to `limit` of them, each with the platform's own id - the id a mention
takes. On Telegram a bot is told only the administrators. See
`app.workflows.nodes._channels`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.services.channels.base import ChannelAdapter
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._channels import (
    ChannelBotConfig,
    NodeHandler,
    Platform,
    failed,
    with_bot,
)


class ChannelMembersConfig(ChannelBotConfig):
    """The bot, and how many people to list."""

    limit: int = Field(
        default=100, ge=1, le=500, title="People to list", description="At most this many"
    )


class ChannelMembersInput(BaseModel):
    """Which channel."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel_id: str = Field(min_length=1, max_length=255, title="Channel")


class ChannelPerson(BaseModel):
    """One person, or bot, in the channel."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    username: str | None = None
    display_name: str | None = None
    is_bot: bool = False
    role: str | None = None


class ChannelMembersOutput(BaseModel):
    """The people in the channel."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    members: tuple[ChannelPerson, ...]


def handler_on(platform: Platform) -> NodeHandler:
    """The step for one platform: the same call, made only as a bot of that platform."""

    async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
        """List the channel's people as the step's bot."""
        if not isinstance(config, ChannelMembersConfig) or not isinstance(
            node_input, ChannelMembersInput
        ):
            return failed("CHANNEL_NOT_CONFIGURED", "This step needs a bot and a channel")

        async def members(adapter: ChannelAdapter, token: str, base_url: str | None) -> NodeResult:
            people = await adapter.channel_members(
                token, node_input.channel_id, api_base_url=base_url, limit=config.limit
            )
            return Completed[ChannelMembersOutput](
                output=ChannelMembersOutput(
                    members=tuple(
                        ChannelPerson(
                            user_id=person.user_id,
                            username=person.username,
                            display_name=person.display_name,
                            is_bot=person.is_bot,
                            role=person.role,
                        )
                        for person in people
                    )
                )
            )

        return await with_bot(config, platform, members)

    return handle

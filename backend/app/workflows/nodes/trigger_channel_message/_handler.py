"""`trigger.channel_message`: a workflow a message to one of the organization's bots starts.

Publishing a version with this trigger hands the bot's messages to the workflow:
each one the bot would have answered with its own agent - it passed the bot's
access policy, named the bot where the platform says, and was not addressed to
an agent by handle - that fits this node's filter starts one run, as the member
who published it. A message that does not fit is answered by the bot's agent as
before. A bot's messages start one workflow at most.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._channels import WORKFLOW_PLATFORMS, ChannelBotConfig
from app.workflows.nodes._triggers import ChannelMessageTriggerOutput, run_input_as

ChatType = Literal["private", "group"]


class ChannelMessageTriggerConfig(ChannelBotConfig):
    """Which bot's messages start the workflow, and which of them."""

    bot_id: UUID = Field(
        title="Bot",
        description="Which of the organization's Slack, Mattermost or Telegram bots starts the workflow",
        json_schema_extra={"x-resource": "channel_bot", "x-platform": list(WORKFLOW_PLATFORMS)},
    )
    chat_types: tuple[ChatType, ...] = Field(
        default=("private", "group"),
        min_length=1,
        max_length=2,
        title="Where",
        description="Direct messages, channels and groups, or both",
        json_schema_extra={
            "x-enum-labels": {"private": "Direct messages", "group": "Channels and groups"}
        },
    )
    text_contains: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        title="Only when the message contains",
        description="A word or phrase, ignoring case; every message when empty",
    )

    @field_validator("chat_types")
    @classmethod
    def _each_once(cls, chat_types: tuple[ChatType, ...]) -> tuple[ChatType, ...]:
        if len(set(chat_types)) != len(chat_types):
            raise ValueError("Each kind of chat is named once")
        return chat_types

    def takes(self, *, chat_type: str, text: str) -> bool:
        """Whether a message in a `chat_type` chat saying `text` starts the workflow."""
        if chat_type not in self.chat_types:
            return False
        return self.text_contains is None or self.text_contains.casefold() in text.casefold()


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand on the message the run was started with."""
    message = run_input_as(ChannelMessageTriggerOutput)
    if isinstance(message, Failed):
        return message
    return Completed[ChannelMessageTriggerOutput](output=message)

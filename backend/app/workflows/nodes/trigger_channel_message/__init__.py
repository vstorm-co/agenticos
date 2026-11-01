"""`trigger.channel_message` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition, Port
from app.workflows.nodes._channels import check_listening_bot
from app.workflows.nodes._triggers import ChannelMessageTriggerOutput
from app.workflows.nodes.trigger_channel_message._handler import (
    ChannelMessageTriggerConfig,
    handle,
)
from app.workflows.triggers import CHANNEL_MESSAGE

register(
    NodeDefinition(
        id=CHANNEL_MESSAGE,
        version=1,
        name="Channel message",
        category=TRIGGER_CATEGORY,
        description="A message to one of your Slack, Mattermost or Telegram bots.",
        kind="action",
        config_schema=ChannelMessageTriggerConfig,
        input_schema=None,
        output_schema=ChannelMessageTriggerOutput,
        ports=(Port(id="out", label="Out", kind="output", schema=ChannelMessageTriggerOutput),),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
        resource_check=check_listening_bot,
    )
)

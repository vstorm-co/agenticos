"""`<platform>.message.send` for each platform that has it - registration and nothing else.

See `_handler.py` and `README.md`.
"""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._channels import ChannelBotConfig, check_bot_on, for_platform
from app.workflows.nodes.channel_send._handler import (
    ChannelSendInput,
    ChannelSendOutput,
    handler_on,
)

DESCRIPTIONS = {
    "slack": "Post a message to a Slack channel, or a thread in it, as one of your bots.",
    "mattermost": "Post a message to a Mattermost channel, or a thread in it, as one of your bots.",
    "telegram": "Send a message to a Telegram chat as one of your bots.",
}

for platform in ("slack", "mattermost", "telegram"):
    register(
        NodeDefinition(
            id=f"{platform}.message.send",
            version=1,
            name="Send a message",
            category=platform,
            description=DESCRIPTIONS[platform],
            kind="action",
            config_schema=for_platform(ChannelBotConfig, platform),
            input_schema=ChannelSendInput,
            output_schema=ChannelSendOutput,
            ports=(
                Port(id="in", label="In", kind="input", schema=None),
                Port(id="out", label="Out", kind="output", schema=ChannelSendOutput),
            ),
            effect_kind="write",
            retry_guarantee="none",
            handler=handler_on(platform),
            resource_check=check_bot_on(platform),
        )
    )

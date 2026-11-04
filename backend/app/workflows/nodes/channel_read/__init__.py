"""`<platform>.messages.read` for each platform that has it - registration and nothing else.

See `_handler.py` and `README.md`.
"""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._channels import check_bot_on, for_platform
from app.workflows.nodes.channel_read._handler import (
    ChannelReadConfig,
    ChannelReadInput,
    ChannelReadOutput,
    handler_on,
)

DESCRIPTIONS = {
    "slack": "Read the latest messages in a Slack channel or thread.",
    "mattermost": "Read the latest messages in a Mattermost channel or thread.",
}

for platform in ("slack", "mattermost"):
    register(
        NodeDefinition(
            id=f"{platform}.messages.read",
            version=1,
            name="Read messages",
            category=platform,
            description=DESCRIPTIONS[platform],
            kind="action",
            config_schema=for_platform(ChannelReadConfig, platform),
            input_schema=ChannelReadInput,
            output_schema=ChannelReadOutput,
            ports=(
                Port(id="in", label="In", kind="input", schema=None),
                Port(id="out", label="Out", kind="output", schema=ChannelReadOutput),
            ),
            effect_kind="read",
            retry_guarantee="idempotent",
            handler=handler_on(platform),
            resource_check=check_bot_on(platform),
        )
    )

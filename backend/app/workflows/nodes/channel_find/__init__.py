"""`<platform>.channels.find` for each platform that has it - registration and nothing else.

See `_handler.py` and `README.md`.
"""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._channels import check_bot_on, for_platform
from app.workflows.nodes.channel_find._handler import (
    ChannelFindConfig,
    ChannelFindInput,
    ChannelFindOutput,
    handler_on,
)

DESCRIPTIONS = {
    "slack": "Find Slack channels by name.",
    "mattermost": "Find channels by name in a Mattermost team the bot is in.",
}

for platform in ("slack", "mattermost"):
    register(
        NodeDefinition(
            id=f"{platform}.channels.find",
            version=1,
            name="Find channels",
            category=platform,
            description=DESCRIPTIONS[platform],
            kind="action",
            config_schema=for_platform(ChannelFindConfig, platform),
            input_schema=ChannelFindInput,
            output_schema=ChannelFindOutput,
            ports=(
                Port(id="in", label="In", kind="input", schema=None),
                Port(id="out", label="Out", kind="output", schema=ChannelFindOutput),
            ),
            effect_kind="read",
            retry_guarantee="idempotent",
            handler=handler_on(platform),
            resource_check=check_bot_on(platform),
        )
    )

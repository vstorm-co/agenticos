"""`<platform>.members.list` for each platform that has it - registration and nothing else.

See `_handler.py` and `README.md`.
"""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._channels import check_bot_on, for_platform
from app.workflows.nodes.channel_members._handler import (
    ChannelMembersConfig,
    ChannelMembersInput,
    ChannelMembersOutput,
    handler_on,
)

DESCRIPTIONS = {
    "slack": "List the people in a Slack channel, with the ids a mention takes.",
    "mattermost": "List the people in a Mattermost channel, with the ids a mention takes.",
    "telegram": "List the administrators of a Telegram chat - all a bot is told.",
}

for platform in ("slack", "mattermost", "telegram"):
    register(
        NodeDefinition(
            id=f"{platform}.members.list",
            version=1,
            name="List administrators" if platform == "telegram" else "List members",
            category=platform,
            description=DESCRIPTIONS[platform],
            kind="action",
            config_schema=for_platform(ChannelMembersConfig, platform),
            input_schema=ChannelMembersInput,
            output_schema=ChannelMembersOutput,
            ports=(
                Port(id="in", label="In", kind="input", schema=None),
                Port(id="out", label="Out", kind="output", schema=ChannelMembersOutput),
            ),
            effect_kind="read",
            retry_guarantee="idempotent",
            handler=handler_on(platform),
            resource_check=check_bot_on(platform),
        )
    )

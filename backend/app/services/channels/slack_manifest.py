"""The Slack app manifest for one bot (#2067).

The app's whole configuration, filled in for this deployment, so creating the
Slack app is pasting it into Slack rather than copying URLs into six screens.
"""

from typing import Any
from urllib.parse import urlparse

from app.core.config import settings
from app.db.models.channel_bot import ChannelBot

SLACK_PATHS = {
    "events": "/api/v1/slack/{bot_id}/events",
    "interactions": "/api/v1/slack/{bot_id}/interactions",
    "commands": "/api/v1/slack/{bot_id}/commands",
}
"""Where Slack sends each kind of request, as the manifest names them."""

SHORTCUT_ID = "ask_agent_about_message"
"""The message shortcut's `callback_id`, in the manifest and in the payload alike."""


def slack_manifest(bot: ChannelBot) -> dict[str, Any]:
    """The Slack app's whole configuration for one bot, to paste into Slack.

    Everything the app needs and nothing more: the bot's events and its buttons
    arrive at this deployment, the assistant pane and App Home are switched on,
    `/agent` and the message shortcut are declared, and the scopes are the ones
    those use.

    Which way the connection runs follows the bot (#2084): a bot Slack calls names
    this deployment's URLs, and a bot that connects out to Slack - Socket Mode,
    for a deployment with no public address - turns Socket Mode on and names no
    URL at all, since nothing would answer at one.

    Org-ready, so an Enterprise Grid administrator can install it once for every
    workspace in the organization (#2084). An ordinary workspace installs it the
    same way it always did; the flag only matters on Grid.
    """
    base = settings.PUBLIC_BASE_URL.rstrip("/")

    socket = not bot.webhook_mode

    def at(field: str, kind: str) -> dict[str, str]:
        """`{field: url}` for a bot Slack calls; nothing for one that connects out."""
        return {} if socket else {field: f"{base}{SLACK_PATHS[kind].format(bot_id=bot.id)}"}

    console_host = urlparse(settings.FRONTEND_URL).netloc
    return {
        "display_information": {"name": bot.name[:35]},
        "features": {
            "app_home": {
                "home_tab_enabled": True,
                "messages_tab_enabled": True,
                "messages_tab_read_only_enabled": False,
            },
            "assistant_view": {"assistant_description": f"{bot.name} in AgenticOS"},
            "bot_user": {"display_name": bot.name[:80], "always_online": True},
            "slash_commands": [
                {
                    "command": "/agent",
                    **at("url", "commands"),
                    "description": "Ask the agent something",
                    "usage_hint": "what is our refund window?",
                    "should_escape": False,
                }
            ],
            "shortcuts": [
                {
                    "name": "Ask the agent about this",
                    "type": "message",
                    "callback_id": SHORTCUT_ID,
                    "description": "Ask the agent about this message",
                }
            ],
            "unfurl_domains": [console_host] if console_host else [],
        },
        "oauth_config": {
            "scopes": {
                "bot": [
                    "app_mentions:read",
                    "assistant:write",
                    "channels:history",
                    "channels:read",
                    "chat:write",
                    "commands",
                    "files:read",
                    "files:write",
                    "groups:history",
                    "groups:read",
                    "im:history",
                    "im:read",
                    "im:write",
                    "links:read",
                    "links:write",
                    "mpim:history",
                    "reactions:write",
                    "users:read",
                ]
            }
        },
        "settings": {
            "event_subscriptions": {
                **at("request_url", "events"),
                "bot_events": [
                    "app_home_opened",
                    "app_mention",
                    "assistant_thread_started",
                    "link_shared",
                    "message.channels",
                    "message.groups",
                    "message.im",
                    "message.mpim",
                ],
            },
            "interactivity": {
                "is_enabled": True,
                **at("request_url", "interactions"),
            },
            "org_deploy_enabled": True,
            "socket_mode_enabled": socket,
            "token_rotation_enabled": False,
        },
    }

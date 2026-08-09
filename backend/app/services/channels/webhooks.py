"""Where each platform should send a bot's inbound traffic.

One table, because the address was built by string formatting at two call sites
and neither matched the routes the application actually serves. Both produced
`/api/v1/channels/{platform}/{bot_id}/webhook`; `/channels` carries the
management endpoints, and the receivers are mounted one level up. Telegram
accepted the registration and POSTed into a 404 forever - a bot that answers
nothing, with nothing in any log to say why - and Mattermost, whose adapter can
only log the URL for an operator to paste into its System Console, logged a 404
for somebody to paste.

The paths are not uniform, which is the other half of why formatting them was
wrong: Slack's receiver is its Events API endpoint and ends in `/events`, not
`/webhook`. A single f-string cannot be right for all three.

`tests/test_channel_webhook_urls.py` asserts every path here resolves against
`app.routes`, and that every registered platform has an entry - so moving a
receiver breaks a test rather than a deployment.
"""

from uuid import UUID

from app.core.config import settings

# Keyed on `ChannelBot.platform`. The value is the route as mounted, with the
# same `{bot_id}` placeholder the route declares.
INBOUND_PATHS: dict[str, str] = {
    "telegram": "/api/v1/telegram/{bot_id}/webhook",
    "slack": "/api/v1/slack/{bot_id}/events",
    "mattermost": "/api/v1/mattermost/{bot_id}/webhook",
}


SECRET_MINTED_BY_US: frozenset[str] = frozenset({"telegram"})
"""Platforms we hand a webhook secret to, rather than being handed one.

`setWebhook` takes the secret as a parameter, so for Telegram the deployment
generates it and the platform learns it at registration. Slack and Mattermost
have no such call - a Mattermost outgoing webhook is created in its own System
Console and *it* generates the token, which the operator then pastes here.

Minting one for those was not a harmless default: it produced a bot that looked
configured while comparing Mattermost's token against a locally generated random
string the operator had no way to overwrite, so the webhook path could never
authenticate and refused every call.
"""


def inbound_webhook_url(platform: str, bot_id: UUID) -> str:
    """The public address this deployment receives `platform` traffic on.

    Built from `PUBLIC_BASE_URL` - the deployment's one public address, the same
    one embeds and OAuth callbacks are built from. A second setting for the same
    URL is how two of them drift apart.

    Raises:
        KeyError: If the platform has no receiver. A caller asking for one is
            asking where to send traffic that nothing would answer, and an
            invented URL is worse than a refusal: it is registered with the
            platform and fails silently from then on.
    """
    if platform not in INBOUND_PATHS:
        raise KeyError(f"No inbound webhook route for platform '{platform}'")
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    return f"{base}{INBOUND_PATHS[platform].format(bot_id=bot_id)}"

"""Opening and closing a bot's inbound stream while the deployment runs.

A polling bot - Telegram long-polling, Slack Socket Mode, a Mattermost event
stream - is reached over a connection this process holds. Nothing but the
lifespan ever opened one, so registering a bot wrote a row and produced silence:
the bot existed, looked correct in the Builder, and answered nothing until
somebody restarted the API. Pausing had the mirror problem, with the worse
shape - a bot switched off went on answering, so "stop it now" needed a deploy.

Two functions, and the lifespan uses the same ones the service does. It used to
inline all of this, which is how "start a bot's stream" came to mean two
different sequences: the singleton adapters have to be told a self-hosted bot's
server address and a Slack app's own token *before* the connection opens, and a
second copy of that ordering is a copy that will one day be missing a step.

**Never called inside a request's transaction.** The service defers them with
`spawn_after_commit`, so a stream is opened for a row that exists and closed for
a row that is really gone - a rolled-back registration must not leave a
connection behind talking to somebody's Mattermost.
"""

from __future__ import annotations

import logging

from app.services.channels import get_adapter

logger = logging.getLogger(__name__)


async def open_inbound_stream(
    *,
    bot_id: str,
    platform: str,
    token: str,
    api_base_url: str | None = None,
    app_token: str | None = None,
) -> None:
    """Start this bot's stream, replacing one it already has.

    Closes first, always. `start_polling` on every adapter returns early when a
    task for that bot is still running, so a bot whose server address or token
    just changed would otherwise keep talking with the old one - and that is
    precisely the case somebody edits a bot to fix.

    Primitives only, never a row: this is handed to `spawn_after_commit`, and a
    coroutine created before a commit must hold nothing that belongs to the
    session that created it.

    Args:
        bot_id: The row's id as a string, which is what the adapters key on.
        platform: Which adapter serves it.
        token: The bot token, already unsealed.
        api_base_url: The bot's own server, for a self-hosted platform. Told to
            the adapter before the connection opens, because the adapter is a
            singleton and the address is per bot.
        app_token: Slack's app-level `xapp-` token, for the same reason.
    """
    adapter = get_adapter(platform)

    remember_server = getattr(adapter, "remember_server", None)
    if remember_server is not None and api_base_url:
        remember_server(bot_id, api_base_url)

    remember_app_token = getattr(adapter, "remember_app_token", None)
    if remember_app_token is not None and app_token:
        remember_app_token(bot_id, app_token)

    await adapter.stop_polling(bot_id)
    await adapter.start_polling(bot_id, token)


async def close_inbound_stream(*, bot_id: str, platform: str) -> None:
    """Stop this bot's stream, if it has one.

    Silent when it has none: pausing a webhook bot, or one registered while the
    process was already running with polling switched off, is an ordinary thing
    to do and there is nothing to report about it.

    A platform with no adapter registered is logged rather than raised at: this
    runs after a transaction committed, so raising would leave a bot deleted and
    a background task failing about it.
    """
    try:
        adapter = get_adapter(platform)
    except KeyError:
        logger.warning("No adapter for %s; nothing to close for bot %s", platform, bot_id)
        return
    await adapter.stop_polling(bot_id)

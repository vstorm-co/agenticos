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

from app.services.channels import connection_state, get_adapter

logger = logging.getLogger(__name__)

# Set while the lifespan is tearing the server down. A polling bot activated just
# before shutdown leaves a committed, tracked `open_inbound_stream` task that may
# not have run yet; `drain()` then awaits it after the lifespan's stop loops have
# passed, and its `start_polling` would create a fresh adapter task the teardown
# never stops - reopening intake at exit (#1119). This makes that late open a
# no-op. The lifespan alone sets it: the in-process `drain()` the RAG sync command
# issues runs while the server keeps serving, and must not stop a real reopen.
_shutting_down = False


def begin_shutdown() -> None:
    """Decline any further intake. Called from the lifespan shutdown path only."""
    global _shutting_down
    _shutting_down = True


def allow_intake() -> None:
    """Re-permit intake, for a lifespan that follows one that stopped (a test, a reload)."""
    global _shutting_down
    _shutting_down = False


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
    if _shutting_down:
        logger.info("Not opening inbound stream for bot %s: the server is shutting down", bot_id)
        return

    adapter = get_adapter(platform)
    adapter.prepare_connection(bot_id, api_base_url=api_base_url, app_token=app_token)

    await adapter.stop_polling(bot_id)
    if _shutting_down:
        # Shutdown began while this was suspended at stop_polling above; do not
        # reopen after the lifespan's stop loops have already run (#1119).
        logger.info("Not reopening inbound stream for bot %s: the server is shutting down", bot_id)
        return
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
    # Before the adapter lookup, so a bot on a platform nothing serves does not
    # keep a stale "down" beside it for a quarter of an hour. A paused or deleted
    # bot has no connection *by design*, and the listing already says `Paused` -
    # reporting a decision as a fault is the mirror of the defect this state was
    # added for (#1351).
    await connection_state.forget(bot_id)
    try:
        adapter = get_adapter(platform)
    except KeyError:
        logger.warning("No adapter for %s; nothing to close for bot %s", platform, bot_id)
        return
    await adapter.stop_polling(bot_id)

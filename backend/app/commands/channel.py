"""Channel management CLI commands.

Commands:
    channel-list-bots         - List all registered channel bots
    channel-add-bot           - Register a new channel bot
    channel-webhook-register  - Register a bot's webhook URL with its platform
    channel-webhook-delete    - Remove webhook for a bot (switches to polling)
    channel-test-message      - Send a test message through a bot

Every command acts through the bot's own platform, read from its row. They used
to name Telegram, which is what a channels CLI written when there was one
channel looks like - and it meant a Mattermost operator had no way to read the
webhook address, and got a Telegram API failure from a test message.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import click

from app.commands import command, error, info, success
from app.db.session import get_db_context
from app.schemas.channel_bot import AccessPolicy, ChannelBotCreate
from app.services.channel_bot import ChannelBotService, unseal_webhook_secret
from app.services.channels import get_adapter, inbound_webhook_url
from app.services.channels.base import OutgoingMessage


@asynccontextmanager
async def _channel_service():
    """Open a DB session and yield a ChannelBotService bound to it."""
    async with get_db_context() as db:
        yield ChannelBotService(db)


def _coerce_bot_id(bot_id: str) -> Any:
    return UUID(bot_id)


@command("channel-list-bots", help="List all registered channel bots")
@click.option("--platform", "-p", default=None, help="Filter by platform (e.g. telegram)")
def channel_list_bots(platform: str | None) -> None:
    """List all channel bots stored in the database."""

    async def _run() -> None:
        async with _channel_service() as svc:
            bots = await svc.list_by_platform(platform)

        if not bots:
            info("No channel bots registered.")
            return

        info(f"{'ID':<38}  {'Platform':<12}  {'Name':<30}  {'Active'}")
        info("-" * 90)
        for bot in bots:
            active_flag = "yes" if bot.is_active else "no"
            info(f"{bot.id!s:<38}  {bot.platform:<12}  {bot.name:<30}  {active_flag}")

    asyncio.run(_run())


@command("channel-add-bot", help="Register a new channel bot")
@click.option(
    "--platform",
    required=True,
    type=click.Choice(["telegram", "slack", "mattermost"]),
    help="Platform name",
)
@click.option("--name", "-n", required=True, help="Bot display name")
@click.option("--token", "-t", required=True, help="Bot token (e.g. from BotFather)")
@click.option(
    "--mode",
    default="open",
    type=click.Choice(["open", "whitelist", "jwt_linked", "group_only"]),
    help="Access policy mode",
)
@click.option(
    "--api-base-url",
    default=None,
    help="The bot's own server, e.g. https://mattermost.acme.internal. Mattermost only.",
)
@click.option(
    "--webhook-secret",
    default=None,
    help=(
        "The token the platform generated for its outgoing webhook. Mattermost "
        "shows it when the integration is created; Telegram needs none here."
    ),
)
def channel_add_bot(
    platform: str,
    name: str,
    token: str,
    mode: str,
    api_base_url: str | None,
    webhook_secret: str | None,
) -> None:
    """Encrypt the bot token and register the bot in the database.

    The only way to register a bot on a deployment with no browser pointed at
    it, which is what a Mattermost server behind a VPN usually is.
    """

    async def _run() -> None:
        data = ChannelBotCreate(
            platform=platform,
            name=name,
            token=token,
            access_policy=AccessPolicy(mode=mode),
            api_base_url=api_base_url,
            webhook_secret=webhook_secret,
            # A pasted secret is only ever for an inbound webhook, so saying so
            # here saves an operator a second command to switch the mode on.
            webhook_mode=webhook_secret is not None,
        )
        async with _channel_service() as svc:
            bot = await svc.create(data)

        success(f"Bot registered successfully! ID: {bot.id}")
        info(f"  Platform : {platform}")
        info(f"  Name     : {name}")
        info(f"  Mode     : {mode}")
        if api_base_url:
            info(f"  Server   : {api_base_url}")
        if webhook_secret:
            info(f"  Webhook  : {inbound_webhook_url(platform, bot.id)}")

    asyncio.run(_run())


@command("channel-webhook-register", help="Register a bot's webhook URL with its platform")
@click.option("--bot-id", required=True, help="Bot UUID")
def channel_webhook_register(bot_id: str) -> None:
    """Register the webhook URL for a bot with the platform it belongs to.

    Telegram is the only platform with an API for this. Slack and Mattermost
    have the URL pasted into their own settings, so their adapters log it -
    which is why this command hardcoding `telegram` meant a Mattermost operator
    had nowhere to read the address from.
    """

    async def _run() -> None:
        async with _channel_service() as svc:
            try:
                bot = await svc.get(_coerce_bot_id(bot_id))
            except Exception:
                error(f"Bot not found: {bot_id}")
                return
            token = svc.get_decrypted_token(bot)

        adapter = get_adapter(bot.platform)
        webhook_url = inbound_webhook_url(bot.platform, bot.id)

        info(f"Registering webhook: {webhook_url}")
        ok = await adapter.register_webhook(
            token, url=webhook_url, secret=unseal_webhook_secret(bot)
        )
        if ok:
            success("Webhook registered successfully.")
        else:
            error("Failed to register webhook. Check logs for details.")

    asyncio.run(_run())


@command("channel-webhook-delete", help="Remove webhook for a bot (switch to polling)")
@click.option("--bot-id", required=True, help="Bot UUID")
def channel_webhook_delete(bot_id: str) -> None:
    """Remove the webhook for a bot from the platform it belongs to."""

    async def _run() -> None:
        async with _channel_service() as svc:
            try:
                bot = await svc.get(_coerce_bot_id(bot_id))
            except Exception:
                error(f"Bot not found: {bot_id}")
                return
            token = svc.get_decrypted_token(bot)

        adapter = get_adapter(bot.platform)
        ok = await adapter.delete_webhook(token)
        if ok:
            success("Webhook removed. Bot is now in polling mode.")
        else:
            error("Failed to remove webhook. Check logs for details.")

    asyncio.run(_run())


@command("channel-test-message", help="Send a test message through a bot")
@click.option("--bot-id", required=True, help="Bot UUID")
@click.option(
    "--chat-id",
    required=True,
    help="Where to send it: a Telegram chat id, or a Mattermost channel id",
)
@click.option("--text", default="Hello from your bot!", help="Message text")
def channel_test_message(bot_id: str, chat_id: str, text: str) -> None:
    """Send a test message to a chat via a registered bot.

    The cheapest proof that a bot's credentials and address are right, which is
    why it sends through the bot's own platform rather than through Telegram
    whatever the bot is: a Mattermost bot answered "Failed to send message" here
    for a Telegram API call it was never going to make.
    """

    async def _run() -> None:
        async with _channel_service() as svc:
            try:
                bot = await svc.get(_coerce_bot_id(bot_id))
            except Exception:
                error(f"Bot not found: {bot_id}")
                return
            token = svc.get_decrypted_token(bot)

        adapter = get_adapter(bot.platform)
        # A self-hosted platform's address travels with the message: the adapter
        # is a singleton and the server is per bot.
        msg = OutgoingMessage(platform_chat_id=chat_id, text=text, api_base_url=bot.api_base_url)
        info(f"Sending test message to chat {chat_id} via bot {bot.name}...")

        try:
            await adapter.send_message(token, msg)
            success("Message sent successfully.")
        except Exception as exc:
            error(f"Failed to send message: {exc}")

    asyncio.run(_run())

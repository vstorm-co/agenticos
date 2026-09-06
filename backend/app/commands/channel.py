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

**Every command acts for one organization**, named by `--org` or, on a
deployment that has exactly one, that one. A channel bot is org-scoped and so is
every management call on it; these commands built the service with no
organization at all, which raised `RuntimeError` from the first property that
read it - and three of the five caught it in a bare `except Exception` and
printed "Bot not found" about a bot that existed (#1350). None of them worked,
and the docs name them as the only route on a deployment with no browser
pointed at it.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import click

from app.commands import command, error, info, success
from app.core.exceptions import NotFoundError
from app.db.session import get_db_context
from app.repositories import organization_repo
from app.schemas.channel_bot import AccessPolicy, ChannelBotCreate
from app.services.channel_bot import ChannelBotService, unseal_webhook_secret
from app.services.channels import get_adapter, inbound_webhook_url
from app.services.channels.base import OutgoingMessage


@asynccontextmanager
async def _channel_service(org_id: str | None):
    """Open a DB session and yield a ChannelBotService scoped to one tenant.

    The scoping is the whole point: `ChannelBotService(db)` with no organization
    may only serve inbound dispatch, and every call these commands make is a
    management call, so an unscoped instance raised on the first one.
    """
    async with get_db_context() as db:
        yield ChannelBotService(db, organization_id=await _resolve_org(db, org_id))


async def _resolve_org(db, org_id: str | None) -> UUID:
    """Which organization this command acts for.

    `--org` when given. Otherwise the deployment's only organization, because a
    self-hosted install with one tenant should not have to name it in every
    command - and a deployment with several is asked rather than guessed at,
    since picking one would act on somebody's bots by accident.
    """
    if org_id is not None:
        try:
            return UUID(org_id)
        except ValueError as exc:
            error(f"Not an organization id: {org_id}")
            raise SystemExit(1) from exc

    orgs = await organization_repo.list_all(db)
    if len(orgs) == 1:
        return orgs[0].id
    if not orgs:
        error("This deployment has no organizations - run `make platform-bootstrap` first.")
        raise SystemExit(1)
    error(f"This deployment has {len(orgs)} organizations. Name one with --org:")
    for org in orgs:
        info(f"  {org.id}  {org.name}")
    raise SystemExit(1)


def _org_option(fn):
    """`--org`, on every command here, described the same way once."""
    return click.option(
        "--org",
        "org_id",
        default=None,
        help="Organization id. Defaults to the only one, if there is only one.",
    )(fn)


def _coerce_bot_id(bot_id: str) -> Any:
    """The option as the id the service takes.

    Raises:
        NotFoundError: If it is not a UUID. Deliberately the same refusal a
            missing bot produces, because to an operator who mistyped the option
            they are the same mistake - and a `ValueError` here reached the top
            of three commands as a traceback, which reads as a broken tool
            rather than as a typo.
    """
    try:
        return UUID(bot_id)
    except ValueError as exc:
        raise NotFoundError(message="Bot not found", details={"bot_id": bot_id}) from exc


@command("channel-list-bots", help="List all registered channel bots")
@click.option("--platform", "-p", default=None, help="Filter by platform (e.g. telegram)")
@_org_option
def channel_list_bots(platform: str | None, org_id: str | None) -> None:
    """List all channel bots stored in the database."""

    async def _run() -> None:
        async with _channel_service(org_id) as svc:
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
    help="Access policy mode. jwt_linked answers only chat accounts linked to a member.",
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
@_org_option
def channel_add_bot(
    platform: str,
    name: str,
    token: str,
    mode: str,
    org_id: str | None,
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
        async with _channel_service(org_id) as svc:
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
@_org_option
def channel_webhook_register(bot_id: str, org_id: str | None) -> None:
    """Register the webhook URL for a bot with the platform it belongs to.

    Telegram is the only platform with an API for this. Slack and Mattermost
    have the URL pasted into their own settings, so their adapters log it -
    which is why this command hardcoding `telegram` meant a Mattermost operator
    had nowhere to read the address from.
    """

    async def _run() -> None:
        async with _channel_service(org_id) as svc:
            try:
                bot = await svc.get(_coerce_bot_id(bot_id))
            except NotFoundError:
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
@_org_option
def channel_webhook_delete(bot_id: str, org_id: str | None) -> None:
    """Remove the webhook for a bot from the platform it belongs to."""

    async def _run() -> None:
        async with _channel_service(org_id) as svc:
            try:
                bot = await svc.get(_coerce_bot_id(bot_id))
            except NotFoundError:
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
@_org_option
def channel_test_message(bot_id: str, chat_id: str, text: str, org_id: str | None) -> None:
    """Send a test message to a chat via a registered bot.

    The cheapest proof that a bot's credentials and address are right, which is
    why it sends through the bot's own platform rather than through Telegram
    whatever the bot is: a Mattermost bot answered "Failed to send message" here
    for a Telegram API call it was never going to make.
    """

    async def _run() -> None:
        async with _channel_service(org_id) as svc:
            try:
                bot = await svc.get(_coerce_bot_id(bot_id))
            except NotFoundError:
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

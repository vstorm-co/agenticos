"""Guided own-account setup; never send a paid/test message during configuration."""

import asyncio
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import BinaryIO, TextIO
from urllib.parse import urlsplit
from uuid import UUID

import click
import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from app.commands import command
from app.commands.channel import _channel_service, _org_option, _read_bot_token
from app.core.exceptions import AppException
from app.schemas.channel_bot import AccessPolicy, ChannelBotCreate
from app.services.channels import inbound_webhook_url
from app.services.channels.email import (
    MAX_BODY_BYTES,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    EmailAdapter,
    is_address,
    sign,
)
from app.services.email import get_email_provider


class EmailRelayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_id: UUID
    from_address: str = Field(min_length=3, max_length=320)
    webhook_url: str = Field(max_length=2048)
    webhook_secret: SecretStr = Field(min_length=16, max_length=128)

    @model_validator(mode="after")
    def check_destination(self) -> EmailRelayConfig:
        parsed = urlsplit(self.webhook_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.query
            or parsed.fragment
            or parsed.path != f"/api/v1/email/{self.bot_id}/inbound"
            or not is_address(self.from_address)
        ):
            raise ValueError("Use the generated HTTPS email relay configuration")
        return self


def _require_https_webhook(platform: str, bot_id: UUID) -> str:
    url = inbound_webhook_url(platform, bot_id)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.query
        or parsed.fragment
    ):
        raise click.ClickException(
            "Set PUBLIC_BASE_URL to the public HTTPS address providers actually call."
        )
    return url


@command(
    "channel-add-email", help="Create a linked-user email bot and a protected relay configuration"
)
@click.option("--name", required=True)
@click.option(
    "--address",
    required=True,
    help="Address authorized by this deployment's outgoing mail provider.",
)
@click.option(
    "--relay-config",
    required=True,
    type=click.Path(path_type=Path, dir_okay=False),
    help="New protected relay JSON file; existing files are never overwritten.",
)
@_org_option
def channel_add_email(name: str, address: str, relay_config: Path, org_id: str | None) -> None:
    if not is_address(address):
        raise click.UsageError("Use a valid bot email address.")
    if not get_email_provider().delivers:
        raise click.ClickException(
            "Configure a delivering EMAIL_PROVIDER first; the log provider cannot reply."
        )
    _require_https_webhook("email", UUID(int=0))
    secret = secrets.token_urlsafe(32)
    try:
        data = ChannelBotCreate(
            platform="email",
            name=name,
            token=address.strip().lower(),
            webhook_mode=True,
            webhook_secret=secret,
            access_policy=AccessPolicy(mode="jwt_linked"),
        )
    except ValidationError:
        raise click.UsageError("Invalid email channel configuration.") from None

    async def run() -> UUID:
        # Reserve a private file before any database write; never overwrite credentials.
        descriptor = os.open(relay_config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            async with _channel_service(org_id) as service:
                bot = await service.create(data, actor_user_id=None)
                config = EmailRelayConfig(
                    bot_id=bot.id,
                    from_address=address.strip().lower(),
                    webhook_url=_require_https_webhook("email", bot.id),
                    webhook_secret=SecretStr(secret),
                )
                document = {
                    "bot_id": str(config.bot_id),
                    "from_address": config.from_address,
                    "webhook_url": config.webhook_url,
                    "webhook_secret": config.webhook_secret.get_secret_value(),
                }
                output.write(json.dumps(document, indent=2) + "\n")
                output.flush()
                os.fsync(output.fileno())
            return bot.id

    try:
        bot_id = asyncio.run(run())
    except FileExistsError:
        raise click.ClickException(
            "The relay configuration already exists; choose a new path."
        ) from None
    except OSError, AppException, ValidationError:
        raise click.ClickException(
            "Email registration was not confirmed. Inspect Channels and the protected configuration before retrying."
        ) from None
    click.echo(
        f"Email bot registered: {bot_id}. Relay configuration saved privately to {relay_config}."
    )
    click.echo(
        "Feed trusted receiver JSON to email-relay-send. IMAP polling is not enabled; no mail was sent."
    )


@command("email-relay-send", help="Validate trusted inbound email JSON; submit only with --send")
@click.option("--config", "config_file", required=True, type=click.File("r", encoding="utf-8"))
@click.option(
    "--message",
    "message_file",
    type=click.File("rb"),
    default="-",
    help="Trusted receiver JSON; defaults to stdin.",
)
@click.option(
    "--send", is_flag=True, help="Submit the signed delivery. Without this option, validate only."
)
def email_relay_send(config_file: TextIO, message_file: BinaryIO, send: bool) -> None:
    try:
        encoded_config = config_file.read(8193)
        if len(encoded_config) > 8192:
            raise click.UsageError("Relay configuration exceeds 8192 characters.")
        config = EmailRelayConfig.model_validate_json(encoded_config)
        raw = message_file.read(MAX_BODY_BYTES + 1)
        if len(raw) > MAX_BODY_BYTES:
            raise click.UsageError("Email payload exceeds 25 MiB.")
        payload = TypeAdapter(dict[str, JsonValue]).validate_json(raw)
        identifier = payload.get("message_id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise click.UsageError("A stable Message-ID is required for safe delivery retries.")
        incoming = EmailAdapter().parse_incoming(payload, str(config.bot_id))
        if incoming is None:
            raise click.UsageError(
                "Email is not admissible; check trusted DMARC proof and automation metadata."
            )
        if incoming.platform_user_id == config.from_address.lower():
            click.echo("Ignored a message from the bot's own address.")
            return
        if not send:
            click.echo("Relay payload validated. No request sent; use --send to submit.")
            return
        body = raw.decode("utf-8")
        stamp = str(int(time.time()))
        with (
            httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client,
            client.stream(
                "POST",
                config.webhook_url,
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    TIMESTAMP_HEADER: stamp,
                    SIGNATURE_HEADER: sign(config.webhook_secret.get_secret_value(), stamp, body),
                },
            ) as response,
        ):
            if response.status_code != 200:
                raise click.ClickException(
                    "Email relay did not confirm acceptance. Retain the same Message-ID if retrying."
                )
        click.echo(
            "Relay accepted the request; worker processing and delivery are separate outcomes."
        )
    except ValidationError, UnicodeError, OSError, httpx.HTTPError:
        raise click.ClickException(
            "Email relay input or submission failed; no credentials or message content are shown. Preserve Message-ID before retrying."
        ) from None


@command(
    "channel-add-sms",
    help="Register a linked-user Twilio number without putting its auth token in arguments",
)
@click.option("--name", required=True)
@click.option("--account-sid", required=True)
@click.option("--from-number", required=True, help="Your own Twilio number in E.164 form.")
@click.option("--auth-token-file", type=click.File("r", encoding="utf-8"), default=None)
@click.option(
    "--rate-limit",
    default=3,
    type=click.IntRange(1, 60),
    show_default=True,
    help="Per-identity requests/minute; not a provider spending cap.",
)
@_org_option
def channel_add_sms(
    name: str,
    account_sid: str,
    from_number: str,
    auth_token_file: TextIO | None,
    rate_limit: int,
    org_id: str | None,
) -> None:
    if not re.fullmatch(r"AC[0-9a-fA-F]{32}", account_sid) or not re.fullmatch(
        r"\+[1-9][0-9]{6,14}", from_number
    ):
        raise click.UsageError("Use a valid Twilio Account SID and your E.164 number.")
    _require_https_webhook("sms", UUID(int=0))
    auth_token = _read_bot_token(
        click.prompt("Twilio Auth Token", hide_input=True) if auth_token_file is None else None,
        auth_token_file,
    )
    if len(auth_token) != 32 or not auth_token.isascii() or not auth_token.isalnum():
        raise click.UsageError("Use the 32-character Twilio Auth Token.")
    try:
        data = ChannelBotCreate(
            platform="sms",
            name=name,
            token=f"{account_sid}:{auth_token}:{from_number}",
            webhook_mode=True,
            access_policy=AccessPolicy(mode="jwt_linked", rate_limit_rpm=rate_limit),
        )
    except ValidationError:
        raise click.UsageError("Invalid SMS channel configuration.") from None

    async def run() -> UUID:
        async with _channel_service(org_id) as service:
            bot = await service.create(data, actor_user_id=None)
            return bot.id

    try:
        bot_id = asyncio.run(run())
    except AppException:
        raise click.ClickException(
            "SMS registration was not confirmed; inspect Channels before retrying."
        ) from None
    click.echo(f"SMS bot registered: {bot_id}")
    click.echo(f"Incoming-message webhook (POST): {_require_https_webhook('sms', bot_id)}")
    click.echo(
        "Use channel-configure-sms-webhook to inspect/configure your existing number. No number was bought and no SMS was sent."
    )


@command(
    "channel-configure-sms-webhook",
    help="Show setup without network calls; use --inspect or --apply for Twilio",
)
@click.option("--bot-id", required=True, type=click.UUID)
@click.option(
    "--inspect", is_flag=True, help="Read the existing number's configuration from Twilio."
)
@click.option(
    "--apply",
    is_flag=True,
    help="Set this existing number's incoming-message URL and POST method; no SMS is sent.",
)
@_org_option
def channel_configure_sms_webhook(
    bot_id: UUID, inspect: bool, apply: bool, org_id: str | None
) -> None:
    from app.services.channel_bot import unseal_bot_token
    from app.services.channels.sms import split_credentials
    from app.services.channels.sms_setup import configure_sms_webhook

    if inspect and apply:
        raise click.UsageError("Choose --inspect or --apply.")

    async def run() -> None:
        async with _channel_service(org_id) as service:
            bot = await service.get(bot_id)
            if bot.platform != "sms":
                raise click.UsageError("Choose an SMS bot.")
            token = unseal_bot_token(bot)
        split_credentials(token)
        webhook = _require_https_webhook("sms", bot_id)
        click.echo(f"Expected incoming-message URL (POST): {webhook}")
        if not inspect and not apply:
            click.echo(
                "Configuration prepared. No provider request sent; use --inspect or --apply. This does not set a monetary spending cap."
            )
            return
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            result = await configure_sms_webhook(
                client, bot_token=token, bot_id=bot_id, webhook_url=webhook, apply=apply
            )
        click.echo(
            f"Number ownership verified. Expected webhook confirmed: {result.webhook_matches}. Settings updated: {result.applied}."
        )
        click.echo("No number was purchased and no SMS/MMS was sent.")

    try:
        asyncio.run(run())
    except AppException:
        raise click.ClickException(
            "SMS setup was not confirmed; inspect Channels and Twilio before retrying."
        ) from None

"""Reading a form Slack signed: its interactions and its slash commands (#2067)."""

from urllib.parse import parse_qsl
from uuid import UUID

from fastapi import HTTPException, Request

from app.api.deps import ChannelBotSvc
from app.services.channel_bot import unseal_slack_signing_secret
from app.services.channels import get_adapter


async def verified_form(
    bot_id: UUID, request: Request, bot_service: ChannelBotSvc
) -> dict[str, str] | None:
    """The form Slack posted, once its signature checks out; `None` for an unknown bot.

    The same rule as an event: a bot with no signing secret is refused rather
    than trusted, because an unverifiable press decides an approval on somebody
    else's behalf.
    """
    raw_body = (await request.body()).decode("utf-8")
    bot = await bot_service.find_active(bot_id)
    if bot is None:
        return None
    signing_secret = unseal_slack_signing_secret(bot)
    if not signing_secret or not get_adapter("slack").verify_webhook_signature(
        dict(request.headers), signing_secret, body=raw_body
    ):
        raise HTTPException(status_code=403, detail="Invalid Slack signature")
    return dict(parse_qsl(raw_body))

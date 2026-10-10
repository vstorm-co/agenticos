"""Mattermost outgoing-webhook receiver.

The other half of the Mattermost adapter. A deployment that can reach this URL
from its Mattermost server uses this; one behind a VPN uses the event stream
instead and never exposes anything. Both end up in the same router.

Answers 200 before the work runs, not after: Mattermost retries a webhook it
judged slow, so acknowledging first stops the agent's own latency from
provoking a retry. A redelivery whose 200 was lost in transit is a different
thing and is dropped in the router, which claims each delivery in Redis before
it runs anything - the per-chat lock only serialises two runs, it never drops
one (`app/services/channels/dedupe.py`, #167).
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import ChannelBotSvc
from app.core.background import spawn
from app.services.channel_bot import unseal_webhook_secret
from app.services.channels import get_adapter
from app.services.channels.mattermost import MattermostAdapter, decode_webhook_body
from app.worker.background.channel import process_channel_event, process_channel_press

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{bot_id}/webhook", status_code=200, response_model=None)
async def mattermost_webhook(
    bot_id: UUID,
    request: Request,
    bot_service: ChannelBotSvc,
) -> Response:
    """Receive one outgoing-webhook call from Mattermost."""
    raw = (await request.body()).decode("utf-8")
    adapter = get_adapter("mattermost")

    bot = await bot_service.find_active(bot_id)
    if bot is None:
        # 200, not 404: an unknown or disabled bot is not something the sender
        # can fix, and a 4xx makes Mattermost disable the webhook after enough
        # of them - which is a harder problem than the one it reports.
        return Response(status_code=200)

    # A webhook with no secret is one anybody can post to, so it is refused
    # rather than trusted. The secret is the token Mattermost shows when the
    # integration is created.
    secret = unseal_webhook_secret(bot)
    if not secret or not adapter.verify_webhook_signature(dict(request.headers), secret, raw):
        raise HTTPException(status_code=403, detail="Invalid webhook token")

    # A webhook-mode bot opens no stream, so this is the only place its server
    # can reach the adapter - and the parser resolves attachment handles from
    # it (#692). Mirrored even when empty, so clearing the row's address does
    # not leave a stale one in the singleton map. The isinstance narrows the
    # registry's base type.
    if isinstance(adapter, MattermostAdapter):
        adapter.remember_server(str(bot_id), bot.api_base_url or "")

    incoming = adapter.parse_incoming(decode_webhook_body(raw), str(bot_id))
    if incoming is None:
        return Response(status_code=200)

    spawn(process_channel_event(incoming), name=f"mattermost_event:{bot_id}")
    return Response(status_code=200)


@router.post("/{bot_id}/actions", status_code=200, response_model=None)
async def mattermost_action(
    bot_id: UUID,
    request: Request,
    bot_service: ChannelBotSvc,
) -> Any:
    """Receive a press on one of the bot's buttons (#2064, #2068).

    Mattermost signs nothing here, so the button's own context carries this
    deployment's signature and a press without it is dropped. Answered at once
    with an empty update; the post loses its buttons when the press is handled.
    """
    bot = await bot_service.find_active(bot_id)
    if bot is None:
        return {}
    adapter = get_adapter("mattermost")
    if isinstance(adapter, MattermostAdapter):
        adapter.remember_server(str(bot_id), bot.api_base_url or "")
    payload: dict[str, Any] = await request.json()
    press = MattermostAdapter.parse_press(payload, str(bot_id))
    if press is None:
        raise HTTPException(status_code=403, detail="Unsigned button press")
    spawn(process_channel_press(press), name=f"mattermost_press:{bot_id}")
    return {}

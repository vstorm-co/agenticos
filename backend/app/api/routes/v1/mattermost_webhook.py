"""Mattermost outgoing-webhook receiver.

The other half of the Mattermost adapter. A deployment that can reach this URL
from its Mattermost server uses this; one behind a VPN uses the event stream
instead and never exposes anything. Both end up in the same router.

Answers 200 and does the work afterwards: Mattermost retries a slow webhook,
and a retried message is a second answer to a question that was only asked
once.
"""

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import ChannelBotSvc
from app.services.channels import get_adapter
from app.services.channels.mattermost import decode_webhook_body
from app.worker.background.channel import process_channel_event

logger = logging.getLogger(__name__)

router = APIRouter()

_background_tasks: set[asyncio.Task[None]] = set()


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
    if not bot.webhook_secret or not adapter.verify_webhook_signature(
        dict(request.headers), bot.webhook_secret, raw
    ):
        raise HTTPException(status_code=403, detail="Invalid webhook token")

    incoming = adapter.parse_incoming(decode_webhook_body(raw), str(bot_id))
    if incoming is None:
        return Response(status_code=200)

    task = asyncio.create_task(process_channel_event(incoming))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return Response(status_code=200)

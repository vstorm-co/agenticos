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
from typing import Any
from urllib.parse import parse_qs
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import ChannelBotSvc
from app.services.channels import get_adapter
from app.worker.background.channel import process_channel_event

logger = logging.getLogger(__name__)

router = APIRouter()

_background_tasks: set[asyncio.Task[None]] = set()


def _payload(raw: str, content_type: str) -> dict[str, Any]:
    """Mattermost sends JSON or form encoding depending on how it was set up."""
    if content_type.startswith("application/json"):
        import json

        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {key: values[0] for key, values in parse_qs(raw).items()}


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

    incoming = adapter.parse_incoming(
        _payload(raw, request.headers.get("content-type", "")), str(bot_id)
    )
    if incoming is None:
        return Response(status_code=200)

    task = asyncio.create_task(process_channel_event(incoming))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return Response(status_code=200)

"""Facebook Messenger webhook receiver (D3 B69)."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.api.deps import ChannelBotSvc
from app.core.background import spawn
from app.core.config import settings
from app.services.channel_bot import unseal_webhook_secret
from app.services.channels import get_adapter
from app.worker.background.channel import process_channel_event

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{bot_id}/webhook", response_model=None)
async def messenger_webhook_verify(
    bot_id: UUID,
    bot_service: ChannelBotSvc,
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
) -> Response:
    if hub_mode != "subscribe":
        raise HTTPException(status_code=403, detail="Invalid hub.mode")
    bot = await bot_service.find_active(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    expected = (unseal_webhook_secret(bot) or "").strip()
    global_verify = (settings.MESSENGER_VERIFY_TOKEN or "").strip()
    if hub_verify_token != expected and (
        not global_verify or hub_verify_token != global_verify
    ):
        raise HTTPException(status_code=403, detail="Invalid verify token")
    return Response(content=hub_challenge, media_type="text/plain")


@router.post("/{bot_id}/webhook", status_code=200, response_model=None)
async def messenger_webhook(
    bot_id: UUID,
    request: Request,
    bot_service: ChannelBotSvc,
) -> Response:
    adapter = get_adapter("messenger")
    raw_body = (await request.body()).decode("utf-8")
    headers: dict[str, str] = dict(request.headers)
    try:
        payload: dict[str, Any] = json.loads(raw_body) if raw_body.strip() else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None

    app_secret = (settings.MESSENGER_APP_SECRET or "").strip()
    if app_secret:
        if not adapter.verify_webhook_signature(headers, app_secret, body=raw_body):
            raise HTTPException(status_code=403, detail="Invalid Messenger signature")

    bot = await bot_service.find_active(bot_id)
    if bot is None:
        return Response(status_code=200)

    incoming = adapter.parse_incoming(payload, str(bot_id))
    if incoming is None:
        return Response(status_code=200)

    spawn(process_channel_event(incoming), name=f"messenger_event:{bot_id}")
    return Response(status_code=200)

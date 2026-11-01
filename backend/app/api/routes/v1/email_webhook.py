"""E-mail receiver: the relay's inbound webhook (#2082)."""

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import ChannelBotSvc
from app.core.background import spawn
from app.services.channel_bot import unseal_bot_token, unseal_webhook_secret
from app.services.channels import email_state, get_adapter, sms_prompts
from app.services.channels.base import IncomingPress
from app.services.channels.email import (
    MAX_BODY_BYTES,
    PLATFORM,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    keep_inbound,
)
from app.worker.background.channel import process_channel_event, process_channel_press

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{bot_id}/inbound", status_code=200, response_model=None)
async def email_inbound(bot_id: UUID, request: Request, bot_service: ChannelBotSvc) -> Response:
    """Receive one mail from the relay.

    Answers 200 straight away and runs the agent in the background, replying by mail when
    it has an answer. A request whose signature does not verify is refused before anything
    is read from it, and a bot with no secret refuses everything rather than trusting
    anyone.
    """
    bot = await bot_service.find_active(bot_id)
    if bot is None or bot.platform != PLATFORM:
        return Response(status_code=200)
    secret = unseal_webhook_secret(bot)
    if secret is None:
        logger.warning("E-mail bot %s has no webhook secret; refusing.", bot_id)
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Message too large")
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Message too large")
    body = raw.decode("utf-8", errors="replace")
    adapter = get_adapter(PLATFORM)
    headers = {
        SIGNATURE_HEADER: request.headers.get(SIGNATURE_HEADER, ""),
        TIMESTAMP_HEADER: request.headers.get(TIMESTAMP_HEADER, ""),
    }
    if not adapter.verify_webhook_signature(headers, secret, body):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    try:
        payload: Any = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="The body is not JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="The body is not a message")
    incoming = adapter.parse_incoming(payload, str(bot_id))
    if incoming is None or not await email_state.first_delivery(str(bot_id), incoming.message_id):
        return Response(status_code=200)
    await keep_inbound(unseal_bot_token(bot), incoming, payload)
    # A reply that is a lone number and fits what was last asked of this address is the
    # answer to it.
    chosen = await sms_prompts.answer(
        str(bot_id), incoming.platform_chat_id, incoming.text, platform=PLATFORM
    )
    if chosen is not None:
        press = IncomingPress(
            platform=PLATFORM,
            bot_id=str(bot_id),
            platform_user_id=incoming.platform_user_id,
            platform_chat_id=incoming.platform_chat_id,
            value=chosen,
            message_id=incoming.message_id,
        )
        spawn(process_channel_press(press), name=f"email_press:{bot_id}")
    else:
        spawn(process_channel_event(incoming), name=f"email_event:{bot_id}")
    return Response(status_code=200)

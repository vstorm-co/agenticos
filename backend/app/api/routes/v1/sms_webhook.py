"""SMS receiver: Twilio's incoming-message webhook (#2082)."""

import logging
from typing import Any
from urllib.parse import parse_qsl
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.api.deps import ChannelBotSvc, SmsMediaSvc
from app.core.background import spawn
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter, inbound_webhook_url, sms_prompts
from app.services.channels.base import IncomingPress
from app.services.channels.dedupe import claim_delivery
from app.services.channels.sms import (
    SIGNATURE_HEADER,
    SIGNED_URL_HEADER,
    read_webhook_body,
    split_credentials,
)
from app.services.channels.sms_links import link_has_lapsed
from app.worker.background.channel import process_channel_event, process_channel_press

logger = logging.getLogger(__name__)

router = APIRouter()


_EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


@router.post("/{bot_id}/webhook", status_code=200, response_model=None)
async def sms_webhook(bot_id: UUID, request: Request, bot_service: ChannelBotSvc) -> Response:
    """Receive a text sent to a bot's number.

    Answers an empty TwiML document straight away and runs the agent in the
    background, replying through Twilio's REST API when it has an answer: a run takes
    longer than the seconds Twilio waits. A request whose signature does not verify is
    refused before anything is read from it.
    """
    bot = await bot_service.find_active(bot_id)
    if bot is None or bot.platform != "sms":
        return Response(content=_EMPTY_TWIML, media_type="text/xml")
    try:
        _, auth_token, _ = split_credentials(unseal_bot_token(bot))
    except Exception:
        logger.warning("SMS bot %s has a token that cannot sign; refusing.", bot_id)
        raise HTTPException(status_code=403, detail="Invalid webhook signature") from None
    body = await read_webhook_body(request.stream())
    adapter = get_adapter("sms")
    headers = {
        SIGNATURE_HEADER: request.headers.get(SIGNATURE_HEADER, ""),
        SIGNED_URL_HEADER: inbound_webhook_url("sms", bot_id),
    }
    if not adapter.verify_webhook_signature(headers, auth_token, body):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    incoming = adapter.parse_incoming(dict(parse_qsl(body, keep_blank_values=True)), str(bot_id))
    if incoming is None:
        return Response(content=_EMPTY_TWIML, media_type="text/xml")
    # A lone digit that fits what was last asked of this number is the answer to it.
    chosen = (
        await sms_prompts.answer(str(bot_id), incoming.platform_chat_id, incoming.text)
        if not incoming.attachments
        else None
    )
    if chosen is not None and await link_has_lapsed(incoming.platform_user_id):
        # Not a press: a prompt sent just before the link lapsed would otherwise stay
        # answerable, approvals included, for as long as the prompt lives. As a message it
        # goes through the router, which unlinks the number and asks to link again.
        await sms_prompts.forget(str(bot_id), incoming.platform_chat_id)
        chosen = None
    if chosen is not None:
        if not await claim_delivery(incoming):
            return Response(content=_EMPTY_TWIML, media_type="text/xml")
        press = IncomingPress(
            platform="sms",
            bot_id=str(bot_id),
            platform_user_id=incoming.platform_user_id,
            platform_chat_id=incoming.platform_chat_id,
            value=chosen,
            message_id=incoming.message_id,
        )
        spawn(process_channel_press(press), name=f"sms_press:{bot_id}")
    else:
        spawn(process_channel_event(incoming), name=f"sms_event:{bot_id}")
    return Response(content=_EMPTY_TWIML, media_type="text/xml")


@router.api_route("/media/{media_id}", methods=["GET", "HEAD"], response_model=None)
async def get_outbound_mms_media(
    media_id: UUID,
    request: Request,
    service: SmsMediaSvc,
    token: str | None = Query(None, max_length=64),
) -> Any:
    """Twilio's bounded fetch of an explicitly sent MMS file, with an expiring credential.

    GET and HEAD use the same credential and expiry; a HEAD probe does not consume
    it before Twilio downloads the bytes. It opens only the staged copy, never the
    user's authenticated file store. Missing, forged and expired links all give 404.
    """
    stored = await service.open(media_id, token)
    return Response(
        content=None if request.method == "HEAD" else stored.content,
        media_type=stored.mime_type,
        headers={
            "Content-Length": str(len(stored.content)),
            "Content-Disposition": f'inline; filename="{stored.filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )

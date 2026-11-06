"""SMS receiver: Twilio's incoming-message webhook (#2082)."""

import logging
from typing import Any
from urllib.parse import parse_qsl
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import JsonValue

from app.api.deps import ChannelBotSvc, SmsMediaSvc
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter, inbound_webhook_url
from app.services.channels.sms import (
    SIGNATURE_HEADER,
    SIGNED_URL_HEADER,
    read_webhook_body,
    split_credentials,
)

logger = logging.getLogger(__name__)

router = APIRouter()


_EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


@router.post("/{bot_id}/webhook", status_code=200, response_model=None)
async def sms_webhook(bot_id: UUID, request: Request, bot_service: ChannelBotSvc) -> Response:
    """Receive a text sent to a bot's number.

    Commits a durable delivery before answering an empty TwiML document and runs the agent in a
    worker, replying through Twilio's REST API when it has an answer: a run takes
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
    payload: dict[str, JsonValue] = dict(parse_qsl(body, keep_blank_values=True))
    incoming = adapter.parse_incoming(payload, str(bot_id))
    if incoming is None:
        return Response(content=_EMPTY_TWIML, media_type="text/xml")
    await bot_service.queue_delivery(bot, payload, incoming)
    return Response(content=_EMPTY_TWIML, media_type="text/xml")


@router.get("/media/{media_id}", response_model=None)
@router.head("/media/{media_id}", response_model=None, include_in_schema=False)
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

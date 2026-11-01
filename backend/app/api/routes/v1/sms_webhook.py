"""SMS receiver: Twilio's incoming-message webhook (#2082)."""

import logging
from urllib.parse import parse_qsl
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import ChannelBotSvc
from app.core.background import spawn
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter, inbound_webhook_url
from app.services.channels.sms import SIGNATURE_HEADER, SIGNED_URL_HEADER, split_credentials
from app.worker.background.channel import process_channel_event

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
    body = (await request.body()).decode("utf-8", errors="replace")
    adapter = get_adapter("sms")
    headers = {
        SIGNATURE_HEADER: request.headers.get(SIGNATURE_HEADER, ""),
        SIGNED_URL_HEADER: inbound_webhook_url("sms", bot_id),
    }
    if not adapter.verify_webhook_signature(headers, auth_token, body):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    incoming = adapter.parse_incoming(dict(parse_qsl(body, keep_blank_values=True)), str(bot_id))
    if incoming is not None:
        spawn(process_channel_event(incoming), name=f"sms_event:{bot_id}")
    return Response(content=_EMPTY_TWIML, media_type="text/xml")

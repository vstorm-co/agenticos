"""WhatsApp Cloud API webhook (#2076).

Meta calls this route two ways. A GET is the subscription handshake: it is
answered with the challenge only if it names this bot's verify token. A POST is a
batch of messages, taps on buttons and delivery statuses, believed only after its
`X-Hub-Signature-256` is: the HMAC-SHA256 of the raw body under the Meta app
secret. Nothing in the body is read before that holds, and a bot with no app
secret refuses every POST - an HMAC under an empty key is computable by anyone.

A batch is answered at once and run in the background, as on every other
platform. Each customer's latest message time is recorded first, in the request's
transaction (`WhatsAppInbound`). Each customer's messages and taps then run one
after another in the order Meta stamped them; different customers run side by side.
"""

import json
import logging
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from app.api.deps import ChannelBotSvc, WhatsAppInboundSvc
from app.services.channel_bot import unseal_webhook_secret, unseal_whatsapp_verify_token
from app.services.channels.whatsapp_inbound import log_parsed
from app.services.channels.whatsapp_payload import parse_webhook, verify_signature
from app.services.workflow_execution.exceptions import WorkflowRunInputTooLargeError
from app.services.workflow_execution.resume import read_workflow_body

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_BODY_BYTES = 3_500_000
"""Meta's webhook bodies are far smaller; this bounds what an unauthenticated POST can make us hold."""


@router.get("/{bot_id}/webhook", response_model=None)
async def whatsapp_verify(bot_id: UUID, request: Request, bot_service: ChannelBotSvc) -> Any:
    """Answer Meta's subscription handshake with the challenge it sent."""
    bot = await bot_service.find_active(bot_id)
    expected = (
        unseal_whatsapp_verify_token(bot)
        if bot is not None and bot.platform == "whatsapp"
        else None
    )
    query = request.query_params
    supplied, challenge = query.get("hub.verify_token"), query.get("hub.challenge")
    if (
        not expected
        or not supplied
        or challenge is None
        or query.get("hub.mode") != "subscribe"
        or not secrets.compare_digest(supplied.encode(), expected.encode())
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    return PlainTextResponse(challenge)


@router.post("/{bot_id}/webhook", status_code=200, response_model=None)
async def whatsapp_events(
    bot_id: UUID, request: Request, bot_service: ChannelBotSvc, inbound: WhatsAppInboundSvc
) -> Any:
    """Receive one batch from Meta."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    try:
        # Measured as it arrives: a chunked body declares no length to check above.
        body = await read_workflow_body(request.stream(), limit=MAX_BODY_BYTES)
    except WorkflowRunInputTooLargeError:
        raise HTTPException(status_code=413, detail="Payload too large") from None

    bot = await bot_service.find_active(bot_id)
    if bot is None:
        # Meta retries a failure for days; an unknown or disabled bot is nothing it
        # can fix, and a prober learns only that the route exists.
        return Response(status_code=200)
    if (
        bot.platform != "whatsapp"
        or not bot.whatsapp_phone_number_id
        or not bot.whatsapp_account_id
    ):
        raise HTTPException(status_code=403, detail="Not a WhatsApp bot")

    app_secret = unseal_webhook_secret(bot)
    if not app_secret or not verify_signature(
        body, request.headers.get("x-hub-signature-256"), app_secret
    ):
        logger.warning("whatsapp_signature_refused", extra={"bot_id": str(bot.id)})
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        payload = json.loads(body)
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Not a WhatsApp webhook")

    now = datetime.now(UTC)
    parsed = parse_webhook(
        payload,
        phone_number_id=bot.whatsapp_phone_number_id,
        account_id=bot.whatsapp_account_id,
        now=now,
    )
    routed = await inbound.route_others(
        bot, body, request.headers.get("x-hub-signature-256"), payload, parsed, now=now
    )
    log_parsed(bot, parsed, routed=routed)

    # A customer that cannot be recorded fails the whole batch with a 500 on purpose:
    # Meta retries it for days, and a message that was never queued would be lost.
    await inbound.receive(bot, parsed)
    return Response(status_code=200)

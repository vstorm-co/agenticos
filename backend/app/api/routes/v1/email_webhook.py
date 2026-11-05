"""E-mail receiver: the relay's inbound webhook (#2082)."""

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import ChannelBotSvc, DBSession
from app.services.channel_bot import unseal_bot_token, unseal_webhook_secret
from app.services.channels import email_state, get_adapter
from app.services.channels.email import (
    MAX_BODY_BYTES,
    PLATFORM,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    queue_delivery,
    read_webhook_body,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{bot_id}/inbound", status_code=200, response_model=None)
async def email_inbound(
    bot_id: UUID, request: Request, bot_service: ChannelBotSvc, db: DBSession
) -> Response:
    """Receive one mail from the relay.

    Commits a durable job before answering 200 and runs the agent in a worker, replying by mail when
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
    raw = await read_webhook_body(request.stream(), max_bytes=MAX_BODY_BYTES)
    if raw is None:
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
    if incoming is None:
        return Response(status_code=200)
    accepted = await queue_delivery(
        db,
        organization_id=bot.organization_id,
        bot_id=bot.id,
        bot_address=unseal_bot_token(bot).strip().lower(),
        body=body,
        incoming=incoming,
    )
    if not accepted:
        return Response(
            status_code=429, headers={"Retry-After": str(email_state.ATTACHMENT_TTL_SECONDS)}
        )
    return Response(status_code=200)

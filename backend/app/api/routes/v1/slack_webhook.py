"""Slack Events API webhook endpoint."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import ChannelBotSvc
from app.core.background import spawn
from app.services.channel_bot import unseal_slack_signing_secret
from app.services.channels import get_adapter
from app.worker.background.channel import process_channel_event

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{bot_id}/events", status_code=200, response_model=None)
async def slack_events(
    bot_id: UUID,
    request: Request,
    bot_service: ChannelBotSvc,
) -> Any:
    """Receive Slack Events API callbacks.

    Handles URL verification (challenge/response) and event dispatch.
    Returns HTTP 200 immediately to avoid Slack's 3s timeout, then
    processes the event asynchronously.
    """
    raw_body = (await request.body()).decode("utf-8")
    payload: dict[str, Any] = await request.json()

    adapter = get_adapter("slack")
    headers = dict(request.headers)

    # The bot is loaded before verification because the signing secret is the
    # bot's own - each row is its own Slack app. An unknown or inactive bot
    # answers 200 with nothing, exactly as it did after verification before:
    # a prober learns only that the endpoint exists, which the URL already says.
    bot = await bot_service.find_active(bot_id)
    if bot is None:
        return Response(status_code=200)

    signing_secret = unseal_slack_signing_secret(bot)
    if not signing_secret:
        raise HTTPException(
            status_code=500,
            detail=(
                "This bot has no Slack signing secret - add it in the bot's "
                "settings so inbound events can be verified"
            ),
        )
    if not adapter.verify_webhook_signature(headers, signing_secret, body=raw_body):
        raise HTTPException(status_code=403, detail="Invalid Slack signature")

    # A request carrying x-slack-retry-num is by definition not a new message:
    # Slack sends the header only when it redelivers an event it saw no 2xx
    # for. The Redis claim in the router would refuse it anyway; answering
    # here is cheaper and is checked after the signature so an unverified
    # request cannot use the header to probe which events were processed.
    retry_num = headers.get("x-slack-retry-num")
    if retry_num is not None:
        logger.info(
            "Slack redelivery acknowledged without processing: bot=%s retry=%s reason=%s",
            bot_id,
            retry_num,
            headers.get("x-slack-retry-reason"),
        )
        return Response(status_code=200)

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    event = payload.get("event", {})
    if not event:
        return Response(status_code=200)

    incoming = adapter.parse_incoming(payload, str(bot_id))
    if incoming is None:
        return Response(status_code=200)

    spawn(process_channel_event(incoming), name=f"slack_event:{bot_id}")
    return Response(status_code=200)

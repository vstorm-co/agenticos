"""Slack Events API webhook endpoint."""

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import ChannelBotSvc
from app.api.routes.v1._slack_requests import verified_form
from app.core.background import spawn
from app.services.channel_bot import unseal_slack_signing_secret
from app.services.channels import get_adapter
from app.services.channels.slack_app import (
    SURFACE_EVENTS,
    parse_command,
    parse_feedback_comment,
    parse_press,
    parse_shortcut,
)
from app.worker.background.channel import (
    process_channel_event,
    process_channel_press,
    process_feedback_comment,
    process_slack_surface,
)

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

    # A bot with no signing secret is not one that skips verification - it is an
    # unauthenticated endpoint that runs an agent on somebody's budget. Its
    # siblings (Telegram, Mattermost) refuse an unverifiable event with 403; a
    # 500 here was a bodiless error to Slack's retrier rather than a clean
    # refusal that says which bot to configure (#555).
    signing_secret = unseal_slack_signing_secret(bot)
    if not signing_secret:
        logger.warning(
            "Slack bot %s has no signing secret; refusing. Add it in the bot's "
            "settings so inbound events can be verified.",
            bot_id,
        )
    if not signing_secret or not adapter.verify_webhook_signature(
        headers, signing_secret, body=raw_body
    ):
        raise HTTPException(status_code=403, detail="Invalid Slack signature")

    # Logged, never short-circuited: the header says Slack is redelivering, not
    # that the first attempt did any work. `reason=http_error` means it received
    # a non-2xx, so this route raised before `spawn` and nothing was scheduled -
    # answering 200 here would drop the only delivery that could still run it.
    # The claim in the router is what knows the difference (#167).
    retry_num = headers.get("x-slack-retry-num")
    if retry_num is not None:
        logger.info(
            "Slack redelivery: bot=%s retry=%s reason=%s",
            bot_id,
            retry_num,
            headers.get("x-slack-retry-reason"),
        )

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    event = payload.get("event", {})
    if not event:
        return Response(status_code=200)
    if event.get("type") in SURFACE_EVENTS:
        spawn(process_slack_surface(payload, str(bot_id)), name=f"slack_surface:{bot_id}")
        return Response(status_code=200)

    incoming = adapter.parse_incoming(payload, str(bot_id))
    if incoming is None:
        return Response(status_code=200)

    spawn(process_channel_event(incoming), name=f"slack_event:{bot_id}")
    return Response(status_code=200)


@router.post("/{bot_id}/interactions", status_code=200, response_model=None)
async def slack_interactions(bot_id: UUID, request: Request, bot_service: ChannelBotSvc) -> Any:
    """Receive a button press or a message shortcut (#2067).

    Answered at once, like an event, with the work done in the background.
    """
    form = await verified_form(bot_id, request, bot_service)
    if form is None:
        return Response(status_code=200)
    payload: dict[str, Any] = json.loads(form.get("payload") or "{}")
    # The "what was wrong?" modal: an empty 200 is what closes it.
    comment = parse_feedback_comment(payload, str(bot_id))
    if comment is not None:
        spawn(process_feedback_comment(comment), name=f"slack_feedback:{bot_id}")
        return Response(status_code=200)
    press = parse_press(payload, str(bot_id))
    if press is not None:
        spawn(process_channel_press(press), name=f"slack_press:{bot_id}")
        return Response(status_code=200)
    shortcut = parse_shortcut(payload, str(bot_id))
    if shortcut is not None:
        spawn(process_channel_event(shortcut), name=f"slack_shortcut:{bot_id}")
    return Response(status_code=200)


@router.post("/{bot_id}/commands", status_code=200, response_model=None)
async def slack_commands(bot_id: UUID, request: Request, bot_service: ChannelBotSvc) -> Any:
    """Receive `/agent <question>`, answered in the channel it was typed in (#2067)."""
    form = await verified_form(bot_id, request, bot_service)
    if form is None:
        return Response(status_code=200)
    incoming = parse_command(form, str(bot_id))
    if incoming is None:
        return {"response_type": "ephemeral", "text": "Ask a question after `/agent`."}
    spawn(process_channel_event(incoming), name=f"slack_command:{bot_id}")
    return Response(status_code=200)

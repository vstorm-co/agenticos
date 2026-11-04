"""Microsoft Teams messaging endpoint (#1985).

The Azure Bot resource's messaging endpoint is this route. Every activity is
believed only after its Bot Connector token is: signed by a key its issuer
publishes, issued to this bot's app, unexpired, and for the service the activity
names (`teams_auth`). Anything that fails is a 401 before a field of the body is
used. The bot is single-tenant, so an activity from another tenant is refused
as well.

A message is answered at once and run in the background, as on every other
platform. A press on a card is an invoke, which Teams waits on: it is answered
with a short confirmation while the decision runs, and the card is replaced with
what was chosen when it lands.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import ChannelBotSvc
from app.core.background import spawn
from app.services.channel_bot import unseal_bot_token
from app.services.channels.teams import (
    chat_id_of,
    conversation_of,
    teams_adapter,
)
from app.services.channels.teams_auth import TeamsAuthError, TeamsCredentials, is_connector_url
from app.worker.background.channel import process_channel_event, process_channel_press

logger = logging.getLogger(__name__)

router = APIRouter()

PRESS_RECEIVED = {
    "statusCode": 200,
    "type": "application/vnd.microsoft.activity.message",
    "value": "Received.",
}
"""What a pressed card shows while the decision runs."""


@router.post("/{bot_id}/messages", status_code=200, response_model=None)
async def teams_messages(bot_id: UUID, request: Request, bot_service: ChannelBotSvc) -> Any:
    """Receive one activity from the Bot Connector."""
    bot = await bot_service.find_active(bot_id)
    if bot is None:
        # The Connector retries a failure; an unknown or disabled bot is nothing
        # it can fix, and a prober learns only that the route exists.
        return Response(status_code=200)
    if bot.platform != "teams" or not bot.teams_app_id or not bot.teams_tenant_id:
        raise HTTPException(status_code=403, detail="Not a Teams bot")

    activity: dict[str, Any] = await request.json()
    service_url = str(activity.get("serviceUrl") or "")
    adapter = teams_adapter()
    try:
        await adapter.auth.verify(
            request.headers.get("authorization"),
            app_id=bot.teams_app_id,
            tenant_id=bot.teams_tenant_id,
            service_url=service_url,
            channel_id=activity.get("channelId"),
        )
    except TeamsAuthError as refused:
        logger.warning("teams_activity_refused", extra={"bot_id": str(bot_id), "why": str(refused)})
        raise HTTPException(status_code=401, detail="Unauthorized") from None

    ref = conversation_of(activity)
    if ref is None or not is_connector_url(ref.service_url):
        raise HTTPException(status_code=400, detail="Not a Bot Connector activity")
    if ref.tenant_id and ref.tenant_id.lower() != bot.teams_tenant_id.lower():
        raise HTTPException(status_code=403, detail="This bot serves one tenant")

    await bot_service.record_teams_conversation(bot, ref)
    credentials = TeamsCredentials.decode(unseal_bot_token(bot))
    adapter.remember(str(bot_id), credentials, ref)

    kind = activity.get("type")
    if kind == "message":
        incoming = adapter.parse_incoming(activity, str(bot_id))
        if incoming is not None:
            spawn(process_channel_event(incoming), name=f"teams_event:{bot_id}")
        return Response(status_code=200)

    if kind == "invoke" and activity.get("name") == "adaptiveCard/action":
        press = adapter.parse_press(activity, str(bot_id))
        if press is None:
            return {"statusCode": 400, "type": "application/vnd.microsoft.error", "value": {}}
        spawn(process_channel_press(press), name=f"teams_press:{bot_id}")
        return PRESS_RECEIVED

    if kind == "invoke" and activity.get("name") == "fileConsent/invoke":
        chat_id = chat_id_of(activity)
        if chat_id is not None:
            spawn(
                adapter.complete_file_consent(credentials.encode(), activity, chat_id),
                name=f"teams_file:{bot_id}",
            )
        return {}

    # `conversationUpdate` and `installationUpdate`: the bot was added somewhere,
    # which the conversation record above already captured for later posts.
    return Response(status_code=200)

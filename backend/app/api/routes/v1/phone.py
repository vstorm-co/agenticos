"""Telephone consent, routes and receipts, plus signed Twilio-only provider entry points."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, WebSocket
from starlette.websockets import WebSocketState

from app.api.deps import Auth, DBSession, PhoneCallsSvc, PhonePolicySvc, PhoneWebhooksSvc, require
from app.core.exceptions import AppException
from app.core.permissions import Perm
from app.schemas.telephony import (
    PhoneCallCreate,
    PhoneCallRead,
    PhoneChoice,
    PhoneContactConfig,
    PhoneContactRead,
    PhoneEndpointConfig,
    PhoneEndpointRead,
    PhoneSettingsRead,
    PhoneTransfer,
)
from app.services.telephony import runtime
from app.services.telephony.webhooks import read_body

router = APIRouter()


@router.get("/settings", response_model=PhoneSettingsRead)
async def settings(ctx: Auth, service: PhonePolicySvc) -> Any:
    """Own contact policy and telephone routes; administrative choices require channels:manage."""
    return await service.settings(ctx)


@router.put("/contact", response_model=PhoneContactRead)
async def contact(data: PhoneContactConfig, ctx: Auth, service: PhonePolicySvc) -> Any:
    """Opt into calls, reports or transfers on the caller's already verified SMS identity."""
    return await service.set_contact(ctx, data)


@router.put(
    "/bots/{bot_id}",
    response_model=PhoneEndpointRead,
    dependencies=[Depends(require(Perm.CHANNELS_MANAGE))],
)
async def configure(
    bot_id: UUID, data: PhoneEndpointConfig, ctx: Auth, service: PhonePolicySvc
) -> Any:
    """Configure a Twilio number; inbound callers receive only a selected public voice exposure."""
    return await service.configure(ctx, bot_id, data)


@router.post("/calls", response_model=PhoneCallRead, status_code=202)
async def call(data: PhoneCallCreate, ctx: Auth, service: PhoneCallsSvc) -> Any:
    """Queue one idempotent call to the caller's opted-in, verified number."""
    return await service.create(ctx, data)


@router.get("/calls", response_model=list[PhoneCallRead])
async def calls(ctx: Auth, service: PhoneCallsSvc) -> Any:
    """Own call receipts; channel administrators can inspect their organization's routing receipts."""
    return await service.recent(ctx)


@router.get("/calls/{call_id}", response_model=PhoneCallRead)
async def receipt(call_id: UUID, ctx: Auth, service: PhoneCallsSvc) -> Any:
    """Read a call's state, estimated telephony cost and transcript link."""
    return await service.get(ctx, call_id)


@router.post("/calls/{call_id}/hangup", response_model=None, status_code=204)
async def hangup(call_id: UUID, ctx: Auth, db: DBSession) -> Any:
    """Cancel a queued intention or end the provider call without redialling it."""
    await runtime.hangup(db, ctx, call_id)


@router.get("/calls/{call_id}/transfer-options", response_model=list[PhoneChoice])
async def transfer_options(call_id: UUID, ctx: Auth, db: DBSession) -> Any:
    """Allowed, opted-in contacts currently able to receive this call; never phone numbers."""
    return await runtime.transfer_options(db, call_id, ctx=ctx)


@router.post("/calls/{call_id}/transfer", response_model=None, status_code=204)
async def transfer(call_id: UUID, data: PhoneTransfer, ctx: Auth, db: DBSession) -> Any:
    """Transfer an active call to an opted-in, allowlisted contact within the remaining cap."""
    await runtime.transfer(db, call_id, data.contact_id, ctx=ctx)


@router.post("/inbound/{endpoint_id}", response_class=Response, response_model=None)
async def inbound(endpoint_id: UUID, request: Request, service: PhoneWebhooksSvc) -> Any:
    """Twilio-signed inbound admission; caller ID is never member authentication."""
    twiml = await service.inbound(
        endpoint_id,
        await read_body(request.stream()),
        request.headers.get("x-twilio-signature", ""),
    )
    return Response(content=twiml, media_type="text/xml")


@router.post("/status/{call_id}", response_model=None, status_code=204)
async def status(call_id: UUID, request: Request, service: PhoneWebhooksSvc) -> Any:
    """Settle a signed, source-bound outbound receipt, including unknown submission outcomes."""
    await service.status(
        call_id, await read_body(request.stream()), request.headers.get("x-twilio-signature", "")
    )


@router.post("/inbound-status/{endpoint_id}", response_model=None, status_code=204)
async def inbound_status(endpoint_id: UUID, request: Request, service: PhoneWebhooksSvc) -> Any:
    """The stable status URL to configure beside a number's inbound voice URL in Twilio."""
    await service.inbound_status(
        endpoint_id,
        await read_body(request.stream()),
        request.headers.get("x-twilio-signature", ""),
    )


@router.websocket("/media/{call_id}")
async def media(call_id: UUID, websocket: WebSocket) -> None:
    """One signed, nonce- and receipt-bound Twilio Media Stream into the existing voice runtime."""
    try:
        await runtime.media(websocket, call_id)
    except AppException:
        if websocket.application_state != WebSocketState.DISCONNECTED:
            await websocket.close(code=1008)

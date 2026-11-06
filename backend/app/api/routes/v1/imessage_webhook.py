"""Authenticated incoming messages from an organization's BlueBubbles bridge."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response

from app.api.deps import ImessageWebhookSvc

router = APIRouter()


@router.post("/{bot_id}/webhook", status_code=200, response_model=None)
async def imessage_webhook(bot_id: UUID, request: Request, service: ImessageWebhookSvc) -> Any:
    """Accept a bounded, authenticated message and dispatch after transaction commit."""
    await service.receive(bot_id, request.headers.get("authorization", ""), request.stream())
    return Response(status_code=200)

"""Zalo OA webhook receiver (D3 B68)."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import ChannelBotSvc
from app.core.background import spawn
from app.core.config import settings
from app.services.channels import get_adapter
from app.worker.background.channel import process_channel_event

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{bot_id}/webhook", status_code=200, response_model=None)
async def zalo_webhook(
    bot_id: UUID,
    request: Request,
    bot_service: ChannelBotSvc,
) -> Response:
    adapter = get_adapter("zalo")
    raw_body = (await request.body()).decode("utf-8")
    headers: dict[str, str] = dict(request.headers)
    try:
        payload: dict[str, Any] = json.loads(raw_body) if raw_body.strip() else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None

    bot = await bot_service.find_active(bot_id)
    if bot is None:
        return Response(status_code=200)

    signature = headers.get("x-zevent-signature") or headers.get("X-ZEvent-Signature") or ""
    webhook_secret = (settings.ZALO_OA_WEBHOOK_SECRET or "").strip()
    app_secret = (settings.ZALO_OA_APP_SECRET or "").strip()
    verify_secrets: list[str] = []
    for candidate in (webhook_secret, app_secret):
        if candidate and candidate not in verify_secrets:
            verify_secrets.append(candidate)
    if signature:
        if not verify_secrets:
            raise HTTPException(
                status_code=403,
                detail=(
                    "ZALO_OA_WEBHOOK_SECRET not configured "
                    "(OA Secret Key in Zalo Developer → linked OA → Webhook)"
                ),
            )
        if webhook_secret and app_secret and webhook_secret == app_secret:
            logger.warning(
                "ZALO_OA_WEBHOOK_SECRET equals ZALO_OA_APP_SECRET — "
                "use OA Secret Key from linked OA Webhook page, not App Secret"
            )
        verified = any(
            adapter.verify_webhook_signature(headers, secret, body=raw_body)
            for secret in verify_secrets
        )
        if not verified:
            logger.warning(
                "Zalo webhook signature rejected bot=%s event=%s body_len=%d",
                bot_id,
                payload.get("event_name"),
                len(raw_body),
            )
            raise HTTPException(status_code=403, detail="Invalid Zalo webhook signature")

    incoming = adapter.parse_incoming(payload, str(bot_id))
    if incoming is None:
        return Response(status_code=200)

    spawn(process_channel_event(incoming), name=f"zalo_event:{bot_id}")
    return Response(status_code=200)

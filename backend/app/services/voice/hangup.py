"""Hanging up a call on the provider's side, from a `finally` or from the reaper (#54).

Closing our sideband leaves an OpenAI WebRTC call talking and billing, with no
tools and no governance (spike, live result 2). `POST /v1/realtime/calls/{id}/hangup`
ends it; 404 means it already ended or was never ours. It needs only the call id
and the key, so the reaper can do it for a process that died.

A relay call (Gemini, xAI, Azure) is our own upstream socket: when the session
exits, the provider ends the call (provider docs). Not verified live.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import openai
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_kinds import ApiKeySecret, StorableSecret
from app.db.models.voice_call import VoiceCall
from app.services.organization_secret import OrganizationSecretService

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class HangUpTarget:
    """What a hang-up needs, and nothing of the session: so the reaper can build one."""

    transport: str
    provider: str
    provider_call_id: str | None
    secret: StorableSecret | None


async def hang_up(target: HangUpTarget) -> bool:
    """End the call at the provider. `True` when it no longer holds the call."""
    if target.transport == "relay" or target.provider_call_id is None:
        return True
    if not isinstance(target.secret, ApiKeySecret):
        logger.warning("voice_hangup_no_key", extra={"provider": target.provider})
        return False
    client = AsyncOpenAI(
        api_key=target.secret.api_key.get_secret_value(), timeout=_TIMEOUT_SECONDS, max_retries=1
    )
    try:
        await client.realtime.calls.hangup(target.provider_call_id)
    except openai.NotFoundError:
        return True
    except openai.OpenAIError:
        # The client's text names the request URL; the log line says what failed, not that.
        logger.warning("voice_hangup_failed", extra={"provider": target.provider}, exc_info=True)
        return False
    else:
        return True
    finally:
        await client.close()


async def hang_up_row(db: AsyncSession, row: VoiceCall) -> bool:
    """Hang up a call from its row alone: the reaper's path, and a reconnect's for a
    connection another worker still holds (Task 17). The key is unsealed only to be
    handed to the provider's hang-up endpoint."""
    secret = (
        None
        if row.secret_id is None
        else await OrganizationSecretService(db).voice_call_key(row.organization_id, row.secret_id)
    )
    return await hang_up(
        HangUpTarget(
            transport=row.transport,
            provider=row.provider,
            provider_call_id=row.provider_call_id,
            secret=secret,
        )
    )

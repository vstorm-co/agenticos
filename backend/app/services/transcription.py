"""Turning a voice note into text, on the organization's own credential.

A voice message is the one attachment an agent cannot be handed as a file: a
model reads a PDF and looks at a screenshot, and an `audio/ogg` blob is a byte
count. So a bot that receives one has three options - ignore it, tell the sender
it cannot listen, or transcribe it. This is the third.

**Where the credential comes from, and why not a new one.** Transcription happens
to a voice note before an agent is involved, so there is no spec to seal a key
into. It runs instead on the model profile the organization already configured for
that provider, resolved through `ModelProfileService.resolve_credential` - the one
place that knows how the vault and the legacy credential store join. Choosing
"OpenAI" for transcription on a bot therefore needs nothing new configured, and
there is no second place a key can be wrong.

**One API shape.** Every catalogued provider serves OpenAI's
`POST /audio/transcriptions`: multipart in, `{"text": ...}` out. That is what
makes three providers one client. The shape is declared per entry in the catalog
rather than assumed here, so a provider whose only route to audio is a chat call
arrives as another branch instead of a name check in the middle of this.

**A failure here is never a failure of the turn.** The caller gets `None` and
answers without the transcript, saying so - a bot that goes silent because a
transcription provider was rate-limited is worse than one that says it could not
listen to this particular message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_kinds import ApiKeySecret
from app.repositories import credential as credential_repo
from app.services import speech_to_text
from app.services.model_profile import ModelProfileService

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 60.0
"""How long one transcription may take.

A voice note is short and the providers here are fast, but a cold model on a busy
endpoint is not - and this sits in front of an answer somebody is waiting for in a
chat window, where the alternative to a slow reply is no reply.
"""

MAX_BYTES = 25 * 1024 * 1024
"""What the endpoint accepts, which is smaller than what a chat platform sends.

Refused before the upload rather than after it: a 25 MB POST that comes back 413
has spent the time twice.
"""


@dataclass(frozen=True)
class Recording:
    """A voice note, in hand."""

    content: bytes
    filename: str
    mime_type: str


class TranscriptionService:
    """Transcribes a recording with the model a bot was configured with."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def transcribe(
        self,
        recording: Recording,
        *,
        organization_id: UUID,
        provider: str,
        model: str,
    ) -> str | None:
        """The words in this recording, or `None` where it could not be read.

        `None` rather than an exception for every reason: no such provider, no
        credential configured for it, a recording too large, a refusal from the
        endpoint, a timeout. Each is logged with what actually happened, and the
        caller answers without the transcript - the sender is told the bot could
        not listen to this message, which beats a bot that goes quiet.
        """
        entry = speech_to_text.by_provider(provider)
        if entry is None or not speech_to_text.is_offered(provider, model):
            logger.warning(
                "Transcription asked for a model that is not offered: %s/%s", provider, model
            )
            return None

        if len(recording.content) > MAX_BYTES:
            logger.info(
                "Recording of %d bytes is over the transcription limit", len(recording.content)
            )
            return None

        key, base_url = await self._credential(organization_id, provider)
        if key is None:
            logger.warning("No %s credential in this organization to transcribe with", provider)
            return None

        return await self._post(
            recording, base_url=base_url or entry.base_url, api_key=key, model=model
        )

    async def _credential(
        self, organization_id: UUID, provider: str
    ) -> tuple[str | None, str | None]:
        """This organization's key for one provider, and its endpoint if it set one.

        Any profile on that provider will do, and the first with a resolvable
        credential wins: a profile is "the organization's OpenAI", and holding two
        of them is about chat models rather than about which key transcribes. A
        profile whose secret was deleted is skipped rather than fatal, because the
        next one may be fine and refusing on the first would make transcription
        depend on row order.
        """
        profiles = [
            profile
            for profile in await credential_repo.list_profiles(
                self.db, organization_id=organization_id
            )
            if profile.provider == provider
        ]
        service = ModelProfileService(self.db)
        for profile in profiles:
            try:
                resolved = await service.resolve_credential(organization_id, profile)
            except Exception:
                logger.info(
                    "Skipping model profile %s while looking for a %s key",
                    profile.id,
                    provider,
                    exc_info=True,
                )
                continue
            if isinstance(resolved.secret, ApiKeySecret):
                return resolved.secret.api_key.get_secret_value(), resolved.base_url
        return None, None

    @staticmethod
    async def _post(recording: Recording, *, base_url: str, api_key: str, model: str) -> str | None:
        """`POST /audio/transcriptions`, as OpenAI defined it.

        The provider's own error text is logged and never returned: this string
        reaches a chat as part of an answer, and a provider client puts the failing
        request URL - key in the query string - in its message.
        """
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    data={"model": model},
                    files={"file": (recording.filename, recording.content, recording.mime_type)},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception:
            logger.warning("Transcription request failed for model %s", model, exc_info=True)
            return None

        text = str(payload.get("text") or "").strip() if isinstance(payload, dict) else ""
        if not text:
            logger.info("Transcription for model %s came back empty", model)
            return None
        return text

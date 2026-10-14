"""Turning a voice note into text, on the organization's own credential.

A voice message is the one attachment an agent cannot be handed as a file: a
model reads a PDF and looks at a screenshot, and an `audio/ogg` blob is a byte
count. So a bot that receives one has three options - ignore it, tell the sender
it cannot listen, or transcribe it. This is the third.

**Where the credential comes from, and why not a new one.** Transcription happens
to a voice note before an agent is involved, so there is no spec to seal a key
into. It runs instead on the model profile the organization already configured for
that provider, resolved through `ModelProfileService.resolve_credential` - the one
place that knows how the vault and the legacy credential store join. Failing a
profile, an organization-visible vault key stored for that provider will do
(#1797): an organization that keeps an OpenAI key and runs no OpenAI chat model
should not have to invent one to transcribe. Choosing "OpenAI" for transcription
therefore needs nothing new configured, and the deployment's own environment key
is never used.

**One API shape.** Every catalogued provider serves OpenAI's
`POST /audio/transcriptions`: multipart in, `{"text": ...}` out. That is what
makes three providers one client. The shape is declared per entry in the catalog
rather than assumed here, so a provider whose only route to audio is a chat call
arrives as another branch instead of a name check in the middle of this.

**A failure raises, and says why.** Every refusal is a domain exception carrying
`details.reason` - `not_configured`, `too_large`, `empty`, `provider_error`,
`timeout` - and never the provider's own text. The channel router turns any of
them into its per-recording "could not be transcribed" line, so a bot still
answers without the transcript rather than going silent; the ML facade records
them in the usage log and hands them to the caller, so the composer can say what
went wrong.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.model_resolver import get_provider
from app.core.exceptions import BadRequestError, ConfigurationError, ExternalServiceError
from app.core.secret_kinds import ApiKeySecret, NoSecret
from app.db.models.credential import ModelProfile
from app.repositories import credential as credential_repo
from app.services import speech_to_text
from app.services.model_profile import ModelProfileService
from app.services.organization_secret import OrganizationSecretService

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


RECORDING_EXTENSIONS: dict[str, str] = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
}
"""The extension a provider is sent for each recording type.

OpenAI and Groq read the format from the file name, not from the part's
content type, so the name is chosen from the type rather than passed through:
a Telegram voice note arrives named `audio`, a Slack clip may say `.mp4`, and
`.opus` or `.aac` is a name the endpoint refuses for audio it would have
read. MP4 audio goes as `.m4a`, the name OpenAI, Groq and Mistral all list.
Shared by composer dictation and channel voice notes, so the two cannot
disagree about what a type is called.
"""

RECORDING_TYPE_ALIASES: dict[str, str] = {
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/x-m4a": "audio/mp4",
    "audio/m4a": "audio/mp4",
    "audio/opus": "audio/ogg",
    "audio/x-ogg": "audio/ogg",
    "audio/mp3": "audio/mpeg",
}
"""Other names clients and platforms use for the same containers."""


def recording_type(mime_type: str) -> str:
    """A recording's type without parameters, in the spelling `RECORDING_EXTENSIONS` uses.

    `audio/webm;codecs=opus` is `audio/webm`, `Audio/X-WAV` is `audio/wav`. A
    type nobody aliased is returned lowercased and otherwise as given.
    """
    base = mime_type.split(";", 1)[0].strip().lower()
    return RECORDING_TYPE_ALIASES.get(base, base)


@dataclass(frozen=True)
class Recording:
    """A voice note, in hand."""

    content: bytes
    filename: str
    mime_type: str


@dataclass(frozen=True)
class TranscriptionResult:
    """What was said, and how long the recording was where the provider says."""

    text: str
    audio_seconds: float | None
    """The provider's own figure (`audio_seconds_of`), or `None` where its answer
    carries none - `gpt-4o(-mini)-transcribe` reports tokens, not seconds. A
    caller with a figure of its own (platform metadata, the browser's clock)
    falls back to it; nothing here decodes the audio to measure it."""


def audio_seconds_of(payload: dict[str, object]) -> float | None:
    """The recording's length in an `/audio/transcriptions` answer, if it states one.

    Three shapes, in the order they are trusted:

    - OpenAI bills `whisper-1` by duration and says so: `usage.type ==
      "duration"` with `usage.seconds`. Its `gpt-4o-*` models answer
      `usage.type == "tokens"`, which is not a length and is not read as one.
    - Mistral answers `usage.prompt_audio_seconds`.
    - Groq answers a top-level `duration`, in `verbose_json` only - which is why
      its catalog entry asks for that format (`SpeechToTextEntry.response_format`).

    A value that is not a positive number - absent, a string, a boolean, zero -
    is no figure at all rather than a recording of no length.
    """
    usage = payload.get("usage")
    candidates: list[object] = []
    if isinstance(usage, dict):
        if usage.get("type") == "duration":
            candidates.append(usage.get("seconds"))
        candidates.append(usage.get("prompt_audio_seconds"))
    candidates.append(payload.get("duration"))
    for value in candidates:
        if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
            return float(value)
    return None


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
        language: str | None = None,
    ) -> TranscriptionResult:
        """The words in this recording, and its length where the provider states it.

        `language` is an ISO-639-1 code to pin the recording to; `None` leaves the
        engine to detect it.

        Raises:
            ConfigurationError: `reason="not_configured"` - the pair is not offered, or
                this organization has no usable profile for the provider.
            BadRequestError: `reason="too_large"` over `MAX_BYTES`, or `reason="empty"`
                when the engine heard nothing.
            ExternalServiceError: `reason="timeout"` or `reason="provider_error"`. The
                provider's own text stays in the log: a provider client puts the
                request URL, key and all, in its message.
        """
        context = {"provider": provider, "model": model}
        entry = speech_to_text.by_provider(provider)
        if entry is None or not speech_to_text.is_offered(provider, model):
            logger.warning(
                "Transcription asked for a model that is not offered: %s/%s", provider, model
            )
            raise ConfigurationError(
                message=f"{provider} does not offer {model} for transcription here.",
                details={"reason": "not_configured", **context},
            )

        if len(recording.content) > MAX_BYTES:
            logger.info(
                "Recording of %d bytes is over the transcription limit", len(recording.content)
            )
            raise BadRequestError(
                message="The recording is larger than transcription accepts.",
                details={"reason": "too_large", "limit_bytes": MAX_BYTES, **context},
            )

        endpoint = await self._credential(organization_id, provider)
        if endpoint is None:
            logger.warning("No %s credential in this organization to transcribe with", provider)
            raise ConfigurationError(
                message=f"This organization has no {provider} credentials to transcribe with.",
                details={"reason": "not_configured", **context},
            )
        api_key, base_url = endpoint
        return await self._post(
            recording,
            base_url=base_url or entry.base_url,
            api_key=api_key,
            model=model,
            language=language,
            response_format=entry.response_format,
            context=context,
        )

    async def _credential(
        self, organization_id: UUID, provider: str
    ) -> tuple[str | None, str | None] | None:
        """`(api_key, base_url)` for one provider, or `None` when there is none.

        A keyed profile first, in label order, then a keyless one, and an
        organization-visible vault key for the provider last - sent to the
        catalog's address, since a vault key carries none of its own. That
        last fallback reads organization-visible keys only, because the call is
        paid on everybody's behalf (`OrganizationSecretService.transcription_key`);
        a model profile is taken as configured, so one pointing at a member's
        private key transcribes on it, as a chat run on that profile would
        spend it. Keyed first is what keeps a bot that
        transcribes on OpenAI today on OpenAI once a keyless `openai` profile - a
        vLLM or LiteLLM proxy for chat, with no `/audio/transcriptions` - is added
        and happens to sort earlier. A keyless profile counts only with an address
        of its own, and returns `api_key=None`: the request then carries no
        `Authorization` header at all, and never the deployment's environment key.

        A profile whose secret was deleted is skipped rather than fatal, because
        the next one may be fine and refusing on the first would make
        transcription depend on row order.
        """
        profiles = [
            profile
            for profile in await credential_repo.list_profiles(
                self.db, organization_id=organization_id
            )
            if profile.provider == provider
        ]
        service = ModelProfileService(self.db)
        keyless: tuple[str | None, str | None] | None = None
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
            if keyless is None and isinstance(resolved.secret, NoSecret) and resolved.base_url:
                keyless = (None, resolved.base_url)
        if keyless is not None:
            return keyless
        key = await OrganizationSecretService(self.db).transcription_key(organization_id, provider)
        return None if key is None else (key, None)

    async def credentialed_providers(self, organization_id: UUID) -> frozenset[str]:
        """Which catalogued providers this organization could transcribe on.

        The same three sources `_credential` tries, read for existence and never
        unsealed: a profile with a key, a keyless profile with an address, or an
        organization-visible vault key. So a picker can grey out a provider
        without a plaintext leaving the vault, and without the reader holding
        `secrets:view` - a Builder choosing an agent's engine may not.

        "Has one", not "it works": a key revoked at the provider is still found
        here, and is reported when a recording arrives as `provider_error`.
        """
        offered = {entry.provider for entry in speech_to_text.providers()}
        found = {
            profile.provider
            for profile in await credential_repo.list_profiles(
                self.db, organization_id=organization_id
            )
            if profile.provider in offered
            and (profile.secret_id is not None or self._keyless_with_address(profile))
        }
        found |= await OrganizationSecretService(self.db).transcription_key_providers(
            organization_id, sorted(offered - found)
        )
        return frozenset(found)

    @staticmethod
    def _keyless_with_address(profile: ModelProfile) -> bool:
        """A self-hosted profile `resolve_credential` would answer with no key."""
        return get_provider(profile.provider).keyless and bool(profile.base_url)

    @staticmethod
    async def _post(
        recording: Recording,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        language: str | None,
        response_format: str | None,
        context: dict[str, str],
    ) -> TranscriptionResult:
        """`POST /audio/transcriptions`, as OpenAI defined it.

        The provider's own error text is logged and never raised: it reaches a
        chat or a composer as part of an answer, and a provider client puts the
        failing request URL - key in the query string - in its message.
        """
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        data = {"model": model}
        if language is not None:
            data["language"] = language
        if response_format is not None:
            data["response_format"] = response_format
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/audio/transcriptions",
                    headers=headers,
                    data=data,
                    files={"file": (recording.filename, recording.content, recording.mime_type)},
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            logger.warning("Transcription timed out for model %s", model, exc_info=True)
            raise ExternalServiceError(
                message="The transcription provider did not answer in time.",
                details={"reason": "timeout", "stage": "engine", **context},
            ) from exc
        except Exception as exc:
            logger.warning("Transcription request failed for model %s", model, exc_info=True)
            raise ExternalServiceError(
                message="The transcription provider refused or failed the request.",
                details={"reason": "provider_error", "stage": "engine", **context},
            ) from exc

        text = str(payload.get("text") or "").strip() if isinstance(payload, dict) else ""
        if not text:
            logger.info("Transcription for model %s came back empty", model)
            raise BadRequestError(
                message="No speech was heard in the recording.",
                details={"reason": "empty", "stage": "engine", **context},
            )
        # A dict, or `text` above would have been empty and refused.
        return TranscriptionResult(text=text, audio_seconds=audio_seconds_of(payload))

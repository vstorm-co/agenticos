"""Turning a voice note into text, on the key named for it.

A voice message is the one attachment an agent cannot be handed as a file: a
model reads a PDF and looks at a screenshot, and an `audio/ogg` blob is a byte
count. So a bot that receives one has three options - ignore it, tell the sender
it cannot listen, or transcribe it. This is the third.

**Which key, and why it is never chosen here.** The key is named next to the
pair, wherever the pair was chosen - the organization's default, an agent's
override, a channel bot's own - and arrives here as a `secret_id`
(`speech_to_text_settings`). This only opens it: no model profile is scanned
and no vault key is looked up by provider, because with two keys for one
provider either lookup is a guess about who pays. A key that is gone, is for
another provider, or - where the platform spends it for everybody - is no
longer organization-visible, is refused as `not_configured`. The deployment's
own environment key is never used.

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

import logging
from dataclasses import dataclass
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConfigurationError, ExternalServiceError
from app.services import speech_to_text
from app.services.organization_secret import OrganizationSecretService
from app.services.speech_to_text import LanguageField

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
        secret_id: UUID | None,
        shared_key: bool,
        language: str | None = None,
    ) -> TranscriptionResult:
        """The words in this recording, and its length where the provider states it.

        `secret_id` is the vault key named next to the pair, and `shared_key`
        whether it is spent on everybody's behalf (`ResolvedSpeechToText.shared_key`),
        which then requires it to be organization-visible. `language` is an
        ISO-639-1 code to pin the recording to; `None` leaves the engine to
        detect it.

        Raises:
            ConfigurationError: `reason="not_configured"` - the pair is not offered,
                no key is named, or the named key is not usable for the provider.
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

        api_key = (
            None
            if secret_id is None
            else await OrganizationSecretService(self.db).transcription_key(
                organization_id, secret_id, provider=provider, shared=shared_key
            )
        )
        if api_key is None:
            logger.warning("No usable %s key is named to transcribe with", provider)
            raise ConfigurationError(
                message=f"No usable {provider} key is chosen for transcription here.",
                details={"reason": "not_configured", **context},
            )
        # `is_offered` above found it.
        offered = next(candidate for candidate in entry.models if candidate.id == model)
        return await self._post(
            recording,
            base_url=entry.base_url,
            api_key=api_key,
            model=model,
            language=language,
            language_field=offered.language_field,
            response_format=entry.response_format,
            context=context,
        )

    async def has_key(
        self, organization_id: UUID, *, provider: str, secret_id: UUID | None, shared_key: bool
    ) -> bool:
        """Whether `transcribe` would find the named key usable - read, never opened.

        So a readiness check can say "choose a key" without a plaintext leaving
        the vault. "Usable", not "works": a key revoked at the provider is still
        found here, and is reported when a recording arrives as `provider_error`.
        """
        if secret_id is None:
            return False
        row = await OrganizationSecretService(self.db).usable_transcription_key(
            organization_id, secret_id, provider=provider, shared=shared_key
        )
        return row is not None

    @staticmethod
    async def _post(
        recording: Recording,
        *,
        base_url: str,
        api_key: str,
        model: str,
        language: str | None,
        language_field: LanguageField,
        response_format: str | None,
        context: dict[str, str],
    ) -> TranscriptionResult:
        """`POST /audio/transcriptions`, as OpenAI defined it.

        The provider's own error text is logged and never raised: it reaches a
        chat or a composer as part of an answer, and a provider client puts the
        failing request URL - key in the query string - in its message.
        """
        headers = {"Authorization": f"Bearer {api_key}"}
        data = {"model": model}
        if language is not None:
            # A list field, form-encoded the way OpenAI's own clients send one.
            data["languages[]" if language_field == "languages" else "language"] = language
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

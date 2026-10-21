"""Hear a voice before publishing it (#54): a few seconds of the realtime model speaking.

The Builder's Voice card plays this beside the voice it offers. What is heard is
the draft's section - provider, model or Azure deployment, key, voice, language -
so a choice is judged before anybody calls the agent. The sentence is one of a
fixed set, one per console language, and never the caller's text: this speaks a
sample, it is not a text-to-speech service.

Like a dictation it is a paid call on the organization's own provider account,
outside every model budget, so it is rate limited per person and its audio is
cached per organization, provider, model, voice and language: listening to the
same voice again costs nothing.
"""

import base64
import io
import logging
import wave
from collections.abc import Awaitable, Callable
from typing import Literal
from uuid import UUID

import anyio
from pydantic_ai import Agent
from pydantic_ai.realtime import RealtimeModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.realtime import build_realtime_model, realtime_settings
from app.agents.spec import VoiceSpec
from app.clients.redis import RedisClient
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.services import provider_keys, realtime_models, speech_to_text
from app.services.organization_secret import OrganizationSecretService
from app.services.voice.settings import resolve_voice

logger = logging.getLogger(__name__)

PreviewLocale = Literal["en", "pl", "de"]

PREVIEW_LINES: dict[PreviewLocale, str] = {
    "en": "Hi, this is how I sound. Ask me anything, and I'll answer out loud.",
    "pl": "Cześć, tak brzmi mój głos. Zapytaj mnie o cokolwiek, a odpowiem na głos.",
    "de": "Hallo, so klingt meine Stimme. Frag mich etwas, und ich antworte laut.",
}

CACHE_SECONDS = 7 * 24 * 3600
"""A voice does not change from one day to the next; a week keeps the cache small."""

PREVIEW_TIMEOUT_SECONDS = 20.0
"""Connecting and speaking one sentence takes a few seconds; past this the provider is not answering."""

_INSTRUCTIONS = (
    "You are previewing your own voice. When you are given a sentence, say it exactly "
    "as written, once, in its language, and say nothing else."
)

Speak = Callable[[RealtimeModel, str], Awaitable[tuple[bytes, int]]]
"""Speak one line on a realtime model: its PCM16 mono audio and the sample rate."""


async def speak_line(model: RealtimeModel, line: str) -> tuple[bytes, int]:
    """Open a session, ask for `line` and collect the audio until it has all played out."""
    async with Agent(instructions=_INSTRUCTIONS).realtime(model).session() as session:
        audio = session.stream_audio()
        chunks: list[bytes] = []

        async def collect() -> None:
            async for chunk in audio:
                chunks.append(chunk)

        async with anyio.create_task_group() as group:
            group.start_soon(collect)
            await session.send(f"Say exactly: {line}")
            await session.wait_for_reply()
            await session.wait_for_playback()
            group.cancel_scope.cancel()
        return b"".join(chunks), session.audio_output_sample_rate


def as_wav(pcm: bytes, *, sample_rate: int) -> bytes:
    """PCM16 mono as a WAV file a browser's `<audio>` plays."""
    out = io.BytesIO()
    with wave.open(out, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(sample_rate)
        file.writeframes(pcm)
    return out.getvalue()


class VoicePreviewService:
    """A sample of a draft Voice section's voice, as WAV."""

    def __init__(self, db: AsyncSession, redis: RedisClient, *, speak: Speak = speak_line) -> None:
        self.db = db
        self.redis = redis
        self._speak = speak

    async def preview(self, ctx: AuthContext, block: VoiceSpec, *, locale: PreviewLocale) -> bytes:
        """The voice saying the preview sentence.

        In the section's own language where a sentence is written in it, and in
        the console's (`locale`) otherwise.

        Raises:
            BadRequestError: The section names no provider, model or key yet, a
                model the catalog does not offer, a language calls do not
                accept, or a key the caller cannot use for it (`details.fields`).
            ExternalServiceError: The provider refused, sent no audio, or did not
                answer in time (`details.reason`: `provider_error` or `timeout`).
        """
        resolved = resolve_voice(block)
        provider = realtime_models.by_provider(block.provider) if block.provider else None
        if resolved is None or provider is None:
            raise BadRequestError(
                message="Choose a provider, a model and a key before listening to a voice.",
                details={"reason": "incomplete"},
            )
        language = resolved.language or locale
        said: PreviewLocale = _preview_locale(language) or locale
        if language not in speech_to_text.LANGUAGES:
            raise refused_field("language", f"'{language}' is not a language calls accept")
        problem = await provider_keys.key_problem(
            self.db,
            resolved.secret_id,
            organization_id=ctx.organization_id,
            provider=resolved.provider,
            kind=provider.secret_kind,
            feature="voice conversations",
            ctx=ctx,
        )
        if problem is not None:
            raise refused_field("secret_id", problem)

        key = _cache_key(
            ctx.organization_id,
            resolved.provider,
            resolved.wire_model,
            resolved.voice,
            language,
            said,
        )
        cached = await self.redis.get(key)
        if cached is not None:
            return base64.b64decode(cached)

        secrets = await OrganizationSecretService(self.db).resolve_for_bindings(
            ctx, [resolved.secret_id]
        )
        secret = secrets.get(resolved.secret_id)
        if secret is None:
            raise refused_field("secret_id", "That key is not in this organization's vault")
        model = build_realtime_model(
            provider=resolved.provider,
            model=resolved.wire_model,
            secret=secret,
            settings=realtime_settings(
                provider=resolved.provider,
                voice=resolved.voice,
                language=language,
                thinking=None,
                supports_thinking=False,
            ),
        )
        context = {"provider": resolved.provider, "model": resolved.model}
        try:
            with anyio.fail_after(PREVIEW_TIMEOUT_SECONDS):
                pcm, rate = await self._speak(model, PREVIEW_LINES[said])
        except TimeoutError as exc:
            raise ExternalServiceError(
                message="The voice provider did not answer in time.",
                details={"reason": "timeout", **context},
            ) from exc
        except Exception as exc:
            logger.warning("voice_preview_failed", extra=context, exc_info=True)
            raise ExternalServiceError(
                message="The voice provider refused or failed the preview.",
                details={"reason": "provider_error", **context},
            ) from exc
        if not pcm:
            raise ExternalServiceError(
                message="The voice provider sent no audio.",
                details={"reason": "provider_error", **context},
            )
        audio = as_wav(pcm, sample_rate=rate)
        await self.redis.set(key, base64.b64encode(audio).decode("ascii"), ttl=CACHE_SECONDS)
        return audio


def _preview_locale(language: str) -> PreviewLocale | None:
    for locale in PREVIEW_LINES:
        if locale == language:
            return locale
    return None


def _cache_key(
    organization_id: UUID, provider: str, model: str, voice: str, language: str, said: str
) -> str:
    return f"voice-preview:{organization_id}:{provider}:{model}:{voice}:{language}:{said}"

"""One function per API shape, each turning one piece of text into audio bytes.

Every client returns either MP3 or raw PCM - 16-bit signed little-endian, mono,
24 kHz - and nothing else. Those are the two encodings every provider here can
produce *and* that can be joined: MP3 frames concatenate, and PCM concatenates
before a single WAV header is written around it. That is what lets a text longer
than one request be spoken as one clip (:mod:`.synthesis`).

The key travels in a header and only there. Of a provider's error only its code
is logged (`provider_error_code.py`); the body is neither logged nor put in the
exception: it is not text this repository controls, and it reaches a chat.
"""

import base64
import binascii
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import quote

import httpx

from app.services.provider_error_code import error_code
from app.services.text_to_speech.exceptions import SpeechFailure, SpeechProviderError

logger = logging.getLogger(__name__)

Encoding = Literal["mp3", "pcm"]

SAMPLE_RATE = 24_000
"""The PCM rate every provider is asked for, so their pieces join without resampling."""


@dataclass(frozen=True)
class SpeechCall:
    """One request's worth of speech, already within the model's limit."""

    provider: str
    base_url: str
    # A dataclass repr ends up in log lines and traceback frames.
    api_key: str = field(repr=False)
    model: str
    voice: str
    text: str
    encoding: Encoding
    instructions: str | None = None


Client = Callable[[httpx.AsyncClient, SpeechCall], Awaitable[bytes]]


_KEY_REFUSED = "api_key_invalid"
"""Google's reason for a bad key, which it answers 400 rather than 401."""

_QUOTA_SPENT = "quota_exceeded"
"""ElevenLabs' reason for a spent quota, which it answers 401 rather than 429."""

_VOICE_MISSING = "voice_not_found"
"""ElevenLabs' reason for a voice the account no longer has, which it answers 400."""


def _failure_for(status: int, body: str) -> SpeechFailure:
    """What kind of failure this was, from the status and the provider's reason.

    The reason is read and never repeated: Gemini answers a bad key with 400 and
    ElevenLabs a spent quota with 401, so the status alone would tell the model to
    rephrase text that was fine and the operator to replace a key that works.
    """
    lowered = body.lower()
    if _KEY_REFUSED in lowered:
        return SpeechFailure.CREDENTIALS
    if status == 429 or _QUOTA_SPENT in lowered:
        return SpeechFailure.RATE_LIMITED
    if status == 404 or _VOICE_MISSING in lowered:
        return SpeechFailure.NOT_FOUND
    if status in (401, 402, 403):
        # 402 is a plan the account lacks: the key's owner has to act, as for a
        # refused key, and no rewording of the text will help.
        return SpeechFailure.CREDENTIALS
    if status == 408:
        return SpeechFailure.UNAVAILABLE
    if 400 <= status < 500:
        return SpeechFailure.REJECTED
    return SpeechFailure.UNAVAILABLE


def _raise_for(call: SpeechCall, response: httpx.Response) -> None:
    """Refuse a non-2xx answer, logging only the provider's error code."""
    if response.is_success:
        return
    body = response.text
    logger.warning(
        "Speech request to %s for model %s failed (%s): %s",
        call.provider,
        call.model,
        response.status_code,
        error_code(body) or "no error code",
    )
    raise SpeechProviderError(
        _failure_for(response.status_code, body),
        provider=call.provider,
        status=response.status_code,
    )


def _audio(call: SpeechCall, data: bytes) -> bytes:
    """The audio a provider answered with, refusing what cannot be a clip.

    An empty body is a clip of nothing that would be stored and billed as one, and
    an odd number of PCM bytes would shift every later sample of the joined WAV
    by one byte - noise from that piece on.
    """
    if not data or (call.encoding == "pcm" and len(data) % 2):
        logger.warning(
            "Speech answer from %s for model %s was not audio", call.provider, call.model
        )
        raise SpeechProviderError(SpeechFailure.UNAVAILABLE, provider=call.provider)
    return data


async def openai_speech(client: httpx.AsyncClient, call: SpeechCall) -> bytes:
    """`POST /audio/speech`: JSON in, the audio file out."""
    body: dict[str, str] = {
        "model": call.model,
        "input": call.text,
        "voice": call.voice,
        "response_format": call.encoding,
    }
    if call.instructions:
        body["instructions"] = call.instructions
    response = await client.post(
        f"{call.base_url}/audio/speech",
        headers={"Authorization": f"Bearer {call.api_key}"},
        json=body,
    )
    _raise_for(call, response)
    return _audio(call, response.content)


async def elevenlabs(client: httpx.AsyncClient, call: SpeechCall) -> bytes:
    """`POST /text-to-speech/{voice_id}`: the format is a query parameter.

    The voice id goes in the path, so it is encoded as a path segment - it comes
    from a binding's configuration, and a slash in it must not reach another
    endpoint of the account.
    """
    output_format = "mp3_44100_128" if call.encoding == "mp3" else f"pcm_{SAMPLE_RATE}"
    response = await client.post(
        f"{call.base_url}/text-to-speech/{quote(call.voice, safe='')}",
        params={"output_format": output_format},
        headers={"xi-api-key": call.api_key},
        json={"text": call.text, "model_id": call.model},
    )
    _raise_for(call, response)
    return _audio(call, response.content)


async def gemini_interactions(client: httpx.AsyncClient, call: SpeechCall) -> bytes:
    """`POST /interactions` with an audio response, the audio base64 in the steps.

    MP3 is not among the formats Gemini returns, so it is asked for raw PCM and
    the catalog offers it only as WAV. A direction on how to speak travels as the
    text's `speech_metadata` annotation, which is where Gemini reads a style.
    """
    text_part: dict[str, object] = {"type": "text", "text": call.text}
    if call.instructions:
        text_part["annotations"] = [{"type": "speech_metadata", "style": call.instructions}]
    response = await client.post(
        f"{call.base_url}/interactions",
        headers={"x-goog-api-key": call.api_key},
        json={
            "model": call.model,
            "input": [{"type": "user_input", "content": [text_part]}],
            "response_format": {
                "type": "audio",
                "mime_type": "audio/l16",
                "sample_rate": SAMPLE_RATE,
            },
            "generation_config": {"speech_config": [{"voice": call.voice}]},
        },
    )
    _raise_for(call, response)
    return _gemini_audio(call, response)


def _gemini_audio(call: SpeechCall, response: httpx.Response) -> bytes:
    """The last audio block of the model's output, decoded."""
    try:
        payload = response.json()
        blocks = [
            content["data"]
            for step in payload.get("steps", [])
            if step.get("type") == "model_output"
            for content in step.get("content", [])
            if content.get("type") == "audio"
        ]
        audio = base64.b64decode(blocks[-1], validate=True)
    except ValueError, KeyError, IndexError, AttributeError, TypeError, binascii.Error:
        logger.warning("Gemini returned no audio for model %s", call.model, exc_info=True)
        raise SpeechProviderError(SpeechFailure.UNAVAILABLE, provider=call.provider) from None
    return _audio(call, audio)


CLIENTS: dict[str, Client] = {
    "openai_speech": openai_speech,
    "elevenlabs": elevenlabs,
    "gemini_interactions": gemini_interactions,
}
"""The client for each API shape the catalog may name."""

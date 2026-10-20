"""One function per API shape, each turning one piece of text into audio bytes.

Every client returns either MP3 or raw PCM - 16-bit signed little-endian, mono,
24 kHz - and nothing else. Those are the two encodings every provider here can
produce *and* that can be joined: MP3 frames concatenate, and PCM concatenates
before a single WAV header is written around it. That is what lets a text longer
than one request be spoken as one clip (:mod:`.synthesis`).

The key travels in a header and only there. A provider's response body is logged
at the point it is received and is never put in the exception: it is not text this
repository controls, and it reaches a chat.
"""

from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import httpx

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
    api_key: str
    model: str
    voice: str
    text: str
    encoding: Encoding
    instructions: str | None = None


Client = Callable[[httpx.AsyncClient, SpeechCall], Awaitable[bytes]]


def _failure_for(status: int) -> SpeechFailure:
    if status in (401, 403):
        return SpeechFailure.CREDENTIALS
    if status == 404:
        return SpeechFailure.NOT_FOUND
    if status == 429:
        return SpeechFailure.RATE_LIMITED
    if 400 <= status < 500:
        return SpeechFailure.REJECTED
    return SpeechFailure.UNAVAILABLE


def _raise_for(call: SpeechCall, response: httpx.Response) -> None:
    """Refuse a non-2xx answer, logging what the provider said and keeping it out."""
    if response.is_success:
        return
    logger.warning(
        "Speech request to %s for model %s failed (%s): %s",
        call.provider,
        call.model,
        response.status_code,
        response.text[:2000],
    )
    raise SpeechProviderError(
        _failure_for(response.status_code), provider=call.provider, status=response.status_code
    )


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
    return response.content


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
    return response.content


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
        return base64.b64decode(blocks[-1], validate=True)
    except (ValueError, KeyError, IndexError, AttributeError, TypeError, binascii.Error):
        logger.warning("Gemini returned no audio for model %s", call.model, exc_info=True)
        raise SpeechProviderError(SpeechFailure.UNAVAILABLE, provider=call.provider) from None


CLIENTS: dict[str, Client] = {
    "openai_speech": openai_speech,
    "elevenlabs": elevenlabs,
    "gemini_interactions": gemini_interactions,
}
"""The client for each API shape the catalog may name."""

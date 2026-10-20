"""Speaking a text of any length through one provider, as one clip.

A provider takes a few thousand characters per request and a chapter is longer, so
the text is split at the most natural boundary inside each model's limit - a
paragraph, then a sentence, then a word - and the pieces are spoken in order and
joined. MP3 joins by concatenation; WAV is spoken as raw PCM and wrapped in one
header at the end, because two WAV files back to back are not one WAV file.

The pieces are requested one after another rather than all at once. A provider
rate-limits per key, and the key is the organization's; a chapter fanned out into
ten parallel requests is ten chances to be refused halfway through.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass

import httpx

from app.services.text_to_speech.clients import CLIENTS, SAMPLE_RATE, SpeechCall
from app.services.text_to_speech.exceptions import SpeechFailure, SpeechProviderError
from app.services.text_to_speech_models import TextToSpeechProvider

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 120.0
"""How long one request may take. A few thousand characters is under a minute of
work for every provider here; twice that covers a cold model on a busy endpoint."""

_BOUNDARIES = ("\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ")
"""Where a text is best cut, most natural first."""


@dataclass(frozen=True)
class Speech:
    """A clip, and what it took to make it."""

    data: bytes
    audio_format: str
    """`mp3` or `wav`, which is also the extension it is stored under."""

    characters: int
    """What was spoken, which is what the provider bills."""

    requests: int


def split_text(text: str, limit: int) -> list[str]:
    """The text in pieces of at most `limit` characters, cut where speech pauses.

    A cut is taken only in the second half of a window, so a piece is never a
    sliver; a window with no boundary there - one very long word - is cut at the
    limit, which a provider speaks rather than refuses.
    """
    remaining = text.strip()
    pieces: list[str] = []
    while len(remaining) > limit:
        cut = _cut(remaining, limit)
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _cut(text: str, limit: int) -> int:
    window = text[:limit]
    for boundary in _BOUNDARIES:
        at = window.rfind(boundary)
        if at >= limit // 2:
            return at + len(boundary)
    return limit


def wav(pcm: bytes) -> bytes:
    """Raw PCM - 16-bit signed little-endian, mono, 24 kHz - as a WAV file."""
    channels, bits = 1, 16
    block_align = channels * bits // 8
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        SAMPLE_RATE,
        SAMPLE_RATE * block_align,
        block_align,
        bits,
        b"data",
        len(pcm),
    )
    return header + pcm


async def synthesize(
    provider: TextToSpeechProvider,
    *,
    model: str,
    voice: str,
    text: str,
    audio_format: str,
    api_key: str,
    instructions: str | None = None,
) -> Speech:
    """Speak `text` with one provider's model and voice, as one clip.

    Args:
        provider: The catalog entry, which says how to call it.
        model: A model the entry lists.
        voice: A voice the entry lists, or the account's own voice id where the
            provider's voices belong to the account.
        text: What to say. Split where it exceeds the model's limit.
        audio_format: `mp3` or `wav`; one the entry lists.
        api_key: The binding's key, sent in a header and nowhere else.
        instructions: A direction on how to speak, for models that read one.

    Raises:
        SpeechProviderError: A request failed, timed out, or returned no audio.
            Pieces already spoken are discarded: half a clip is not an answer.
        ValueError: The model or format is not one the entry offers - a
            configuration the binding's validation should have refused - or
            the text is blank, which the caller should have refused first.
    """
    chosen = provider.model(model)
    if chosen is None or audio_format not in provider.formats:
        raise ValueError(f"{provider.provider} does not offer {model} as {audio_format}")
    pieces = split_text(text, chosen.max_characters)
    if not pieces:
        raise ValueError("There is no text to speak")
    speak = CLIENTS[provider.api]
    audio: list[bytes] = []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            for piece in pieces:
                call = SpeechCall(
                    provider=provider.provider,
                    base_url=provider.base_url,
                    api_key=api_key,
                    model=model,
                    voice=voice,
                    text=piece,
                    encoding="mp3" if audio_format == "mp3" else "pcm",
                    instructions=instructions if chosen.takes_instructions else None,
                )
                audio.append(await speak(client, call))
    except httpx.HTTPError:
        logger.warning("Speech request to %s failed in transit", provider.provider, exc_info=True)
        raise SpeechProviderError(SpeechFailure.UNAVAILABLE, provider=provider.provider) from None
    joined = b"".join(audio)
    return Speech(
        data=joined if audio_format == "mp3" else wav(joined),
        audio_format=audio_format,
        characters=sum(len(piece) for piece in pieces),
        requests=len(pieces),
    )

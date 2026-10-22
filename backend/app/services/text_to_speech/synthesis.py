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

import logging
import re
import struct
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.services.text_to_speech.clients import CLIENTS, SAMPLE_RATE, SpeechCall
from app.services.text_to_speech.exceptions import SpeechFailure, SpeechProviderError
from app.services.text_to_speech_models import TextToSpeechProvider

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 120.0
"""The longest wait for any one phase of a request - connecting, sending, or the
gap between two chunks of the answer. A few thousand characters is under a minute
of work for every provider here; twice that covers a cold model on a busy
endpoint."""

_BOUNDARIES = (
    "\n\n",
    "\n",
    ". ",
    "! ",
    "? ",
    "。",
    "\uff01",  # fullwidth !
    "\uff1f",  # fullwidth ?
    "; ",
    "\uff1b",  # fullwidth ;
    ", ",
    "\uff0c",  # fullwidth ,
    "、",
    " ",
)
"""Where a text is best cut, most natural first. Chinese and Japanese end a
sentence with no space after it, so their marks are listed without one."""

ACCOUNT_VOICE_ID = re.compile(r"[A-Za-z0-9_-]+")
"""What an account's own voice id may be. It goes into a URL path, and `.` or `..`
there would be resolved away and send the key to another endpoint."""


@dataclass(frozen=True)
class SpokenPiece:
    """One piece of a text whose audio is in hand."""

    characters: int
    seconds: float | None
    """How long its audio runs, where that is known from the bytes - raw PCM; an
    MP3's frames are not read here."""


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


def _without_id3(mp3: bytes) -> bytes:
    """An MP3 with a leading ID3v2 tag taken off, so it can follow another piece.

    The tag's size is four 7-bit bytes after its 10-byte header. A tag left in the
    middle of a joined clip is skipped by most players and read as noise by some.
    """
    if len(mp3) < 10 or not mp3.startswith(b"ID3"):
        return mp3
    size = (mp3[6] << 21) | (mp3[7] << 14) | (mp3[8] << 7) | mp3[9]
    return mp3[10 + size :]


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
    on_spoken: Callable[[SpokenPiece], None] | None = None,
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
        on_spoken: Told each piece - its characters, and its audio's length
            where that is known - as soon as its audio is in hand, so a caller
            books the cost of a long text as it goes, and
            a failure or a cancelled run partway through still books every
            piece that came back. A piece in flight when the run is cancelled,
            or answered with something that is not audio, is not booked.

    Raises:
        SpeechProviderError: A request failed, timed out, or returned no audio.
            Pieces already spoken are discarded - half a clip is not an answer -
            though `on_spoken` has already been told about them.
        ValueError: The model, voice or format is not one the entry offers - a
            configuration the binding's validation should have refused - or
            the text is blank, which the caller should have refused first.
    """
    chosen = provider.model(model)
    if chosen is None or audio_format not in provider.formats:
        raise ValueError(f"{provider.provider} does not offer {model} as {audio_format}")
    if provider.account_voices:
        if ACCOUNT_VOICE_ID.fullmatch(voice) is None:
            raise ValueError(f"{voice!r} is not a voice id")
    elif voice not in {offered.id for offered in provider.voices_for(chosen)}:
        raise ValueError(f"{model} has no voice {voice!r}")
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
                spoken = await speak(client, call)
                audio.append(spoken)
                if on_spoken is not None:
                    seconds = len(spoken) / (SAMPLE_RATE * 2) if call.encoding == "pcm" else None
                    on_spoken(SpokenPiece(characters=len(piece), seconds=seconds))
    except httpx.HTTPError:
        logger.warning("Speech request to %s failed in transit", provider.provider, exc_info=True)
        raise SpeechProviderError(SpeechFailure.UNAVAILABLE, provider=provider.provider) from None
    joined = (
        b"".join([audio[0], *(_without_id3(piece) for piece in audio[1:])])
        if audio_format == "mp3"
        else b"".join(audio)
    )
    return Speech(
        data=joined if audio_format == "mp3" else wav(joined),
        audio_format=audio_format,
        characters=sum(len(piece) for piece in pieces),
        requests=len(pieces),
    )

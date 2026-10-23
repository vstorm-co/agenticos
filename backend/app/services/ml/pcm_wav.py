"""Dictation's own audio format: 16 kHz mono 16-bit PCM in a WAV file (#1797).

The format a dictation is in unless the deployment has accepted compressed
audio, and the reason is the cost. A provider bills by the second, and a
compressed file says how many seconds it holds in a header its sender wrote,
so a file built by hand can say less than it holds. Raw PCM at a fixed rate
cannot: its length is its byte count, 32,000 bytes a second, and the longest
dictation then bounds what one recording can cost exactly.

**Strict, because a lenient reader would bring the header back into it.** One
`fmt ` chunk saying integer PCM, one channel, 16,000 Hz and 16 bits - nothing
else, so a stereo, 48 kHz, 24-bit or float file is not read at some other
rate - and one `data` chunk after it, whole and of whole samples. A chunk of any
other kind is stepped over. The RIFF size has to be the file's own, and a chunk
that runs past the end, a pad byte missing, a second `fmt ` or `data`, or more
than `MAX_CHUNKS` chunks are all a file this does not read. Nothing raises: a
recording is samples or `None`, and the caller says what was accepted.

**The provider never receives the sender's header.** `wrap` builds a canonical
44-byte one around the samples that were counted, so what is paid for is what
was measured, and whatever else the file carried stays here.
"""

import struct

SAMPLE_RATE = 16_000
"""What the composer and the widget resample a microphone to."""

BYTES_PER_SECOND = SAMPLE_RATE * 2
"""One channel of 16-bit samples: 32,000 bytes for every second of audio."""

HEADER_BYTES = 44
"""The canonical header `wrap` writes: RIFF, a 16-byte `fmt `, and `data`'s own eight."""

MAX_CHUNKS = 64
"""How many chunks one file may hold. A browser's recording holds two."""

_PCM = 1
_FMT = struct.Struct("<HHIIHH")
_FMT_SIZES = frozenset({16, 18})
"""A PCM `fmt ` body is 16 bytes; some writers add an empty two-byte extension."""


def samples(content: bytes) -> bytes | None:
    """The recording's samples, or `None` for anything but dictation's own WAV."""
    if len(content) < 12 or content[:4] != b"RIFF" or content[8:12] != b"WAVE":
        return None
    end = 8 + struct.unpack_from("<I", content, 4)[0]
    if end != len(content):
        return None
    offset = 12
    found_fmt = False
    data: bytes | None = None
    for _ in range(MAX_CHUNKS):
        if offset == end:
            break
        if offset + 8 > end:
            return None
        kind = content[offset : offset + 4]
        size = struct.unpack_from("<I", content, offset + 4)[0]
        body = offset + 8
        offset = body + size + (size & 1)
        if offset > end:
            return None
        if kind == b"fmt ":
            if found_fmt or not _is_dictation_pcm(content[body : body + size]):
                return None
            found_fmt = True
        elif kind == b"data":
            if not found_fmt or data is not None or size % 2:
                return None
            data = content[body : body + size]
    else:
        if offset != end:
            return None
    return data


def wrap(pcm: bytes) -> bytes:
    """`pcm` behind a canonical 44-byte header, as the provider is sent it."""
    return (
        b"RIFF"
        + struct.pack("<I", HEADER_BYTES - 8 + len(pcm))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", _FMT.size)
        + _FMT.pack(_PCM, 1, SAMPLE_RATE, BYTES_PER_SECOND, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )


def _is_dictation_pcm(body: bytes) -> bool:
    """Whether a `fmt ` body says 16 kHz mono 16-bit integer PCM, and nothing more."""
    if len(body) not in _FMT_SIZES or (len(body) == 18 and body[16:18] != b"\x00\x00"):
        return False
    return _FMT.unpack_from(body) == (_PCM, 1, SAMPLE_RATE, BYTES_PER_SECOND, 2, 16)

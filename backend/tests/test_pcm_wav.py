"""Dictation's own WAV, read strictly and rebuilt for the provider (#1797).

By default a dictation's cost is bounded by counting its samples, so anything
that would let a file be read at another rate - or carry bytes past what was
counted - has to come back as `None`, and what the provider is sent has to be
exactly the samples that were counted.
"""

from __future__ import annotations

import struct

import pytest

from app.services.ml import pcm_wav
from tests.recordings import pcm_wav as dictation_wav
from tests.recordings import wav, wav_chunk, wav_fmt

_SAMPLES = bytes(range(256)) * 125
"""32,000 bytes: one second of dictation, not silence, so an offset slip shows."""


def test_a_browsers_recording_is_its_samples() -> None:
    assert pcm_wav.samples(wav(wav_fmt(), wav_chunk(b"data", _SAMPLES))) == _SAMPLES
    assert len(pcm_wav.samples(dictation_wav(2.5)) or b"") == 2.5 * pcm_wav.BYTES_PER_SECOND


def test_other_chunks_are_stepped_over_padding_included() -> None:
    recording = wav(
        wav_chunk(b"LIST", b"odd"),
        wav_fmt(),
        wav_chunk(b"fact", b"\x00" * 4),
        wav_chunk(b"data", _SAMPLES),
        wav_chunk(b"id3 ", b"\x01" * 9),
    )

    assert pcm_wav.samples(recording) == _SAMPLES


def test_an_empty_two_byte_fmt_extension_is_still_pcm() -> None:
    body = struct.pack("<HHIIHH", 1, 1, 16_000, 32_000, 2, 16) + b"\x00\x00"

    assert pcm_wav.samples(wav(wav_chunk(b"fmt ", body), wav_chunk(b"data", b"\x00" * 8)))


def test_a_recording_with_no_samples_is_empty_not_refused() -> None:
    """Well formed and silent of length: the caller answers `empty` for it."""
    assert pcm_wav.samples(wav(wav_fmt(), wav_chunk(b"data", b""))) == b""


@pytest.mark.parametrize(
    "fmt",
    [
        wav_fmt(rate=48_000),
        wav_fmt(rate=8_000),
        wav_fmt(channels=2),
        wav_fmt(bits=8),
        wav_fmt(bits=24),
        wav_fmt(bits=32),
        wav_fmt(tag=0x0003, bits=32),
        wav_fmt(tag=0x0011),
        wav_fmt(tag=0xFFFE),
        # Every field right but the byte rate, which a reader at another rate trusts.
        wav_chunk(b"fmt ", struct.pack("<HHIIHH", 1, 1, 16_000, 64_000, 2, 16)),
        wav_chunk(b"fmt ", struct.pack("<HHIIHH", 1, 1, 16_000, 32_000, 4, 16)),
        wav_chunk(b"fmt ", struct.pack("<HHIIHH", 1, 1, 16_000, 32_000, 2, 16) + b"\x16\x00"),
        wav_chunk(b"fmt ", struct.pack("<HHIIHH", 1, 1, 16_000, 32_000, 2, 16) + b"\x00" * 24),
        wav_chunk(b"fmt ", b"\x01\x00" * 7),
    ],
    ids=[
        "48-khz",
        "8-khz",
        "stereo",
        "8-bit",
        "24-bit",
        "32-bit",
        "float",
        "adpcm",
        "extensible",
        "byte-rate",
        "block-align",
        "fmt-extension",
        "fmt-oversized",
        "fmt-truncated",
    ],
)
def test_anything_but_16_khz_mono_16_bit_integer_pcm_is_refused(fmt: bytes) -> None:
    assert pcm_wav.samples(wav(fmt, wav_chunk(b"data", b"\x00" * 64))) is None


@pytest.mark.parametrize(
    "recording",
    [
        b"",
        b"RIFF",
        b"RIFX" + dictation_wav(0.1)[4:],
        dictation_wav(0.1)[:8] + b"AVI " + dictation_wav(0.1)[12:],
        # The RIFF size disagreeing with the file, either way.
        dictation_wav(0.1)[:-2],
        dictation_wav(0.1) + b"\x00\x00",
        # A data chunk that says it is longer than what follows it.
        wav(wav_fmt(), wav_chunk(b"data", b"\x00" * 64, declared=128)),
        # A streaming writer's "unknown" size.
        wav(wav_fmt(), wav_chunk(b"data", b"\x00" * 64, declared=0xFFFFFFFF)),
        # Half a sample.
        wav(wav_fmt(), wav_chunk(b"data", b"\x00" * 63)),
        # An odd chunk whose pad byte is missing at the end of the file.
        wav(wav_fmt(), wav_chunk(b"data", b"\x00" * 64), b"LIST" + struct.pack("<I", 3) + b"odd"),
        # A chunk header cut short.
        wav(wav_fmt(), wav_chunk(b"data", b"\x00" * 64), b"LIS"),
        wav(wav_fmt()),
        wav(wav_chunk(b"data", b"\x00" * 64), wav_fmt()),
        wav(wav_fmt(), wav_fmt(), wav_chunk(b"data", b"\x00" * 64)),
        wav(wav_fmt(), wav_chunk(b"data", b"\x00" * 64), wav_chunk(b"data", b"\x00" * 64)),
    ],
    ids=[
        "empty",
        "riff-only",
        "big-endian-riff",
        "not-wave",
        "riff-size-over",
        "riff-size-under",
        "data-truncated",
        "data-unknown-size",
        "half-a-sample",
        "pad-missing",
        "chunk-header-cut",
        "no-data",
        "data-before-fmt",
        "two-fmt",
        "two-data",
    ],
)
def test_a_malformed_file_is_refused_rather_than_guessed_at(recording: bytes) -> None:
    assert pcm_wav.samples(recording) is None


def test_more_chunks_than_a_browser_writes_is_refused() -> None:
    filler = [wav_chunk(b"junk", b"") for _ in range(pcm_wav.MAX_CHUNKS)]
    within = [wav_chunk(b"junk", b"") for _ in range(pcm_wav.MAX_CHUNKS - 2)]

    assert pcm_wav.samples(wav(wav_fmt(), wav_chunk(b"data", b"\x00" * 8), *filler)) is None
    assert pcm_wav.samples(wav(wav_fmt(), wav_chunk(b"data", b"\x00" * 8), *within)) is not None


def test_the_provider_is_sent_a_canonical_header_around_the_counted_samples() -> None:
    """Whatever the caller's file carried besides the samples stays here."""
    sent = pcm_wav.wrap(_SAMPLES)

    assert len(sent) == pcm_wav.HEADER_BYTES + len(_SAMPLES)
    assert sent[pcm_wav.HEADER_BYTES :] == _SAMPLES
    assert sent[: pcm_wav.HEADER_BYTES] == (
        b"RIFF"
        + struct.pack("<I", 36 + len(_SAMPLES))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16_000, 32_000, 2, 16)
        + b"data"
        + struct.pack("<I", len(_SAMPLES))
    )
    # And it reads back as itself, so the provider gets what this accepts.
    assert pcm_wav.samples(sent) == _SAMPLES

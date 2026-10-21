"""Reading a recording's length from its container, for the dictation cost ceiling (#1797).

The figure decides whether a stranger's recording reaches a paid provider, so
each container is read the way a browser writes it - and every malformed,
truncated or hostile shape has to come back as `None`, quickly, rather than
raise or walk a file to its end.
"""

import struct
import time

import pytest

from app.services.ml import audio_duration
from app.services.ml.audio_duration import measure
from tests.recordings import (
    TRACK_RUN,
    box,
    cluster,
    ebml,
    ftyp,
    full_box,
    header_box,
    moof,
    mvex,
    ogg_opus,
    ogg_page,
    opus_head,
    pcm_wav,
    segment_info,
    simple_block,
    tfdt,
    tfhd,
    track_run,
    trak,
    vorbis_id,
    wav,
    wav_chunk,
    wav_fmt,
    webm,
)


def test_an_unknown_container_has_no_length() -> None:
    assert measure(b"ID3\x04\x00" + b"\x00" * 64) is None
    assert measure(b"") is None


# -- WAV ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rate", "channels", "bits"), [(16_000, 1, 16), (8_000, 1, 8), (48_000, 2, 16)]
)
def test_a_wav_is_its_data_at_its_frame_rate(rate: int, channels: int, bits: int) -> None:
    assert measure(pcm_wav(1.5, rate=rate, channels=channels, bits=bits)) == pytest.approx(1.5)


def test_a_wav_steps_over_other_chunks_and_their_padding() -> None:
    recording = wav(
        wav_chunk(b"LIST", b"odd"),
        wav_fmt(tag=0xFFFE),
        wav_chunk(b"fact", b"\x00" * 4),
        wav_chunk(b"data", b"\x00" * 32_000),
    )

    assert measure(recording) == pytest.approx(1.0)


def test_a_streaming_writers_placeholder_size_counts_the_bytes_that_are_there() -> None:
    recording = wav(wav_fmt(), wav_chunk(b"data", b"\x00" * 64_000, declared=0xFFFFFFFF))

    assert measure(recording) == pytest.approx(2.0)


@pytest.mark.parametrize(
    "recording",
    [
        wav(wav_fmt(tag=0x0011), wav_chunk(b"data", b"\x00" * 100)),
        wav(wav_fmt(rate=0), wav_chunk(b"data", b"\x00" * 100)),
        wav(wav_fmt(bits=0), wav_chunk(b"data", b"\x00" * 100)),
        wav(wav_chunk(b"fmt ", b"\x01\x00" * 7), wav_chunk(b"data", b"\x00" * 100)),
        wav(wav_chunk(b"data", b"\x00" * 100), wav_fmt()),
        wav(wav_fmt()),
        wav(wav_fmt())[:30],
    ],
    ids=["compressed", "no-rate", "no-frame-size", "short-fmt", "data-first", "no-data", "cut"],
)
def test_a_wav_whose_length_a_header_does_not_state_is_unknown(recording: bytes) -> None:
    assert measure(recording) is None


# -- Ogg ----------------------------------------------------------------------


def test_an_opus_stream_is_its_last_granule_less_the_pre_skip() -> None:
    assert measure(ogg_opus(4.5)) == pytest.approx(4.5)


def test_a_vorbis_stream_counts_at_its_own_rate() -> None:
    recording = ogg_page(vorbis_id(rate=44_100), granule=0) + ogg_page(
        b"\x00" * 10, granule=88_200, sequence=1
    )

    assert measure(recording) == pytest.approx(2.0)


def test_the_last_page_is_found_past_pages_that_do_not_end_a_packet() -> None:
    """A trailing page from another stream, one with no packet ending on it (`-1`),
    a capture pattern of another version and one too close to the end to be a
    page are all stepped over on the way back to the real last page."""
    recording = (
        ogg_opus(3.0)
        + ogg_page(b"\x00" * 10, granule=-1, sequence=3)
        + ogg_page(b"\x00" * 10, granule=48_000 * 900, serial=99)
        + ogg_page(b"\x00" * 10, granule=48_000 * 900, version=1)
        + b"OggS\x00"
    )

    assert measure(recording) == pytest.approx(3.0)


def test_a_stream_shorter_than_its_pre_skip_is_no_length_rather_than_negative() -> None:
    recording = ogg_page(opus_head(pre_skip=312), granule=0) + ogg_page(b"\x00", granule=100)

    assert measure(recording) == 0


@pytest.mark.parametrize(
    "recording",
    [
        ogg_page(b"Speex   " + b"\x00" * 72, granule=0) + ogg_page(b"\x00", granule=48_000),
        ogg_page(vorbis_id(rate=0), granule=0) + ogg_page(b"\x00", granule=48_000),
        ogg_page(opus_head(), granule=-1) + ogg_page(b"\x00", granule=-1, sequence=1),
        b"OggS\x00\x02",
    ],
    ids=["unknown-codec", "no-rate", "no-granule", "cut"],
)
def test_an_ogg_stream_without_a_readable_end_is_unknown(recording: bytes) -> None:
    assert measure(recording) is None


# -- WebM ---------------------------------------------------------------------


def test_a_media_recorder_webm_is_its_last_cluster_and_block() -> None:
    """No `Duration`, and the segment and clusters of unknown size, as Chrome and
    Firefox stream them."""
    recording = webm(segment_info(), cluster(0, [0, 20, 980]), cluster(1000, [0, 20, 1960]))

    assert measure(recording) == pytest.approx(2.96)


def test_a_stated_duration_is_read_and_the_larger_figure_wins() -> None:
    stated = segment_info(duration=struct.pack(">d", 5000.0))
    short_stated = segment_info(duration=struct.pack(">f", 100.0))
    blocks = cluster(0, [0, 2500], unknown=False)

    assert measure(webm(stated, blocks)) == pytest.approx(5.0)
    assert measure(webm(short_stated, blocks)) == pytest.approx(2.5)
    assert measure(webm(stated)) == pytest.approx(5.0)


def test_a_timecode_scale_other_than_a_millisecond_is_applied() -> None:
    recording = webm(segment_info(scale=500_000), cluster(0, [4000]))

    assert measure(recording) == pytest.approx(2.0)


def test_a_block_inside_a_block_group_counts_too() -> None:
    group = ebml(0xA0, simple_block(3000, element=0xA1))
    recording = webm(ebml(0x1F43B675, ebml(0xE7, b"\x00") + group, unknown=True))

    assert measure(recording) == pytest.approx(3.0)


@pytest.mark.parametrize(
    "recording",
    [
        webm(segment_info()),
        webm(simple_block(10)),
        webm(ebml(0x1654AE6B, unknown=True)),
        webm(segment_info(scale=0)),
        webm(segment_info(duration=b"\x00\x01")),
        webm(segment_info(duration=struct.pack(">d", float("nan")))),
        webm(segment_info(duration=struct.pack(">d", -1.0))),
        webm(ebml(0x1549A966, ebml(0x4489, b"\x00" * 8)[:-4])),
        webm() + b"\x00",
        webm() + b"\x08\x81",
        webm() + b"\x1a\x45",
        webm() + b"\xec\x00",
        webm() + b"\xec\x40",
    ],
    ids=[
        "nothing-timed",
        "block-outside-a-cluster",
        "unknown-size-elsewhere",
        "zero-scale",
        "duration-not-a-float",
        "duration-not-a-number",
        "duration-negative",
        "info-child-past-its-parent",
        "id-of-zero",
        "id-over-four-bytes",
        "id-cut",
        "size-of-zero",
        "size-cut",
    ],
)
def test_a_webm_without_a_readable_length_is_unknown(recording: bytes) -> None:
    assert measure(recording) is None


# -- MP4 ----------------------------------------------------------------------


@pytest.mark.parametrize("version", [0, 1])
def test_an_mp4_is_its_movie_headers_duration(version: int) -> None:
    recording = ftyp() + box(
        b"moov", header_box(b"mvhd", 1000, 7229, version=version) + trak(44_100)
    )

    assert measure(recording) == pytest.approx(7.229)


def test_a_fragmented_mp4_is_where_its_last_fragment_ends() -> None:
    """Safari's `MediaRecorder` writes 0 in the movie header; the fragments say how
    long it is - each from its decode time, or after the previous one."""
    recording = (
        ftyp()
        + box(
            b"moov",
            header_box(b"mvhd", 1000, 0) + trak(48_000) + trak(1) + mvex(trex_duration=1024),
        )
        + moof(tfhd(), tfdt(0), track_run(47))
        + moof(tfhd(default_duration=2048, base_offset=True), track_run(10))
        + moof(tfhd(), box(b"sbgp"), tfdt(96_000, version=0), track_run(3, [1024, 1024, 960]))
        + box(b"mdat", b"\x00" * 16)
    )

    assert measure(recording) == pytest.approx((96_000 + 3008) / 48_000)


def test_the_fragment_duration_the_movie_extends_to_counts() -> None:
    recording = ftyp() + box(
        b"moov", header_box(b"mvhd", 600, 0) + box(b"mvex", box(b"free")) + mvex(mehd=1800)
    )

    assert measure(recording) == pytest.approx(3.0)


def test_a_version_1_fragment_duration_is_read_as_64_bits() -> None:
    mehd = full_box(b"mehd", struct.pack(">Q", 1200), version=1)
    recording = ftyp() + box(b"moov", header_box(b"mvhd", 600, 0) + box(b"mvex", mehd))

    assert measure(recording) == pytest.approx(2.0)


def test_box_sizes_of_one_and_zero_are_the_large_and_the_open_ended() -> None:
    moov_body = header_box(b"mvhd", 1000, 2500)
    large = struct.pack(">I", 1) + b"moov" + struct.pack(">Q", 16 + len(moov_body)) + moov_body
    open_ended = struct.pack(">I", 0) + b"moov" + moov_body

    assert measure(ftyp() + large) == pytest.approx(2.5)
    assert measure(ftyp() + open_ended) == pytest.approx(2.5)


@pytest.mark.parametrize(
    "recording",
    [
        ftyp() + box(b"mdat", b"\x00" * 8),
        ftyp() + box(b"moov", header_box(b"mvhd", 1000, 0xFFFFFFFF)),
        ftyp() + box(b"moov", header_box(b"mvhd", 0, 2500)),
        ftyp() + box(b"moov", header_box(b"mvhd", 1000, 0) + box(b"trak")) + moof(track_run(4)),
        ftyp() + box(b"moov", header_box(b"mvhd", 1000, 0) + trak(None)) + moof(track_run(4)),
        ftyp() + struct.pack(">I", 4) + b"moov",
        ftyp()
        + box(b"moov", trak(48_000))
        + moof(full_box(TRACK_RUN, struct.pack(">I", 9), flags=0x100)),
    ],
    ids=[
        "no-movie",
        "unknown-duration",
        "no-timescale",
        "fragments-without-a-media-track",
        "fragments-without-a-media-timescale",
        "box-smaller-than-its-header",
        "run-longer-than-its-box",
    ],
)
def test_an_mp4_without_a_readable_length_is_unknown(recording: bytes) -> None:
    assert measure(recording) is None


# -- bounded work -------------------------------------------------------------


def test_a_file_of_a_million_empty_elements_is_given_up_on_quickly() -> None:
    """A hostile WebM of two-byte `Void` elements would be a million steps; the
    budget answers unknown long before that."""
    recording = webm() + b"\xec\x80" * 1_000_000
    started = time.monotonic()

    assert measure(recording) is None
    assert time.monotonic() - started < 5


def test_a_run_of_more_samples_than_the_step_cap_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio_duration, "MAX_ELEMENTS", 50)
    recording = (
        ftyp()
        + box(b"moov", header_box(b"mvhd", 1000, 0) + trak(48_000))
        + moof(tfhd(), tfdt(0), track_run(60, [1024] * 60))
    )

    assert measure(recording) is None

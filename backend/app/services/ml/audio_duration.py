"""How long a recording is, read from its own container (#1797).

A provider bills transcription by the second of audio, and dictation on a hosted
page or a widget is sent by a stranger. A byte cap does not bound seconds: Opus
at the lowest bitrate a script can ask for packs one to three hours into the
bytes 300 seconds of the composer's own recording take. So the length is read
here, before the provider is called, and the dictation core refuses a recording
longer than the organization allows.

**Read, not decoded.** Every container the composer records states its own
length or its timestamps somewhere cheap to reach, so nothing here knows a codec
and nothing new is installed:

- **WAV** - the PCM format's frame size and rate, against the size of the
  `data` chunk.
- **Ogg** (Opus or Vorbis) - the granule position of the stream's last page,
  less Opus's pre-skip, at the rate the stream's first page declares.
- **WebM / Matroska** - the larger of the segment's `Duration`, when the muxer
  wrote one, and the latest block timestamp. `MediaRecorder` writes no
  `Duration`, so for a browser recording it is the cluster timecode plus the
  last block's offset, scaled by `TimecodeScale`.
- **MP4 / M4A** - the larger of the movie header's duration, the fragment
  duration the movie extends to, and the end of the last fragment. Safari's
  `MediaRecorder` writes a fragmented file whose movie header says 0, so the
  fragments are what carry its length.
- **MP3** - every frame's samples at its own rate, walked header to header past
  an ID3v2 tag. A Mattermost voice note is MP3, and the platform states no length
  for it (Codex on #2204). Anything after the last frame longer than a trailing
  tag is an unknown length: a decoder resynchronises past junk, so audio behind
  it would be heard and not counted.

**The container is sniffed, not taken from the declared type.** The type a
caller sends is a claim; the bytes are what a provider decodes. An unrecognised
container is an unknown length.

**A figure or `None`, never an exception, and never unbounded.** Every loop
advances through the bytes or spends from `MAX_ELEMENTS`, so a hostile file of
a million empty boxes costs a bounded amount of work, and anything malformed,
truncated in a header or out of budget answers `None`. What an unknown length
is worth is the caller's decision.

**The container's word, not the decoder's.** A file built by hand to state
less than it holds is measured at what it states. The byte cap the caller keeps
is what bounds that one.
"""

import math
import struct
from collections.abc import Iterator

MAX_ELEMENTS = 100_000
"""How many chunks, pages, elements, boxes or samples one measurement may visit.

Ten minutes of browser Opus in WebM is 30,000 blocks at 20 ms each, and Safari's
AAC in MP4 under 30,000 samples, so an honest recording never comes near it. A
file that does is answered as unknown rather than walked to its end.
"""

_PCM_FORMATS = frozenset({0x0001, 0x0003, 0xFFFE})
"""WAV format tags whose frames are fixed-size: integer PCM, float, and
`WAVE_FORMAT_EXTENSIBLE`. A compressed format inside RIFF has no length a
header states, and is unknown."""

_OGG_HEADER = 27
_OGG_MAX_PAGE = _OGG_HEADER + 255 + 255 * 255
"""The largest an Ogg page can be, so the last page starts within two of these
of the end of any file that ends on a page."""

_OPUS_RATE = 48_000
"""Opus granule positions count 48 kHz samples whatever the input rate was."""

_EBML_HEADER = b"\x1a\x45\xdf\xa3"
_SEGMENT = 0x18538067
_CLUSTER = 0x1F43B675
_BLOCK_GROUP = 0xA0
_INFO = 0x1549A966
_TIMECODE_SCALE = 0x2AD7B1
_DURATION = 0x4489
_TIMECODE = 0xE7
_BLOCK = 0xA1
_SIMPLE_BLOCK = 0xA3
_DESCEND = frozenset({_SEGMENT, _CLUSTER, _BLOCK_GROUP})
"""Matroska elements walked into rather than over. `MediaRecorder` writes the
segment and each cluster with an unknown size, so their children are simply
what follows."""

_MP3_BITRATES = {
    (1, 3): (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (1, 2): (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (1, 1): (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (2, 3): (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    (2, 2): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (2, 1): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
"""kbit/s by (MPEG-1 or 2/2.5, layer bits) and the header's bitrate index; 0 is free format."""

_MP3_RATES = {3: (44_100, 48_000, 32_000), 2: (22_050, 24_000, 16_000), 0: (11_025, 12_000, 8_000)}
"""Sample rates by the header's version bits: MPEG-1, MPEG-2 and MPEG-2.5."""

_MP3_TRAILER = 4096
"""What may follow the last frame and still be a tag (ID3v1 is 128 bytes, an APE
tag a few hundred) rather than audio a decoder would find by resynchronising."""

_TRACK_RUN = b"trun"  # codespell:ignore trun
"""ISO-BMFF's track fragment run box, which lists a fragment's samples."""

_NANOSECONDS = 1_000_000_000
_DEFAULT_TIMECODE_SCALE = 1_000_000
"""Matroska's default tick: one millisecond, in nanoseconds."""


class _Malformed(ValueError):
    """A header that cannot be what it claims to be."""


class _Budget:
    """What is left of `MAX_ELEMENTS` for one measurement."""

    def __init__(self) -> None:
        self.left = MAX_ELEMENTS

    def spend(self, count: int = 1) -> None:
        self.left -= count
        if self.left < 0:
            raise _Malformed("out of budget")


def measure(content: bytes) -> float | None:
    """The recording's length in seconds, or `None` where it cannot be read.

    `None` covers a container this does not know, a header that is malformed or
    truncated, a file that would take more than `MAX_ELEMENTS` steps to read, and
    a figure that is not a finite, non-negative number.
    """
    if content.startswith(b"RIFF") and content[8:12] == b"WAVE":
        reader = _wav
    elif content.startswith(b"OggS"):
        reader = _ogg
    elif content.startswith(_EBML_HEADER):
        reader = _matroska
    elif content[4:8] == b"ftyp":
        reader = _mp4
    elif content.startswith(b"ID3") or _mp3_sync(content, 0):
        reader = _mp3
    else:
        return None
    try:
        seconds = reader(content, _Budget())
    except _Malformed, struct.error, IndexError:
        return None
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def _mp3_sync(content: bytes, position: int) -> bool:
    return (
        position + 4 <= len(content)
        and content[position] == 0xFF
        and content[position + 1] & 0xE0 == 0xE0
    )


def _mp3(content: bytes, budget: _Budget) -> float | None:
    """Every frame's samples at its own rate, from the first frame to the last.

    Walked rather than estimated from one frame's bitrate or a Xing header: a
    file whose first frame claims 320 kbit/s and whose others carry 8 would be
    measured at a fortieth of its length.
    """
    position = 0
    if content.startswith(b"ID3"):
        if len(content) < 10:
            raise _Malformed("truncated ID3 tag")
        size = 0
        for byte in content[6:10]:
            size = (size << 7) | (byte & 0x7F)
        footer = 10 if content[5] & 0x10 else 0
        position = 10 + size + footer
    seconds = 0.0
    frames = 0
    while _mp3_sync(content, position):
        budget.spend()
        version = (content[position + 1] >> 3) & 0x3
        layer = (content[position + 1] >> 1) & 0x3
        bitrate_index = content[position + 2] >> 4
        rate_index = (content[position + 2] >> 2) & 0x3
        padding = (content[position + 2] >> 1) & 0x1
        if version == 1 or layer == 0 or bitrate_index in (0, 15) or rate_index == 3:
            raise _Malformed("not an MP3 frame header")
        bitrate = _MP3_BITRATES[(1 if version == 3 else 2, layer)][bitrate_index] * 1000
        rate = _MP3_RATES[version][rate_index]
        if layer == 3:  # Layer I
            samples, length = 384, (12 * bitrate // rate + padding) * 4
        elif layer == 2 or version == 3:  # Layer II, or Layer III of MPEG-1
            samples, length = 1152, 144 * bitrate // rate + padding
        else:  # Layer III of MPEG-2 and 2.5
            samples, length = 576, 72 * bitrate // rate + padding
        seconds += samples / rate
        frames += 1
        position += length
    if frames == 0 or len(content) - position > _MP3_TRAILER:
        return None
    return seconds


def _wav(content: bytes, budget: _Budget) -> float | None:
    """The `data` chunk's frames at the rate the `fmt ` chunk declares.

    Frames rather than the header's `byte_rate`: for PCM the two agree, and
    where a file makes them disagree the frame size and rate are what a decoder
    plays it at. A `data` chunk declared longer than the file - a streaming
    writer's placeholder - counts the bytes actually there.
    """
    position = 12
    bytes_per_second: int | None = None
    while position + 8 <= len(content):
        budget.spend()
        kind = content[position : position + 4]
        (size,) = struct.unpack_from("<I", content, position + 4)
        body = position + 8
        if kind == b"fmt ":
            if size < 16:
                raise _Malformed("fmt chunk too short")
            tag, _channels, rate, _byte_rate, block_align = struct.unpack_from(
                "<HHIIH", content, body
            )
            if tag not in _PCM_FORMATS or rate == 0 or block_align == 0:
                return None
            bytes_per_second = rate * block_align
        elif kind == b"data":
            if bytes_per_second is None:
                return None
            return min(size, len(content) - body) / bytes_per_second
        # Chunks are padded to an even length.
        position = body + size + (size & 1)
    return None


def _ogg(content: bytes, budget: _Budget) -> float | None:
    """The last page's granule position, at the rate the first page declares.

    The first page carries the codec's identification header: `OpusHead`, whose
    granules are always 48 kHz and whose pre-skip is priming the decoder drops,
    or Vorbis's, which states its own rate. The last page is found by searching
    back from the end for the capture pattern, on the same logical stream and
    with a granule set - `-1` marks a page on which no packet ends.
    """
    payload = _OGG_HEADER + content[26]
    (serial,) = struct.unpack_from("<I", content, 14)
    if content.startswith(b"OpusHead", payload):
        rate = _OPUS_RATE
        (pre_skip,) = struct.unpack_from("<H", content, payload + 10)
    elif content.startswith(b"\x01vorbis", payload):
        (rate,) = struct.unpack_from("<I", content, payload + 12)
        pre_skip = 0
    else:
        return None
    if rate == 0:
        return None
    floor = max(0, len(content) - 2 * _OGG_MAX_PAGE)
    end = len(content)
    while (page := content.rfind(b"OggS", floor, end)) >= 0:
        budget.spend()
        end = page
        if page + _OGG_HEADER > len(content) or content[page + 4] != 0:
            continue
        granule, page_serial = struct.unpack_from("<qI", content, page + 6)
        if page_serial == serial and granule >= 0:
            return max(0, granule - pre_skip) / rate
    return None


def _matroska(content: bytes, budget: _Budget) -> float | None:
    """The larger of the stated `Duration` and the latest block, in seconds.

    One pass over the file: the segment, its clusters and their block groups are
    walked into, and everything else with a known size is stepped over. An
    element of unknown size that is not one of those cannot be stepped over,
    and the length is unknown.
    """
    scale = _DEFAULT_TIMECODE_SCALE
    stated: float | None = None
    cluster: int | None = None
    latest: int | None = None
    position = 0
    while position < len(content):
        budget.spend()
        element, position = _element_id(content, position)
        size, position = _element_size(content, position)
        if element in _DESCEND:
            continue
        if size is None:
            raise _Malformed("an element of unknown size that cannot be skipped")
        body, position = position, position + size
        if element == _INFO:
            scale, stated = _segment_info(content, body, min(position, len(content)), budget)
        elif element == _TIMECODE:
            cluster = int.from_bytes(content[body:position], "big")
        elif element in (_SIMPLE_BLOCK, _BLOCK):
            if cluster is None:
                raise _Malformed("a block outside a cluster")
            _track, at = _element_size(content, body)
            (offset,) = struct.unpack_from(">h", content, at)
            latest = cluster + offset if latest is None else max(latest, cluster + offset)
    ticks = [figure for figure in (stated, latest) if figure is not None]
    if not ticks:
        return None
    return max(ticks) * scale / _NANOSECONDS


def _segment_info(
    content: bytes, start: int, end: int, budget: _Budget
) -> tuple[int, float | None]:
    """`(TimecodeScale, Duration)` from a segment's `Info`, defaulted where absent."""
    scale = _DEFAULT_TIMECODE_SCALE
    duration: float | None = None
    position = start
    while position < end:
        budget.spend()
        element, position = _element_id(content, position)
        size, position = _element_size(content, position)
        if size is None or position + size > end:
            raise _Malformed("an Info child past its parent")
        if element == _TIMECODE_SCALE:
            scale = int.from_bytes(content[position : position + size], "big")
            if scale == 0:
                raise _Malformed("a zero TimecodeScale")
        elif element == _DURATION:
            if size not in (4, 8):
                raise _Malformed("a Duration that is not a float")
            (duration,) = struct.unpack_from(">f" if size == 4 else ">d", content, position)
        position += size
    return scale, duration


def _element_id(content: bytes, position: int) -> tuple[int, int]:
    """An EBML element id, marker bit kept as Matroska writes ids, and where it ends."""
    first = content[position]
    length = 9 - first.bit_length()
    if first == 0 or length > 4:
        raise _Malformed("an element id longer than four bytes")
    end = position + length
    if end > len(content):
        raise _Malformed("a truncated element id")
    return int.from_bytes(content[position:end], "big"), end


def _element_size(content: bytes, position: int) -> tuple[int | None, int]:
    """An EBML variable-length size, `None` when every value bit is set (unknown)."""
    first = content[position]
    if first == 0:
        raise _Malformed("a size longer than eight bytes")
    length = 9 - first.bit_length()
    end = position + length
    if end > len(content):
        raise _Malformed("a truncated size")
    value = int.from_bytes(content[position:end], "big") & ((1 << (7 * length)) - 1)
    return (None if value == (1 << (7 * length)) - 1 else value), end


def _mp4(content: bytes, budget: _Budget) -> float | None:
    """The longest of what the movie header, `mehd` and the fragments say.

    The movie header's duration is in its own timescale; a fragment's samples
    are in the track's media timescale, from the first track's `mdhd`. A
    fragment starts at its `tfdt` decode time where it has one, else where the
    previous one ended.
    """
    movie_scale = 0
    figures: list[float] = []
    media_scale = 0
    default_duration = 0
    fragment_end = 0
    fragmented = False
    for kind, body, end in _boxes(content, 0, len(content), budget):
        if kind == b"moov":
            movie_scale, stated, extends, media_scale, default_duration = _movie(
                content, body, end, budget
            )
            figures += [ticks / movie_scale for ticks in (stated, extends) if ticks and movie_scale]
        elif kind == b"moof":
            fragmented = True
            for child, child_body, child_end in _boxes(content, body, end, budget):
                if child == b"traf":
                    fragment_end = max(
                        fragment_end,
                        _track_fragment_end(
                            content, child_body, child_end, budget, default_duration, fragment_end
                        ),
                    )
    if fragmented and media_scale:
        figures.append(fragment_end / media_scale)
    return max(figures) if figures else None


def _movie(content: bytes, start: int, end: int, budget: _Budget) -> tuple[int, int, int, int, int]:
    """`(movie timescale, duration, mehd duration, media timescale, trex default)`.

    A duration of all ones is the format's "unknown", and reads as 0 like an
    unset one.
    """
    movie_scale = duration = extends = media_scale = default_duration = 0
    for kind, body, child_end in _boxes(content, start, end, budget):
        if kind == b"mvhd":
            movie_scale, duration = _timescale_and_duration(content, body)
        elif kind == b"trak" and not media_scale:
            media_scale = _media_timescale(content, body, child_end, budget)
        elif kind == b"mvex":
            for child, child_body, _ in _boxes(content, body, child_end, budget):
                if child == b"mehd":
                    extends = _versioned(content, child_body, child_body + 4)
                elif child == b"trex":
                    (default_duration,) = struct.unpack_from(">I", content, child_body + 12)
    return movie_scale, duration, extends, media_scale, default_duration


def _media_timescale(content: bytes, start: int, end: int, budget: _Budget) -> int:
    """A track's `mdia/mdhd` timescale, or 0 where it has none."""
    for kind, body, child_end in _boxes(content, start, end, budget):
        if kind == b"mdia":
            for child, child_body, _ in _boxes(content, body, child_end, budget):
                if child == b"mdhd":
                    return _timescale_and_duration(content, child_body)[0]
    return 0


def _timescale_and_duration(content: bytes, body: int) -> tuple[int, int]:
    """`mvhd` and `mdhd` share a layout: times, then the timescale, then the duration."""
    if content[body] == 1:
        timescale, duration = struct.unpack_from(">IQ", content, body + 20)
        unknown = (1 << 64) - 1
    else:
        timescale, duration = struct.unpack_from(">II", content, body + 12)
        unknown = (1 << 32) - 1
    return timescale, 0 if duration == unknown else duration


def _versioned(content: bytes, body: int, at: int) -> int:
    """A field that is 64-bit in a version-1 box and 32-bit in a version-0 one."""
    return struct.unpack_from(">Q" if content[body] == 1 else ">I", content, at)[0]


def _track_fragment_end(
    content: bytes, start: int, end: int, budget: _Budget, default_duration: int, previous: int
) -> int:
    """Where one `traf` ends on the media timeline: its start plus its samples."""
    base: int | None = None
    total = 0
    for kind, body, child_end in _boxes(content, start, end, budget):
        if kind == b"tfhd":
            flags = int.from_bytes(content[body + 1 : body + 4], "big")
            at = body + 8 + (8 if flags & 0x01 else 0) + (4 if flags & 0x02 else 0)
            if flags & 0x08:
                (default_duration,) = struct.unpack_from(">I", content, at)
        elif kind == b"tfdt":
            base = _versioned(content, body, body + 4)
        elif kind == _TRACK_RUN:
            total += _run_duration(content, body, child_end, budget, default_duration)
    return (previous if base is None else base) + total


def _run_duration(
    content: bytes, start: int, end: int, budget: _Budget, default_duration: int
) -> int:
    """A track run's samples added up: each its own duration, or the default for all."""
    flags = int.from_bytes(content[start + 1 : start + 4], "big")
    (count,) = struct.unpack_from(">I", content, start + 4)
    at = start + 8 + (4 if flags & 0x001 else 0) + (4 if flags & 0x004 else 0)
    if not flags & 0x100:
        return count * default_duration
    stride = 4 * bin(flags & 0xF00).count("1")
    if at + count * stride > end:
        raise _Malformed("a track run with more samples than bytes")
    budget.spend(count)
    return sum(struct.unpack_from(">I", content, at + index * stride)[0] for index in range(count))


def _boxes(
    content: bytes, start: int, end: int, budget: _Budget
) -> Iterator[tuple[bytes, int, int]]:
    """`(type, body start, body end)` for each ISO-BMFF box between two offsets.

    A size of 1 means a 64-bit size follows; 0 means the box runs to the end of
    its parent. A box claiming to end past its parent is cut at the parent.
    """
    position = start
    while position + 8 <= end:
        budget.spend()
        size, kind = struct.unpack_from(">I4s", content, position)
        header = 8
        if size == 1:
            (size,) = struct.unpack_from(">Q", content, position + 8)
            header = 16
        elif size == 0:
            size = end - position
        if size < header:
            raise _Malformed("a box smaller than its header")
        yield kind, position + header, min(position + size, end)
        position += size

"""Recordings built byte by byte, for the tests of what reads their length.

Each builder writes the least of its container that a demuxer needs to find the
length - the headers and the timestamps, with silence or zeros where the codec's
data would be. Nothing here encodes audio, so a test states the length it means
and a fixture cannot drift from a binary nobody can read.
"""

import struct
from collections.abc import Sequence

# -- WAV ----------------------------------------------------------------------


def wav_chunk(kind: bytes, body: bytes, *, declared: int | None = None) -> bytes:
    """One RIFF chunk, padded to an even length; `declared` overrides its size field."""
    size = len(body) if declared is None else declared
    return kind + struct.pack("<I", size) + body + (b"\x00" if len(body) % 2 else b"")


def wav_fmt(*, tag: int = 1, channels: int = 1, rate: int = 16_000, bits: int = 16) -> bytes:
    block_align = channels * bits // 8
    body = struct.pack("<HHIIHH", tag, channels, rate, rate * block_align, block_align, bits)
    return wav_chunk(b"fmt ", body)


def wav(*chunks: bytes) -> bytes:
    body = b"WAVE" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def pcm_wav(seconds: float, *, rate: int = 16_000, channels: int = 1, bits: int = 16) -> bytes:
    """Silence of `seconds`, as the composer's WAV encoder writes it."""
    frames = round(seconds * rate) * channels * bits // 8
    return wav(
        wav_fmt(channels=channels, rate=rate, bits=bits), wav_chunk(b"data", b"\x00" * frames)
    )


# -- Ogg ----------------------------------------------------------------------


def ogg_page(
    payload: bytes, *, granule: int, serial: int = 7, sequence: int = 0, version: int = 0
) -> bytes:
    """One Ogg page. The CRC is left zero: nothing that measures a length checks it."""
    lacing = [255] * (len(payload) // 255) + [len(payload) % 255]
    header = (
        b"OggS"
        + bytes([version, 0])
        + struct.pack("<qIII", granule, serial, sequence, 0)
        + bytes([len(lacing)])
        + bytes(lacing)
    )
    return header + payload


def opus_head(*, pre_skip: int = 312) -> bytes:
    return b"OpusHead" + bytes([1, 1]) + struct.pack("<HIhB", pre_skip, 48_000, 0, 0)


def vorbis_id(*, rate: int = 44_100) -> bytes:
    return b"\x01vorbis" + struct.pack("<IBIiiiBB", 0, 1, rate, 0, 0, 0, 0xB8, 1)


def ogg_opus(seconds: float, *, pre_skip: int = 312, serial: int = 7) -> bytes:
    """An Opus stream ending `seconds` after its pre-skip, as a browser writes it."""
    return (
        ogg_page(opus_head(pre_skip=pre_skip), granule=0, serial=serial)
        + ogg_page(b"OpusTags", granule=0, serial=serial, sequence=1)
        + ogg_page(
            b"\x00" * 300,
            granule=round(seconds * 48_000) + pre_skip,
            serial=serial,
            sequence=2,
        )
    )


# -- WebM / Matroska ----------------------------------------------------------

UNKNOWN_SIZE = b"\x01\xff\xff\xff\xff\xff\xff\xff"


def ebml(element_id: int, body: bytes = b"", *, unknown: bool = False) -> bytes:
    """One EBML element, its size as eight bytes - or the unknown size `MediaRecorder` writes."""
    identifier = element_id.to_bytes((element_id.bit_length() + 7) // 8, "big")
    size = UNKNOWN_SIZE if unknown else ((1 << 56) | len(body)).to_bytes(8, "big")
    return identifier + size + body


def simple_block(offset_ms: int, *, element: int = 0xA3) -> bytes:
    """A block on track 1, `offset_ms` after its cluster's timecode."""
    return ebml(element, b"\x81" + struct.pack(">hB", offset_ms, 0x80) + b"\x00" * 4)


def cluster(timecode: int, offsets: Sequence[int], *, unknown: bool = True) -> bytes:
    body = ebml(0xE7, timecode.to_bytes(4, "big")) + b"".join(
        simple_block(offset) for offset in offsets
    )
    return ebml(0x1F43B675, body, unknown=unknown)


def segment_info(*, scale: int | None = None, duration: bytes | None = None) -> bytes:
    body = ebml(0x4D80, b"agenticos-tests")  # MuxingApp, which nothing reads
    if scale is not None:
        body += ebml(0x2AD7B1, scale.to_bytes(4, "big"))
    if duration is not None:
        body += ebml(0x4489, duration)
    return ebml(0x1549A966, body)


def webm(*children: bytes) -> bytes:
    """An EBML header and a segment of unknown size, as `MediaRecorder` streams one."""
    header = ebml(0x1A45DFA3, ebml(0x4282, b"webm"))
    return header + ebml(0x18538067, b"".join(children), unknown=True)


# -- MP4 ----------------------------------------------------------------------


def box(kind: bytes, body: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(body)) + kind + body


def full_box(kind: bytes, body: bytes = b"", *, version: int = 0, flags: int = 0) -> bytes:
    return box(kind, bytes([version]) + flags.to_bytes(3, "big") + body)


def ftyp() -> bytes:
    return box(b"ftyp", b"M4A \x00\x00\x00\x00isomM4A ")


def header_box(kind: bytes, timescale: int, duration: int, *, version: int = 0) -> bytes:
    """An `mvhd` or `mdhd`: the two share their times, timescale and duration."""
    if version == 1:
        fields = struct.pack(">QQIQ", 0, 0, timescale, duration)
    else:
        fields = struct.pack(">IIII", 0, 0, timescale, duration)
    return full_box(kind, fields + b"\x00" * 8, version=version)


def trak(media_timescale: int | None) -> bytes:
    """A track whose media header states `media_timescale`, or has no `mdhd` for `None`."""
    media = box(b"hdlr")
    if media_timescale is not None:
        media += header_box(b"mdhd", media_timescale, 0)
    return box(b"trak", box(b"tkhd") + box(b"mdia", media))


def mvex(*, trex_duration: int = 0, mehd: int | None = None) -> bytes:
    body = b"" if mehd is None else full_box(b"mehd", struct.pack(">I", mehd))
    body += full_box(b"trex", struct.pack(">IIIII", 1, 1, trex_duration, 0, 0))
    return box(b"mvex", body)


def tfhd(*, default_duration: int | None = None, base_offset: bool = False) -> bytes:
    flags = 0x020000  # default-base-is-moof, which nothing here reads
    fields = struct.pack(">I", 1)
    if base_offset:
        flags |= 0x01
        fields += struct.pack(">Q", 0)
    if default_duration is not None:
        flags |= 0x02 | 0x08
        fields += struct.pack(">II", 1, default_duration)
    return full_box(b"tfhd", fields, flags=flags)


def tfdt(base: int, *, version: int = 1) -> bytes:
    return full_box(b"tfdt", struct.pack(">Q" if version == 1 else ">I", base), version=version)


TRACK_RUN = b"trun"  # codespell:ignore trun


def track_run(count: int, durations: Sequence[int] | None = None) -> bytes:
    """A run of `count` samples, each with its own duration or all on the default."""
    if durations is None:
        return full_box(TRACK_RUN, struct.pack(">I", count))
    # Data offset, first-sample flags, then per sample: duration and size.
    flags = 0x001 | 0x004 | 0x100 | 0x200
    fields = struct.pack(">IiI", count, 0, 0) + b"".join(
        struct.pack(">II", duration, 100) for duration in durations
    )
    return full_box(TRACK_RUN, fields, flags=flags)


def moof(*traf_children: bytes) -> bytes:
    return box(
        b"moof", full_box(b"mfhd", struct.pack(">I", 1)) + box(b"traf", b"".join(traf_children))
    )


# -- MP3 ----------------------------------------------------------------------


def mp3_frame(
    length: int,
    *,
    version: int = 3,
    layer: int = 1,
    bitrate: int = 9,
    rate: int = 0,
    padding: int = 0,
) -> bytes:
    """A frame header in the bits it is written in, then zeros to `length` bytes.

    Version bits 3/2/0 are MPEG-1/2/2.5 and layer bits 3/2/1 are Layers I/II/III;
    `bitrate` and `rate` are the header's indexes, not values. The defaults are
    MPEG-1 Layer III at 128 kbit/s and 44.1 kHz, whose frame is 417 bytes. The
    length is the caller's to state, from the format, so a builder computing it
    cannot agree with the reader for the wrong reason.
    """
    flags = (0xE0 | version << 3 | layer << 1 | 1, bitrate << 4 | rate << 2 | padding << 1)
    return bytes((0xFF, *flags, 0)) + bytes(length - 4)


def id3(size: int, *, footer: bool = False) -> bytes:
    """An ID3v2.4 tag of `size` bytes of frames, its size written seven bits a byte."""
    synchsafe = bytes((size >> shift) & 0x7F for shift in (21, 14, 7, 0))
    flags = bytes((0x10 if footer else 0,))
    return b"ID3\x04\x00" + flags + synchsafe + bytes(size) + (b"3DI" + bytes(7) if footer else b"")

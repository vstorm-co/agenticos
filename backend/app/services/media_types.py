"""Small media signatures for stored file labels; inspection still verifies the bytes."""


def sniff_av_header(data: bytes) -> str | None:
    """Recognize bounded, self-contained audio/video containers, never a playlist.

    These are labels for uploads, not validation of a codec, duration or dimensions.
    The media inspector independently opens the bytes before a workflow uses them.
    """
    head = data[:4096]
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head.startswith(b"fLaC"):
        return "audio/flac"
    if head.startswith(b"ID3"):
        return "audio/mpeg"
    if (
        len(head) >= 4
        and head[0] == 0xFF
        and head[1] & 0xE0 == 0xE0
        and head[1] & 0x18 != 0x08
        and head[1] & 0x06 != 0
        and head[2] & 0xF0 not in {0, 0xF0}
        and head[2] & 0x0C != 0x0C
    ):
        return "audio/mpeg"
    if head.startswith(b"OggS") and any(
        marker in head[:128] for marker in (b"OpusHead", b"\x01vorbis", b"\x7fFLAC")
    ):
        return "audio/ogg"
    if head.startswith(b"\x1a\x45\xdf\xa3") and b"webm" in head[:128]:
        return "video/webm"
    if len(head) >= 16 and head[4:8] == b"ftyp":
        size = int.from_bytes(head[:4], "big")
        if 16 <= size <= min(len(head), 256) and size % 4 == 0:
            brands = {head[8:12], *(head[i : i + 4] for i in range(16, size, 4))}
            if brands & {b"isom", b"iso2", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1"}:
                return "video/mp4"
    return None

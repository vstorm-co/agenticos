"""Inspect scoped media bytes without accepting a URL or trusting an extension.

Images are bounded before decoding. Audio/video use a managed ffprobe process
with a small format/protocol allowlist, output/deadline/concurrency ceilings and
POSIX memory/CPU limits. Its diagnostic output never reaches a caller or a log.
"""

import asyncio
import contextlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
import weakref
from pathlib import Path
from typing import Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from app.core.blocking import create_cancel_safe, delete_cancel_safe, run_blocking_settled
from app.services.file_storage import sniff_image_header
from app.services.media_types import sniff_av_header

MAX_PROBE_OUTPUT = 16_384
PROBE_SECONDS = 8
_IMAGE_FORMATS = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}
_FORMATS = {
    "audio/wav": "wav",
    "audio/flac": "flac",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "video/mp4": "mov",
    "video/webm": "matroska",
}
_LAUNCHER = """
import os, resource, sys
for kind, value in ((resource.RLIMIT_CPU, 6), (resource.RLIMIT_AS, 1073741824),
                    (resource.RLIMIT_FSIZE, 0)):
    if sys.platform == 'darwin' and kind == resource.RLIMIT_AS:
        continue
    _, hard = resource.getrlimit(kind)
    ceiling = value if hard == resource.RLIM_INFINITY else min(value, hard)
    resource.setrlimit(kind, (ceiling, ceiling))
os.execv(sys.argv[1], sys.argv[1:])
"""
_gates: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


class MediaInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["image", "audio", "video"]
    media_type: str
    byte_size: int = Field(gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class MediaInspectionError(ValueError):
    """A controlled reason, containing no file bytes, provider response or path."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _invalid() -> MediaInspectionError:
    return MediaInspectionError("MEDIA_INVALID", "The media bytes could not be verified")


def _pixels(width: object, height: object, limit: int) -> tuple[int, int]:
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise _invalid()
    if width > 10_000 or height > 10_000 or width * height > limit:
        raise MediaInspectionError("MEDIA_TOO_LARGE", "The media exceeds its pixel limit")
    return width, height


def _image(data: bytes, expected: str, max_pixels: int) -> MediaInfo:
    try:
        with Image.open(io.BytesIO(data)) as source:
            if _IMAGE_FORMATS.get(source.format or "") != expected:
                raise _invalid()
            width, height = _pixels(source.width, source.height, max_pixels)
            if getattr(source, "n_frames", 1) != 1:
                raise MediaInspectionError(
                    "MEDIA_UNSUPPORTED", "This step accepts still images, not animated images"
                )
            source.load()
            if source.getexif().get(274) in {5, 6, 7, 8}:
                width, height = height, width
            return MediaInfo(
                kind="image", media_type=expected, byte_size=len(data), width=width, height=height
            )
    except Image.DecompressionBombError as exc:
        raise MediaInspectionError("MEDIA_TOO_LARGE", "The image exceeds its pixel limit") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise _invalid() from exc


def _probe_metadata(
    data: bytes, *, expected: str, byte_size: int, max_pixels: int, max_seconds: float
) -> MediaInfo:
    try:
        report = json.loads(data)
        streams, container = report["streams"], report["format"]
        if not isinstance(streams, list) or not 1 <= len(streams) <= 2:
            raise _invalid()
        if _FORMATS[expected] not in container["format_name"].split(","):
            raise _invalid()
        kinds = [stream["codec_type"] for stream in streams]
        is_video = expected.startswith("video/")
        if any(kind not in {"video", "audio"} for kind in kinds):
            raise _invalid()
        if (is_video and kinds.count("video") != 1) or (not is_video and kinds != ["audio"]):
            raise _invalid()
        durations = [float(container["duration"])]
        durations.extend(float(stream["duration"]) for stream in streams if "duration" in stream)
        if any(not math.isfinite(value) or value <= 0 for value in durations):
            raise _invalid()
        duration = max(durations)
        if duration > max_seconds:
            raise MediaInspectionError("MEDIA_TOO_LONG", "The media exceeds its duration limit")
        width = height = None
        if is_video:
            video = next(stream for stream in streams if stream["codec_type"] == "video")
            width, height = _pixels(video["width"], video["height"], max_pixels)
        return MediaInfo(
            kind="video" if is_video else "audio",
            media_type=expected,
            byte_size=byte_size,
            width=width,
            height=height,
            duration_seconds=duration,
        )
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError) as exc:
        if isinstance(exc, MediaInspectionError):
            raise
        raise _invalid() from exc


async def _stop(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
    waiter = asyncio.create_task(process.wait())
    cancelled = False
    while not waiter.done():
        try:
            await asyncio.shield(waiter)
        except asyncio.CancelledError:
            cancelled = True
    waiter.result()
    if cancelled:
        raise asyncio.CancelledError


async def _run_probe(command: list[str]) -> bytes:
    creation = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    )
    try:
        process = await asyncio.shield(creation)
    except BaseException:
        # Creation may already have launched the process. Acquire and reap that
        # exact child even if cancellation arrives while Python returns its handle.
        while not creation.done():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(creation)
        if not creation.cancelled() and creation.exception() is None:
            await _stop(creation.result())
        raise
    try:
        if process.stdout is None:
            raise _invalid()
        chunks: list[bytes] = []
        size = 0
        while chunk := await process.stdout.read(4096):
            size += len(chunk)
            if size > MAX_PROBE_OUTPUT:
                raise _invalid()
            chunks.append(chunk)
        if await process.wait() != 0:
            raise _invalid()
        return b"".join(chunks)
    finally:
        await _stop(process)


def _stage(data: bytes, holder: list[str]) -> None:
    directory = tempfile.mkdtemp(prefix="workflow-media-")
    holder.append(directory)
    path = Path(directory) / "input"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def _command(binary: str, source: Path, media_type: str) -> list[str]:
    arguments = [
        binary,
        "-v",
        "error",
        "-max_alloc",
        "33554432",
        "-threads",
        "1",
        "-protocol_whitelist",
        "file",
        "-format_whitelist",
        _FORMATS[media_type],
        "-max_streams",
        "2",
        "-probesize",
        "1048576",
        "-analyzeduration",
        "3000000",
        "-show_entries",
        "format=format_name,duration:stream=codec_type,width,height,duration",
        "-of",
        "json",
    ]
    if media_type == "video/mp4":
        arguments.extend(["-enable_drefs", "0", "-use_absolute_path", "0"])
    arguments.extend(["-i", str(source)])
    # The deployed Linux worker gets kernel limits before ffprobe starts. Windows
    # development still has the same deadline, format, allocation and output bounds.
    return [sys.executable, "-I", "-c", _LAUNCHER, *arguments] if os.name == "posix" else arguments


async def inspect_media(
    data: bytes, *, expected_type: str, max_bytes: int, max_pixels: int, max_seconds: float
) -> MediaInfo:
    if not data:
        raise _invalid()
    if len(data) > max_bytes:
        raise MediaInspectionError("MEDIA_TOO_LARGE", "The media exceeds its byte limit")
    image = sniff_image_header(data[:4096])
    detected = image or sniff_av_header(data)
    if detected is None:
        raise MediaInspectionError("MEDIA_UNSUPPORTED", "This media format is not supported")
    if detected != expected_type:
        raise MediaInspectionError("MEDIA_TYPE_MISMATCH", "The media bytes do not match its type")
    loop = asyncio.get_running_loop()
    gate = _gates.setdefault(loop, asyncio.Semaphore(2))
    async with asyncio.timeout(PROBE_SECONDS), gate:
        if image:
            return await run_blocking_settled(_image, data, expected_type, max_pixels)
        binary = shutil.which("ffprobe")
        if binary is None:
            raise MediaInspectionError(
                "MEDIA_INSPECTOR_UNAVAILABLE", "This deployment cannot inspect audio or video yet"
            )
        holder: list[str] = []
        try:
            await create_cancel_safe(
                lambda: _stage(data, holder),
                lambda: shutil.rmtree(holder[0], ignore_errors=True) if holder else None,
            )
            source = Path(holder[0]) / "input"
            try:
                output = await _run_probe(_command(binary, source, detected))
            except OSError as exc:
                raise MediaInspectionError(
                    "MEDIA_INSPECTOR_UNAVAILABLE", "The media inspector could not start"
                ) from exc
            return _probe_metadata(
                output,
                expected=detected,
                byte_size=len(data),
                max_pixels=max_pixels,
                max_seconds=max_seconds,
            )
        finally:
            if holder:
                await delete_cancel_safe(shutil.rmtree, holder[0], True)

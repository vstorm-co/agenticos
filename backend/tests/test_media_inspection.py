"""Actual media bytes, bounded probes and closed parser failures."""

import asyncio
import io
import json
import shutil
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

from app.services import media_inspection as inspection
from app.services.media_inspection import MediaInspectionError
from app.services.media_types import sniff_av_header

pytestmark = pytest.mark.anyio


def png(width: int = 12, height: int = 8) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "blue").save(output, format="PNG")
    return output.getvalue()


def wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(b"\0\0" * 800)
    return output.getvalue()


async def inspect(data: bytes, content_type: str = "image/png", **limits):
    return await inspection.inspect_media(
        data,
        expected_type=content_type,
        max_bytes=limits.get("max_bytes", 1_000_000),
        max_pixels=limits.get("max_pixels", 1_000_000),
        max_seconds=limits.get("max_seconds", 1),
    )


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"RIFF\0\0\0\0WAVE", "audio/wav"),
        (b"fLaC\0", "audio/flac"),
        (b"ID3\0", "audio/mpeg"),
        (b"\xff\xfb\x90\0", "audio/mpeg"),
        (b"\xff\xfe\xfd", None),
        (b"\xff\xeb\x90\0", None),
        (b"\xff\xf9\x90\0", None),
        (b"\xff\xfb\xf0\0", None),
        (b"\xff\xfb\x00\0", None),
        (b"\xff\xfb\x9c\0", None),
        (b"OggS" + b"\0" * 20 + b"OpusHead", "audio/ogg"),
        (b"\x1a\x45\xdf\xa3webm", "video/webm"),
        (b"\0\0\0\x14ftypisom\0\0\0\0mp42", "video/mp4"),
        (b"\0\0\0\x10ftypqt  \0\0\0\0", None),
        (b"\0\0\0\x15ftypisom\0\0\0\0mp42x", None),
        (b"\0\0\x04\x00ftypisom\0\0\0\0", None),
        (b"#EXTM3U\nhttps://example.com/private", None),
        (b"OggS\0unrecognized codec", None),
        (b"RIFF\0\0\0\0WEBP", None),
        (b"", None),
    ],
)
def test_signature_labels_are_bounded_and_exclude_playlists(data, expected):
    assert sniff_av_header(data) == expected


async def test_static_image_metadata_comes_from_decoded_bytes():
    data = png()
    result = await inspect(data)
    assert result.model_dump() == {
        "kind": "image",
        "media_type": "image/png",
        "byte_size": len(data),
        "width": 12,
        "height": 8,
        "duration_seconds": None,
    }


@pytest.mark.security
@pytest.mark.parametrize(
    "data,content_type,limits,code",
    [
        (b"", "image/png", {}, "MEDIA_INVALID"),
        (b"hello", "image/png", {}, "MEDIA_UNSUPPORTED"),
        (png(), "image/jpeg", {}, "MEDIA_TYPE_MISMATCH"),
        (png(), "image/png", {"max_bytes": 1}, "MEDIA_TOO_LARGE"),
        (png(), "image/png", {"max_pixels": 10}, "MEDIA_TOO_LARGE"),
        (png()[:24], "image/png", {}, "MEDIA_INVALID"),
    ],
)
async def test_invalid_or_mismatched_media_is_refused(data, content_type, limits, code):
    with pytest.raises(MediaInspectionError) as error:
        await inspect(data, content_type, **limits)
    assert error.value.code == code


async def test_animation_is_not_silently_treated_as_one_still_frame():
    output = io.BytesIO()
    first, second = Image.new("RGB", (2, 2), "red"), Image.new("RGB", (2, 2), "blue")
    first.save(output, format="GIF", save_all=True, append_images=[second], duration=100)
    with pytest.raises(MediaInspectionError, match="animated"):
        await inspect(output.getvalue(), "image/gif")


async def test_exif_orientation_controls_the_display_dimensions():
    output = io.BytesIO()
    image = Image.new("RGB", (12, 8), "blue")
    exif = image.getexif()
    exif[274] = 6
    image.save(output, format="JPEG", exif=exif)
    result = await inspect(output.getvalue(), "image/jpeg")
    assert (result.width, result.height) == (8, 12)


def test_decoder_must_agree_with_the_previously_detected_type():
    with pytest.raises(MediaInspectionError, match="verified"):
        inspection._image(png(), "image/jpeg", 1024)


async def test_image_decoder_bomb_refusal_stays_a_controlled_limit(monkeypatch):
    data = png()
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)
    with pytest.raises(MediaInspectionError) as error:
        await inspect(data)
    assert error.value.code == "MEDIA_TOO_LARGE"


def video_report(**changes):
    result = {
        "streams": [{"codec_type": "video", "width": 16, "height": 16, "duration": "0.2"}],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "0.2"},
    }
    result.update(changes)
    return result


def metadata(report, **limits):
    return inspection._probe_metadata(
        json.dumps(report).encode(),
        expected="video/mp4",
        byte_size=2048,
        max_pixels=limits.get("max_pixels", 1024),
        max_seconds=limits.get("max_seconds", 1),
    )


def test_video_metadata_uses_the_longest_reported_stream():
    report = video_report()
    report["streams"].append({"codec_type": "audio", "duration": "0.3"})
    result = metadata(report)
    assert result.kind == "video" and result.duration_seconds == 0.3
    assert (result.width, result.height) == (16, 16)


@pytest.mark.security
@pytest.mark.parametrize(
    "report",
    [
        None,
        [],
        {},
        video_report(streams=[]),
        video_report(streams=[{}]),
        video_report(streams=[{"codec_type": "subtitle"}]),
        video_report(streams=[{"codec_type": "audio"}]),
        video_report(streams=[{"codec_type": "video"}] * 3),
        video_report(format={"format_name": "hls", "duration": "0.2"}),
        video_report(format={"format_name": None, "duration": "0.2"}),
        video_report(format={"format_name": "mov", "duration": "nan"}),
        video_report(format={"format_name": "mov", "duration": "inf"}),
        video_report(format={"format_name": "mov", "duration": "0"}),
        video_report(format={"format_name": "mov", "duration": "-1"}),
        video_report(streams=[{"codec_type": "video", "width": True, "height": 16}]),
        video_report(streams=[{"codec_type": "video", "width": 0, "height": 16}]),
        video_report(streams=[{"codec_type": "video", "width": 16, "height": "16"}]),
    ],
)
def test_unverified_probe_shapes_are_refused(report):
    with pytest.raises(MediaInspectionError, match="verified"):
        metadata(report)


@pytest.mark.parametrize(
    "limits,code",
    [({"max_pixels": 16}, "MEDIA_TOO_LARGE"), ({"max_seconds": 0.1}, "MEDIA_TOO_LONG")],
)
def test_real_dimensions_and_duration_enforce_limits(limits, code):
    with pytest.raises(MediaInspectionError) as error:
        metadata(video_report(), **limits)
    assert error.value.code == code


@pytest.mark.security
def test_probe_command_cannot_use_network_or_external_mp4_tracks():
    command = inspection._command("ffprobe", Path("/owned/input"), "video/mp4")
    assert command[command.index("-protocol_whitelist") + 1] == "file"
    assert command[command.index("-format_whitelist") + 1] == "mov"
    assert command[command.index("-enable_drefs") + 1] == "0"
    assert command[command.index("-use_absolute_path") + 1] == "0"
    assert command[command.index("-max_streams") + 1] == "2"
    assert command[command.index("-max_alloc") + 1] == "33554432"
    assert command[-2:] == ["-i", str(Path("/owned/input"))]


async def test_installed_probe_verifies_a_synthetic_wave_without_network():
    assert shutil.which("ffprobe"), "Install ffmpeg; the Docker image and backend CI provide it"
    result = await inspect(wav(), "audio/wav")
    assert result.kind == "audio" and result.duration_seconds == pytest.approx(0.1)
    assert result.width is None and result.height is None


@pytest.fixture
def synthetic_mp4(tmp_path):
    executable = shutil.which("ffmpeg")
    assert executable, "Install ffmpeg; the Docker image and backend CI provide it"
    target = tmp_path / "synthetic.mp4"
    created = subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=16x16:r=5:d=0.2",
            "-frames:v",
            "1",
            "-c:v",
            "mpeg4",
            "-an",
            str(target),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert created.returncode == 0, "The deterministic local video fixture could not be encoded"
    return target.read_bytes()


async def test_installed_probe_decodes_a_synthetic_mp4_with_external_tracks_disabled(synthetic_mp4):
    result = await inspect(synthetic_mp4, "video/mp4")
    assert result.kind == "video" and result.duration_seconds == pytest.approx(0.2)
    assert (result.width, result.height) == (16, 16)


async def test_missing_inspector_is_an_explicit_refusal(monkeypatch):
    monkeypatch.setattr(inspection.shutil, "which", lambda _name: None)
    with pytest.raises(MediaInspectionError) as error:
        await inspect(wav(), "audio/wav")
    assert error.value.code == "MEDIA_INSPECTOR_UNAVAILABLE"


async def test_failed_process_creation_is_sanitized_and_staged_bytes_are_removed(monkeypatch):
    directories = []
    original = inspection._stage

    def staged(data, holder):
        original(data, holder)
        directories.extend(holder)

    monkeypatch.setattr(inspection, "_stage", staged)
    monkeypatch.setattr(
        inspection.asyncio,
        "create_subprocess_exec",
        AsyncMock(side_effect=OSError("private host and input details")),
    )
    with pytest.raises(MediaInspectionError) as error:
        await inspect(wav(), "audio/wav")
    assert error.value.code == "MEDIA_INSPECTOR_UNAVAILABLE"
    assert "private host" not in str(error.value)
    assert directories and all(not Path(path).exists() for path in directories)


async def test_missing_probe_pipe_is_refused_and_the_child_is_reaped(monkeypatch):
    process = SimpleNamespace(
        stdout=None, returncode=0, wait=AsyncMock(return_value=0), kill=Mock()
    )
    monkeypatch.setattr(
        inspection.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
    )
    with pytest.raises(MediaInspectionError):
        await inspection._run_probe(["owned-probe"])
    process.wait.assert_awaited_once()
    process.kill.assert_not_called()


async def test_cancellation_during_spawn_waits_for_and_reaps_only_that_child(monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    process = SimpleNamespace(returncode=0, wait=AsyncMock(return_value=0), kill=Mock())

    async def spawn(*_args, **_kwargs):
        started.set()
        await release.wait()
        return process

    monkeypatch.setattr(inspection.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(inspection._run_probe(["owned-probe"]))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    process.wait.assert_awaited_once()


async def test_repeated_cancellation_cannot_abandon_process_reaping():
    started, release = asyncio.Event(), asyncio.Event()

    async def wait():
        started.set()
        await release.wait()
        return -9

    process = SimpleNamespace(returncode=None, wait=AsyncMock(side_effect=wait), kill=Mock())
    task = asyncio.create_task(inspection._stop(process))
    await started.wait()
    for _ in range(2):
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()


@pytest.mark.parametrize(
    "payload,returncode", [(b"x" * (inspection.MAX_PROBE_OUTPUT + 1), 0), (b"{}", 1)]
)
async def test_bounded_probe_output_and_failed_exit_are_refused(monkeypatch, payload, returncode):
    reader = asyncio.StreamReader()
    reader.feed_data(payload)
    reader.feed_eof()
    process = SimpleNamespace(
        stdout=reader, returncode=returncode, wait=AsyncMock(return_value=returncode), kill=Mock()
    )
    monkeypatch.setattr(
        inspection.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
    )
    with pytest.raises(MediaInspectionError):
        await inspection._run_probe(["owned-probe"])
    process.wait.assert_awaited()


async def test_probe_cancellation_reaps_the_exact_child(monkeypatch):
    reader = asyncio.StreamReader()
    process = SimpleNamespace(
        stdout=reader, returncode=None, wait=AsyncMock(return_value=-9), kill=Mock()
    )
    created = asyncio.Event()

    async def spawn(*_args, **_kwargs):
        created.set()
        return process

    monkeypatch.setattr(inspection.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(inspection._run_probe(["owned-probe"]))
    await created.wait()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()

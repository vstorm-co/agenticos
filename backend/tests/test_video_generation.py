"""Making a video through each provider, and what a failed or slow job may say.

Every provider is answered by a `MockTransport` routing on method and path, so
these pin the request each one is sent - the key in a header, never to a storage
host - the job each is polled for, and what is made of the answer: the clip's
bytes fetched before the address expires, and a refusal that never carries the
provider's own words.
"""

import asyncio
import base64
import json
import logging
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import anyio
import httpx
import pytest

from app.services import video_models
from app.services.video_generation import (
    FirstFrame,
    VideoFailure,
    VideoProviderError,
    generate_video,
)
from app.services.video_generation import clients as clients_module
from app.services.video_generation import generation as generation_module

pytestmark = pytest.mark.anyio

KEY = "sk-video-secret"
MP4 = b"\x00\x00\x00\x20ftypisom-video"
PNG = FirstFrame(data=b"\x89PNG-frame", mime_type="image/png")

Route = Callable[[httpx.Request], httpx.Response]

REAL_PAUSE = clients_module._pause
"""Kept before the fixture below makes every pause instant."""


@pytest.fixture(autouse=True)
def _instant_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(clients_module, "_pause", no_wait)


@contextmanager
def _answering(
    routes: dict[tuple[str, str], Route | list[Route]],
) -> Generator[list[httpx.Request]]:
    """Answer each (method, path) from `routes`; a list answers in turn."""
    seen: list[httpx.Request] = []
    real = httpx.AsyncClient

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        route = routes[(request.method, request.url.path)]
        if isinstance(route, list):
            return route.pop(0)(request)
        return route(request)

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handle)
        return real(*args, **kwargs)

    with patch.object(generation_module.httpx, "AsyncClient", client):
        yield seen


def _json(payload: object, status: int = 200) -> Route:
    return lambda _request: httpx.Response(status, json=payload)


def _redirect(location: str) -> Route:
    return lambda _request: httpx.Response(302, headers={"location": location})


def _bytes(body: bytes = MP4, status: int = 200) -> Route:
    return lambda _request: httpx.Response(status, content=body)


def _provider(provider_id: str) -> video_models.VideoProvider:
    entry = video_models.by_provider(provider_id)
    assert entry is not None
    return entry


async def _make(provider_id: str, model: str, **overrides: Any):
    request: dict[str, Any] = {
        "prompt": "A red bicycle in the rain.",
        "resolution": "720p",
        "aspect_ratio": "16:9",
        "api_key": KEY,
        "timeout_seconds": 600.0,
    }
    return await generate_video(_provider(provider_id), model=model, **{**request, **overrides})


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


class TestGemini:
    BASE = "/v1beta"

    def _answer(self, content: dict[str, object]) -> Route:
        return _json(
            {"steps": [{"type": "thought"}, {"type": "model_output", "content": [content]}]}
        )

    async def test_asks_for_a_file_then_downloads_it_with_the_key(self):
        routes = {
            ("POST", f"{self.BASE}/interactions"): self._answer(
                {
                    "type": "video",
                    "uri": "https://generativelanguage.googleapis.com/v1beta/files/abc123:download?alt=media",
                }
            ),
            ("GET", f"{self.BASE}/files/abc123"): [
                _json({"state": "PROCESSING"}),
                _json({"state": "ACTIVE"}),
            ],
            ("GET", f"{self.BASE}/files/abc123:download"): _bytes(),
        }
        with _answering(routes) as seen:
            clip = await _make("google", "gemini-omni-1.1-flash", duration=5, audio=False)

        submit = seen[0]
        assert submit.headers["x-goog-api-key"] == KEY
        assert _body(submit) == {
            "model": "gemini-omni-1.1-flash",
            "input": "A red bicycle in the rain.",
            "response_format": {
                "type": "video",
                "aspect_ratio": "16:9",
                "resolution": "720p",
                "delivery": "uri",
            },
            "background": False,
            "store": True,
            "stream": False,
        }
        assert seen[-1].headers["x-goog-api-key"] == KEY
        assert (clip.data, clip.seconds) == (MP4, None)

    async def test_an_image_goes_first_as_base64_without_a_data_prefix(self):
        routes = {
            ("POST", f"{self.BASE}/interactions"): self._answer(
                {"type": "video", "data": base64.b64encode(MP4).decode()}
            )
        }
        with _answering(routes) as seen:
            clip = await _make("google", "gemini-omni-1.1-flash", first_frame=PNG)

        assert _body(seen[0])["input"] == [
            {
                "type": "image",
                "data": base64.b64encode(PNG.data).decode(),
                "mime_type": "image/png",
            },
            {"type": "text", "text": "<FIRST_FRAME> A red bicycle in the rain."},
        ]
        assert clip.data == MP4

    @pytest.mark.parametrize(
        "content",
        [
            {"type": "text", "text": "no"},
            {"type": "video", "data": "*"},
            {"type": "video", "uri": "https://x/nope"},
        ],
        ids=["no video", "not base64", "no file id"],
    )
    async def test_an_answer_with_no_usable_video_is_unavailable(self, content):
        with (
            _answering({("POST", f"{self.BASE}/interactions"): self._answer(content)}),
            pytest.raises(VideoProviderError) as caught,
        ):
            await _make("google", "gemini-omni-1.1-flash")

        assert caught.value.failure is VideoFailure.UNAVAILABLE

    async def test_a_failed_file_is_unavailable(self):
        routes = {
            ("POST", f"{self.BASE}/interactions"): self._answer(
                {"type": "video", "uri": "/v1beta/files/f1"}
            ),
            ("GET", f"{self.BASE}/files/f1"): _json({"state": "FAILED"}),
        }
        with _answering(routes), pytest.raises(VideoProviderError) as caught:
            await _make("google", "gemini-omni-1.1-flash")

        assert caught.value.failure is VideoFailure.UNAVAILABLE


class TestBytePlus:
    TASKS = "/api/v3/contents/generations/tasks"

    async def test_parameters_go_as_fields_and_the_clip_comes_from_the_unsigned_address(self):
        routes = {
            ("POST", self.TASKS): _json({"id": "cgt-1"}),
            ("GET", f"{self.TASKS}/cgt-1"): [
                _json({"status": "queued"}),
                _json({"status": "running"}),
                _json(
                    {
                        "status": "succeeded",
                        "content": {"video_url": "https://tos.example/v.mp4"},
                        "duration": 5,
                    }
                ),
            ],
            ("GET", "/v.mp4"): _bytes(),
        }
        with _answering(routes) as seen:
            clip = await _make("byteplus", "dreamina-seedance-2-0-260128", duration=5, audio=False)

        assert seen[0].headers["authorization"] == f"Bearer {KEY}"
        assert _body(seen[0]) == {
            "model": "dreamina-seedance-2-0-260128",
            "content": [{"type": "text", "text": "A red bicycle in the rain."}],
            "resolution": "720p",
            "ratio": "16:9",
            "watermark": False,
            "duration": 5,
            "generate_audio": False,
        }
        download = seen[-1]
        assert download.url.host == "tos.example"
        assert "authorization" not in download.headers
        assert (clip.data, clip.seconds) == (MP4, 5.0)

    async def test_seedance_2_5_starts_from_an_image_at_the_images_own_shape(self):
        routes = {
            ("POST", self.TASKS): _json({"id": "cgt-2"}),
            ("GET", f"{self.TASKS}/cgt-2"): _json(
                {"status": "succeeded", "content": {"video_url": "https://tos.example/v.mp4"}}
            ),
            ("GET", "/v.mp4"): _bytes(),
        }
        with _answering(routes) as seen:
            clip = await _make("byteplus", "dreamina-seedance-2-5-260628", first_frame=PNG)

        body = _body(seen[0])
        assert body["ratio"] == "adaptive"
        assert body["content"][1] == {
            "type": "image_url",
            "image_url": {"url": PNG.data_uri()},
            "role": "first_frame",
        }
        assert "duration" not in body and "generate_audio" not in body
        assert clip.seconds is None

    async def test_an_older_seedance_keeps_the_chosen_ratio_with_an_image(self):
        routes = {
            ("POST", self.TASKS): _json({"id": "cgt-3"}),
            ("GET", f"{self.TASKS}/cgt-3"): _json(
                {"status": "succeeded", "content": {"video_url": "https://tos.example/v.mp4"}}
            ),
            ("GET", "/v.mp4"): _bytes(),
        }
        with _answering(routes) as seen:
            await _make(
                "byteplus", "dreamina-seedance-2-0-260128", first_frame=PNG, aspect_ratio="9:16"
            )

        assert _body(seen[0])["ratio"] == "9:16"

    @pytest.mark.parametrize(
        ("task", "failure"),
        [
            (
                {"status": "failed", "error": {"code": "OutputVideoSensitiveContentDetected"}},
                VideoFailure.POLICY,
            ),
            ({"status": "failed", "error": {"code": "InvalidParameter"}}, VideoFailure.REJECTED),
            ({"status": "expired", "error": None}, VideoFailure.UNAVAILABLE),
            ({"status": "succeeded", "content": {}}, VideoFailure.UNAVAILABLE),
        ],
        ids=["policy", "parameter", "expired", "no address"],
    )
    async def test_a_settled_task_that_is_not_a_clip(self, task, failure):
        routes = {
            ("POST", self.TASKS): _json({"id": "cgt-4"}),
            ("GET", f"{self.TASKS}/cgt-4"): _json(task),
        }
        with _answering(routes), pytest.raises(VideoProviderError) as caught:
            await _make("byteplus", "dreamina-seedance-2-0-260128")

        assert caught.value.failure is failure

    async def test_a_task_past_the_deadline_is_cancelled_and_times_out(self):
        routes = {
            ("POST", self.TASKS): _json({"id": "cgt-5"}),
            ("GET", f"{self.TASKS}/cgt-5"): _json({"status": "queued"}),
            ("DELETE", f"{self.TASKS}/cgt-5"): lambda _r: httpx.Response(204),
        }
        with _answering(routes) as seen, pytest.raises(VideoProviderError) as caught:
            await _make("byteplus", "dreamina-seedance-2-0-260128", timeout_seconds=1.0)

        assert caught.value.failure is VideoFailure.TIMED_OUT
        assert seen[-1].method == "DELETE"
        assert seen[-1].headers["authorization"] == f"Bearer {KEY}"

    async def test_a_call_cancelled_mid_job_cancels_the_task_too(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A run that went away leaves no queued task billing for nobody."""
        # An instant pause never yields, so the cancel would never be delivered.
        monkeypatch.setattr(clients_module, "_pause", lambda _seconds: anyio.sleep(0.01))
        routes = {
            ("POST", self.TASKS): _json({"id": "cgt-9"}),
            ("GET", f"{self.TASKS}/cgt-9"): _json({"status": "queued"}),
            ("DELETE", f"{self.TASKS}/cgt-9"): lambda _r: httpx.Response(204),
        }
        with _answering(routes) as seen, anyio.move_on_after(0.2):
            await _make("byteplus", "dreamina-seedance-2-0-260128")

        assert seen[-1].method == "DELETE"

    async def test_a_cancel_that_fails_still_times_out(self):
        def unreachable(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down", request=request)

        routes = {
            ("POST", self.TASKS): _json({"id": "cgt-6"}),
            ("GET", f"{self.TASKS}/cgt-6"): _json({"status": "running"}),
            ("DELETE", f"{self.TASKS}/cgt-6"): unreachable,
        }
        with _answering(routes), pytest.raises(VideoProviderError) as caught:
            await _make("byteplus", "dreamina-seedance-2-0-260128", timeout_seconds=1.0)

        assert caught.value.failure is VideoFailure.TIMED_OUT

    async def test_a_create_answer_without_an_id_is_unavailable(self):
        with (
            _answering({("POST", self.TASKS): _json({})}),
            pytest.raises(VideoProviderError) as caught,
        ):
            await _make("byteplus", "dreamina-seedance-2-0-260128")

        assert caught.value.failure is VideoFailure.UNAVAILABLE


class TestXai:
    async def test_a_text_clip_takes_the_ratio_and_an_image_clip_does_not(self):
        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "r1"}),
            ("GET", "/v1/videos/r1"): [
                _json({"status": "pending"}),
                _json(
                    {
                        "status": "done",
                        "video": {"url": "https://vidgen.example/v.mp4", "duration": 8},
                    }
                ),
            ],
            ("GET", "/v.mp4"): _bytes(),
        }
        with _answering(routes) as seen:
            clip = await _make("xai", "grok-imagine-video-1.5", duration=8)

        assert _body(seen[0]) == {
            "model": "grok-imagine-video-1.5",
            "prompt": "A red bicycle in the rain.",
            "resolution": "720p",
            "duration": 8,
            "aspect_ratio": "16:9",
        }
        assert "authorization" not in seen[-1].headers
        assert (clip.data, clip.seconds) == (MP4, 8.0)

        routes[("GET", "/v1/videos/r1")] = _json(
            {"status": "done", "video": {"url": "https://vidgen.example/v.mp4"}}
        )
        with _answering(routes) as seen:
            clip = await _make("xai", "grok-imagine-video-1.5-lite", first_frame=PNG)

        body = _body(seen[0])
        assert body["image"] == {"url": PNG.data_uri()}
        assert "aspect_ratio" not in body and "duration" not in body
        assert clip.seconds is None

    async def test_sound_is_sent_when_the_call_chose_it(self):
        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "r3"}),
            ("GET", "/v1/videos/r3"): _json(
                {"status": "done", "video": {"url": "https://vidgen.example/v.mp4"}}
            ),
            ("GET", "/v.mp4"): _bytes(),
        }
        with _answering(routes) as seen:
            await _make("xai", "grok-imagine-video-1.5", audio=False)

        assert _body(seen[0])["generate_audio"] is False

    @pytest.mark.parametrize(
        ("job", "failure"),
        [
            (
                {"status": "done", "video": {"url": "", "respect_moderation": False}},
                VideoFailure.POLICY,
            ),
            (
                # Withheld with the address still there: xAI says to check the flag
                # before using it, so it is not downloaded.
                {
                    "status": "done",
                    "video": {"url": "https://vidgen.example/v.mp4", "respect_moderation": False},
                },
                VideoFailure.POLICY,
            ),
            (
                {"status": "failed", "error": {"code": "permission_denied"}},
                VideoFailure.CREDENTIALS,
            ),
            ({"status": "failed", "error": {"code": "invalid_argument"}}, VideoFailure.REJECTED),
            (
                {"status": "failed", "error": {"code": "service_unavailable"}},
                VideoFailure.UNAVAILABLE,
            ),
            ({"status": "failed"}, VideoFailure.UNAVAILABLE),
        ],
        ids=[
            "withheld by moderation",
            "flagged with an address",
            "key",
            "argument",
            "down",
            "no error",
        ],
    )
    async def test_a_settled_job_that_is_not_a_clip(self, job, failure):
        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "r2"}),
            ("GET", "/v1/videos/r2"): _json(job),
        }
        with _answering(routes), pytest.raises(VideoProviderError) as caught:
            await _make("xai", "grok-imagine-video-1.5")

        assert caught.value.failure is failure

    async def test_a_job_past_the_deadline_times_out_with_nothing_to_cancel(self):
        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "r3"}),
            ("GET", "/v1/videos/r3"): _json({"status": "pending"}),
        }
        with _answering(routes) as seen, pytest.raises(VideoProviderError) as caught:
            await _make("xai", "grok-imagine-video-1.5", timeout_seconds=1.0)

        assert caught.value.failure is VideoFailure.TIMED_OUT
        assert all(request.method != "DELETE" for request in seen)

    async def test_a_create_answer_without_an_id_is_unavailable(self):
        with (
            _answering({("POST", "/v1/videos/generations"): _json({"id": "wrong-field"})}),
            pytest.raises(VideoProviderError),
        ):
            await _make("xai", "grok-imagine-video-1.5")


class TestAlibaba:
    SUBMIT = "/api/v1/services/aigc/video-generation/video-synthesis"

    async def test_a_workspace_binding_is_called_at_its_own_host(self):
        routes = {
            ("POST", self.SUBMIT): _json({"output": {"task_id": "t1"}}),
            ("GET", "/api/v1/tasks/t1"): _json(
                {"output": {"task_status": "SUCCEEDED", "video_url": "https://oss.example/v.mp4"}}
            ),
            ("GET", "/v.mp4"): _bytes(),
        }
        with _answering(routes) as seen:
            await _make(
                "alibaba",
                "wan3.0-video",
                base_url="https://ws-1a2b.us-east-1.maas.aliyuncs.com/api/v1",
            )

        assert [request.url.host for request in seen[:2]] == [
            "ws-1a2b.us-east-1.maas.aliyuncs.com"
        ] * 2

    async def test_asks_asynchronously_with_an_upper_case_resolution(self):
        routes = {
            ("POST", self.SUBMIT): _json({"output": {"task_id": "t1", "task_status": "PENDING"}}),
            ("GET", "/api/v1/tasks/t1"): [
                _json({"output": {"task_status": "RUNNING"}}),
                _json(
                    {
                        "output": {
                            "task_status": "SUCCEEDED",
                            "video_url": "https://oss.example/v.mp4",
                        },
                        "usage": {"output_video_duration": 5.0},
                    }
                ),
            ],
            ("GET", "/v.mp4"): _bytes(),
        }
        with _answering(routes) as seen:
            clip = await _make("alibaba", "wan3.0-video", duration=5, audio=True, first_frame=PNG)

        submit = seen[0]
        assert submit.headers["x-dashscope-async"] == "enable"
        assert submit.headers["authorization"] == f"Bearer {KEY}"
        assert _body(submit) == {
            "model": "wan3.0-video",
            "input": {
                "prompt": "A red bicycle in the rain.",
                "media": [{"type": "first_frame", "url": PNG.data_uri()}],
            },
            "parameters": {
                "resolution": "720P",
                "ratio": "16:9",
                "watermark": False,
                "duration": 5,
                "audio": True,
            },
        }
        assert (clip.data, clip.seconds) == (MP4, 5.0)

    async def test_a_text_clip_sends_no_media_and_leaves_length_and_sound_to_the_model(self):
        routes = {
            ("POST", self.SUBMIT): _json({"output": {"task_id": "t2"}}),
            ("GET", "/api/v1/tasks/t2"): _json(
                {"output": {"task_status": "SUCCEEDED", "video_url": "https://oss.example/v.mp4"}}
            ),
            ("GET", "/v.mp4"): _bytes(),
        }
        with _answering(routes) as seen:
            clip = await _make("alibaba", "wan3.0-video-prime")

        body = _body(seen[0])
        assert body["input"] == {"prompt": "A red bicycle in the rain."}
        assert body["parameters"] == {"resolution": "720P", "ratio": "16:9", "watermark": False}
        assert clip.seconds is None

    @pytest.mark.parametrize(
        ("output", "failure"),
        [
            ({"task_status": "FAILED", "code": "DataInspectionFailed"}, VideoFailure.POLICY),
            ({"task_status": "FAILED", "code": "InvalidApiKey"}, VideoFailure.CREDENTIALS),
            ({"task_status": "FAILED", "code": "InvalidParameter"}, VideoFailure.REJECTED),
            ({"task_status": "UNKNOWN"}, VideoFailure.UNAVAILABLE),
            ({"task_status": "SUCCEEDED"}, VideoFailure.UNAVAILABLE),
        ],
        ids=["policy", "key", "parameter", "unknown", "no address"],
    )
    async def test_a_settled_task_that_is_not_a_clip(self, output, failure):
        routes = {
            ("POST", self.SUBMIT): _json({"output": {"task_id": "t3"}}),
            ("GET", "/api/v1/tasks/t3"): _json({"output": output}),
        }
        with _answering(routes), pytest.raises(VideoProviderError) as caught:
            await _make("alibaba", "wan3.0-video")

        assert caught.value.failure is failure

    async def test_a_create_answer_without_a_task_is_unavailable(self):
        with (
            _answering({("POST", self.SUBMIT): _json({"output": {}})}),
            pytest.raises(VideoProviderError),
        ):
            await _make("alibaba", "wan3.0-video")


class TestARefusedOrBrokenAnswer:
    @pytest.mark.parametrize(
        ("status", "body", "failure"),
        [
            (401, "bad key", VideoFailure.CREDENTIALS),
            (403, "no access", VideoFailure.CREDENTIALS),
            (429, "slow down", VideoFailure.RATE_LIMITED),
            # Prepaid credit spent - Gemini's `payment_required` - is the quota.
            (402, '{"error":{"status":"payment_required"}}', VideoFailure.RATE_LIMITED),
            (400, '{"code":"InputTextSensitiveContentDetected"}', VideoFailure.POLICY),
            (400, '{"code":"InvalidParameter"}', VideoFailure.REJECTED),
            (500, "boom", VideoFailure.UNAVAILABLE),
        ],
    )
    async def test_says_what_went_wrong_and_not_what_the_provider_said(self, status, body, failure):
        leaked = f"{body} {KEY}"
        routes = {
            ("POST", "/v1/videos/generations"): lambda _r: httpx.Response(status, text=leaked)
        }
        with _answering(routes), pytest.raises(VideoProviderError) as caught:
            await _make("xai", "grok-imagine-video-1.5")

        assert caught.value.failure is failure
        assert caught.value.details == {
            "provider": "xai",
            "failure": failure.value,
            "status": status,
        }
        assert KEY not in caught.value.message

    async def test_only_the_providers_error_code_is_logged(self, caplog):
        body = f'{{"code":"InvalidParameter","message":"A red bicycle {KEY}"}}'
        routes = {("POST", "/v1/videos/generations"): lambda _r: httpx.Response(400, text=body)}
        with (
            caplog.at_level(logging.WARNING),
            _answering(routes),
            pytest.raises(VideoProviderError),
        ):
            await _make("xai", "grok-imagine-video-1.5")

        assert caplog.records[-1].getMessage().endswith("failed (400): InvalidParameter")
        assert KEY not in caplog.text and "red bicycle" not in caplog.text

    async def test_an_empty_download_is_no_clip(self):
        """A storage host answering 200 with nothing - a CDN still publishing the
        object - would otherwise be stored and shown as a zero-byte video."""
        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "r4"}),
            ("GET", "/v1/videos/r4"): _json(
                {"status": "done", "video": {"url": "https://vidgen.example/v.mp4"}}
            ),
            ("GET", "/v.mp4"): _bytes(b""),
        }
        with _answering(routes), pytest.raises(VideoProviderError) as caught:
            await _make("xai", "grok-imagine-video-1.5")

        assert caught.value.failure is VideoFailure.UNAVAILABLE

    @pytest.mark.parametrize("body", [b"not json", b"[1, 2]"], ids=["not JSON", "not an object"])
    async def test_an_answer_that_is_not_an_object_is_unavailable(self, body):
        routes = {("POST", "/v1/videos/generations"): _bytes(body)}
        with _answering(routes), pytest.raises(VideoProviderError) as caught:
            await _make("xai", "grok-imagine-video-1.5")

        assert caught.value.failure is VideoFailure.UNAVAILABLE

    @pytest.mark.parametrize("status", [403, 404])
    async def test_a_download_the_storage_host_refuses_is_unavailable(self, status):
        """An expired signed address says nothing about the key - the storage host
        never saw it - so the operator is not told to replace one."""
        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "r4"}),
            ("GET", "/v1/videos/r4"): _json(
                {"status": "done", "video": {"url": "https://vidgen.example/v.mp4"}}
            ),
            ("GET", "/v.mp4"): _bytes(b"gone", status=status),
        }
        with _answering(routes), pytest.raises(VideoProviderError) as caught:
            await _make("xai", "grok-imagine-video-1.5")

        assert caught.value.failure is VideoFailure.UNAVAILABLE
        assert caught.value.details["status"] == status

    async def test_a_download_past_the_size_limit_is_refused(self, monkeypatch):
        monkeypatch.setattr(clients_module, "MAX_BYTES", 4)
        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "r5"}),
            ("GET", "/v1/videos/r5"): _json(
                {"status": "done", "video": {"url": "https://vidgen.example/v.mp4"}}
            ),
            ("GET", "/v.mp4"): _bytes(),
        }
        with _answering(routes), pytest.raises(VideoProviderError) as caught:
            await _make("xai", "grok-imagine-video-1.5")

        assert caught.value.failure is VideoFailure.UNAVAILABLE

    @pytest.mark.parametrize(
        ("error", "failure"),
        [
            (httpx.ReadTimeout, VideoFailure.UNAVAILABLE),
            (httpx.ConnectError, VideoFailure.UNAVAILABLE),
        ],
    )
    async def test_a_transport_failure_is_a_refusal_too(self, error, failure):
        def fail(request: httpx.Request) -> httpx.Response:
            raise error("no", request=request)

        with (
            _answering({("POST", "/v1/videos/generations"): fail}),
            pytest.raises(VideoProviderError) as caught,
        ):
            await _make("xai", "grok-imagine-video-1.5")

        assert caught.value.failure is failure


class TestWhatTheCallerMustRefuseFirst:
    @pytest.mark.parametrize(
        ("provider", "model", "overrides"),
        [
            ("xai", "grok-imagine-video-9", {}),
            ("xai", "grok-imagine-video-1.5", {"resolution": "4k"}),
            ("xai", "grok-imagine-video-1.5", {"aspect_ratio": "5:4"}),
            ("byteplus", "dreamina-seedance-2-0-260128", {"duration": 16}),
            ("xai", "grok-imagine-video-1.5", {"prompt": "   "}),
        ],
        ids=["unknown model", "resolution", "aspect ratio", "too long", "blank prompt"],
    )
    async def test_a_request_the_model_cannot_make_is_refused_before_any_call(
        self, provider, model, overrides
    ):
        with _answering({}) as seen, pytest.raises(ValueError):
            await _make(provider, model, **overrides)

        assert seen == []

    async def test_a_model_that_takes_no_image_is_not_sent_one(self, monkeypatch):
        entry = video_models.CATALOG[2]
        no_frames = tuple(
            model.__class__(**{**model.__dict__, "first_frame": False}) for model in entry.models
        )
        monkeypatch.setattr(
            video_models, "CATALOG", (entry.__class__(**{**entry.__dict__, "models": no_frames}),)
        )

        with _answering({}) as seen, pytest.raises(ValueError):
            await _make("xai", "grok-imagine-video-1.5", first_frame=PNG)

        assert seen == []


async def test_the_pause_between_polls_really_waits():
    await REAL_PAUSE(0)


class TestTheKeyAndTheStorageHost:
    BASE = "/v1beta"

    def _gemini_routes(self, download: Route) -> dict[tuple[str, str], Route | list[Route]]:
        return {
            ("POST", f"{self.BASE}/interactions"): _json(
                {
                    "steps": [
                        {
                            "type": "model_output",
                            "content": [{"type": "video", "uri": "/v1beta/files/f9:download"}],
                        }
                    ]
                }
            ),
            ("GET", f"{self.BASE}/files/f9"): _json({"state": "ACTIVE"}),
            ("GET", f"{self.BASE}/files/f9:download"): download,
            ("GET", "/bucket/v.mp4"): _bytes(),
        }

    async def test_a_redirected_gemini_download_leaves_the_key_behind(self):
        """httpx strips only `Authorization` on a cross-host redirect, and Gemini's
        key is `x-goog-api-key` - so the redirect is followed here, without it."""
        to_storage = _redirect("https://storage.example/bucket/v.mp4")
        with _answering(self._gemini_routes(to_storage)) as seen:
            clip = await _make("google", "gemini-omni-1.1-flash")

        storage = seen[-1]
        assert storage.url.host == "storage.example"
        assert "x-goog-api-key" not in storage.headers
        assert clip.data == MP4

    async def test_a_redirect_to_plain_http_is_refused(self):
        to_http = _redirect("http://storage.example/bucket/v.mp4")
        with (
            _answering(self._gemini_routes(to_http)) as seen,
            pytest.raises(VideoProviderError) as caught,
        ):
            await _make("google", "gemini-omni-1.1-flash")

        assert caught.value.failure is VideoFailure.UNAVAILABLE
        assert all(request.url.host != "storage.example" for request in seen)

    async def test_a_redirect_loop_is_refused(self):
        def loop(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "/v1beta/files/f9:download"})

        with (
            _answering(self._gemini_routes(loop)) as seen,
            pytest.raises(VideoProviderError) as caught,
        ):
            await _make("google", "gemini-omni-1.1-flash")

        assert caught.value.failure is VideoFailure.UNAVAILABLE
        downloads = [request for request in seen if request.url.path.endswith(":download")]
        assert len(downloads) == clients_module.MAX_REDIRECTS + 1

    async def test_the_key_stays_on_the_same_host_and_goes_at_the_first_other_one(self):
        """A same-host hop may still need the key; once the download leaves for a
        storage host it never comes back."""
        hops = [
            _redirect("/v1beta/files/f9:download2"),
        ]
        routes = self._gemini_routes(hops[0])
        routes[("GET", f"{self.BASE}/files/f9:download2")] = _redirect(
            "https://storage.example/bucket/v.mp4"
        )
        with _answering(routes) as seen:
            await _make("google", "gemini-omni-1.1-flash")

        same_host = next(r for r in seen if r.url.path.endswith(":download2"))
        storage = seen[-1]
        assert same_host.headers["x-goog-api-key"] == KEY
        assert storage.url.host == "storage.example"
        assert "x-goog-api-key" not in storage.headers

    @pytest.mark.parametrize(
        "first",
        [lambda _r: httpx.Response(503), "timeout"],
        ids=["5xx", "timeout"],
    )
    async def test_a_transient_download_failure_is_tried_again(self, first):
        """The clip is finished and billed; one CDN hiccup must not lose it."""
        if first == "timeout":

            def first(request: httpx.Request) -> httpx.Response:
                raise httpx.ReadTimeout("slow", request=request)

        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "rd"}),
            ("GET", "/v1/videos/rd"): _json(
                {"status": "done", "video": {"url": "https://vidgen.example/v.mp4"}}
            ),
            ("GET", "/v.mp4"): [first, _bytes()],
        }
        with _answering(routes):
            clip = await _make("xai", "grok-imagine-video-1.5")

        assert clip.data == MP4

    async def test_a_download_that_keeps_failing_ends_at_the_grace_period(self, monkeypatch):
        monkeypatch.setattr(clients_module, "DOWNLOAD_GRACE_SECONDS", 0.0)
        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "re"}),
            ("GET", "/v1/videos/re"): _json(
                {"status": "done", "video": {"url": "https://vidgen.example/v.mp4"}}
            ),
            ("GET", "/v.mp4"): lambda _r: httpx.Response(503),
        }
        with _answering(routes), pytest.raises(VideoProviderError) as caught:
            await _make("xai", "grok-imagine-video-1.5", timeout_seconds=0.01)

        assert caught.value.failure is VideoFailure.TIMED_OUT

    @pytest.mark.parametrize(
        "url", ["http://tos.example/v.mp4", "https://[::1", ""], ids=["http", "invalid", "empty"]
    )
    async def test_an_address_that_is_not_https_is_not_fetched(self, url):
        routes = {
            ("POST", "/api/v3/contents/generations/tasks"): _json({"id": "cgt-9"}),
            ("GET", "/api/v3/contents/generations/tasks/cgt-9"): _json(
                {"status": "succeeded", "content": {"video_url": url}}
            ),
        }
        with _answering(routes) as seen, pytest.raises(VideoProviderError) as caught:
            await _make("byteplus", "dreamina-seedance-2-0-260128")

        assert caught.value.failure is VideoFailure.UNAVAILABLE
        assert len(seen) == 2

    async def test_a_download_past_the_jobs_deadline_times_out(self, monkeypatch):
        monkeypatch.setattr(clients_module, "DOWNLOAD_GRACE_SECONDS", -10_000.0)
        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "r8"}),
            ("GET", "/v1/videos/r8"): _json(
                {"status": "done", "video": {"url": "https://vidgen.example/v.mp4"}}
            ),
            ("GET", "/v.mp4"): _bytes(),
        }
        with _answering(routes), pytest.raises(VideoProviderError) as caught:
            await _make("xai", "grok-imagine-video-1.5")

        assert caught.value.failure is VideoFailure.TIMED_OUT


class TestAStatusReadThatFails:
    @pytest.mark.parametrize(
        "first",
        [
            "timeout",
            lambda _r: httpx.Response(503),
            lambda _r: httpx.Response(429),
        ],
        ids=["timeout", "5xx", "429"],
    )
    async def test_is_read_again_rather_than_abandoning_a_billed_job(self, first):
        """The job is still running and billed; giving up would send the model to
        start a second one."""
        if first == "timeout":

            def first(request: httpx.Request) -> httpx.Response:
                raise httpx.ReadTimeout("slow", request=request)

        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "r9"}),
            ("GET", "/v1/videos/r9"): [
                first,
                _json({"status": "done", "video": {"url": "https://vidgen.example/v.mp4"}}),
            ],
            ("GET", "/v.mp4"): _bytes(),
        }
        with _answering(routes):
            clip = await _make("xai", "grok-imagine-video-1.5")

        assert clip.data == MP4

    @pytest.mark.parametrize(
        "first",
        [lambda _r: httpx.Response(408), lambda _r: httpx.Response(200, content=b"<html>")],
        ids=["408", "a 2xx that is not JSON"],
    )
    async def test_a_passing_hiccup_is_read_again_too(self, first):
        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "rh"}),
            ("GET", "/v1/videos/rh"): [
                first,
                _json({"status": "done", "video": {"url": "https://vidgen.example/v.mp4"}}),
            ],
            ("GET", "/v.mp4"): _bytes(),
        }
        with _answering(routes):
            assert (await _make("xai", "grok-imagine-video-1.5")).data == MP4

    async def test_a_refusal_ends_the_poll_at_once(self):
        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "rf"}),
            ("GET", "/v1/videos/rf"): lambda _r: httpx.Response(400, text="bad id"),
        }
        with _answering(routes) as seen, pytest.raises(VideoProviderError) as caught:
            await _make("xai", "grok-imagine-video-1.5")

        assert caught.value.failure is VideoFailure.REJECTED
        assert len([r for r in seen if r.method == "GET"]) == 1

    async def test_a_proxy_that_refuses_is_not_retried_until_the_deadline(self):
        def proxy(request: httpx.Request) -> httpx.Response:
            raise httpx.ProxyError("no", request=request)

        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "rp"}),
            ("GET", "/v1/videos/rp"): proxy,
        }
        with _answering(routes) as seen, pytest.raises(VideoProviderError) as caught:
            await _make("xai", "grok-imagine-video-1.5")

        assert caught.value.failure is VideoFailure.UNAVAILABLE
        assert len([r for r in seen if r.method == "GET"]) == 1

    async def test_one_slow_request_past_the_deadline_is_a_timeout(self):
        def slow(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        with (
            _answering({("POST", "/v1/videos/generations"): slow}),
            pytest.raises(VideoProviderError) as caught,
        ):
            await _make("xai", "grok-imagine-video-1.5", timeout_seconds=-1.0)

        assert caught.value.failure is VideoFailure.TIMED_OUT


class TestAnAnswerOfTheWrongShape:
    @pytest.mark.parametrize(
        ("provider", "model", "routes"),
        [
            (
                "google",
                "gemini-omni-1.1-flash",
                {("POST", "/v1beta/interactions"): _json({"steps": "nope"})},
            ),
            (
                "google",
                "gemini-omni-1.1-flash",
                {("POST", "/v1beta/interactions"): _json({})},
            ),
            (
                "google",
                "gemini-omni-1.1-flash",
                {
                    ("POST", "/v1beta/interactions"): _json(
                        {"steps": [{"type": "model_output", "content": 7}]}
                    )
                },
            ),
            (
                "byteplus",
                "dreamina-seedance-2-0-260128",
                {
                    ("POST", "/api/v3/contents/generations/tasks"): _json({"id": "c"}),
                    ("GET", "/api/v3/contents/generations/tasks/c"): _json(
                        {"status": "succeeded", "content": []}
                    ),
                },
            ),
            (
                "xai",
                "grok-imagine-video-1.5",
                {
                    ("POST", "/v1/videos/generations"): _json({"request_id": "r"}),
                    ("GET", "/v1/videos/r"): _json({"status": "done", "video": "x"}),
                },
            ),
            (
                "alibaba",
                "wan3.0-video",
                {
                    ("POST", "/api/v1/services/aigc/video-generation/video-synthesis"): _json(
                        {"output": []}
                    )
                },
            ),
            (
                "alibaba",
                "wan3.0-video",
                {
                    ("POST", "/api/v1/services/aigc/video-generation/video-synthesis"): _json(
                        {"output": {"task_id": "t"}}
                    ),
                    ("GET", "/api/v1/tasks/t"): _json({"output": "x"}),
                },
            ),
        ],
        ids=[
            "gemini steps",
            "gemini no steps",
            "gemini content",
            "byteplus content",
            "xai video",
            "alibaba create",
            "alibaba task",
        ],
    )
    async def test_is_unavailable_rather_than_a_crash(self, provider, model, routes):
        with _answering(routes), pytest.raises(VideoProviderError) as caught:
            await _make(provider, model)

        assert caught.value.failure is VideoFailure.UNAVAILABLE


@pytest.mark.parametrize(
    ("status", "body", "failure"),
    [
        (400, '{"error":{"details":[{"reason":"API_KEY_INVALID"}]}}', VideoFailure.CREDENTIALS),
        (408, "slow", VideoFailure.UNAVAILABLE),
    ],
    ids=["gemini bad key", "request timeout"],
)
async def test_the_providers_reason_outranks_its_status(status, body, failure):
    routes = {("POST", "/v1/videos/generations"): lambda _r: httpx.Response(status, text=body)}
    with _answering(routes), pytest.raises(VideoProviderError) as caught:
        await _make("xai", "grok-imagine-video-1.5")

    assert caught.value.failure is failure


def test_every_api_shape_the_catalog_accepts_has_a_client():
    from app.services.video_generation.clients import CLIENTS
    from app.services.video_models import SUPPORTED_APIS

    assert frozenset(CLIENTS) == SUPPORTED_APIS


def test_a_video_call_keeps_its_key_out_of_its_repr():
    from app.services.video_generation.clients import VideoCall

    call = VideoCall(
        provider="xai",
        base_url="https://x",
        api_key=KEY,
        model="m",
        prompt="p",
        resolution="720p",
        aspect_ratio="16:9",
    )

    assert KEY not in repr(call)


@pytest.mark.parametrize(
    ("status", "body", "failure"),
    [
        (500, "echo: invalid api key", VideoFailure.UNAVAILABLE),
        (429, "invalid api key", VideoFailure.RATE_LIMITED),
        (400, "value is case-sensitive", VideoFailure.REJECTED),
        (400, '{"code":"InputTextSensitiveContentDetected"}', VideoFailure.POLICY),
    ],
    ids=["outage echoing a key", "rate limit echoing a key", "case-sensitive", "sensitive content"],
)
async def test_the_status_is_read_before_the_body(status, body, failure):
    """A rate limit or an outage must not tell the operator to rotate a working key."""
    routes = {("POST", "/v1/videos/generations"): lambda _r: httpx.Response(status, text=body)}
    with _answering(routes), pytest.raises(VideoProviderError) as caught:
        await _make("xai", "grok-imagine-video-1.5")

    assert caught.value.failure is failure


async def test_an_xai_job_done_with_no_address_field_is_malformed_not_moderated():
    routes = {
        ("POST", "/v1/videos/generations"): _json({"request_id": "rx"}),
        ("GET", "/v1/videos/rx"): _json({"status": "done", "video": {"duration": 5}}),
    }
    with _answering(routes), pytest.raises(VideoProviderError) as caught:
        await _make("xai", "grok-imagine-video-1.5")

    assert caught.value.failure is VideoFailure.UNAVAILABLE


async def test_an_inline_gemini_clip_past_the_size_limit_is_refused_before_decoding(monkeypatch):
    monkeypatch.setattr(clients_module, "MAX_BYTES", 4)
    payload = {
        "steps": [
            {
                "type": "model_output",
                "content": [{"type": "video", "data": base64.b64encode(MP4).decode()}],
            }
        ]
    }
    with (
        _answering({("POST", "/v1beta/interactions"): _json(payload)}),
        pytest.raises(VideoProviderError) as caught,
    ):
        await _make("google", "gemini-omni-1.1-flash")

    assert caught.value.failure is VideoFailure.UNAVAILABLE


async def test_a_submit_answered_with_neither_success_nor_error_is_unavailable():
    """A redirect on the submit is not followed: the key would go with it."""
    routes = {("POST", "/v1/videos/generations"): _redirect("https://elsewhere.example/x")}
    with _answering(routes), pytest.raises(VideoProviderError) as caught:
        await _make("xai", "grok-imagine-video-1.5")

    assert caught.value.failure is VideoFailure.UNAVAILABLE


async def test_a_status_read_that_is_no_object_is_unavailable():
    routes = {
        ("POST", "/v1/videos/generations"): _json({"request_id": "rl"}),
        ("GET", "/v1/videos/rl"): _json([1, 2]),
    }
    with _answering(routes), pytest.raises(VideoProviderError) as caught:
        await _make("xai", "grok-imagine-video-1.5")

    assert caught.value.failure is VideoFailure.UNAVAILABLE


async def test_a_host_trickling_bytes_past_the_grace_period_times_out(monkeypatch):
    """A per-read timeout alone lets a byte every few seconds run for ever."""
    monkeypatch.setattr(clients_module, "DOWNLOAD_GRACE_SECONDS", 0.05)

    async def trickle():
        yield b"a"
        await asyncio.sleep(0.1)
        yield b"b"

    routes = {
        ("POST", "/v1/videos/generations"): _json({"request_id": "rt"}),
        ("GET", "/v1/videos/rt"): _json(
            {"status": "done", "video": {"url": "https://vidgen.example/v.mp4"}}
        ),
        ("GET", "/v.mp4"): lambda _r: httpx.Response(200, content=trickle()),
    }
    with _answering(routes), pytest.raises(VideoProviderError) as caught:
        await _make("xai", "grok-imagine-video-1.5", timeout_seconds=0.0)

    assert caught.value.failure is VideoFailure.TIMED_OUT


@pytest.mark.parametrize(
    ("provider", "model", "routes"),
    [
        (
            "byteplus",
            "dreamina-seedance-2-0-260128",
            {
                ("POST", "/api/v3/contents/generations/tasks"): _json({"id": "t1"}),
                ("GET", "/api/v3/contents/generations/tasks/t1"): _json(
                    {"status": "succeeded", "content": {"video_url": "https://cdn.example/v.mp4"}}
                ),
                ("GET", "/v.mp4"): _bytes(b"", status=403),
            },
        ),
        (
            "xai",
            "grok-imagine-video-1.5",
            {
                ("POST", "/v1/videos/generations"): _json({"request_id": "r1"}),
                ("GET", "/v1/videos/r1"): _json(
                    {"status": "done", "video": {"url": "https://vidgen.example/v.mp4"}}
                ),
                ("GET", "/v.mp4"): _bytes(b"", status=403),
            },
        ),
    ],
    ids=["byteplus", "xai"],
)
async def test_a_clip_made_and_not_fetched_reports_both_stages(provider, model, routes):
    """`made` is what tells the tool the provider billed a clip it could not hand over."""
    stages: list[str] = []
    with _answering(routes), pytest.raises(VideoProviderError):
        await _make(provider, model, reached=stages.append)

    assert stages == ["submitted", "made"]


async def test_a_call_cancelled_where_the_provider_has_no_cancel_just_stops(
    monkeypatch: pytest.MonkeyPatch,
):
    """xAI documents no cancel, so a run that went away sends nothing more."""
    monkeypatch.setattr(clients_module, "_pause", lambda _seconds: anyio.sleep(0.01))
    routes = {
        ("POST", "/v1/videos/generations"): _json({"request_id": "r2"}),
        ("GET", "/v1/videos/r2"): _json({"status": "pending"}),
    }
    with _answering(routes) as seen, anyio.move_on_after(0.2):
        await _make("xai", "grok-imagine-video-1.5")

    assert {r.method for r in seen} == {"POST", "GET"}


@pytest.mark.parametrize(
    ("answer", "stages"),
    [
        (httpx.ReadTimeout, ["sent"]),
        (httpx.RemoteProtocolError, ["sent"]),
        (httpx.ConnectError, []),
        (httpx.ConnectTimeout, []),
    ],
    ids=["read-timeout", "dropped", "never-connected", "connect-timeout"],
)
async def test_a_creation_request_lost_in_transit_reports_sent_only_if_it_may_have_left(
    answer, stages
):
    """A job the provider may have taken with no answer to say so may be billed."""

    def lost(request: httpx.Request) -> httpx.Response:
        raise answer("lost", request=request)

    seen: list[str] = []
    with _answering({("POST", "/v1/videos/generations"): lost}), pytest.raises(VideoProviderError):
        await _make("xai", "grok-imagine-video-1.5", reached=seen.append)

    assert seen == stages


@pytest.mark.parametrize(
    ("provider", "model", "path"),
    [
        ("xai", "grok-imagine-video-1.5", "/v1/videos/generations"),
        ("byteplus", "dreamina-seedance-2-0-260128", "/api/v3/contents/generations/tasks"),
    ],
    ids=["xai", "byteplus"],
)
async def test_an_accepted_request_that_names_no_job_reports_sent(provider, model, path):
    seen: list[str] = []
    with _answering({("POST", path): _json({"status": "ok"})}), pytest.raises(VideoProviderError):
        await _make(provider, model, reached=seen.append)

    assert seen == ["sent"]


async def test_a_refused_submission_reports_no_stage():
    stages: list[str] = []
    routes = {("POST", "/v1/videos/generations"): lambda _r: httpx.Response(400, text="{}")}
    with _answering(routes), pytest.raises(VideoProviderError):
        await _make("xai", "grok-imagine-video-1.5", reached=stages.append)

    assert stages == []

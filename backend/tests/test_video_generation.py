"""Making a video through each provider, and what a failed or slow job may say.

Every provider is answered by a `MockTransport` routing on method and path, so
these pin the request each one is sent - the key in a header, never to a storage
host - the job each is polled for, and what is made of the answer: the clip's
bytes fetched before the address expires, and a refusal that never carries the
provider's own words.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

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
            "store": False,
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
            {"type": "text", "text": "A red bicycle in the rain."},
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

    @pytest.mark.parametrize(
        ("job", "failure"),
        [
            (
                {"status": "done", "video": {"url": "", "respect_moderation": False}},
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
        ids=["withheld by moderation", "key", "argument", "down", "no error"],
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

    @pytest.mark.parametrize("body", [b"not json", b"[1, 2]"], ids=["not JSON", "not an object"])
    async def test_an_answer_that_is_not_an_object_is_unavailable(self, body):
        routes = {("POST", "/v1/videos/generations"): _bytes(body)}
        with _answering(routes), pytest.raises(VideoProviderError) as caught:
            await _make("xai", "grok-imagine-video-1.5")

        assert caught.value.failure is VideoFailure.UNAVAILABLE

    async def test_a_download_the_storage_host_refuses_is_unavailable(self):
        routes = {
            ("POST", "/v1/videos/generations"): _json({"request_id": "r4"}),
            ("GET", "/v1/videos/r4"): _json(
                {"status": "done", "video": {"url": "https://vidgen.example/v.mp4"}}
            ),
            ("GET", "/v.mp4"): _bytes(b"gone", status=404),
        }
        with _answering(routes), pytest.raises(VideoProviderError):
            await _make("xai", "grok-imagine-video-1.5")

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
            (httpx.ReadTimeout, VideoFailure.TIMED_OUT),
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

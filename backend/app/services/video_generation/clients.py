"""One function per API shape, each turning one request into the bytes of a video.

Gemini answers in the call itself; BytePlus, xAI and Alibaba each take a job,
are polled until it settles, and hand back an address the clip is downloaded
from. Every address they hand back expires - within a day for most of them - so
the bytes are fetched here, before the call returns, and the platform keeps its
own copy (:mod:`app.agents.capabilities._generated`).

**Time is the binding's.** A job is polled until it settles or the deadline the
caller set passes. Past it, a job the provider can cancel is cancelled - BytePlus
cancels one still queued - and the call fails as timed out. xAI and Alibaba
document no cancel, so a job there may still finish and be billed; that is said
in the capability's documentation rather than hidden.

The key travels in a header and only there, and never to a download address: a
provider's storage URL is signed already, and a key sent there is a key handed
to a storage host. A provider's response body is logged where it is received
and never put in the exception.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.services.video_generation.exceptions import VideoFailure, VideoProviderError

logger = logging.getLogger(__name__)

MAX_BYTES = 300 * 1024 * 1024
"""The largest clip downloaded. Thirty seconds of 4K is well under it; a body
past it is a provider answering with something that is not one clip."""

POLL_SECONDS = {
    "byteplus_tasks": 5.0,
    "xai_videos": 5.0,
    "dashscope_tasks": 15.0,
    "gemini_files": 3.0,
}
"""How long to wait between polls, per API. Alibaba asks for no more than one
poll in fifteen seconds of a long job; the others take a status read every few."""

POLL_REQUEST_SECONDS = 30.0
"""The longest one status read may take; never past the job's own deadline."""

DOWNLOAD_GRACE_SECONDS = 120.0
"""How far past the job's deadline the download of a finished clip may run. A clip
done at the last moment is worth fetching; one trickling in for ever is not."""

MAX_REDIRECTS = 5

_POLICY_MARKERS = ("sensitive", "policyviolation", "datainspection", "ipinfringement", "moderation")
"""Fragments of a provider's error code that mean its content policy refused."""

_KEY_MARKERS = ("api_key_invalid", "invalid api key", "invalidapikey")
"""Fragments that mean the key was refused, whatever the status. Gemini answers a
bad key with 400 and `API_KEY_INVALID`, which by status alone reads as a request
the model should try again."""


@dataclass(frozen=True)
class FirstFrame:
    """An image the clip starts from."""

    data: bytes
    mime_type: str

    def data_uri(self) -> str:
        return f"data:{self.mime_type};base64,{base64.b64encode(self.data).decode()}"


@dataclass(frozen=True)
class VideoCall:
    """One clip's worth of request, already within the model's limits."""

    provider: str
    base_url: str
    # A dataclass repr ends up in log lines and traceback frames.
    api_key: str = field(repr=False)
    model: str
    prompt: str
    resolution: str
    aspect_ratio: str
    duration: int | None = None
    """Seconds, or `None` where the model decides its own length."""

    audio: bool | None = None
    """Whether the clip carries sound, or `None` where the model decides."""

    first_frame: FirstFrame | None = None


@dataclass(frozen=True)
class Clip:
    """A finished video, and how long the provider says it is."""

    data: bytes
    seconds: float | None


Client = Callable[[httpx.AsyncClient, VideoCall, float], Awaitable[Clip]]
"""A client takes the HTTP client, the call, and the deadline on the loop's clock."""


async def _pause(seconds: float) -> None:
    """The wait between polls - its own function so a test can make it instant."""
    await asyncio.sleep(seconds)


def _failure_for(status: int, body: str) -> VideoFailure:
    lowered = body.lower()
    if status in (401, 403) or any(marker in lowered for marker in _KEY_MARKERS):
        return VideoFailure.CREDENTIALS
    if status == 429:
        return VideoFailure.RATE_LIMITED
    if status == 408:
        return VideoFailure.UNAVAILABLE
    if 400 <= status < 500:
        if any(marker in lowered for marker in _POLICY_MARKERS):
            return VideoFailure.POLICY
        return VideoFailure.REJECTED
    return VideoFailure.UNAVAILABLE


def _raise_for(call: VideoCall, response: httpx.Response) -> None:
    """Refuse a non-2xx answer, logging what the provider said and keeping it out."""
    if response.is_success:
        return
    body = response.text[:2000]
    logger.warning(
        "Video request to %s for model %s failed (%s): %s",
        call.provider,
        call.model,
        response.status_code,
        body,
    )
    raise VideoProviderError(
        _failure_for(response.status_code, body),
        provider=call.provider,
        status=response.status_code,
    )


def _dict(call: VideoCall, value: object) -> dict[str, Any]:
    """A nested object of a provider's answer, or a refusal where it is not one."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _unusable(call)
    return value


def _dicts(call: VideoCall, value: object) -> list[dict[str, Any]]:
    """A nested list of objects, keeping the objects; a refusal where it is no list."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise _unusable(call)
    return [item for item in value if isinstance(item, dict)]


def _storage_url(call: VideoCall, value: object) -> httpx.URL:
    """A clip's address, which must be https: it came from a provider's answer."""
    if not isinstance(value, str) or not value:
        raise _unusable(call)
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        raise _unusable(call) from None
    if url.scheme != "https" or not url.host:
        raise _unusable(call)
    return url


def _job_failure(call: VideoCall, code: object) -> VideoProviderError:
    """A job the provider marked failed, by the error code it gave."""
    logger.warning("Video job at %s for model %s failed: %s", call.provider, call.model, code)
    lowered = str(code or "").lower()
    if any(marker in lowered for marker in _POLICY_MARKERS):
        return VideoProviderError(VideoFailure.POLICY, provider=call.provider)
    if lowered in {"permission_denied", "invalidapikey"}:
        return VideoProviderError(VideoFailure.CREDENTIALS, provider=call.provider)
    if lowered in {"service_unavailable", "internal_error", ""}:
        return VideoProviderError(VideoFailure.UNAVAILABLE, provider=call.provider)
    return VideoProviderError(VideoFailure.REJECTED, provider=call.provider)


def _unusable(call: VideoCall) -> VideoProviderError:
    logger.warning("Video answer from %s for model %s had no video", call.provider, call.model)
    return VideoProviderError(VideoFailure.UNAVAILABLE, provider=call.provider)


async def _download(
    client: httpx.AsyncClient,
    call: VideoCall,
    url: httpx.URL,
    deadline: float,
    headers: dict[str, str] | None = None,
) -> bytes:
    """Fetch the finished clip, refusing a body past :data:`MAX_BYTES`.

    Redirects are followed here rather than by httpx, which strips only an
    `Authorization` header on the way to another host: Gemini's key travels as
    `x-goog-api-key`, so it would reach whatever storage host the download
    redirects to. The key goes to the first address only, every hop must be https,
    and the whole fetch ends a grace period after the job's own deadline.
    """
    sent = headers or {}
    loop = asyncio.get_running_loop()
    ends = deadline + DOWNLOAD_GRACE_SECONDS

    def overdue() -> None:
        if loop.time() > ends:
            raise TimeoutError

    try:
        # The timeout catches a host that stops answering; the checks below, one
        # that keeps trickling bytes or redirecting.
        async with asyncio.timeout_at(ends):
            for _ in range(MAX_REDIRECTS + 1):
                overdue()
                async with client.stream("GET", url, headers=sent) as response:
                    if response.is_redirect:
                        url = _storage_url(
                            call, str(url.join(response.headers.get("location", "")))
                        )
                        sent = {}
                        continue
                    if not response.is_success:
                        # A signed address that expired or is refused says nothing
                        # about the key: the storage host never saw it.
                        logger.warning(
                            "Video download from %s failed (%s)",
                            call.provider,
                            response.status_code,
                        )
                        raise VideoProviderError(
                            VideoFailure.UNAVAILABLE,
                            provider=call.provider,
                            status=response.status_code,
                        )
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise _unusable(call)
                        overdue()
                    return bytes(data)
    except TimeoutError:
        raise VideoProviderError(VideoFailure.TIMED_OUT, provider=call.provider) from None
    raise _unusable(call)


async def _poll(
    client: httpx.AsyncClient,
    call: VideoCall,
    deadline: float,
    *,
    url: str,
    headers: dict[str, str],
    every: float,
    settled: Callable[[dict[str, Any]], bool],
    cancel: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Read a job's status until it settles, or cancel it once the deadline passes.

    A status read that times out, cannot connect, or is answered 5xx or 429 says
    nothing about the job, which is still running and billed: it is read again
    until the deadline rather than abandoned - abandoning it would tell the model
    to start a second, billed job. A read the provider refuses for another reason
    ends the poll.
    """
    loop = asyncio.get_running_loop()
    while True:
        remaining = deadline - loop.time()
        try:
            response = await client.get(
                url, headers=headers, timeout=max(min(POLL_REQUEST_SECONDS, remaining), 1.0)
            )
        except httpx.TransportError:
            logger.info("Status read at %s failed in transit; reading again", call.provider)
        else:
            if response.status_code == 429 or response.status_code >= 500:
                logger.info(
                    "Status read at %s answered %s; reading again",
                    call.provider,
                    response.status_code,
                )
            else:
                _raise_for(call, response)
                payload = _json(call, response)
                if settled(payload):
                    return payload
        remaining = deadline - loop.time()
        if remaining <= 0:
            if cancel is not None:
                await cancel()
            raise VideoProviderError(VideoFailure.TIMED_OUT, provider=call.provider)
        await _pause(min(every, remaining))


def _json(call: VideoCall, response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        raise _unusable(call) from None
    if not isinstance(payload, dict):
        raise _unusable(call)
    return payload


async def gemini_interactions(client: httpx.AsyncClient, call: VideoCall, deadline: float) -> Clip:
    """`POST /interactions` with a video response, delivered as a Files API file.

    Asked for by address rather than inline because a clip over 4 MB must be: the
    file is polled until it is ready, then downloaded with the key, which the
    Files API - unlike a storage host - needs. Omni decides the length itself, so
    none is sent; its sound is always on.
    """
    headers = {"x-goog-api-key": call.api_key}
    prompt: object = call.prompt
    if call.first_frame is not None:
        prompt = [
            {
                "type": "image",
                "data": base64.b64encode(call.first_frame.data).decode(),
                "mime_type": call.first_frame.mime_type,
            },
            {"type": "text", "text": call.prompt},
        ]
    response = await client.post(
        f"{call.base_url}/interactions",
        headers=headers,
        json={
            "model": call.model,
            "input": prompt,
            "response_format": {
                "type": "video",
                "aspect_ratio": call.aspect_ratio,
                "resolution": call.resolution,
                "delivery": "uri",
            },
            "background": False,
            "store": False,
            "stream": False,
        },
        timeout=max(deadline - asyncio.get_running_loop().time(), 1.0),
    )
    _raise_for(call, response)
    video = next(
        (
            content
            for step in _dicts(call, _json(call, response).get("steps"))
            if step.get("type") == "model_output"
            for content in _dicts(call, step.get("content"))
            if content.get("type") == "video"
        ),
        None,
    )
    if video is None:
        raise _unusable(call)
    if isinstance(video.get("data"), str):
        try:
            return Clip(data=base64.b64decode(video["data"], validate=True), seconds=None)
        except binascii.Error:
            raise _unusable(call) from None
    found = re.search(r"/files/([^/:?]+)", str(video.get("uri") or ""))
    if found is None:
        raise _unusable(call)
    file_url = f"{call.base_url}/files/{found.group(1)}"
    ready = await _poll(
        client,
        call,
        deadline,
        url=file_url,
        headers=headers,
        every=POLL_SECONDS["gemini_files"],
        settled=lambda file: file.get("state") in {"ACTIVE", "FAILED"},
    )
    if ready.get("state") == "FAILED":
        raise _job_failure(call, "")
    return Clip(
        data=await _download(
            client, call, _storage_url(call, f"{file_url}:download?alt=media"), deadline, headers
        ),
        seconds=None,
    )


async def byteplus_tasks(client: httpx.AsyncClient, call: VideoCall, deadline: float) -> Clip:
    """`POST /contents/generations/tasks`, polled, then the clip downloaded.

    Parameters go as JSON fields - the strict form BytePlus recommends - never as
    `--flags` in the prompt. Seedance 2.5 starts from an image only at its
    `adaptive` ratio, which follows the image's own shape.
    """
    headers = {"Authorization": f"Bearer {call.api_key}"}
    content: list[dict[str, object]] = [{"type": "text", "text": call.prompt}]
    ratio = call.aspect_ratio
    if call.first_frame is not None:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": call.first_frame.data_uri()},
                "role": "first_frame",
            }
        )
        if "seedance-2-5" in call.model:
            ratio = "adaptive"
    body: dict[str, object] = {
        "model": call.model,
        "content": content,
        "resolution": call.resolution,
        "ratio": ratio,
        "watermark": False,
    }
    if call.duration is not None:
        body["duration"] = call.duration
    if call.audio is not None:
        body["generate_audio"] = call.audio
    response = await client.post(
        f"{call.base_url}/contents/generations/tasks", headers=headers, json=body
    )
    _raise_for(call, response)
    task_id = _json(call, response).get("id")
    if not isinstance(task_id, str):
        raise _unusable(call)
    task_url = f"{call.base_url}/contents/generations/tasks/{task_id}"

    async def cancel() -> None:
        # Only a queued task can be cancelled; on a running one this is refused,
        # and either way the timeout is what the caller hears about.
        try:
            await client.delete(task_url, headers=headers)
        except httpx.HTTPError:
            logger.info("Cancelling video task at %s failed", call.provider, exc_info=True)

    task = await _poll(
        client,
        call,
        deadline,
        url=task_url,
        headers=headers,
        every=POLL_SECONDS["byteplus_tasks"],
        settled=lambda job: job.get("status") not in {"queued", "running"},
        cancel=cancel,
    )
    if task.get("status") != "succeeded":
        error = task.get("error")
        raise _job_failure(call, error.get("code") if isinstance(error, dict) else "")
    url = _storage_url(call, _dict(call, task.get("content")).get("video_url"))
    duration = task.get("duration")
    return Clip(
        data=await _download(client, call, url, deadline),
        seconds=float(duration) if isinstance(duration, int | float) else None,
    )


async def xai_videos(client: httpx.AsyncClient, call: VideoCall, deadline: float) -> Clip:
    """`POST /videos/generations`, polled at `GET /videos/{request_id}`.

    xAI ignores an aspect ratio when it starts from an image - the image sets the
    shape - so none is sent then. Its clips always carry sound.
    """
    headers = {"Authorization": f"Bearer {call.api_key}"}
    body: dict[str, object] = {
        "model": call.model,
        "prompt": call.prompt,
        "resolution": call.resolution,
    }
    if call.duration is not None:
        body["duration"] = call.duration
    if call.first_frame is not None:
        body["image"] = {"url": call.first_frame.data_uri()}
    else:
        body["aspect_ratio"] = call.aspect_ratio
    response = await client.post(f"{call.base_url}/videos/generations", headers=headers, json=body)
    _raise_for(call, response)
    request_id = _json(call, response).get("request_id")
    if not isinstance(request_id, str):
        raise _unusable(call)
    job = await _poll(
        client,
        call,
        deadline,
        url=f"{call.base_url}/videos/{request_id}",
        headers=headers,
        every=POLL_SECONDS["xai_videos"],
        settled=lambda job: job.get("status") != "pending",
    )
    if job.get("status") != "done":
        error = job.get("error")
        raise _job_failure(call, error.get("code") if isinstance(error, dict) else "")
    video = _dict(call, job.get("video"))
    if not video.get("url"):
        # `respect_moderation: false` comes back done with an empty address: the
        # clip was made and withheld by xAI's own moderation.
        raise VideoProviderError(VideoFailure.POLICY, provider=call.provider)
    url = _storage_url(call, video.get("url"))
    duration = video.get("duration")
    return Clip(
        data=await _download(client, call, url, deadline),
        seconds=float(duration) if isinstance(duration, int | float) else None,
    )


async def dashscope_tasks(client: httpx.AsyncClient, call: VideoCall, deadline: float) -> Clip:
    """DashScope's asynchronous video synthesis, polled at `GET /tasks/{task_id}`.

    The resolution is upper case on this API (`720P`), and a first frame is one
    entry in `input.media`, which a text-only request leaves out.
    """
    headers = {"Authorization": f"Bearer {call.api_key}"}
    request_input: dict[str, object] = {"prompt": call.prompt}
    if call.first_frame is not None:
        request_input["media"] = [{"type": "first_frame", "url": call.first_frame.data_uri()}]
    parameters: dict[str, object] = {
        "resolution": call.resolution.upper(),
        "ratio": call.aspect_ratio,
        "watermark": False,
    }
    if call.duration is not None:
        parameters["duration"] = call.duration
    if call.audio is not None:
        parameters["audio"] = call.audio
    response = await client.post(
        f"{call.base_url}/services/aigc/video-generation/video-synthesis",
        headers={**headers, "X-DashScope-Async": "enable"},
        json={"model": call.model, "input": request_input, "parameters": parameters},
    )
    _raise_for(call, response)
    task_id = _dict(call, _json(call, response).get("output")).get("task_id")
    if not isinstance(task_id, str):
        raise _unusable(call)
    task = await _poll(
        client,
        call,
        deadline,
        url=f"{call.base_url}/tasks/{task_id}",
        headers=headers,
        every=POLL_SECONDS["dashscope_tasks"],
        # An `output` that is no object settles the poll, to be refused below.
        settled=lambda job: (
            not isinstance(job.get("output"), dict)
            or job["output"].get("task_status") not in {"PENDING", "RUNNING"}
        ),
    )
    output = _dict(call, task.get("output"))
    if output.get("task_status") != "SUCCEEDED":
        raise _job_failure(call, output.get("code"))
    url = _storage_url(call, output.get("video_url"))
    seconds = _dict(call, task.get("usage")).get("output_video_duration")
    return Clip(
        data=await _download(client, call, url, deadline),
        seconds=float(seconds) if isinstance(seconds, int | float) else None,
    )


CLIENTS: dict[str, Client] = {
    "gemini_interactions": gemini_interactions,
    "byteplus_tasks": byteplus_tasks,
    "xai_videos": xai_videos,
    "dashscope_tasks": dashscope_tasks,
}
"""The client for each API shape the catalog may name."""

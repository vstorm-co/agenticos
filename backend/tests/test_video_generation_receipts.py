"""Workflow recovery collects known provider jobs; it never resubmits them."""

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock

import httpx
import httpx2
import pytest
from pydantic import ValidationError

from app.core import pinned_http
from app.core.sanitize import PinnedAddress
from app.services import video_models
from app.services.video_generation import (
    VideoFailure,
    VideoProviderError,
    VideoReceipt,
    generate_video,
)
from app.services.video_generation import clients as clients_module
from app.services.video_generation import generation as generation_module

pytestmark = pytest.mark.anyio

PROVIDERS = ("google", "byteplus", "xai", "alibaba")
KEY = "synthetic-video-key"
CLIP = b"synthetic-mp4-output"
OPAQUE = "job_123-abc"


@dataclass
class Offering:
    provider: video_models.VideoProvider
    model: video_models.VideoModel
    submit: str
    poll: str
    download: str

    def receipt(self, **changes):
        return VideoReceipt.model_validate(
            {
                "provider": self.provider.provider,
                "api": self.provider.api,
                "model": self.model.id,
                "kind": "file" if self.provider.provider == "google" else "job",
                "id": OPAQUE,
                **changes,
            }
        )

    def accepted(self, *, opaque_id=OPAQUE):
        match self.provider.provider:
            case "google":
                return {
                    "steps": [
                        {
                            "type": "model_output",
                            "content": [
                                {
                                    "type": "video",
                                    "uri": f"{self.provider.base_url}/files/{opaque_id}:download",
                                }
                            ],
                        }
                    ]
                }
            case "byteplus":
                return {"id": opaque_id}
            case "xai":
                return {"request_id": opaque_id}
            case "alibaba":
                return {"output": {"task_id": opaque_id}}
        raise AssertionError("Unreviewed provider fixture")

    def ready(self, url="https://video.example/clip.mp4?signature=synthetic"):
        match self.provider.provider:
            case "google":
                return {"state": "ACTIVE"}
            case "byteplus":
                return {"status": "succeeded", "content": {"video_url": url}}
            case "xai":
                return {"status": "done", "video": {"url": url}}
            case "alibaba":
                return {"output": {"task_status": "SUCCEEDED", "video_url": url}}
        raise AssertionError("Unreviewed provider fixture")


def offering(provider_id):
    provider = video_models.by_provider(provider_id)
    assert provider is not None
    base = httpx.URL(provider.base_url).path.rstrip("/")
    suffixes = {
        "google": ("/interactions", f"/files/{OPAQUE}"),
        "byteplus": ("/contents/generations/tasks", f"/contents/generations/tasks/{OPAQUE}"),
        "xai": ("/videos/generations", f"/videos/{OPAQUE}"),
        "alibaba": ("/services/aigc/video-generation/video-synthesis", f"/tasks/{OPAQUE}"),
    }
    submit, poll = suffixes[provider_id]
    download = f"{base}{poll}:download" if provider_id == "google" else "/clip.mp4"
    return Offering(provider, provider.models[0], base + submit, base + poll, download)


async def make(chosen, **options):
    return await generate_video(
        chosen.provider,
        model=chosen.model.id,
        prompt="Synthetic clip",
        resolution=chosen.model.resolutions[0],
        aspect_ratio=chosen.model.aspect_ratios[0],
        api_key=KEY,
        timeout_seconds=60,
        **options,
    )


@pytest.fixture(autouse=True)
def instant_polls(monkeypatch):
    monkeypatch.setattr(clients_module, "_pause", AsyncMock())


def api_transport(monkeypatch, handler):
    requests = []
    real = httpx.AsyncClient

    def answer(request):
        requests.append(request)
        return handler(request)

    def client(**kwargs):
        return real(**kwargs, transport=httpx.MockTransport(answer))

    monkeypatch.setattr(generation_module.httpx, "AsyncClient", client)
    return requests


def protected_transport(monkeypatch, handler):
    """Keep the actual pinning transport; replace only DNS and the network."""
    requests, resolved, clients = [], [], []
    resolver = pinned_http.resolve_pinned_url
    real = clients_module.PinnedAsyncClient

    def resolve(url, *, private_allowlist):
        resolved.append(url)
        parsed = httpx2.URL(url)
        if parsed.host in {"video.example", "cdn.example", "generativelanguage.googleapis.com"}:
            return PinnedAddress(hostname=parsed.host, port=443, ips=("93.184.216.34",))
        return resolver(url, private_allowlist=private_allowlist)

    def answer(request):
        requests.append(request)
        assert request.url.host == "93.184.216.34"
        assert request.extensions["sni_hostname"] == request.headers["host"]
        return handler(request)

    def client(**kwargs):
        created = real(**kwargs, transport=httpx2.MockTransport(answer))
        clients.append(created)
        return created

    monkeypatch.setattr(pinned_http, "resolve_pinned_url", resolve)
    monkeypatch.setattr(clients_module, "PinnedAsyncClient", client)
    return requests, resolved, clients


@pytest.mark.parametrize("provider_id", PROVIDERS)
async def test_journal_commits_before_poll_and_recovery_sends_no_new_submission(
    monkeypatch, provider_id
):
    chosen = offering(provider_id)
    saved = []
    committed = False
    transient = True

    async def journal(receipt):
        nonlocal committed
        assert not committed
        await asyncio.sleep(0)
        saved.append(receipt.model_dump_json())
        committed = True

    def answer(request):
        nonlocal transient
        if request.method == "POST":
            assert request.url.path == chosen.submit and not committed
            return httpx.Response(200, json=chosen.accepted())
        assert committed
        if request.url.path == chosen.poll:
            if transient:
                transient = False
                return httpx.Response(503, json={"error": "synthetic"})
            return httpx.Response(200, json=chosen.ready())
        assert request.url.path == chosen.download
        return httpx.Response(200, content=CLIP)

    requests = api_transport(monkeypatch, answer)
    assert (await make(chosen, on_receipt=journal)).data == CLIP
    assert len(saved) == 1
    receipt = VideoReceipt.model_validate_json(saved[0])
    assert receipt == chosen.receipt()
    assert KEY not in saved[0] and "https:" not in saved[0]
    original = len(requests)
    no_new_receipt = AsyncMock(
        side_effect=AssertionError("Recovery must use its persisted receipt")
    )
    assert (await make(chosen, receipt=receipt, on_receipt=no_new_receipt)).data == CLIP
    assert [r.method for r in requests].count("POST") == 1
    assert all(r.method == "GET" for r in requests[original:])
    no_new_receipt.assert_not_awaited()


@pytest.mark.parametrize("provider_id", PROVIDERS)
@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_or_cancelled_receipt_commit_stops_before_poll(
    monkeypatch, provider_id, cancelled
):
    chosen = offering(provider_id)
    requests = api_transport(monkeypatch, lambda _r: httpx.Response(200, json=chosen.accepted()))
    error = asyncio.CancelledError if cancelled else RuntimeError
    journal = AsyncMock(side_effect=error("synthetic journal failure"))
    with pytest.raises(error):
        await make(chosen, on_receipt=journal)
    assert [r.method for r in requests] == ["POST"]
    journal.assert_awaited_once_with(chosen.receipt())


@pytest.mark.security
@pytest.mark.parametrize(
    "changes",
    [
        {"provider": "byteplus"},
        {"api": "byteplus_tasks"},
        {"model": "another-model"},
        {"kind": "file"},
    ],
)
async def test_receipt_mismatch_is_refused_before_network_or_new_submission(monkeypatch, changes):
    chosen = offering("xai")
    requests = api_transport(monkeypatch, lambda _r: pytest.fail("No HTTP request is authorized"))
    with pytest.raises(ValueError, match="receipt does not match"):
        await make(chosen, receipt=chosen.receipt(**changes))
    assert not requests


@pytest.mark.security
@pytest.mark.parametrize(
    "changes",
    [
        {"id": ""},
        {"id": "../job"},
        {"id": "job?key=secret"},
        {"id": "job#fragment"},
        {"id": "job/second"},
        {"id": "job\n"},
        {"id": "x" * 257},
        {"provider": "custom"},
        {"api": "custom"},
        {"kind": "custom"},
        {"model": ""},
        {"url": "https://signed.example"},
        {"api_key": KEY},
    ],
)
def test_receipt_is_closed_bounded_and_cannot_carry_urls_or_credentials(changes):
    with pytest.raises(ValidationError):
        offering("xai").receipt(**changes)


def test_receipt_cannot_be_mutated_after_validation():
    receipt = offering("xai").receipt()
    with pytest.raises(ValidationError):
        receipt.id = "another-job"


@pytest.mark.security
@pytest.mark.parametrize("provider_id", PROVIDERS)
async def test_provider_job_id_cannot_change_the_path(monkeypatch, provider_id):
    chosen = offering(provider_id)
    requests = api_transport(
        monkeypatch, lambda _r: httpx.Response(200, json=chosen.accepted(opaque_id=".."))
    )
    journal = AsyncMock()
    with pytest.raises(VideoProviderError):
        await make(chosen, on_receipt=journal)
    assert [r.method for r in requests] == ["POST"]
    journal.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize(
    "options",
    [
        {"base_url": "https://untrusted.example", "on_receipt": AsyncMock()},
        {},
    ],
)
async def test_protected_submission_requires_fixed_endpoint_and_durable_journal(
    monkeypatch, options
):
    chosen = offering("xai")
    requests = api_transport(monkeypatch, lambda _r: pytest.fail("No request is authorized"))
    with pytest.raises(ValueError, match=r"catalog provider endpoint|durable receipt journal"):
        await make(chosen, protected_downloads=True, **options)
    assert not requests


@pytest.mark.security
@pytest.mark.parametrize("provider_id", ["google", "xai"])
async def test_protected_collection_pins_each_hop_and_never_restores_a_dropped_key(
    monkeypatch, provider_id
):
    chosen = offering(provider_id)
    api_requests = api_transport(monkeypatch, lambda _r: httpx.Response(200, json=chosen.ready()))
    first_host = "generativelanguage.googleapis.com" if provider_id == "google" else "video.example"

    def download(request):
        if request.url.path == chosen.download:
            assert (request.headers.get("x-goog-api-key") == KEY) == (provider_id == "google")
            return httpx2.Response(302, headers={"location": "/same-origin"})
        if request.url.path == "/same-origin":
            assert (request.headers.get("x-goog-api-key") == KEY) == (provider_id == "google")
            return httpx2.Response(302, headers={"location": "https://cdn.example/next"})
        assert "x-goog-api-key" not in request.headers and "authorization" not in request.headers
        if request.url.path == "/next":
            return httpx2.Response(302, headers={"location": f"https://{first_host}/final"})
        assert request.url.path == "/final"
        return httpx2.Response(200, content=CLIP)

    wire, resolved, clients = protected_transport(monkeypatch, download)
    assert (await make(chosen, receipt=chosen.receipt(), protected_downloads=True)).data == CLIP
    assert len(wire) == len(resolved) == 4
    assert all(request.method == "GET" for request in api_requests + wire)
    assert clients[0].is_closed


@pytest.mark.security
@pytest.mark.parametrize("redirected", [False, True])
async def test_private_storage_target_is_refused_before_dialling_it(monkeypatch, redirected):
    chosen = offering("xai")
    target = "https://video.example/clip.mp4" if redirected else "https://127.0.0.1/private"
    api_transport(monkeypatch, lambda _r: httpx.Response(200, json=chosen.ready(target)))
    wire, resolved, clients = protected_transport(
        monkeypatch,
        lambda _r: httpx2.Response(302, headers={"location": "https://127.0.0.1/private"}),
    )
    with pytest.raises(VideoProviderError) as error:
        await make(chosen, receipt=chosen.receipt(), protected_downloads=True)
    assert error.value.failure is VideoFailure.REJECTED
    assert len(wire) == int(redirected)
    assert resolved[-1] == "https://127.0.0.1/private"
    assert clients[0].is_closed


@pytest.mark.security
async def test_protected_download_failure_does_not_log_the_signed_url(monkeypatch, caplog):
    chosen = offering("xai")
    api_transport(monkeypatch, lambda _r: httpx.Response(200, json=chosen.ready()))

    def fail(_request):
        raise httpx2.ProxyError("https://video.example/clip.mp4?private-signature=DO_NOT_LOG")

    protected_transport(monkeypatch, fail)
    with pytest.raises(VideoProviderError) as error:
        await make(chosen, receipt=chosen.receipt(), protected_downloads=True)
    assert error.value.failure is VideoFailure.UNAVAILABLE
    assert "DO_NOT_LOG" not in caplog.text and "DO_NOT_LOG" not in str(error.value)

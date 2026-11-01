"""`http.*` steps reach a host on `OUTBOUND_PRIVATE_ALLOWLIST`, and only from an origin that needs it.

The handlers run for real behind the real pinned client; the network is a
recording transport and DNS is a stub, so the SSRF check and the pin decide
what is dialled.
"""

import socket
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx2
import pytest

from app.core.config import settings
from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import NO_PRIVATE_ADDRESSES
from app.services.workflow_execution import context
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed
from app.workflows.files import StoredFile
from app.workflows.nodes._http import private_allowlist_for
from app.workflows.nodes.http_download import _handler as download_handler
from app.workflows.nodes.http_request import _handler as request_handler
from app.workflows.nodes.http_upload import _handler as upload_handler

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_ANSWERS = {
    "wiki": "10.1.2.5",
    "files.corp.example": "10.1.2.6",
    "elsewhere": "10.9.9.9",
    "docs.example.com": "93.184.216.34",
}


class _Wire(httpx2.AsyncBaseTransport):
    def __init__(self) -> None:
        self.responder: Callable[[httpx2.Request], httpx2.Response] = lambda _r: httpx2.Response(
            200, content=_PNG
        )
        self.sent: list[str] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        # The URL carries the pinned address; the name is the `Host` header.
        self.sent.append(request.headers["host"] + request.url.raw_path.decode())
        return self.responder(request)


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> _Wire:
    transport = _Wire()

    def fake_getaddrinfo(host: str, port: Any, *_args: Any, **_kwargs: Any) -> list[Any]:
        if host not in _ANSWERS:
            raise socket.gaierror("no such name")
        return [(2, 1, 6, "", (_ANSWERS[host], port))]

    monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(settings, "OUTBOUND_PRIVATE_ALLOWLIST", ["10.1.2.0/24"])
    monkeypatch.setattr(context, "current", lambda: SimpleNamespace(idempotency_key="key"))

    def client(*, timeout: httpx2.Timeout, private_allowlist=NO_PRIVATE_ADDRESSES):
        return PinnedAsyncClient(
            timeout=timeout, transport=transport, private_allowlist=private_allowlist
        )

    for module in (request_handler, download_handler, upload_handler):
        monkeypatch.setattr(module, "PinnedAsyncClient", client)
    return transport


def _redirect_to(location: str) -> Callable[[httpx2.Request], httpx2.Response]:
    return lambda _r: httpx2.Response(302, headers={"location": location})


async def _request(url: str) -> Any:
    return await request_handler.handle(
        request_handler.HttpRequestConfig(url=url, method="GET"), None
    )


class TestHttpRequest:
    async def test_a_request_to_a_listed_private_host_succeeds(self, wire: _Wire) -> None:
        wire.responder = lambda _r: httpx2.Response(200, json={"ok": True})

        result = await _request("http://wiki/status")

        assert isinstance(result, Completed)
        assert wire.sent == ["wiki/status"]

    async def test_a_request_to_an_unlisted_private_host_still_fails_as_before(
        self, wire: _Wire
    ) -> None:
        result = await _request("http://elsewhere/status")

        assert isinstance(result, Failed)
        assert result.error.code == "URL_REFUSED"
        assert wire.sent == []

    async def test_a_redirect_from_a_public_origin_to_a_listed_host_is_refused(
        self, wire: _Wire
    ) -> None:
        wire.responder = _redirect_to("http://wiki/secret")

        result = await _request("http://docs.example.com/start")

        assert isinstance(result, Failed)
        assert result.error.code == "URL_REFUSED"
        assert wire.sent == ["docs.example.com/start"]

    async def test_a_redirect_from_a_listed_origin_to_another_listed_host_is_followed(
        self, wire: _Wire
    ) -> None:
        def responder(request: httpx2.Request) -> httpx2.Response:
            if request.headers["host"] == "wiki":
                return httpx2.Response(302, headers={"location": "http://files.corp.example/x"})
            return httpx2.Response(200, json={"landed": True})

        wire.responder = responder

        result = await _request("http://wiki/start")

        assert isinstance(result, Completed)
        assert wire.sent == ["wiki/start", "files.corp.example/x"]

    async def test_a_name_on_no_list_gets_no_allowlist(self, wire: _Wire) -> None:
        assert await private_allowlist_for("http://docs.example.com/") == NO_PRIVATE_ADDRESSES
        assert await private_allowlist_for("http://wiki/")


class TestHttpFiles:
    async def test_a_download_and_an_upload_reach_a_listed_host(
        self, wire: _Wire, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        saved = AsyncMock(
            return_value=FileRef(
                file_id="00000000-0000-0000-0000-000000000001",
                content_type="image/png",
                byte_size=len(_PNG),
            )
        )
        monkeypatch.setattr(download_handler.files, "save", saved)
        downloaded = await download_handler.handle(
            download_handler.HttpDownloadConfig(url="http://wiki/logo.png"), None
        )

        async def chunks() -> AsyncIterator[bytes]:
            yield b"payload"

        monkeypatch.setattr(
            upload_handler.files,
            "open_stream",
            AsyncMock(return_value=(StoredFile(b"", "text/plain", "a.txt"), chunks())),
        )
        wire.responder = lambda _r: httpx2.Response(200, json={"stored": True})
        uploaded = await upload_handler.handle(
            upload_handler.HttpUploadConfig(url="http://wiki/inbox"),
            upload_handler.HttpUploadInput(file=saved.return_value),
        )

        assert isinstance(downloaded, Completed)
        assert isinstance(uploaded, Completed)
        assert wire.sent == ["wiki/logo.png", "wiki/inbox"]

    async def test_a_download_redirected_from_a_public_origin_to_a_listed_host_is_refused(
        self, wire: _Wire
    ) -> None:
        wire.responder = _redirect_to("http://wiki/logo.png")

        result = await download_handler.handle(
            download_handler.HttpDownloadConfig(url="http://docs.example.com/logo.png"), None
        )

        assert isinstance(result, Failed)
        assert result.error.code == "URL_REFUSED"
        assert wire.sent == ["docs.example.com/logo.png"]

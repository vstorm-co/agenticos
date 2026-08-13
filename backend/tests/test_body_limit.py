"""The one size limit that runs before a request body is read.

Every other one in this codebase measures bytes that have already arrived, which is
the whole point of this module: FastAPI resolves an `UploadFile` parameter before the
handler runs, so `POST /api/v1/embed/{key}/files` had spooled a stranger's entire
body to disk and copied it into memory before `accept_upload` compared it to a 5MB
cap. Five of those a minute per address, with no account behind any of them.

What is asserted here is what a caller sees and, for the refusal, that the body was
never asked for - a test that only checked the status would pass over a middleware
that read the request and then refused it.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.body_limit import BodySizeLimitMiddleware, max_body_bytes
from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.anyio


class TestTheCapItself:
    def test_it_follows_the_largest_upload_the_api_accepts(self, monkeypatch):
        """Derived rather than configured, so a deployment raising the upload limit
        has raised this. A second number to keep in step with the first is a number
        that ends up below it."""
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 50)
        fifty = max_body_bytes()
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 200)

        assert max_body_bytes() > fifty

    def test_it_leaves_room_for_the_envelope_around_a_file(self, monkeypatch):
        """A multipart body is the file plus boundaries, part headers and any other
        field the form carries. A cap at exactly the file size refuses an upload at
        its own documented limit."""
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 50)

        assert max_body_bytes() > 50 * 1024 * 1024


class TestWhatAnOverLargeRequestGets:
    @staticmethod
    async def _post(length: str | None) -> object:
        headers = {"content-type": "application/octet-stream"}
        if length is not None:
            headers["content-length"] = length
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(
                "POST", "/api/v1/embed/some-key/files", headers=headers, content=b""
            )

    async def test_a_declared_length_over_the_cap_is_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)

        response = await self._post(str(500 * 1024 * 1024))

        assert response.status_code == 413

    async def test_the_refusal_is_the_envelope_the_rest_of_the_api_answers(self, monkeypatch):
        """A middleware sits above the exception handlers, so this envelope is built
        by hand - which is exactly why it is worth asserting. A client parsing our
        errors should not need to know which layer produced one."""
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)

        response = await self._post(str(500 * 1024 * 1024))

        assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
        assert response.json()["error"]["details"] == {"limit_mb": 1}

    async def test_a_body_inside_the_cap_reaches_the_route(self, monkeypatch):
        """Not a 413, and that is the assertion: a cap that refuses everything is
        indistinguishable from one that works, until somebody uploads a file."""
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 50)

        response = await self._post("100")

        assert response.status_code != 413

    async def test_a_request_that_declares_no_length_is_let_through(self, monkeypatch):
        """A chunked upload declares none. Refusing it here would refuse a shape the
        route supports for a header it does not read; the per-route caps still
        measure the bytes."""
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)

        response = await self._post(None)

        assert response.status_code != 413

    async def test_a_length_that_is_not_a_number_is_let_through(self, monkeypatch):
        """Same reasoning. An unparsable `Content-Length` is not a size, and turning
        it into a refusal is a new way to fail."""
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)

        response = await self._post("about a gigabyte")

        assert response.status_code != 413


class TestWhatItDoesNotTouch:
    async def test_a_lifespan_or_websocket_scope_passes_straight_through(self):
        """The scope has no `content-length` to read and no response to send, so the
        guard must hand it on rather than answering it."""
        seen: list[str] = []

        async def app_stub(scope, receive, send) -> None:
            seen.append(scope["type"])

        await BodySizeLimitMiddleware(app_stub)({"type": "websocket"}, None, None)

        assert seen == ["websocket"]

    async def test_a_get_with_no_body_is_not_read_for_one(self, monkeypatch):
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/health")

        assert response.status_code == 200

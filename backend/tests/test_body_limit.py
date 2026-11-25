"""The one size limit that runs before a request body is read.

Every other one in this codebase measures bytes that have already arrived, which is
the whole point of this module: FastAPI resolves an `UploadFile` parameter before the
handler runs, so `POST /api/v1/embed/{key}/files` had spooled a stranger's entire
body to disk and copied it into memory before `accept_upload` compared it to a 5MB
cap. Five of those a minute per address, with no account behind any of them.

What is asserted here is what a caller sees and, for a streamed refusal, that the
chunk crossing the ceiling never reaches the application - a test that only checked
the status would pass over a middleware that buffered the whole request first.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import Body, FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.types import Message, Receive, Scope, Send

import app.core.body_limit as body_limit
from app.core.body_limit import BodySizeLimitMiddleware, max_body_bytes
from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.anyio


async def _stream_through_middleware(
    headers: list[tuple[bytes, bytes]], chunks: list[bytes]
) -> tuple[list[bytes], list[Message]]:
    incoming: list[Message] = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    seen: list[bytes] = []
    sent: list[Message] = []

    async def receive() -> Message:
        return incoming.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    async def read_body(_scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            seen.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    scope: Scope = {"type": "http", "path": "/api/v1/embed/key/files", "headers": headers}
    await BodySizeLimitMiddleware(read_body)(scope, receive, send)
    return seen, sent


class TestTheCapItself:
    def test_it_follows_the_largest_upload_the_api_accepts(self, monkeypatch):
        """Derived rather than configured, so a deployment raising the upload limit
        has raised this. A second number to keep in step with the first is a number
        that ends up below it."""
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 50)
        fifty = max_body_bytes()
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 200)

        assert max_body_bytes() > fifty

    def test_it_follows_the_chat_ceiling_when_that_is_the_larger(self, monkeypatch):
        """This middleware is global; the upload ceilings are per surface.

        The name of the test above is the invariant, and it stopped being true
        the moment chat got a ceiling of its own: derived from
        `MAX_UPLOAD_SIZE_MB` alone, a chat limit configured above the knowledge
        base's would be unreachable - a 413 from here before the route that
        enforces it ran, so the setting could not raise the limit it names
        (#498).
        """
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 50)
        monkeypatch.setattr(settings, "CHAT_MAX_UPLOAD_SIZE_MB", 100)

        assert max_body_bytes() > 100 * 1024 * 1024

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

    @staticmethod
    async def _post_dictation(origin: str, path: str) -> object:
        headers = {
            "content-type": "application/octet-stream",
            "content-length": str(500 * 1024 * 1024),
            "origin": origin,
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request("POST", path, headers=headers, content=b"")

    async def test_a_widget_can_read_that_its_recording_was_too_large(self, monkeypatch):
        """A widget posts from somebody else's site, and a refusal it cannot read
        reaches its `fetch` as a network error - "offline" for a recording that
        was simply too long (#1797)."""
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)

        response = await self._post_dictation("https://shop.example", "/api/v1/embed/k/dictation")

        assert response.status_code == 413
        assert response.headers["access-control-allow-origin"] == "https://shop.example"

    async def test_a_dictation_without_an_origin_gets_no_cors_header(self, monkeypatch):
        """Same-origin and server-to-server callers send no `Origin`; there is
        nobody to name, so nothing is echoed."""
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
        headers = {
            "content-type": "application/octet-stream",
            "content-length": str(500 * 1024 * 1024),
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.request(
                "POST", "/api/v1/embed/k/dictation", headers=headers, content=b""
            )

        assert response.status_code == 413
        assert "access-control-allow-origin" not in response.headers

    async def test_no_other_route_echoes_an_origin(self, monkeypatch):
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)

        response = await self._post_dictation("https://shop.example", "/api/v1/embed/k/files")

        assert response.status_code == 413
        assert "access-control-allow-origin" not in response.headers

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

    async def test_a_small_request_with_no_supplied_length_is_let_through(self, monkeypatch):
        """A chunked upload declares none. Its shape remains supported while the
        receive wrapper measures the bytes it actually carries."""
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)

        response = await self._post(None)

        assert response.status_code != 413

    async def test_a_length_that_is_not_a_number_is_let_through(self, monkeypatch):
        """Same reasoning. An unparsable `Content-Length` is not a size, and turning
        it into a refusal is a new way to fail; the actual-byte counter still holds."""
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)

        response = await self._post("about a gigabyte")

        assert response.status_code != 413


class TestWhatTheStreamActuallyCarries:
    @pytest.mark.security
    async def test_retrying_a_refused_receive_cannot_read_more_body_bytes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(body_limit, "max_body_bytes", lambda: 5)
        reads = 0
        sent: list[Message] = []

        async def receive() -> Message:
            nonlocal reads
            reads += 1
            return {"type": "http.request", "body": b"abcdef", "more_body": True}

        async def send(message: Message) -> None:
            sent.append(message)

        async def catching_app(_scope: Scope, receive: Receive, send: Send) -> None:
            for _ in range(2):
                with pytest.raises(body_limit._BodyTooLarge) as refused:
                    await receive()
                assert refused.value.received_bytes == 6
            await send({"type": "http.response.start", "status": 200, "headers": []})

        scope: Scope = {"type": "http", "path": "/upload", "headers": []}
        await BodySizeLimitMiddleware(catching_app)(scope, receive, send)

        assert reads == 1
        assert [
            message["status"] for message in sent if message["type"] == "http.response.start"
        ] == [413]

    @pytest.mark.security
    async def test_a_late_body_refusal_does_not_start_a_second_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(body_limit, "max_body_bytes", lambda: 5)
        sent: list[Message] = []

        async def receive() -> Message:
            return {"type": "http.request", "body": b"abcdef", "more_body": False}

        async def send(message: Message) -> None:
            sent.append(message)

        async def started_app(_scope: Scope, receive: Receive, send: Send) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await receive()

        scope: Scope = {"type": "http", "path": "/upload", "headers": []}
        with pytest.raises(body_limit._BodyTooLarge) as refused:
            await BodySizeLimitMiddleware(started_app)(scope, receive, send)

        assert refused.value.received_bytes == 6
        assert sent == [{"type": "http.response.start", "status": 200, "headers": []}]

    @pytest.mark.security
    async def test_json_parser_cannot_turn_an_over_limit_stream_into_a_parse_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(body_limit, "max_body_bytes", lambda: 5)
        parser_app = FastAPI()
        parser_app.add_middleware(BodySizeLimitMiddleware)

        @parser_app.post("/json")
        async def parse(payload: dict[str, str] = Body(...)) -> dict[str, str]:
            return payload

        async def chunks() -> AsyncIterator[bytes]:
            yield b'{"a":'
            yield b'"b"}'

        async with AsyncClient(
            transport=ASGITransport(app=parser_app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/json", content=chunks(), headers={"Content-Type": "application/json"}
            )

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"

    @pytest.mark.security
    @pytest.mark.parametrize(
        "headers",
        [
            pytest.param([(b"transfer-encoding", b"chunked")], id="chunked"),
            pytest.param([], id="http2-or-missing-length"),
            pytest.param([(b"content-length", b"not-a-number")], id="malformed-length"),
            pytest.param([(b"content-length", b"1")], id="underreported-length"),
        ],
    )
    async def test_actual_bytes_over_the_cap_are_refused_before_the_crossing_chunk(
        self, monkeypatch: pytest.MonkeyPatch, headers: list[tuple[bytes, bytes]]
    ) -> None:
        monkeypatch.setattr(body_limit, "max_body_bytes", lambda: 5)

        seen, sent = await _stream_through_middleware(headers, [b"abc", b"def"])

        assert seen == [b"abc"]
        assert sent[0]["type"] == "http.response.start"
        assert sent[0]["status"] == 413

    async def test_a_multichunk_body_at_the_cap_reaches_the_application(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(body_limit, "max_body_bytes", lambda: 5)

        seen, sent = await _stream_through_middleware([], [b"abc", b"de"])

        assert seen == [b"abc", b"de"]
        assert sent[0]["type"] == "http.response.start"
        assert sent[0]["status"] == 204


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

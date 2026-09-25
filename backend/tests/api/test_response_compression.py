"""Responses are compressed on the way out, and the bodies that must not be are not.

A transcript is why this exists. `GET /conversations/{id}/messages` answers with up
to a hundred turns carrying their reasoning, their `parts` timeline and every tool
call's arguments and result, and until `GZipMiddleware` was registered that JSON went
out raw over whatever link the reader happened to be on.

The tests that matter here are the ones nothing else would notice losing: the
exclusion that keeps an event stream uncompressed (there is no SSE route today, so
the first one added would hang in production rather than fail in CI), the position
of the layer in the stack, and `Vary` naming the encoding - a response cached
without it is served gzipped to a client that never asked for it.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from httpx import ASGITransport, AsyncClient
from starlette.middleware.gzip import GZipMiddleware

from app.core.config import settings
from app.main import UNCOMPRESSED_CONTENT_TYPES
from app.main import app as real_app

pytestmark = pytest.mark.anyio

# Comfortably past `minimum_size`, and repetitive the way a transcript is.
_BIG = [{"role": "assistant", "content": "the agent said something" * 8} for _ in range(60)]


def _app() -> FastAPI:
    """The application's own compression settings, over routes that isolate them."""
    built = FastAPI()
    built.add_middleware(
        GZipMiddleware,
        minimum_size=1024,
        compresslevel=5,
        exclude_content_types=UNCOMPRESSED_CONTENT_TYPES,
    )

    @built.get("/transcript")
    async def transcript() -> JSONResponse:
        return JSONResponse(content=_BIG)

    @built.get("/tiny")
    async def tiny() -> JSONResponse:
        return JSONResponse(content={"ok": True})

    @built.get("/stream")
    async def stream() -> StreamingResponse:
        async def events():
            for index in range(20):
                yield f"data: {'x' * 200} {index}\n\n".encode()

        return StreamingResponse(events(), media_type="text/event-stream")

    @built.get("/download")
    async def download() -> StreamingResponse:
        async def chunks():
            yield b"%PDF-1.7" + b"\x00" * 4096

        return StreamingResponse(chunks(), media_type="application/pdf")

    return built


async def _get(path: str, *, accept: str = "gzip"):
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as ac:
        return await ac.get(path, headers={"Accept-Encoding": accept})


async def test_a_transcript_sized_body_is_compressed_and_arrives_intact() -> None:
    resp = await _get("/transcript")

    assert resp.headers["content-encoding"] == "gzip"
    # httpx decodes the body but leaves the header, so both halves are assertable:
    # the answer is the same JSON it would have been uncompressed.
    assert resp.json() == json.loads(json.dumps(_BIG))


async def test_a_small_body_is_left_alone() -> None:
    """Below a TCP segment there is nothing to win, and a header to pay for."""
    resp = await _get("/tiny")

    assert "content-encoding" not in resp.headers


async def test_a_client_that_does_not_ask_for_gzip_gets_plain_bytes() -> None:
    resp = await _get("/transcript", accept="identity")

    assert "content-encoding" not in resp.headers
    assert resp.json() == json.loads(json.dumps(_BIG))


async def test_the_answer_varies_on_the_encoding_that_was_asked_for() -> None:
    """A shared cache that stored this without `Vary` would hand a gzipped body to
    the next client, whatever that client said it could read."""
    resp = await _get("/transcript")

    assert "accept-encoding" in resp.headers["vary"].lower()


async def test_an_event_stream_is_never_compressed() -> None:
    """There is no SSE route in this backend today - chat streams over a
    WebSocket, which compression cannot reach at all. So nothing else in the
    suite would notice this exclusion being dropped, and the first event stream
    somebody adds would stall behind a compressor instead of failing here.
    """
    resp = await _get("/stream")

    assert "content-encoding" not in resp.headers
    assert resp.text.count("data: ") == 20


async def test_an_already_compressed_download_keeps_its_own_encoding() -> None:
    """A PDF and the office formats are containers that are already compressed, so
    compressing them again burns CPU for nothing - and it drops the
    `Content-Length` a streamed response carries, which is the download progress
    the browser draws."""
    resp = await _get("/download")

    assert "content-encoding" not in resp.headers


def test_every_excluded_type_starlette_ships_is_still_excluded() -> None:
    """The list is built by splatting Starlette's own rather than retyping it, so
    an addition upstream - a future sibling of `text/event-stream` - is inherited.
    Retyping the tuple is how that would be lost."""
    assert "text/event-stream" in UNCOMPRESSED_CONTENT_TYPES
    assert "image/png" in UNCOMPRESSED_CONTENT_TYPES
    assert "application/pdf" in UNCOMPRESSED_CONTENT_TYPES


def test_compression_is_the_outermost_layer_of_the_application() -> None:
    """`add_middleware` inserts at the front, so index 0 is the layer added last
    and the one wrapping every other. Position is a decision here, not an
    accident: everything below is a `BaseHTTPMiddleware` that re-emits the body
    through an anyio stream, and `Vary: Accept-Encoding` has to reach an answer an
    inner layer short-circuits. A later `add_middleware` call would move it
    silently, which is what this pins.
    """
    assert real_app.user_middleware[0].cls is GZipMiddleware


async def test_the_security_headers_still_reach_a_compressed_response(client) -> None:
    """Compression sits above them, so it must not shadow what they set."""
    resp = await client.get(f"{settings.API_V1_STR}/health")

    assert "content-security-policy" in resp.headers
    assert resp.headers["x-content-type-options"] == "nosniff"

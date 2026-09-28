"""Responses are compressed on the way out, and the bodies that must not be are not."""

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
    built.add_middleware(GZipMiddleware, **real_app.user_middleware[-1].kwargs)

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
    assert resp.json() == json.loads(json.dumps(_BIG))


async def test_a_small_body_is_left_alone() -> None:
    resp = await _get("/tiny")

    assert "content-encoding" not in resp.headers


async def test_a_client_that_does_not_ask_for_gzip_gets_plain_bytes() -> None:
    resp = await _get("/transcript", accept="identity")

    assert "content-encoding" not in resp.headers
    assert resp.json() == json.loads(json.dumps(_BIG))


async def test_the_answer_varies_on_the_encoding_that_was_asked_for() -> None:
    """A shared cache that stored this without `Vary` would hand a gzipped body to
    a client that never asked for one."""
    resp = await _get("/transcript")

    assert "accept-encoding" in resp.headers["vary"].lower()


async def test_an_event_stream_is_never_compressed() -> None:
    """No route streams SSE today, so nothing else would notice this exclusion
    going: the first event stream added would stall behind the compressor."""
    resp = await _get("/stream")

    assert "content-encoding" not in resp.headers
    assert resp.text.count("data: ") == 20


async def test_an_already_compressed_download_keeps_its_own_encoding() -> None:
    resp = await _get("/download")

    assert "content-encoding" not in resp.headers


def test_every_excluded_type_starlette_ships_is_still_excluded() -> None:
    assert "text/event-stream" in UNCOMPRESSED_CONTENT_TYPES
    assert "image/png" in UNCOMPRESSED_CONTENT_TYPES
    assert "application/pdf" in UNCOMPRESSED_CONTENT_TYPES


def test_compression_is_the_innermost_layer_of_the_application() -> None:
    """`add_middleware` inserts at the front, so the last entry is the first added."""
    assert real_app.user_middleware[-1].cls is GZipMiddleware


async def test_the_application_leaves_a_small_answer_uncompressed(client) -> None:
    """Above GZip, the `BaseHTTPMiddleware` layers would hand it every body as a
    stream, and Starlette does not apply `minimum_size` to a stream."""
    resp = await client.get(f"{settings.API_V1_STR}/health", headers={"Accept-Encoding": "gzip"})

    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers


async def test_the_application_compresses_a_large_answer(client) -> None:
    resp = await client.get(
        f"{settings.API_V1_STR}/openapi.json", headers={"Accept-Encoding": "gzip"}
    )

    assert resp.status_code == 200
    assert resp.headers["content-encoding"] == "gzip"
    assert "paths" in resp.json()


async def test_the_security_headers_still_reach_a_response_through_compression(client) -> None:
    resp = await client.get(f"{settings.API_V1_STR}/health")

    assert "content-security-policy" in resp.headers
    assert resp.headers["x-content-type-options"] == "nosniff"

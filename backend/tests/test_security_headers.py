"""Every response carries the security headers, and a per-response override wins (#18).

`SecurityHeadersMiddleware` was fully written and never registered, so no API
response carried a Content-Security-Policy, and `files.py` opted its one framed
endpoint down to `SAMEORIGIN` against a default that was not there. It is
registered now, and because it sets each header with `setdefault`, that
per-response override still wins.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient

from app.api.exception_handlers import register_exception_handlers
from app.core.config import settings
from app.core.middleware import SecurityHeadersMiddleware

pytestmark = pytest.mark.anyio


async def test_an_ordinary_response_carries_the_security_headers(client: AsyncClient) -> None:
    resp = await client.get(f"{settings.API_V1_STR}/health")

    assert resp.status_code == 200
    assert "content-security-policy" in resp.headers
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    # 0 disables the deprecated legacy auditor; the CSP is the real defence.
    assert resp.headers["x-xss-protection"] == "0"


async def test_a_per_response_x_frame_options_override_survives_the_middleware() -> None:
    # The files download sets SAMEORIGIN so its PDF preview can be framed; the
    # middleware sets its headers with setdefault, so that choice is not
    # overwritten back to DENY - which is what `files.py` already assumes.
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/framed")
    async def framed() -> Response:
        return Response(content=b"pdf", headers={"X-Frame-Options": "SAMEORIGIN"})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/framed")

    assert resp.headers["x-frame-options"] == "SAMEORIGIN"
    assert "content-security-policy" in resp.headers
    assert resp.headers["x-content-type-options"] == "nosniff"


async def test_an_excluded_path_keeps_its_framing_but_drops_the_csp() -> None:
    # /docs drops only the CSP - Swagger's assets need it relaxed - but must keep
    # its framing and MIME protections, or excluding it would leave the page
    # embeddable by any origin.
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, exclude_paths={"/docs"})

    @app.get("/docs")
    async def docs() -> Response:
        return Response(content=b"<html></html>")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/docs")

    assert "content-security-policy" not in resp.headers
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-xss-protection"] == "0"


async def test_an_unhandled_error_still_carries_the_security_headers() -> None:
    # A genuinely unhandled exception is turned into a 500 by Starlette's
    # ServerErrorMiddleware, which sits outside the whole middleware stack - so
    # SecurityHeadersMiddleware never sees that response and the handler stamps
    # the set itself. Without that, a 500 goes out bare.
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/boom")
    async def boom() -> Response:
        raise RuntimeError("kaboom")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/boom")

    assert resp.status_code == 500
    assert "content-security-policy" in resp.headers
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-xss-protection"] == "0"
    assert "permissions-policy" in resp.headers


async def test_a_cors_preflight_carries_the_security_headers(client: AsyncClient) -> None:
    # CORSMiddleware answers a preflight OPTIONS without calling inward, so the
    # security layer has to sit outside it or the preflight response goes out
    # without the headers.
    resp = await client.options(
        f"{settings.API_V1_STR}/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-xss-protection"] == "0"

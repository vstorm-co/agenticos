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

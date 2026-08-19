"""What a client gets for a method a route does not declare.

Two defects met on this path, and neither had a test:

**It answered 500.** OpenTelemetry's FastAPI instrumentation raised while deriving a
span name for a `Match.PARTIAL` route - which is exactly what a wrong method
produces - and the exception escaped above this app's handlers.
`app/core/otel_compat.py` and `tests/test_otel_route_details.py` are that half.

**And then it answered in a shape of its own.** `HTTPException` - Starlette's router
raises one here, and twenty-two routes raise one directly - was answered as
`{"detail": ...}` while every other refusal in this API is
`{"error": {"code", "message", "details"}}`. The module docstring in
`app/api/exception_handlers.py` has claimed one shape since before this was true.

Parametrised over routes owned by different routers on purpose: the fault was in how
`app.routes` is walked, so it was never about one endpoint, and a fix that only
worked for the one route somebody happened to try is the failure mode to catch.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client():
    """No dependency overrides at all: none of this reaches a route handler."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


WRONG_METHOD = [
    ("GET", "/auth/login"),
    ("GET", "/auth/register"),
    ("GET", "/auth/refresh"),
    ("DELETE", "/branding"),
    ("POST", "/health"),
]


class TestAWrongMethod:
    @pytest.mark.parametrize(("method", "path"), WRONG_METHOD)
    async def test_it_is_refused_rather_than_answered_with_a_server_error(
        self, client: AsyncClient, method: str, path: str
    ) -> None:
        response = await client.request(method, f"{settings.API_V1_STR}{path}")

        assert response.status_code == 405, response.text

    @pytest.mark.parametrize(("method", "path"), WRONG_METHOD)
    async def test_it_arrives_in_this_api_s_own_envelope(
        self, client: AsyncClient, method: str, path: str
    ) -> None:
        """A client parsing our errors should not need to know which layer produced
        one - and `{"detail": ...}` is a shape it would have to handle separately."""
        response = await client.request(method, f"{settings.API_V1_STR}{path}")

        body = response.json()
        assert "detail" not in body
        assert body["error"]["code"] == "METHOD_NOT_ALLOWED"
        assert body["error"]["message"]

    async def test_the_refusal_says_which_methods_would_work(self, client: AsyncClient) -> None:
        """`Allow` is the header that makes a 405 useful, and the exception carries
        it - so the handler forwards what it was given rather than rebuilding it."""
        response = await client.get(f"{settings.API_V1_STR}/auth/login")

        assert "POST" in response.headers.get("allow", "")


class TestAnUnmatchedPath:
    async def test_it_is_a_404_in_the_same_envelope(self, client: AsyncClient) -> None:
        response = await client.get(f"{settings.API_V1_STR}/definitely-not-mounted")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


class TestARouteThatRaisesOneItself:
    async def test_it_is_in_the_envelope_too(self) -> None:
        """Twenty-two places in this API raise `HTTPException` directly, and until now
        every one of them answered in a shape of its own.

        The branding image route is the cheapest to reach - unauthenticated, and a
        deployment with no uploaded mark is its ordinary state - but unlike the
        refusals above it does reach a handler, so it needs a session to reach it
        with.
        """
        app.dependency_overrides[deps.get_deployment_settings_service] = lambda: _NoImages()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"{settings.API_V1_STR}/branding/logo")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "NOT_FOUND"
        assert body["error"]["message"] == "No image"


class _NoImages:
    """A deployment using the built-in mark, which is every deployment by default."""

    async def image_path(self, _kind: str) -> None:
        return None

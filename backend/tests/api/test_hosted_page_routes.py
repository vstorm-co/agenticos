"""What a hosted page's own endpoints answer, and to whom.

The service decides everything; these three assertions are about the HTTP shape,
which the service cannot express: that hosting off is a 404 rather than a 403,
that the page's config needs no `Origin` where every other embed route demands
one, and that a logo nobody uploaded is absent rather than a 500.

`tests/api/test_platform_routes.py` is what asserts both routes are *deliberately*
open, with the reason written beside them.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.main import app
from app.services.agent_embed import AgentEmbedService

pytestmark = pytest.mark.anyio


@pytest.fixture
def client_and_service(mock_redis: MagicMock):
    service = MagicMock(spec=AgentEmbedService)
    app.dependency_overrides[deps.get_agent_embed_service] = lambda: service
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    yield service
    app.dependency_overrides.clear()


async def _get(path: str) -> object:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path)


class TestTheHostedConfig:
    async def test_an_embed_nobody_hosted_answers_404(self, client_and_service):
        """404 rather than 403: a key that names nothing and a key whose page is
        not published are the same amount of information to give away."""
        client_and_service.find_page = AsyncMock(return_value=None)

        assert (await _get("/api/v1/embed/some-key/hosted")).status_code == 404

    async def test_a_hosted_page_is_configured_without_an_origin(self, client_and_service):
        """Every other route here demands an `Origin` on the allow-list. This one
        does not, because an allow-list is a rule about other people's sites and
        this page is ours - and a server-rendered page sends no `Origin` at all."""
        client_and_service.find_page = AsyncMock(return_value=MagicMock())
        client_and_service.page_config = AsyncMock(
            return_value={
                "title": "Refunds",
                "welcome": "",
                "accent": "#4f46e5",
                "logo_url": None,
                "agent_name": "Refund helper",
                "variables": [],
            }
        )

        response = await _get("/api/v1/embed/some-key/hosted")

        assert response.status_code == 200
        assert response.json()["title"] == "Refunds"


class TestTheHostedLogo:
    async def test_a_page_with_no_logo_answers_404(self, client_and_service):
        """Not a 500, and not an empty 200: `<img>` handles a 404 and shows the
        alternative, which is what a page with no logo should look like."""
        client_and_service.page_logo_path = AsyncMock(return_value=None)

        assert (await _get("/api/v1/embed/some-key/logo")).status_code == 404

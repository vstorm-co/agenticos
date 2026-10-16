"""`/embed/{public_key}/voice.js`: the widget's call UI, served only where calls are on (#54).

The service decides which widget gets it (`tests/test_agent_embed_voice.py`); this
is the HTTP shape - a script with both placeholders filled, or a 404 a `<script>`
tag can swallow.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.main import app
from app.services.agent_embed import AgentEmbedService
from app.services.embed_voice_js import VOICE_JS_VERSION

pytestmark = pytest.mark.anyio


@pytest.fixture
def service(mock_redis: MagicMock):
    embeds = MagicMock(spec=AgentEmbedService)
    app.dependency_overrides[deps.get_agent_embed_service] = lambda: embeds
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    yield embeds
    app.dependency_overrides.clear()


async def _get(path: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path)


async def test_a_widget_with_calls_on_gets_its_script_with_both_placeholders_filled(service):
    service.find_voice_widget = AsyncMock(return_value=SimpleNamespace(public_key="pk-live"))

    response = await _get("/api/v1/embed/pk-live/voice.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    # Unhashed, or a widget cached from before a deploy: short, like `widget.js`.
    assert response.headers["cache-control"] == "public, max-age=300"
    assert '"pk-live"' in response.text
    assert settings.PUBLIC_BASE_URL.rstrip("/") in response.text
    assert "__PUBLIC_KEY__" not in response.text and "__BASE_URL__" not in response.text


async def test_any_other_key_is_a_404(service):
    """Unknown, paused, not a widget, or calls off: one answer, and not a script."""
    service.find_voice_widget = AsyncMock(return_value=None)

    response = await _get("/api/v1/embed/pk-off/voice.js")

    assert response.status_code == 404
    service.find_voice_widget.assert_awaited_once_with("pk-off")


async def test_the_hashed_url_the_widget_asks_for_is_cached_for_good(service):
    """The URL changes with the script, so a browser cannot pair an old call
    script with a newer widget - and need not ask again for this one."""
    service.find_voice_widget = AsyncMock(return_value=SimpleNamespace(public_key="pk-live"))

    hashed = await _get(f"/api/v1/embed/pk-live/voice.js?v={VOICE_JS_VERSION}")
    stale = await _get("/api/v1/embed/pk-live/voice.js?v=0000000000000000")

    assert hashed.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert stale.headers["cache-control"] == "public, max-age=300"
    assert hashed.text == stale.text


async def test_the_widget_asks_for_the_current_call_script(service):
    embed = SimpleNamespace(public_key="pk-live", is_active=True)
    with patch(
        "app.api.routes.v1.embed.AgentEmbedService.find_public", AsyncMock(return_value=embed)
    ):
        response = await _get("/api/v1/embed/pk-live/widget.js")

    assert response.status_code == 200
    assert f'/voice.js?v={VOICE_JS_VERSION}"' in response.text
    assert "__VOICE_VERSION__" not in response.text

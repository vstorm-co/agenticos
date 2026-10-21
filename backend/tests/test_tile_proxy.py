"""Map tiles fetched by the deployment for a page, by three checked numbers (#2302)."""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from app.core.exceptions import ExternalServiceError, NotFoundError
from app.services import tile_proxy

pytestmark = pytest.mark.anyio

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture(autouse=True)
def _empty_cache() -> Iterator[None]:
    tile_proxy._cache.clear()
    yield
    tile_proxy._cache.clear()


def _server(
    monkeypatch: pytest.MonkeyPatch, answer: httpx.Response | Exception
) -> list[httpx.Request]:
    """A tile server answering every request with `answer`; returns what it was asked."""
    monkeypatch.setattr(
        tile_proxy.settings, "VISUAL_MAP_TILES", "https://t.example/{z}/{x}/{y}.png?key=secret"
    )
    monkeypatch.setattr(tile_proxy.settings, "VISUAL_MAP_TILES_ATTRIBUTION", "© Example")
    asked: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        if isinstance(answer, Exception):
            raise answer
        return answer

    real = httpx.AsyncClient

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(tile_proxy.httpx, "AsyncClient", client)
    return asked


class TestWhichTiles:
    async def test_a_deployment_without_tiles_serves_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tile_proxy.settings, "VISUAL_MAP_TILES", "")
        with pytest.raises(NotFoundError):
            await tile_proxy.tile(0, 0, 0)

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("z", "x", "y"), [(-1, 0, 0), (19, 0, 0), (2, 4, 0), (2, 0, 4), (2, -1, 0), (2, 0, -1)]
    )
    async def test_a_tile_no_zoom_has_is_not_found_and_nothing_is_asked(
        self, monkeypatch: pytest.MonkeyPatch, z: int, x: int, y: int
    ) -> None:
        asked = _server(monkeypatch, httpx.Response(200, content=PNG))
        with pytest.raises(NotFoundError):
            await tile_proxy.tile(z, x, y)
        assert asked == []


class TestFetching:
    async def test_a_tile_is_fetched_once_and_then_kept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked = _server(monkeypatch, httpx.Response(200, content=PNG))

        assert await tile_proxy.tile(3, 4, 5) == (PNG, "image/png")
        assert await tile_proxy.tile(3, 4, 5) == (PNG, "image/png")

        assert len(asked) == 1
        assert str(asked[0].url) == "https://t.example/3/4/5.png?key=secret"
        assert asked[0].headers["user-agent"] == tile_proxy.USER_AGENT

    async def test_the_oldest_tile_makes_room(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tile_proxy, "CACHE_TILES", 1)
        asked = _server(monkeypatch, httpx.Response(200, content=PNG))

        await tile_proxy.tile(1, 0, 0)
        await tile_proxy.tile(1, 1, 0)
        await tile_proxy.tile(1, 0, 0)

        assert len(asked) == 3

    @pytest.mark.security
    @pytest.mark.parametrize(
        "answer",
        [
            httpx.Response(404, content=PNG),
            httpx.Response(200, content=b"<html>not a tile</html>"),
            # Served from the content origin, an SVG could run script there.
            httpx.Response(200, content=b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
            httpx.Response(200, content=PNG + b"\x00" * tile_proxy.TILE_MAX_BYTES),
        ],
    )
    async def test_what_is_not_a_raster_tile_is_refused_and_not_kept(
        self, monkeypatch: pytest.MonkeyPatch, answer: httpx.Response
    ) -> None:
        _server(monkeypatch, answer)
        with pytest.raises(ExternalServiceError):
            await tile_proxy.tile(0, 0, 0)
        assert tile_proxy._cache == {}

    async def test_a_server_that_cannot_be_reached_is_an_external_failure(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        _server(monkeypatch, httpx.ConnectError("refused"))
        with pytest.raises(ExternalServiceError):
            await tile_proxy.tile(0, 0, 0)
        assert "secret" not in caplog.text

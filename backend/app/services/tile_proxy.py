"""Map tiles for visuals and apps, fetched by this deployment rather than by the page (#2302).

A page is model-written script that may have read hostile input. Letting it load
images from the tile server itself would give it two things it must not have:
the server's address with whatever key the operator put in it - readable by
anybody from the public frame - and a way out, since a page can write anything
into a tile's path. So a page asks this deployment for a tile by three numbers,
each checked against the zoom it can exist at, and only this server talks to the
tile server. The content policy names this path and no remote host.

Tiles are kept in a small in-process cache: a map is the same few dozen tiles
for everybody who opens it, and a tile server asks its clients not to fetch the
same tile over and over.
"""

import logging
from collections import OrderedDict

import httpx

from app.core.config import settings
from app.core.exceptions import ExternalServiceError, NotFoundError
from app.services.visual import image_type

logger = logging.getLogger(__name__)

TILE_MAX_BYTES = 512 * 1024
"""One tile's ceiling. A raster tile is tens of kilobytes; more is not a tile."""

TILE_TIMEOUT_SECONDS = 10.0

CACHE_TILES = 2048
"""How many tiles one process keeps - a few busy maps' worth, a few tens of megabytes."""

USER_AGENT = "AgenticOS map tiles"
"""Tile servers ask a client to say who it is; OpenStreetMap's policy refuses one that does not."""

_RASTER = frozenset({"image/png", "image/jpeg", "image/webp"})
"""What a tile may be. Never an SVG: the bytes are served from the content origin."""

_cache: OrderedDict[tuple[int, int, int], tuple[bytes, str]] = OrderedDict()


async def tile(z: int, x: int, y: int) -> tuple[bytes, str]:
    """One map tile and its media type, from the cache or the deployment's tile server.

    Raises:
        NotFoundError: The deployment names no tile server, or no tile has these
            coordinates at this zoom - one answer for both, as for any address
            that serves nothing.
        ExternalServiceError: The tile server did not answer with an image.
    """
    tiles = settings.map_tiles()
    if tiles is None or not 0 <= z <= tiles.max_zoom or not (0 <= x < 2**z and 0 <= y < 2**z):
        raise NotFoundError(message="There is no such map tile", details={"z": z, "x": x, "y": y})
    key = (z, x, y)
    kept = _cache.get(key)
    if kept is not None:
        _cache.move_to_end(key)
        return kept
    url = tiles.url.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
    try:
        async with httpx.AsyncClient(
            timeout=TILE_TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError as failed:
        # The server's name, never its address: the address may carry the key.
        logger.warning(
            "map_tile_fetch_failed", extra={"server": tiles.name, "error": type(failed).__name__}
        )
        raise ExternalServiceError(message="The map tile server did not answer") from failed
    data = response.content
    media_type = image_type(data)
    if (
        response.status_code != 200
        or len(data) > TILE_MAX_BYTES
        or media_type is None
        or media_type not in _RASTER
    ):
        logger.warning(
            "map_tile_refused",
            extra={"server": tiles.name, "status": response.status_code, "bytes": len(data)},
        )
        raise ExternalServiceError(message="The map tile server did not send a map tile")
    _cache[key] = (data, media_type)
    if len(_cache) > CACHE_TILES:
        _cache.popitem(last=False)
    return data, media_type

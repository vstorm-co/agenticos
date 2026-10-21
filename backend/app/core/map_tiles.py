"""The one tile server the deployment draws maps on, when it names one (#2302).

A visual and a published page have no network. A map needs its background, a
few dozen small images from a tile server, so an operator may name one - and
this deployment fetches the tiles for the page, by three checked numbers, through
its own tile path (`app/services/tile_proxy.py`). The page never learns the
server's address, which may carry the operator's key, and cannot write anything
into a request to it. Off by default.

`VISUAL_MAP_TILES` is a preset from `catalog/map_tiles.json` or a URL template
of the operator's own, which then needs `VISUAL_MAP_TILES_ATTRIBUTION`: a tile
server's licence asks for its credit on the map, and only the operator knows it.
"""

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from app.core.catalog import load

CUSTOM = "custom"
"""The id a tile server named by its URL template is known by."""

CUSTOM_MAX_ZOOM = 18
"""How far a map on an operator's own server zooms - where most tile servers stop."""

_PLACEHOLDER = re.compile(r"\{[^{}]*\}")

# What no tile address has: a template carrying one is a typo or a pasted
# snippet, refused at startup rather than requested.
_UNSAFE = re.compile(r"[\s;,'\"<>\\]")


def template_problem(url: str) -> str | None:
    """Why a tile URL template cannot be served, or `None` when it can."""
    if not url.startswith("https://"):
        return "a tile server's URL template must start with https://"
    if _UNSAFE.search(url):
        return "a tile server's URL template must not contain spaces, quotes, `;` or `,`"
    parts = urlsplit(url)
    if not parts.hostname or _PLACEHOLDER.search(parts.netloc):
        return "a tile server's URL template must name its host without placeholders"
    if "@" in parts.netloc:
        return "a tile server's URL template must not carry a user name or password"
    try:
        parts.port  # noqa: B018 - reading it is the check: a bad port raises
    except ValueError:
        return "a tile server's URL template names a port no client can use"
    if sorted(_PLACEHOLDER.findall(url)) != ["{x}", "{y}", "{z}"]:
        return "a tile server's URL template must hold {z}, {x} and {y} once each, and no other placeholder"
    return None


class MapTiles(BaseModel):
    """A tile server, as a drawing reads it and as the content policy admits it."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    name: str = Field(min_length=1, max_length=80)
    url: str
    """The Leaflet URL template - `{z}`, `{x}` and `{y}`."""
    attribution: str = Field(min_length=1, max_length=200)
    attribution_url: str | None = None
    max_zoom: int = Field(ge=1, le=22)

    @field_validator("url")
    @classmethod
    def _servable(cls, url: str) -> str:
        problem = template_problem(url)
        if problem is not None:
            raise ValueError(problem)
        return url


PRESETS: dict[str, MapTiles] = {
    preset.id: preset for preset in load("map_tiles.json", TypeAdapter(list[MapTiles]))
}


def resolve(choice: str, attribution: str) -> MapTiles | None:
    """The tile server `VISUAL_MAP_TILES` names, or `None` when it names none.

    Raises:
        ValueError: An unknown preset, an unservable template, or a template with
            no attribution - each a refusal to start, since a deployment that
            meant to have maps would otherwise draw every map without one.
    """
    choice = choice.strip()
    if not choice:
        return None
    if "://" not in choice:
        preset = PRESETS.get(choice)
        if preset is None:
            raise ValueError(
                f"VISUAL_MAP_TILES={choice!r} is not a preset. Use one of "
                f"{', '.join(sorted(PRESETS))}, or a https:// URL template"
            )
        return preset
    problem = template_problem(choice)
    if problem is not None:
        raise ValueError(f"VISUAL_MAP_TILES: {problem}")
    if not attribution.strip():
        raise ValueError(
            "VISUAL_MAP_TILES names a tile server of your own, so VISUAL_MAP_TILES_ATTRIBUTION "
            "must say whose map it is - e.g. '© OpenStreetMap contributors'"
        )
    return MapTiles(
        id=CUSTOM,
        name=urlsplit(choice).hostname or CUSTOM,
        url=choice,
        attribution=attribution.strip(),
        max_zoom=CUSTOM_MAX_ZOOM,
    )

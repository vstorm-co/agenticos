"""The one tile server a drawing may load a map from, when the deployment names one (#2302).

A visual and a published page have no network: their policy admits nothing
remote but the deployment's own library set, so a page cannot send what it shows
anywhere. A map needs its background, which is a few hundred small images from
a tile server - so an operator may name one, and the content policy then admits
images from that server's tile path and from nowhere else. Scripts, styles and
`connect-src` stay closed. An image request still carries its own address, so a
page could spell something into a tile's path; what it reaches is the server the
operator chose, which is why there is exactly one and it is off by default.

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

# Anything that could end a source expression, or start another, once the address
# is written into the content policy.
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

    @property
    def source(self) -> str:
        """The content policy's source for these tiles: the host and the path up to the tiles.

        A source ending in `/` matches every path under it, so the policy admits
        this server's tile directory and not the rest of the host. A template
        whose placeholders are all in the query admits its exact path.
        """
        parts = urlsplit(self.url)
        path = parts.path
        first = path.find("{")
        if first >= 0:
            path = path[: path.rfind("/", 0, first) + 1]
        return f"https://{parts.netloc}{path or '/'}"


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

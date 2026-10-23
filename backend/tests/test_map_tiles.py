"""The one tile server a drawing may load a map from (#2302)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.map_tiles import CUSTOM, CUSTOM_MAX_ZOOM, PRESETS, MapTiles, resolve, template_problem


class TestPresets:
    def test_none_is_none(self) -> None:
        assert resolve("", "") is None
        assert resolve("   ", "ignored") is None

    def test_a_preset_is_the_catalog_s_entry(self) -> None:
        tiles = resolve("openstreetmap", "")
        assert tiles is PRESETS["openstreetmap"]
        assert tiles is not None
        assert tiles.attribution == "© OpenStreetMap contributors"

    def test_every_preset_is_servable(self) -> None:
        assert set(PRESETS) == {"openstreetmap", "usgs-topo"}
        for tiles in PRESETS.values():
            assert template_problem(tiles.url) is None
            assert tiles.attribution_url is not None

    def test_an_unknown_preset_is_refused_naming_the_known_ones(self) -> None:
        with pytest.raises(ValueError, match="openstreetmap, usgs-topo"):
            resolve("google", "")


class TestOwnServer:
    def test_a_template_with_an_attribution_is_a_server_of_its_own(self) -> None:
        tiles = resolve("https://tiles.example.com/v1/{z}/{x}/{y}.png?key=abc", " © Example ")
        assert tiles is not None
        assert tiles.id == CUSTOM
        assert tiles.name == "tiles.example.com"
        assert tiles.attribution == "© Example"
        assert tiles.max_zoom == CUSTOM_MAX_ZOOM

    def test_a_template_needs_its_attribution(self) -> None:
        with pytest.raises(ValueError, match="VISUAL_MAP_TILES_ATTRIBUTION"):
            resolve("https://tiles.example.com/{z}/{x}/{y}.png", "  ")

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("url", "problem"),
        [
            ("http://tiles.example.com/{z}/{x}/{y}.png", "https://"),
            ("https://tiles.example.com/{z}/{x}/{y}.png; script-src *", "spaces"),
            ("https://tiles.example.com/{z}/{x}/{y}.png,https://evil.example", "`,`"),
            ("https://{s}.tiles.example.com/{z}/{x}/{y}.png", "host"),
            ("https:///{z}/{x}/{y}.png", "host"),
            ("https://tiles.example.com/{z}/{x}.png", "{z}, {x} and {y}"),
            ("https://tiles.example.com/{z}/{x}/{y}/{r}.png", "{z}, {x} and {y}"),
            ("https://tiles.example.com/{z}/{z}/{x}/{y}.png", "{z}, {x} and {y}"),
            ("https://tiles.example.com:99999/{z}/{x}/{y}.png", "port"),
            ("https://tiles.example.com:abc/{z}/{x}/{y}.png", "port"),
            ("https://user:pass@tiles.example.com/{z}/{x}/{y}.png", "user name"),
        ],
    )
    def test_a_template_that_could_widen_the_policy_is_refused(
        self, url: str, problem: str
    ) -> None:
        refusal = template_problem(url)
        assert refusal is not None
        assert problem in refusal
        with pytest.raises(ValueError, match="VISUAL_MAP_TILES"):
            resolve(url, "© Example")


class TestSettings:
    def test_a_deployment_with_a_bad_tile_setting_refuses_to_start(self) -> None:
        with pytest.raises(ValidationError, match="is not a preset"):
            Settings(VISUAL_MAP_TILES="google")

    def test_the_setting_resolves_to_its_server(self) -> None:
        settings = Settings(VISUAL_MAP_TILES="usgs-topo")
        tiles = settings.map_tiles()
        assert tiles is not None
        assert tiles.name == "USGS The National Map"


def test_a_catalog_entry_that_cannot_be_served_is_refused() -> None:
    with pytest.raises(ValidationError, match="https://"):
        MapTiles(
            id="bad", name="Bad", url="http://t.example/{z}/{x}/{y}", attribution="a", max_zoom=3
        )

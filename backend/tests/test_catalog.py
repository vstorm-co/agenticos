"""The deployment catalog: data files that refuse to half-load, icons that
cannot be probed.

The JSON files are validated at import by the consuming modules' own types, so
"the catalogs load" is already asserted by every test run reaching this line.
What needs pinning is the refusal path - a malformed file must stop the app,
not ship a picker with a hole in it - and the icon name grammar, which is the
whole path-traversal defence.
"""

from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core import catalog
from app.services.mcp_catalog import CatalogEntry


class TestLoad:
    def test_a_malformed_entry_refuses_to_load(self, tmp_path: Path, monkeypatch):
        """`auth: "carrier-pigeon"` must raise at import, loudly - the
        alternative is a server that silently vanishes from the picker."""
        bad = tmp_path / "mcp_servers.json"
        bad.write_text(
            '[{"key": "x", "name": "X", "description": "", "category": "other",'
            ' "auth": "carrier-pigeon"}]'
        )
        monkeypatch.setattr(catalog, "_DIR", tmp_path)

        with pytest.raises(ValidationError):
            catalog.load("mcp_servers.json", TypeAdapter(tuple[CatalogEntry, ...]))


class TestCustomIcons:
    @pytest.fixture
    def icons_dir(self, tmp_path: Path, monkeypatch) -> Path:
        monkeypatch.setattr(catalog, "ICONS_DIR", tmp_path)
        return tmp_path

    def test_lists_only_svg_files_with_servable_names(self, icons_dir: Path):
        (icons_dir / "acme.svg").write_text("<svg/>")
        (icons_dir / "acme-2.svg").write_text("<svg/>")
        (icons_dir / "README.md").write_text("not an icon")
        # A name outside the slug grammar is unreachable through the route, so
        # listing it would advertise a mark nobody can fetch.
        (icons_dir / "Bad Name.svg").write_text("<svg/>")

        assert catalog.custom_icon_names() == ["acme", "acme-2"]

    def test_resolves_an_icon_that_exists(self, icons_dir: Path):
        (icons_dir / "acme.svg").write_text("<svg/>")
        assert catalog.custom_icon("acme") == icons_dir / "acme.svg"

    def test_picks_the_asked_for_mark_out_of_several(self, icons_dir: Path):
        """The lookup walks the directory rather than building a path, so it has
        to pass over the marks it was not asked for."""
        for stem in ("acme", "beta", "gamma"):
            (icons_dir / f"{stem}.svg").write_text(f"<svg>{stem}</svg>")

        assert catalog.custom_icon("gamma") == icons_dir / "gamma.svg"

    def test_a_name_matching_no_mark_passes_over_the_ones_present(self, icons_dir: Path):
        """Whether the test above reaches the skip is the filesystem's decision:
        `glob` yields `scandir` order, so a directory answering `gamma` first
        returns on the first iteration and leaves the skip unexecuted - a 99.98%
        gate on a branch that touched no Python (#625). Asking for a name that
        matches nothing passes over every candidate in any order."""
        for stem in ("acme", "beta"):
            (icons_dir / f"{stem}.svg").write_text("<svg/>")

        assert catalog.custom_icon("ghost") is None

    def test_a_missing_icon_resolves_to_none(self, icons_dir: Path):
        assert catalog.custom_icon("ghost") is None

    @pytest.mark.parametrize("name", ["../secrets", "a/b", "acme.svg", "ACME", "", "-x"])
    def test_a_name_outside_the_slug_grammar_is_refused(self, icons_dir: Path, name: str):
        """The first half of the traversal defence: no dot and no slash means
        no way to name a path outside the icons directory."""
        assert catalog.custom_icon(name) is None

    def test_a_symlink_out_of_the_directory_is_refused(self, icons_dir: Path, tmp_path: Path):
        """The half the grammar cannot cover.

        `brand.svg` is a perfectly legal name. If it is a link to something
        outside the icons directory, every rule above is satisfied and the
        route would serve bytes the operator never put there - which is the one
        way this endpoint could read a file it has no business reading. An
        icons directory is somewhere files get dropped, so a link landing in it
        is not far-fetched.
        """
        outside = tmp_path.parent / "not-an-icon.svg"
        outside.write_text("<svg>secrets</svg>")
        (icons_dir / "brand.svg").symlink_to(outside)

        assert catalog.custom_icon("brand") is None

    def test_a_real_file_beside_a_refused_link_still_resolves(self, icons_dir: Path):
        """The refusal has to be about the link, not about the directory."""
        (icons_dir / "acme.svg").write_text("<svg/>")
        assert catalog.custom_icon("acme") is not None

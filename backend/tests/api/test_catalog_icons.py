"""The custom icon endpoints: public, cacheable, unprobeable.

Deliberately tested without auth headers - a CSS mask URL cannot attach a
bearer token, so the moment these routes require one is the moment every
custom mark silently degrades to a monogram.
"""

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core import catalog
from app.core.config import settings

BASE = f"{settings.API_V1_STR}/catalog/icons"


@pytest.fixture
def icons_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(catalog, "ICONS_DIR", tmp_path)
    return tmp_path


@pytest.mark.anyio
async def test_lists_the_marks_the_deployment_ships(client: AsyncClient, icons_dir: Path):
    (icons_dir / "acme.svg").write_text("<svg/>")

    response = await client.get(BASE)

    assert response.status_code == 200
    assert response.json() == {"items": ["acme"], "total": 1}


@pytest.mark.anyio
async def test_serves_the_svg_as_an_inert_image(client: AsyncClient, icons_dir: Path):
    """The CSP is the point: an operator-supplied SVG opened as a document can
    run script, and this header is what makes it a picture again."""
    (icons_dir / "acme.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')

    response = await client.get(f"{BASE}/acme")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["content-security-policy"] == (
        "default-src 'none'; style-src 'unsafe-inline'"
    )
    assert "max-age=3600" in response.headers["cache-control"]
    assert response.text.startswith("<svg")


@pytest.mark.anyio
async def test_an_unknown_icon_is_404(client: AsyncClient, icons_dir: Path):
    response = await client.get(f"{BASE}/ghost")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_a_traversal_shaped_name_is_404_not_a_file_read(client: AsyncClient, icons_dir: Path):
    """`..%2F` decodes to a path segment; the slug grammar refuses it before
    any filesystem call, and the response must not distinguish why."""
    response = await client.get(f"{BASE}/..%2Fpyproject")
    assert response.status_code == 404

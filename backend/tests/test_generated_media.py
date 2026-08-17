"""Storage for agent-generated images - roundtrip and tenant isolation."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.services.generated_media import (
    generated_image_url,
    load_generated_image,
    save_generated_image,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _media_dir(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Point the file store at a throwaway directory for the test."""
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)


async def test_a_saved_image_reads_back_byte_for_byte():
    organization_id = uuid4()
    filename = await save_generated_image(organization_id, b"\x89PNG-bytes", image_format="png")

    assert filename.endswith("_image.png")
    assert await load_generated_image(organization_id, filename) == b"\x89PNG-bytes"


async def test_another_organization_cannot_read_the_image():
    """Storage is per-organization: the directory is built from the reader's id."""
    owner, intruder = uuid4(), uuid4()
    filename = await save_generated_image(owner, b"private", image_format="png")

    with pytest.raises(NotFoundError):
        await load_generated_image(intruder, filename)


async def test_a_missing_image_is_not_found():
    with pytest.raises(NotFoundError):
        await load_generated_image(uuid4(), "deadbeef1234_image.png")


async def test_a_traversing_filename_cannot_climb_out_of_the_org_directory():
    """`../` in a name would resolve inside the shared root, into a sibling org."""
    owner, other = uuid4(), uuid4()
    leaf = await save_generated_image(other, b"someone-elses", image_format="png")

    with pytest.raises(NotFoundError):
        await load_generated_image(owner, f"../generated_{other}/{leaf}")


async def test_the_serving_url_addresses_the_leaf():
    assert generated_image_url("abc123_image.png") == "/api/v1/generated/abc123_image.png"

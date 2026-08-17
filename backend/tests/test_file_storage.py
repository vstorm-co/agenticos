"""The local file store's one refusal: a storage path that leaves the root."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.file_storage import LocalFileStorage

pytestmark = pytest.mark.anyio


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(base_dir=tmp_path / "media")


async def test_a_saved_file_reads_back_byte_for_byte(storage: LocalFileStorage):
    stored = await storage.save("u1", "report.csv", b"month,total")

    assert await storage.load(stored) == b"month,total"
    assert storage.get_full_path(stored) == (storage.base_dir / stored).resolve()


@pytest.mark.parametrize(
    "storage_path",
    [
        "../secrets.env",
        "u1/../../secrets.env",
        "/etc/passwd",
    ],
)
async def test_a_path_leaving_the_storage_root_is_refused(
    storage: LocalFileStorage, storage_path: str
):
    with pytest.raises(ValueError, match="escapes storage root"):
        await storage.load(storage_path)
    with pytest.raises(ValueError, match="escapes storage root"):
        await storage.delete(storage_path)
    assert storage.get_full_path(storage_path) is None


async def test_a_sibling_of_the_root_sharing_its_prefix_is_refused(storage: LocalFileStorage):
    """`media_other` starts with `media`, and a prefix test without the separator would allow it."""
    sibling = storage.base_dir.parent / f"{storage.base_dir.name}_other"
    sibling.mkdir()
    (sibling / "secrets.env").write_bytes(b"KEY=1")

    with pytest.raises(ValueError, match="escapes storage root"):
        await storage.load(f"../{sibling.name}/secrets.env")

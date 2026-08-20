"""The local file store's one refusal: a storage path that leaves the root."""

from __future__ import annotations

import ast
import inspect
import os
import textwrap
from pathlib import Path

import pytest

from app.services.file_storage import LocalFileStorage, image_media_type_for

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.png", "image/png"),
        ("a.jpg", "image/jpeg"),
        ("a.webp", "image/webp"),
        ("a.gif", "image/gif"),
    ],
)
def test_an_image_is_served_as_its_own_type(name: str, expected: str) -> None:
    assert image_media_type_for(f"/uploads/{name}") == expected


@pytest.mark.parametrize("name", ["x.html", "x.svg", "x.xhtml", "x.txt", "x.pdf", "x"])
def test_a_non_image_is_refused_rather_than_served(name: str) -> None:
    # The avatar was stored under the uploader's own suffix, so a file saved as
    # `x.html` guesses to `text/html`; refused here, it cannot be served as a
    # script on the app's own origin (#702). A PDF is refused too - an avatar is
    # an image, and this helper serves only images.
    assert image_media_type_for(f"/uploads/{name}") is None


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


async def test_a_filesystem_root_as_the_storage_root_still_reaches_its_files(tmp_path: Path):
    """`/` already ends in the separator, and `//` is a prefix no descendant of it has."""
    target = (tmp_path / "note.txt").resolve()
    target.write_bytes(b"month,total")
    rooted = LocalFileStorage(base_dir=os.sep)

    stored = str(target.relative_to(os.sep))

    assert await rooted.load(stored) == b"month,total"
    assert rooted.get_full_path(stored) == target


async def test_a_sibling_of_the_root_sharing_its_prefix_is_refused(storage: LocalFileStorage):
    """`media_other` starts with `media`, and a prefix test without the separator would allow it."""
    sibling = storage.base_dir.parent / f"{storage.base_dir.name}_other"
    sibling.mkdir()
    (sibling / "secrets.env").write_bytes(b"KEY=1")

    with pytest.raises(ValueError, match="escapes storage root"):
        await storage.load(f"../{sibling.name}/secrets.env")


async def test_the_storage_root_itself_resolves_to_the_storage_root(storage: LocalFileStorage):
    """An empty path names the root, which is inside itself and not an escape."""
    assert storage.get_full_path("") == storage.base_dir.resolve()


def test_the_containment_check_is_the_whole_condition_of_its_branch():
    """What `py/path-injection` accepts as a barrier, and what #903 was.

    The query clears a normalised path only where the `startswith` call alone
    decides the branch. `candidate != base and not candidate.startswith(prefix)`
    refuses exactly the same paths and reads to a person as the same guard, but
    its fall-through proves neither conjunct, so the barrier never applied and
    both sinks in `load` stayed flagged through a release that said otherwise.

    This pins the shape, not the verdict - only CodeQL answers the verdict.
    """
    source = textwrap.dedent(inspect.getsource(LocalFileStorage._resolve_safe_path))
    branches = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.If) and "startswith" in ast.dump(node.test)
    ]

    assert len(branches) == 1
    test = branches[0].test
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        test = test.operand
    assert isinstance(test, ast.Call)
    assert isinstance(test.func, ast.Attribute)
    assert test.func.attr == "startswith"

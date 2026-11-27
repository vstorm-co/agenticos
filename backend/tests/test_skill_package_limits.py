"""Package limits apply to expanded bytes and workspace observations, not only metadata."""

import struct
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.workspaces import FileEntry, WrapperWorkspace
from pydantic_ai_backends import StateBackend

from app.core.exceptions import BadRequestError
from app.core.skill_files import validate_skill_metadata
from app.services import skill_package
from app.services.skill_workspace import MAX_PROPOSED_BYTES, SKILLS_ROOT, _read_tree
from tests.test_skill_package import BODY, zipped
from tests.workspaces import document_workspace

pytestmark = pytest.mark.security


def test_nested_finite_frontmatter_numbers_remain_json_numbers() -> None:
    metadata = {"evaluation": {"temperature": 0.125, "thresholds": [0.5, 1.0]}}
    assert validate_skill_metadata(metadata) == metadata


def test_archive_expanded_total_is_bounded_before_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_package, "MAX_SKILL_PACKAGE_BYTES", 2048)
    monkeypatch.setattr(skill_package, "MAX_SKILL_FILE_BYTES", 2048)
    archive = zipped([("SKILL.md", BODY), ("a.txt", b"x" * 1000), ("b.txt", b"y" * 1000)])
    assert len(archive) < 2048
    with pytest.raises(BadRequestError, match="Expanded"):
        skill_package.read_package_zip(archive)


def test_archive_declared_size_must_match_decompressed_bytes() -> None:
    archive = bytearray(zipped([("SKILL.md", BODY)]))
    central = archive.index(b"PK\x01\x02")
    struct.pack_into("<I", archive, central + 24, len(BODY) + 1)
    with pytest.raises(BadRequestError, match="declared size"):
        skill_package.read_package_zip(bytes(archive))


@pytest.mark.anyio
async def test_workspace_tree_bounds_depth_and_file_count() -> None:
    document = StateBackend()
    document.write_bytes(f"{SKILLS_ROOT}/deep/" + "child/" * 34 + "script.py", b"pass")
    for index in range(1026):
        document.write_bytes(f"{SKILLS_ROOT}/many/{index:04}.txt", b"small")
    result = await _read_tree(document_workspace(document))
    assert "deep" not in result
    assert len(result["many"]) == 1024


class _StaleSizes(WrapperWorkspace):
    async def list_dir(self, path: str = ".") -> list[FileEntry]:
        return [
            FileEntry(name=entry.name, path=entry.path, is_dir=entry.is_dir, size=0)
            for entry in await self.wrapped.list_dir(path)
        ]


@pytest.mark.anyio
async def test_workspace_refuses_growing_and_binary_files_but_keeps_text() -> None:
    document = StateBackend()
    root = f"{SKILLS_ROOT}/review"
    for name, raw in {
        "growing.txt": b"x" * (MAX_PROPOSED_BYTES + 1),
        "binary.dat": b"\xff",
        "nul.txt": b"valid UTF-8\x00binary",
        "safe.txt": b"keep this proposal",
    }.items():
        document.write_bytes(f"{root}/{name}", raw)
    assert await _read_tree(_StaleSizes(document_workspace(document))) == {
        "review": {f"{root}/safe.txt": "keep this proposal"}
    }


@pytest.mark.anyio
async def test_workspace_cyclic_listing_is_bounded() -> None:
    document = StateBackend()
    document.write_bytes(f"{SKILLS_ROOT}/cycle/safe.txt", b"safe")
    workspace = document_workspace(document)
    original = workspace.list_dir

    async def cyclic(path: str = ".") -> list[FileEntry]:
        entries = list(await original(path))
        if path == f"{SKILLS_ROOT}/cycle":
            entries.append(FileEntry(name="cycle", path=path, is_dir=True, size=None))
        return entries

    workspace.list_dir = AsyncMock(side_effect=cyclic)
    assert await _read_tree(workspace) == {"cycle": {f"{SKILLS_ROOT}/cycle/safe.txt": "safe"}}
    assert workspace.list_dir.await_count == 2

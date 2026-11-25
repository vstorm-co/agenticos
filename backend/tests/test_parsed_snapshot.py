"""Parsed exports are bounded data, not an instruction to parse or embed again."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.exceptions import BadRequestError
from app.services.file_storage import LocalFileStorage
from app.services.rag import parsed_snapshot as snapshots

pytestmark = pytest.mark.anyio


def test_file_snapshot_preserves_exact_text_and_refuses_invalid_rows(tmp_path: Path) -> None:
    path = tmp_path / "chunks.jsonl"
    text = "  Exact αβ text\n"
    chunk = snapshots.ParsedSnapshotChunk(page_num=2, chunk_num=3, content=text)
    path.write_bytes((chunk.model_dump_json() + "\n").encode())
    assert list(snapshots.snapshot_file_chunks(path)) == [chunk]
    for value in (
        b"not json",
        b'{"content":1}',
        b'{"page_num":-1,"chunk_num":0,"content":"x"}',
        b"\xff",
    ):
        path.write_bytes(value)
        with pytest.raises(BadRequestError):
            list(snapshots.snapshot_file_chunks(path))
    with pytest.raises(ValidationError):
        snapshots.ParsedSnapshotChunk(page_num=True, chunk_num=0, content="x")


async def test_stream_reader_handles_partial_utf8_lines_and_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(tmp_path)
    text = (
        snapshots.ParsedSnapshotChunk(page_num=1, chunk_num=0, content="αβ").model_dump_json()
        + "\n"
    ).encode()
    closed: list[bool] = []

    async def pieces() -> AsyncGenerator[bytes]:
        try:
            for index in range(0, len(text), 3):
                yield text[index : index + 3]
        finally:
            closed.append(True)

    async def open_stream(path: str) -> AsyncGenerator[bytes]:
        assert path == "snapshot"
        return pieces()

    monkeypatch.setattr(storage, "open_stream", open_stream)
    assert [row.content async for row in snapshots.stored_snapshot_chunks(storage, "snapshot")] == [
        "αβ"
    ]
    assert closed == [True]


@pytest.mark.parametrize(
    "bound", ["MAX_SNAPSHOT_CHUNKS", "MAX_SNAPSHOT_BYTES", "MAX_SNAPSHOT_LINE_BYTES"]
)
async def test_both_readers_enforce_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bound: str
) -> None:
    storage = LocalFileStorage(tmp_path)
    line = (
        snapshots.ParsedSnapshotChunk(page_num=0, chunk_num=0, content="x")
        .model_dump_json()
        .encode()
    )
    data = line + b"\n" + line
    path = tmp_path / "test.jsonl"
    path.write_bytes(data)
    await storage.save_at("snapshot", data)
    monkeypatch.setattr(snapshots, bound, 1)
    with pytest.raises(BadRequestError):
        list(snapshots.snapshot_file_chunks(path))
    with pytest.raises(BadRequestError):
        _ = [row async for row in snapshots.stored_snapshot_chunks(storage, "snapshot")]


async def test_empty_and_last_unterminated_records_and_partial_line_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(tmp_path)
    path = tmp_path / "empty.jsonl"
    path.write_bytes(b"")
    assert list(snapshots.snapshot_file_chunks(path)) == []
    await storage.save_at("empty", b"")
    assert [row async for row in snapshots.stored_snapshot_chunks(storage, "empty")] == []
    line = (
        snapshots.ParsedSnapshotChunk(page_num=0, chunk_num=0, content="x")
        .model_dump_json()
        .encode()
    )
    await storage.save_at("one", line)
    assert len([row async for row in snapshots.stored_snapshot_chunks(storage, "one")]) == 1
    await storage.save_at("two", line + b"\n" + line + b"\n")
    monkeypatch.setattr(snapshots, "MAX_SNAPSHOT_CHUNKS", 1)
    with pytest.raises(BadRequestError):
        _ = [row async for row in snapshots.stored_snapshot_chunks(storage, "two")]
    monkeypatch.setattr(snapshots, "MAX_SNAPSHOT_LINE_BYTES", 1)
    await storage.save_at("unterminated", b"xxx")
    with pytest.raises(BadRequestError):
        _ = [row async for row in snapshots.stored_snapshot_chunks(storage, "unterminated")]


def test_exact_ten_thousand_chunk_boundary(tmp_path: Path) -> None:
    path = tmp_path / "large.jsonl"
    line = (
        snapshots.ParsedSnapshotChunk(page_num=0, chunk_num=0, content="x")
        .model_dump_json()
        .encode()
        + b"\n"
    )
    path.write_bytes(line * 10_000)
    assert sum(1 for _ in snapshots.snapshot_file_chunks(path)) == 10_000
    with path.open("ab") as file:
        file.write(line)
    with pytest.raises(BadRequestError, match="10,000"):
        list(snapshots.snapshot_file_chunks(path))

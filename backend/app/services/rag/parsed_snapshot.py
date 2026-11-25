"""Bounded parsed-text snapshots; content only, never vectors or provider calls."""

from collections.abc import AsyncIterator, Iterator
from contextlib import aclosing
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.exceptions import BadRequestError
from app.services.file_storage import BaseFileStorage

MAX_SNAPSHOT_CHUNKS = 10_000
MAX_SNAPSHOT_LINE_BYTES = 1024 * 1024
MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024


class ParsedSnapshotChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    page_num: int = Field(ge=0)
    chunk_num: int = Field(ge=0)
    content: str


def parse_snapshot_line(line: bytes) -> ParsedSnapshotChunk:
    if len(line) > MAX_SNAPSHOT_LINE_BYTES:
        raise BadRequestError(message="A parsed-text chunk exceeds the 1 MiB limit")
    try:
        return ParsedSnapshotChunk.model_validate_json(line)
    except ValidationError as exc:
        raise BadRequestError(message="Parsed text must contain UTF-8 chunk records") from exc


def snapshot_file_chunks(path: Path) -> Iterator[ParsedSnapshotChunk]:
    """Validate before any import writes, without materializing the full JSONL."""
    size = 0
    with path.open("rb") as source:
        count = 0
        while line := source.readline(MAX_SNAPSHOT_LINE_BYTES + 1):
            count += 1
            if count > MAX_SNAPSHOT_CHUNKS:
                raise BadRequestError(message="Import at most 10,000 parsed chunks per transfer")
            size += len(line)
            if size > MAX_SNAPSHOT_BYTES:
                raise BadRequestError(message="A parsed-text snapshot exceeds 256 MiB")
            yield parse_snapshot_line(line)


async def stored_snapshot_chunks(
    storage: BaseFileStorage, path: str
) -> AsyncIterator[ParsedSnapshotChunk]:
    """Read local and object-store snapshots with the same line/size bounds."""
    stream = await storage.open_stream(path)
    buffer = bytearray()
    size = count = 0
    async with aclosing(stream):
        async for piece in stream:
            size += len(piece)
            if size > MAX_SNAPSHOT_BYTES:
                raise BadRequestError(message="A parsed-text snapshot exceeds 256 MiB")
            buffer.extend(piece)
            while (end := buffer.find(b"\n")) >= 0:
                count += 1
                if count > MAX_SNAPSHOT_CHUNKS:
                    raise BadRequestError(
                        message="Import at most 10,000 parsed chunks per transfer"
                    )
                line = bytes(buffer[: end + 1])
                del buffer[: end + 1]
                yield parse_snapshot_line(line)
            if len(buffer) > MAX_SNAPSHOT_LINE_BYTES:
                raise BadRequestError(message="A parsed-text chunk exceeds the 1 MiB limit")
        if buffer:
            if count == MAX_SNAPSHOT_CHUNKS:
                raise BadRequestError(message="Import at most 10,000 parsed chunks per transfer")
            yield parse_snapshot_line(bytes(buffer))

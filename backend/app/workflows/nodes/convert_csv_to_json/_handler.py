"""`convert.csv_to_json`: a CSV file as a JSON file of header-keyed rows.

The CSV must be exact - UTF-8, every row as wide as its header - or the step
fails with `FILE_PARSE_FAILED`; a half-converted file is worse than none.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._files import JSON, ParseError, csv_rows, utf8


class ConvertCsvToJsonConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_bytes: int = Field(default=25_000_000, ge=1, le=50_000_000)


class ConvertFileInput(BaseModel):
    """The file to convert, bound from an earlier step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: FileRef


class ConvertCsvToJsonOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file: FileRef
    row_count: int


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, ConvertCsvToJsonConfig) or not isinstance(
        node_input, ConvertFileInput
    ):
        return files.failed("FILE_STEP_NOT_CONFIGURED", "This step has no file to convert")
    stored = await files.load(node_input.file, max_bytes=config.max_bytes)
    if isinstance(stored, Failed):
        return stored
    try:
        rows = csv_rows(utf8(stored.data))
    except ParseError as exc:
        return files.failed("FILE_PARSE_FAILED", f"This is not a CSV file it can read: {exc}")
    stem = (stored.filename or "rows").rsplit(".", 1)[0]
    converted = await files.save(
        json.dumps(list(rows), ensure_ascii=False, indent=2).encode(),
        content_type=JSON,
        filename=f"{stem}.json",
    )
    return Completed[ConvertCsvToJsonOutput](
        output=ConvertCsvToJsonOutput(file=converted, row_count=len(rows))
    )

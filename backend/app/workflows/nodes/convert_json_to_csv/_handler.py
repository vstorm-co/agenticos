"""`convert.json_to_csv`: a JSON list of flat objects as a CSV file.

Only a list of objects whose values are text, numbers, true, false or null is
tabular. Anything else - an object, a nested list, a row holding an object -
fails with `NOT_TABULAR`, never a guessed flattening nobody asked for. The
header is every key, in the order it first appears.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._files import CSV, ParseError, csv_text, utf8
from app.workflows.nodes.convert_csv_to_json._handler import ConvertFileInput


class ConvertJsonToCsvConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_bytes: int = Field(default=25_000_000, ge=1, le=50_000_000)


class ConvertJsonToCsvOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file: FileRef
    row_count: int


def _rows(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        return None
    return value


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, ConvertJsonToCsvConfig) or not isinstance(
        node_input, ConvertFileInput
    ):
        return files.failed("FILE_STEP_NOT_CONFIGURED", "This step has no file to convert")
    stored = await files.load(node_input.file, max_bytes=config.max_bytes)
    if isinstance(stored, Failed):
        return stored
    try:
        value = json.loads(utf8(stored.data))
    except (ParseError, ValueError) as exc:
        return files.failed("FILE_PARSE_FAILED", f"This is not a JSON file it can read: {exc}")
    rows = _rows(value)
    if rows is None:
        return files.failed("NOT_TABULAR", "Only a JSON list of objects converts to CSV")
    try:
        text = csv_text(rows)
    except ParseError as exc:
        return files.failed("NOT_TABULAR", str(exc))
    stem = (stored.filename or "rows").rsplit(".", 1)[0]
    converted = await files.save(text.encode(), content_type=CSV, filename=f"{stem}.csv")
    return Completed[ConvertJsonToCsvOutput](
        output=ConvertJsonToCsvOutput(file=converted, row_count=len(rows))
    )

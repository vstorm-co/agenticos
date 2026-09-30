"""`file.write`: store text, a JSON value or rows as a new file of the run.

The field `format` names is the one written; a step asked to write CSV with no
rows, or text with no text, fails rather than store an empty file nobody meant.
Every call mints a new file, so the step is `at_least_once`: a retry after a
lost answer leaves a second copy rather than finding the first.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._files import CSV, JSON, TEXT, ParseError, csv_text

MAX_WRITE_BYTES = 25_000_000
_EXTENSION = {"text": "txt", "json": "json", "csv": "csv"}
_MEDIA_TYPE = {"text": TEXT, "json": JSON, "csv": CSV}


class FileWriteConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    format: Literal["text", "json", "csv"] = "text"
    filename: str | None = Field(
        default=None,
        max_length=255,
        json_schema_extra={"x-bindable": True},
        description="What to call the file. `output.<format>` when left empty.",
    )


class FileWriteInput(BaseModel):
    """What to write: the field `format` names."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str | None = None
    json_value: Any = None
    rows: tuple[dict[str, Any], ...] | None = None


class FileWriteOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file: FileRef


def _content(config: FileWriteConfig, node_input: FileWriteInput) -> str | None:
    if config.format == "json":
        if "json_value" not in node_input.model_fields_set:
            return None
        return json.dumps(node_input.json_value, ensure_ascii=False, indent=2)
    if config.format == "csv":
        return None if node_input.rows is None else csv_text(node_input.rows)
    return node_input.text


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, FileWriteConfig):
        return files.failed("FILE_STEP_NOT_CONFIGURED", "This step has nothing to write")
    # With nothing bound there is no input at all, which is the empty write below.
    written = node_input if isinstance(node_input, FileWriteInput) else FileWriteInput()
    try:
        content = _content(config, written)
    except ParseError as exc:
        return files.failed("FILE_WRITE_FAILED", str(exc), format=config.format)
    if content is None:
        return files.failed(
            "FILE_WRITE_FAILED",
            f"Bind the {config.format} to write - this step was given none",
            format=config.format,
        )
    data = content.encode()
    if len(data) > MAX_WRITE_BYTES:
        return files.failed(
            files.FILE_TOO_LARGE,
            f"This file would be {len(data)} bytes, over the limit of {MAX_WRITE_BYTES}",
            byte_size=len(data),
            max_bytes=MAX_WRITE_BYTES,
        )
    stored = await files.save(
        data,
        content_type=_MEDIA_TYPE[config.format],
        filename=config.filename or f"output.{_EXTENSION[config.format]}",
    )
    return Completed[FileWriteOutput](output=FileWriteOutput(file=stored))

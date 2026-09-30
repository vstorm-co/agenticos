"""`file.read`: one of the run's files as text, a JSON value or CSV rows.

The whole result travels inline to the next step, so the file is bounded
before anything is read: one larger than `max_bytes` fails before its bytes
leave storage. A file that is not what `parse_as` says - not UTF-8, JSON that
does not parse, a CSV row with the wrong number of fields - fails with
`FILE_PARSE_FAILED` rather than handing on part of it.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._files import ParseError, csv_rows, utf8

MAX_READ_BYTES = 25_000_000


class FileReadConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    parse_as: Literal["text", "json", "csv"] = "text"
    max_bytes: int = Field(default=10_000_000, ge=1, le=MAX_READ_BYTES)


class FileReadInput(BaseModel):
    """The file to read, bound from an earlier step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: FileRef


class FileReadOutput(BaseModel):
    """The one field `parse_as` names is set; the others stay empty."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str | None = None
    json_value: Any = None
    rows: tuple[dict[str, str], ...] | None = None


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, FileReadConfig) or not isinstance(node_input, FileReadInput):
        return files.failed("FILE_STEP_NOT_CONFIGURED", "This step has no file to read")
    stored = await files.load(node_input.file, max_bytes=config.max_bytes)
    if isinstance(stored, Failed):
        return stored
    try:
        text = utf8(stored.data)
        if config.parse_as == "json":
            output = FileReadOutput(json_value=json.loads(text))
        elif config.parse_as == "csv":
            output = FileReadOutput(rows=csv_rows(text))
        else:
            output = FileReadOutput(text=text)
    except (ParseError, ValueError) as exc:
        return files.failed(
            "FILE_PARSE_FAILED",
            f"This file cannot be read as {config.parse_as}: {exc}",
            parse_as=config.parse_as,
        )
    return Completed[FileReadOutput](output=output)

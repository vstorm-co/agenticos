"""`convert.text_to_file`: text - an extraction, an agent's answer - as a TXT file.

The pair of `text.extract`: text that has to travel as a file, to an upload or
an agent attachment, or that is too long to hand on inline.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._files import TEXT

MAX_TEXT_CHARS = 5_000_000


class ConvertTextToFileConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str = Field(
        default="text.txt", min_length=1, max_length=255, json_schema_extra={"x-bindable": True}
    )


class ConvertTextToFileInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(max_length=MAX_TEXT_CHARS)


class ConvertTextToFileOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file: FileRef


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, ConvertTextToFileConfig) or not isinstance(
        node_input, ConvertTextToFileInput
    ):
        return files.failed("FILE_STEP_NOT_CONFIGURED", "This step has no text to store")
    stored = await files.save(node_input.text.encode(), content_type=TEXT, filename=config.filename)
    return Completed[ConvertTextToFileOutput](output=ConvertTextToFileOutput(file=stored))

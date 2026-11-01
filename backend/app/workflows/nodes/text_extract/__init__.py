"""`text.extract` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.text_extract._handler import (
    TextExtractConfig,
    TextExtractInput,
    TextExtractOutput,
    handle,
)

__all__ = ["TextExtractConfig", "TextExtractInput", "TextExtractOutput"]

register(
    NodeDefinition(
        id="text.extract",
        version=1,
        name="Extract text",
        category="files",
        description=(
            "Read the text of a TXT, JSON, CSV, text PDF or DOCX file. A scanned page "
            "fails the step and says it needs OCR."
        ),
        kind="action",
        config_schema=TextExtractConfig,
        input_schema=TextExtractInput,
        output_schema=TextExtractOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=TextExtractOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
    )
)

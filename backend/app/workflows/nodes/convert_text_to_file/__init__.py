"""`convert.text_to_file` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.convert_text_to_file._handler import (
    ConvertTextToFileConfig,
    ConvertTextToFileInput,
    ConvertTextToFileOutput,
    handle,
)

__all__ = ["ConvertTextToFileConfig", "ConvertTextToFileInput", "ConvertTextToFileOutput"]

register(
    NodeDefinition(
        id="convert.text_to_file",
        version=1,
        name="Text to file",
        category="files",
        description="Store text as a UTF-8 TXT file of the run.",
        kind="action",
        config_schema=ConvertTextToFileConfig,
        input_schema=ConvertTextToFileInput,
        output_schema=ConvertTextToFileOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=ConvertTextToFileOutput),
        ),
        effect_kind="write",
        retry_guarantee="at_least_once",
        handler=handle,
    )
)

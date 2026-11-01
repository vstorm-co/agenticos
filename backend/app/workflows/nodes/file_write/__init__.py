"""`file.write` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.file_write._handler import (
    FileWriteConfig,
    FileWriteInput,
    FileWriteOutput,
    handle,
)

__all__ = ["FileWriteConfig", "FileWriteInput", "FileWriteOutput"]

register(
    NodeDefinition(
        id="file.write",
        version=1,
        name="Write a file",
        category="files",
        description="Store text, a JSON value or rows as a new UTF-8 file of the run.",
        kind="action",
        config_schema=FileWriteConfig,
        input_schema=FileWriteInput,
        output_schema=FileWriteOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=FileWriteOutput),
        ),
        effect_kind="write",
        retry_guarantee="at_least_once",
        handler=handle,
    )
)

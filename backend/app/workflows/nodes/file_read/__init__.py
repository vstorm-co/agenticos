"""`file.read` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.file_read._handler import (
    FileReadConfig,
    FileReadInput,
    FileReadOutput,
    handle,
)

__all__ = ["FileReadConfig", "FileReadInput", "FileReadOutput"]

register(
    NodeDefinition(
        id="file.read",
        version=1,
        name="Read a file",
        category="files",
        description="Read one of the run's files as UTF-8 text, a JSON value or CSV rows.",
        kind="action",
        config_schema=FileReadConfig,
        input_schema=FileReadInput,
        output_schema=FileReadOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=FileReadOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
    )
)

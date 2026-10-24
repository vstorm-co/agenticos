"""`convert.json_to_csv` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.convert_csv_to_json._handler import ConvertFileInput
from app.workflows.nodes.convert_json_to_csv._handler import (
    ConvertJsonToCsvConfig,
    ConvertJsonToCsvOutput,
    handle,
)

__all__ = ["ConvertJsonToCsvConfig", "ConvertJsonToCsvOutput"]

register(
    NodeDefinition(
        id="convert.json_to_csv",
        version=1,
        name="JSON to CSV",
        category="files",
        description="Convert a JSON list of flat objects into a CSV file.",
        kind="action",
        config_schema=ConvertJsonToCsvConfig,
        input_schema=ConvertFileInput,
        output_schema=ConvertJsonToCsvOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=ConvertJsonToCsvOutput),
        ),
        effect_kind="write",
        retry_guarantee="at_least_once",
        handler=handle,
    )
)

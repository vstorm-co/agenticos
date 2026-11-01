"""`convert.csv_to_json` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.convert_csv_to_json._handler import (
    ConvertCsvToJsonConfig,
    ConvertCsvToJsonOutput,
    ConvertFileInput,
    handle,
)

__all__ = ["ConvertCsvToJsonConfig", "ConvertCsvToJsonOutput", "ConvertFileInput"]

register(
    NodeDefinition(
        id="convert.csv_to_json",
        version=1,
        name="CSV to JSON",
        category="files",
        description="Convert a CSV file into a JSON file of header-keyed rows.",
        kind="action",
        config_schema=ConvertCsvToJsonConfig,
        input_schema=ConvertFileInput,
        output_schema=ConvertCsvToJsonOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=ConvertCsvToJsonOutput),
        ),
        effect_kind="write",
        retry_guarantee="at_least_once",
        handler=handle,
    )
)

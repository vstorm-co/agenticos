"""`convert.pdf_to_png` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.convert_csv_to_json._handler import ConvertFileInput
from app.workflows.nodes.convert_pdf_to_png._handler import (
    ConvertPdfToPngConfig,
    ConvertPdfToPngOutput,
    RenderedPage,
    handle,
)

__all__ = ["ConvertPdfToPngConfig", "ConvertPdfToPngOutput", "RenderedPage"]

register(
    NodeDefinition(
        id="convert.pdf_to_png",
        version=1,
        name="PDF pages to images",
        category="files",
        description="Render chosen pages of a PDF as PNG images, within the image pixel limit.",
        kind="action",
        config_schema=ConvertPdfToPngConfig,
        input_schema=ConvertFileInput,
        output_schema=ConvertPdfToPngOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=ConvertPdfToPngOutput),
        ),
        effect_kind="write",
        retry_guarantee="at_least_once",
        handler=handle,
    )
)

"""`image.transform` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.image_transform._handler import (
    ImageCrop,
    ImageResize,
    ImageTransformConfig,
    ImageTransformInput,
    ImageTransformOutput,
    handle,
)

__all__ = [
    "ImageCrop",
    "ImageResize",
    "ImageTransformConfig",
    "ImageTransformInput",
    "ImageTransformOutput",
]

register(
    NodeDefinition(
        id="image.transform",
        version=1,
        name="Transform an image",
        category="files",
        description=(
            "Crop, resize, rotate or convert a PNG, JPEG, WebP or GIF image, with its "
            "metadata removed and its size bounded before it is decoded."
        ),
        kind="action",
        config_schema=ImageTransformConfig,
        input_schema=ImageTransformInput,
        output_schema=ImageTransformOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=ImageTransformOutput),
        ),
        effect_kind="write",
        retry_guarantee="at_least_once",
        handler=handle,
    )
)

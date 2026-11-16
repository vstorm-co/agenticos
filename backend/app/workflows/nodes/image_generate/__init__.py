"""Permanent image generation registration; disabled deployments retain its schema."""

from functools import partial

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes import _media_handler
from app.workflows.nodes._media_config import (
    ImageGenerateConfig,
    ImageGenerationOutput,
    MediaGenerateInput,
)

__all__ = ["ImageGenerateConfig", "ImageGenerationOutput", "MediaGenerateInput"]

register(
    NodeDefinition(
        id="image.generate",
        version=1,
        name="Generate an image",
        category="model",
        description="Submit one bounded image request with a provider key, then inspect and retain its output and cost receipt.",
        kind="action",
        config_schema=ImageGenerateConfig,
        input_schema=MediaGenerateInput,
        output_schema=ImageGenerationOutput,
        ports=(
            Port(id="in", label="In", kind="input"),
            Port(id="out", label="Out", kind="output", schema=ImageGenerationOutput),
        ),
        effect_kind="write",
        retry_guarantee="none",
        spends_budget=True,
        handler=partial(_media_handler.handle, kind="image"),
        resource_check=partial(_media_handler.check_resources, kind="image"),
        available=partial(_media_handler.available, "image"),
    )
)

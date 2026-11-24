"""Permanent video registration; a known receipt resumes collection without submission."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._media_config import (
    MediaGenerateInput,
    VideoGenerateConfig,
    VideoGenerationOutput,
)
from app.workflows.nodes.video_generate._handler import available, check_resources, handle

__all__ = ["MediaGenerateInput", "VideoGenerateConfig", "VideoGenerationOutput"]

register(
    NodeDefinition(
        id="video.generate",
        version=1,
        name="Generate a video",
        category="model",
        description="Submit one bounded video request or collect its durable provider receipt, then inspect and retain the clip.",
        kind="action",
        config_schema=VideoGenerateConfig,
        input_schema=MediaGenerateInput,
        output_schema=VideoGenerationOutput,
        ports=(
            Port(id="in", label="In", kind="input"),
            Port(id="out", label="Out", kind="output", schema=VideoGenerationOutput),
        ),
        effect_kind="write",
        retry_guarantee="none",
        spends_budget=True,
        handler=handle,
        resource_check=check_resources,
        available=available,
    )
)

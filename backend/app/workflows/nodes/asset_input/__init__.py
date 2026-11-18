"""Permanent registration for scoped media inspection, including when disabled."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.asset_input._handler import (
    AssetInput,
    AssetInputConfig,
    AssetOutput,
    available,
    check_resources,
    handle,
)

__all__ = ["AssetInput", "AssetInputConfig", "AssetOutput"]

register(
    NodeDefinition(
        id="asset.input",
        version=1,
        name="Inspect a media asset",
        category="files",
        description="Validate a run file's actual media type, size, dimensions and duration without generating or fetching media.",
        kind="action",
        config_schema=AssetInputConfig,
        input_schema=AssetInput,
        output_schema=AssetOutput,
        ports=(
            Port(id="in", label="In", kind="input"),
            Port(id="out", label="Out", kind="output", schema=AssetOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        resource_check=check_resources,
        available=available,
    )
)

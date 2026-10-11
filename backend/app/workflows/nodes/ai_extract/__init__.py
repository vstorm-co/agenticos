"""`ai.extract` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.ai_extract._handler import (
    NAME,
    AiExtractConfig,
    AiExtractInput,
    AiExtractOutput,
    check_resources,
    handle,
)

__all__ = ["AiExtractConfig", "AiExtractInput", "AiExtractOutput"]

register(
    NodeDefinition(
        id="ai.extract",
        version=1,
        name=NAME,
        category="model",
        description="Have a model pull the fields you name out of a text, as an object.",
        kind="action",
        config_schema=AiExtractConfig,
        input_schema=AiExtractInput,
        output_schema=AiExtractOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=AiExtractOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        resource_check=check_resources,
    )
)

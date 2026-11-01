"""`ai.rewrite` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.ai_rewrite._handler import (
    NAME,
    AiRewriteConfig,
    AiRewriteInput,
    AiRewriteOutput,
    check_resources,
    handle,
)

__all__ = ["AiRewriteConfig", "AiRewriteInput", "AiRewriteOutput"]

register(
    NodeDefinition(
        id="ai.rewrite",
        version=1,
        name=NAME,
        category="model",
        description="Have a model summarize, translate or rewrite a text.",
        kind="action",
        config_schema=AiRewriteConfig,
        input_schema=AiRewriteInput,
        output_schema=AiRewriteOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=AiRewriteOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        spends_budget=True,
        resource_check=check_resources,
    )
)

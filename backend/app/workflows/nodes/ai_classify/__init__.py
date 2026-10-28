"""`ai.classify` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition
from app.workflows.nodes.ai_classify._handler import (
    NAME,
    STATIC_PORTS,
    AiClassifyConfig,
    AiClassifyInput,
    AiClassifyOutput,
    Category,
    check_resources,
    handle,
    ports_for,
    routes,
)

__all__ = ["AiClassifyConfig", "AiClassifyInput", "AiClassifyOutput", "Category"]

register(
    NodeDefinition(
        id="ai.classify",
        version=1,
        name=NAME,
        category="model",
        description="Have a model put a text in one of your categories, and branch on it.",
        kind="control",
        config_schema=AiClassifyConfig,
        input_schema=AiClassifyInput,
        output_schema=AiClassifyOutput,
        ports=STATIC_PORTS,
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        routes=routes,
        exclusive_branches=True,
        ports_for=ports_for,
        resource_check=check_resources,
    )
)

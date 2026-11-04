"""`ai.prompt` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.ai_prompt._handler import (
    NAME,
    AiPromptConfig,
    AiPromptInput,
    AiPromptOutput,
    check_resources,
    handle,
)

__all__ = ["AiPromptConfig", "AiPromptInput", "AiPromptOutput"]

register(
    NodeDefinition(
        id="ai.prompt",
        version=1,
        name=NAME,
        category="model",
        description="Ask one of your models something, with instructions of the step's own.",
        kind="action",
        config_schema=AiPromptConfig,
        input_schema=AiPromptInput,
        output_schema=AiPromptOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=AiPromptOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        spends_budget=True,
        resource_check=check_resources,
    )
)

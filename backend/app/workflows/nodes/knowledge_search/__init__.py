"""`knowledge.search` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.knowledge_search._handler import (
    KnowledgeSearchConfig,
    KnowledgeSearchInput,
    KnowledgeSearchOutput,
    check_resources,
    handle,
)

__all__ = ["KnowledgeSearchConfig", "KnowledgeSearchInput", "KnowledgeSearchOutput"]

register(
    NodeDefinition(
        id="knowledge.search",
        version=1,
        name="Search knowledge",
        category="knowledge",
        description="Find passages in knowledge collections, as sources a later step can use.",
        kind="action",
        config_schema=KnowledgeSearchConfig,
        input_schema=KnowledgeSearchInput,
        output_schema=KnowledgeSearchOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=KnowledgeSearchOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        resource_check=check_resources,
    )
)

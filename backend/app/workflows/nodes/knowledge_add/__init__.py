"""`knowledge.add` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.knowledge_add._handler import (
    AddedDocument,
    KnowledgeAddConfig,
    KnowledgeAddInput,
    KnowledgeAddOutput,
    check_resources,
    handle,
)

__all__ = ["AddedDocument", "KnowledgeAddConfig", "KnowledgeAddInput", "KnowledgeAddOutput"]

register(
    NodeDefinition(
        id="knowledge.add",
        version=1,
        name="Add to knowledge",
        category="knowledge",
        description="Put a text or a file into knowledge collections, for agents to find.",
        kind="action",
        config_schema=KnowledgeAddConfig,
        input_schema=KnowledgeAddInput,
        output_schema=KnowledgeAddOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=KnowledgeAddOutput),
        ),
        effect_kind="write",
        retry_guarantee="idempotent",
        handler=handle,
        resource_check=check_resources,
    )
)

"""Register the workflow action for the organization memory ledger."""

from app.services.memory.workflow import MemoryObservationConfig, MemoryObservationOutput
from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.memory_observe._handler import check_resources, handle

register(
    NodeDefinition(
        id="memory.observe",
        version=1,
        name="Record memory observation",
        category="knowledge",
        description="Record a verified delivery in organization memory, with its date and evidence.",
        kind="action",
        config_schema=MemoryObservationConfig,
        input_schema=None,
        output_schema=MemoryObservationOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=MemoryObservationOutput),
        ),
        effect_kind="write",
        retry_guarantee="idempotent",
        resource_check=check_resources,
        handler=handle,
    )
)

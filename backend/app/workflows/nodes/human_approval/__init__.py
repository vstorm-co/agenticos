"""`human.approval` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.human_approval._handler import (
    HumanApprovalConfig,
    HumanApprovalInput,
    HumanApprovalOutput,
    check_resources,
    handle,
    routes,
)

__all__ = ["HumanApprovalConfig", "HumanApprovalInput", "HumanApprovalOutput"]

register(
    NodeDefinition(
        id="human.approval",
        version=1,
        name="Ask for approval",
        category="people",
        description="Wait until a person approves or rejects, then go on by their answer.",
        kind="control",
        config_schema=HumanApprovalConfig,
        input_schema=HumanApprovalInput,
        output_schema=HumanApprovalOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="approved", label="Approved", kind="output", schema=HumanApprovalOutput),
            Port(id="rejected", label="Rejected", kind="output", schema=HumanApprovalOutput),
        ),
        effect_kind="write",
        retry_guarantee="idempotent",
        handler=handle,
        routes=routes,
        resource_check=check_resources,
    )
)

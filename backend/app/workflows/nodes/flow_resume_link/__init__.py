"""`flow.resume_link` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.flow_resume_link._handler import ResumeLinkOutput, handle

__all__ = ["ResumeLinkOutput"]

register(
    NodeDefinition(
        id="flow.resume_link",
        version=1,
        name="Resume link",
        category="control",
        description="The address that resumes this run's Wait steps waiting for a call.",
        kind="action",
        config_schema=None,
        input_schema=None,
        output_schema=ResumeLinkOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=ResumeLinkOutput),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)

"""`trigger.workflow_call`: a workflow another one runs as a step.

It hands the graph what `core.input` does - the input the calling step bound, as
`payload`, typed by the declared fields, with `triggered_by` naming the call - so
shared logic lives in one workflow that others call. A call whose input does not
fit the fields is refused before the run starts, and the calling step fails with
the reason.
"""

from app.workflows.nodes.core_input._handler import (
    STATIC_PORTS,
    TriggerInputConfig,
    handle,
    ports_for,
)

__all__ = ["STATIC_PORTS", "TriggerInputConfig", "handle", "ports_for"]

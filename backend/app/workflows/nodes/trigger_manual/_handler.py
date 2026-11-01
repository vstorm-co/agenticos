"""`trigger.manual`: a run a person starts, from the editor or the workflow's runs page.

It hands the graph what `core.input` does - the run's input as `payload`, with
`triggered_by` naming the surface - and takes the same typed input fields. What
differs is the door, not the step: a Manual workflow is started by clicking Run,
and the editor asks for its fields in a form.
"""

from app.workflows.nodes.core_input._handler import (
    STATIC_PORTS,
    TriggerInputConfig,
    handle,
    ports_for,
)

__all__ = ["STATIC_PORTS", "TriggerInputConfig", "handle", "ports_for"]

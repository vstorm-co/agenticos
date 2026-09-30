"""The trigger nodes a workflow starts from, by id, and which one a graph has.

A leaf module: the execution facade and the node packages both read it, and
neither may import the other's side of the tree.
"""

from app.workflows import _registry
from app.workflows.contracts.definition import TRIGGER_CATEGORY
from app.workflows.graph.model import WorkflowGraph

API = "core.input"
MANUAL = "trigger.manual"
CHAT = "trigger.chat"
WEBHOOK = "trigger.webhook"
SCHEDULE = "trigger.schedule"
TABLE_RECORD = "trigger.table_record"
WORKFLOW_FAILED = "trigger.workflow_failed"

BY_HAND = frozenset({API, MANUAL})
"""The triggers a person or a caller starts - from the editor, the runs page, the
API or a WebSocket - and the ones that may declare typed input fields."""


def live_trigger(graph: WorkflowGraph) -> str | None:
    """The `definition_id` of the trigger `graph` starts from, or None when its
    entry is not a trigger - a graph that starts by hand, as `MANUAL` and `API` do."""
    entry = graph.node_by_id[graph.entry_node_id]
    definition = _registry.get(entry.definition_id, entry.definition_version)
    return entry.definition_id if definition.category == TRIGGER_CATEGORY else None

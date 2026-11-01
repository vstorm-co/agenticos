"""The trigger nodes a workflow starts from, by id, and which one a graph has.

A leaf module: the execution facade and the node packages both read it, and
neither may import the other's side of the tree.
"""

from collections import deque
from uuid import UUID

from app.workflows import _registry
from app.workflows.contracts.definition import TRIGGER_CATEGORY
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import NodeInstance, WorkflowGraph

API = "core.input"
MANUAL = "trigger.manual"
CHAT = "trigger.chat"
WEBHOOK = "trigger.webhook"
SCHEDULE = "trigger.schedule"
TABLE_RECORD = "trigger.table_record"
WORKFLOW_FAILED = "trigger.workflow_failed"
WORKFLOW_CALL = "trigger.workflow_call"
FORM = "trigger.form"
CHANNEL_MESSAGE = "trigger.channel_message"
GITHUB = "trigger.github"
GMAIL = "trigger.gmail"
OUTLOOK = "trigger.outlook"

BY_HAND = frozenset({API, MANUAL})
"""The triggers a person or a caller starts - from the editor, the runs page, the
API or a WebSocket."""

UNATTENDED = frozenset(
    {WEBHOOK, GITHUB, SCHEDULE, TABLE_RECORD, FORM, CHANNEL_MESSAGE, GMAIL, OUTLOOK}
)
"""Triggers retaining the human publisher's authority after the request ends."""

DECLARES_FIELDS = frozenset({*BY_HAND, WORKFLOW_CALL, FORM})
"""The triggers that declare typed input fields, checked when a run starts."""

WEBHOOK_RESPOND = "webhook.respond"
"""Not a trigger but the webhook's other half: the step that answers its sender.
A delivery to a graph holding one waits for its answer rather than taking `202`."""


def answers_webhook(graph: WorkflowGraph) -> bool:
    """Whether a delivery that starts `graph` is answered by one of its steps."""
    return any(node.definition_id == WEBHOOK_RESPOND for node in graph.nodes)


def live_trigger(graph: WorkflowGraph) -> str | None:
    """The `definition_id` of the trigger `graph` starts from, or None when its
    entry is not a trigger - a graph that starts by hand, as `MANUAL` and `API` do."""
    entry = graph.node_by_id[graph.entry_node_id]
    definition = _registry.get(entry.definition_id, entry.definition_version)
    return entry.definition_id if definition.category == TRIGGER_CATEGORY else None


TRIGGERS = frozenset(
    {
        API,
        MANUAL,
        CHAT,
        WEBHOOK,
        SCHEDULE,
        TABLE_RECORD,
        WORKFLOW_FAILED,
        WORKFLOW_CALL,
        FORM,
        CHANNEL_MESSAGE,
        GITHUB,
        GMAIL,
        OUTLOOK,
    }
)


def entry_nodes(graph: WorkflowGraph) -> list[NodeInstance]:
    """The default entry and independent trigger roots, with the default first."""
    primary = graph.node_by_id.get(graph.entry_node_id)
    return ([primary] if primary is not None else []) + [
        node
        for node in graph.nodes
        if node.id != graph.entry_node_id and node.definition_id in TRIGGERS
    ]


def entry_graph(graph: WorkflowGraph, node_id: UUID) -> WorkflowGraph:
    """Only the branch reachable from the trigger that admitted this run.

    Other trigger roots never execute and never keep a shared join waiting.
    Bindings on retained targets are preserved: publication refuses references
    to a branch that does not exist for one of its possible starts.
    """
    if not any(node.id == node_id for node in entry_nodes(graph)):
        raise GraphValidationError([("entry_node_id", "Choose an entry from this workflow")])
    forward: dict[UUID, list[UUID]] = {}
    for edge in graph.edges:
        forward.setdefault(edge.source_node_id, []).append(edge.target_node_id)
    active: set[UUID] = set()
    queue = deque([node_id])
    while queue:
        current = queue.popleft()
        if current in active:
            continue
        active.add(current)
        queue.extend(forward.get(current, ()))
    return graph.model_copy(
        update={
            "entry_node_id": node_id,
            "nodes": [node for node in graph.nodes if node.id in active],
            "edges": [
                edge
                for edge in graph.edges
                if edge.source_node_id in active and edge.target_node_id in active
            ],
            "bindings": [binding for binding in graph.bindings if binding.target_node_id in active],
            "scopes": [],
        }
    )

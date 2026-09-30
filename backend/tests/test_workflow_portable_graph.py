"""What a portable graph leaves out: every pinned resource, pinned data, and
table or file references - and the step kinds it cannot carry at all."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.workflows.contracts.io import Binding, FileRef, LiteralValue, TableIORef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.portable import portable


def _node(definition_id: str, config: dict[str, Any], **extra: Any) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config,
        layout=NodePosition(x=0, y=0),
        **extra,
    )


def test_every_pinned_resource_is_taken_out_and_named():
    secret = str(uuid.uuid4())
    agent = _node(
        "agent.run",
        {
            "agent": {"agent_id": str(uuid.uuid4()), "version_id": str(uuid.uuid4())},
            "structured_output_schema": {"type": "object"},
        },
        pinned_output={"text": "a real answer"},
    )
    http = _node(
        "http.request",
        {
            "url": "https://api.example.com",
            "headers": {"Accept": "application/json"},
            "auth": {"kind": "bearer", "secret_id": secret},
        },
    )
    notify = _node(
        "notification.send",
        {"recipients": [str(uuid.uuid4())], "subject": "Hi", "channels": ["in_app"]},
        label="Tell the team",
    )
    mapping = {"target_field": "email", "source_path": "source.email", "coerce_to": "string"}
    mapped = _node("data.map", {"mappings": [mapping]})
    trigger = _node("trigger.manual", {})
    output = _node("core.output", {})
    graph = WorkflowGraph(
        entry_node_id=trigger.id, nodes=(trigger, agent, http, notify, mapped, output)
    )

    carried, unresolved = portable(graph)

    by_id = {node.id: node for node in carried.nodes}
    assert by_id[agent.id].config == {"structured_output_schema": {"type": "object"}}
    assert by_id[agent.id].pinned_output is None
    assert by_id[mapped.id].config == {"mappings": [mapping]}
    assert by_id[notify.id].config == {"subject": "Hi", "channels": ["in_app"]}
    assert by_id[http.id].config == {
        "url": "https://api.example.com",
        "headers": {"Accept": "application/json"},
        "auth": {"kind": "bearer"},
    }
    assert {(item.node_id, item.step, item.field, item.kind) for item in unresolved} == {
        (agent.id, "Run an agent", "agent", "agent"),
        (http.id, "HTTP request", "auth.secret_id", "secret"),
        (notify.id, "Tell the team", "recipients", "member"),
    }
    assert secret not in carried.model_dump_json()


def test_a_binding_to_a_table_or_a_file_is_taken_out():
    step = _node("debug.echo", {"message": "hi"})
    table = TableIORef(table_id=uuid.uuid4(), schema_version=1)
    graph = WorkflowGraph(
        entry_node_id=step.id,
        nodes=(step,),
        bindings=(
            Binding(target_node_id=step.id, target_field="a", source=table),
            Binding(
                target_node_id=step.id,
                target_field="b",
                source=FileRef(file_id=uuid.uuid4(), content_type="text/plain", byte_size=1),
            ),
            Binding(target_node_id=step.id, target_field="c", source=LiteralValue(value=1)),
        ),
    )

    carried, unresolved = portable(graph)

    assert [binding.target_field for binding in carried.bindings] == ["c"]
    assert {(item.step, item.field, item.kind) for item in unresolved} == {
        ("Echo", "a", "table"),
        ("Echo", "b", "file"),
    }


def test_a_step_this_deployment_does_not_have_is_named():
    unknown = _node("future.step", {})
    with pytest.raises(GraphValidationError) as refused:
        portable(WorkflowGraph(entry_node_id=unknown.id, nodes=(unknown,)))
    assert f"nodes.{unknown.id}" in str(refused.value.details)

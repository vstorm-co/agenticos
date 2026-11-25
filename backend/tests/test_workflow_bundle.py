"""Workflow resource pins are owned schema paths, not UUID-shaped application data."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.resource_bundle import BundleResourceKind
from app.services.portability.workflows import WorkflowContent, workflow_omissions, workflow_pins
from app.workflows.contracts.io import Binding, FileRef, TableIORef
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph


def node(kind: str, config: dict[str, object]) -> NodeInstance:
    return NodeInstance(
        id=uuid4(),
        definition_id=kind,
        definition_version=1,
        config=config,
        layout=NodePosition(x=0, y=0),
    )


def test_catalog_agent_pin_keeps_its_owner_and_published_version() -> None:
    agent, version = uuid4(), uuid4()
    step = node("agent.run", {"agent": {"agent_id": str(agent), "version_id": str(version)}})
    content = WorkflowContent(
        name="Review", graph=WorkflowGraph(entry_node_id=step.id, nodes=(step,))
    )
    pins = workflow_pins(content)
    assert [(pin.kind, pin.source_id, pin.parent_id) for pin in pins] == [
        (BundleResourceKind.AGENT, agent, None),
        (BundleResourceKind.AGENT_VERSION, version, agent),
    ]
    assert set(workflow_omissions(content).values()) == {("graph", "nodes", 0, "config", "agent")}


def test_inline_specs_and_table_bindings_have_owned_references() -> None:
    context, table = uuid4(), uuid4()
    step = node(
        "agent.run",
        {
            "inline": {
                "name": "Assistant",
                "context_ids": [str(context)],
                "instructions": str(table),
            }
        },
    )
    binding = Binding(
        target_node_id=step.id,
        target_field="prompt",
        source=TableIORef(table_id=table, schema_version=2),
    )
    content = WorkflowContent(
        name="Review",
        graph=WorkflowGraph(entry_node_id=step.id, nodes=(step,), bindings=(binding,)),
    )
    pins = workflow_pins(content)
    assert [(pin.kind, pin.source_id) for pin in pins] == [
        (BundleResourceKind.CONTEXT, context),
        (BundleResourceKind.TABLE, table),
        (BundleResourceKind.TABLE, table),
    ]
    assert workflow_omissions(content)[pins[-1].path] == ("graph", "bindings", 0)


@pytest.mark.parametrize("run_data", ["pinned", "file"])
def test_import_refuses_run_outputs_and_uploaded_file_references(run_data: str) -> None:
    step = node("debug.echo", {})
    bindings = ()
    if run_data == "pinned":
        step = step.model_copy(update={"pinned_output": {"text": "private run"}})
    else:
        bindings = (
            Binding(
                target_node_id=step.id,
                target_field="message",
                source=FileRef(file_id=uuid4(), content_type="text/plain", byte_size=1),
            ),
        )
    with pytest.raises(ValidationError):
        WorkflowContent(
            name="Review",
            graph=WorkflowGraph(entry_node_id=step.id, nodes=(step,), bindings=bindings),
        )


def test_empty_workflow_and_nested_owned_binding_omissions() -> None:
    assert workflow_pins(WorkflowContent(name="Empty")) == ()
    connection = uuid4()
    step = node(
        "agent.run",
        {
            "inline": {
                "name": "Assistant",
                "mcp_servers": [{"account": "organization", "connection_id": str(connection)}],
            }
        },
    )
    content = WorkflowContent(
        name="Nested", graph=WorkflowGraph(entry_node_id=step.id, nodes=(step,))
    )
    (pin,) = workflow_pins(content)
    assert workflow_omissions(content)[pin.path] == (
        "graph",
        "nodes",
        0,
        "config",
        "inline",
        "mcp_servers",
        0,
    )


def test_column_specific_table_bindings_must_be_selected_again() -> None:
    step = node("debug.echo", {})
    binding = Binding(
        target_node_id=step.id,
        target_field="message",
        source=TableIORef(table_id=uuid4(), column_ids=(uuid4(),), schema_version=1),
    )
    with pytest.raises(ValidationError, match="columns"):
        WorkflowContent(
            name="Table",
            graph=WorkflowGraph(entry_node_id=step.id, nodes=(step,), bindings=(binding,)),
        )


def test_settings_references_and_local_bindings_are_separate_from_resource_ids() -> None:
    from app.services.portability.workflows import WorkflowBundleSettings
    from app.workflows.contracts.io import LiteralValue

    error = uuid4()
    step = node("core.output", {})
    content = WorkflowContent(
        name="Local",
        settings=WorkflowBundleSettings(error_workflow_id=error),
        graph=WorkflowGraph(
            entry_node_id=step.id,
            nodes=(step,),
            bindings=(
                Binding(
                    target_node_id=step.id,
                    target_field="value",
                    source=LiteralValue(value=str(error)),
                ),
            ),
        ),
    )
    (pin,) = workflow_pins(content)
    assert pin.path == ("settings", "error_workflow_id") and pin.source_id == error
    assert workflow_omissions(content) == {}


def test_malformed_resource_ids_are_domain_errors_without_leaking_input() -> None:
    from app.core.exceptions import BadRequestError

    step = node("agent.run", {"agent": {"agent_id": "bad-reference", "version_id": str(uuid4())}})
    content = WorkflowContent(
        name="Invalid", graph=WorkflowGraph(entry_node_id=step.id, nodes=(step,))
    )
    with pytest.raises(BadRequestError, match="malformed") as error:
        workflow_pins(content)
    assert "bad-reference" not in str(error.value)


def test_reused_table_binding_tracks_the_destination_schema_and_skips_as_a_whole() -> None:
    from app.schemas.resource_bundle import BundleContentLayer, BundleDestination, BundleResource
    from app.services.portability.contracts import references_for
    from app.services.portability.mapping import rebind_definition

    source, target = uuid4(), uuid4()
    step = node("core.output", {})
    binding = Binding(
        target_node_id=step.id,
        target_field="result",
        source=TableIORef(table_id=source, schema_version=2),
    )
    content = WorkflowContent(
        name="Table", graph=WorkflowGraph(entry_node_id=step.id, nodes=(step,), bindings=(binding,))
    )
    resource = BundleResource(
        key="workflow/root",
        kind=BundleResourceKind.WORKFLOW,
        name="Table",
        definition=content.model_dump(mode="json"),
        included=frozenset({BundleContentLayer.DEFINITION}),
        references=tuple(ref for ref, _ in references_for(content)),
    )
    key = f"table/{source}"
    rebound = rebind_definition(
        resource,
        {key: BundleDestination(id=target, version_number=7)},
        omit=workflow_omissions(content),
    )
    imported = WorkflowContent.model_validate(rebound.definition)
    assert imported.graph is not None
    selected = imported.graph.bindings[0].source
    assert (
        isinstance(selected, TableIORef)
        and selected.table_id == target
        and selected.schema_version == 7
    )
    removed = WorkflowContent.model_validate(
        rebind_definition(resource, {key: None}, omit=workflow_omissions(content)).definition
    )
    assert removed.graph is not None and removed.graph.bindings == ()


@pytest.mark.anyio
async def test_workflow_entrypoints_refuse_agent_roots_and_keep_imports_reviewed(
    mock_db_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.spec import AgentSpec
    from app.core.exceptions import BadRequestError
    from app.core.permissions import AuthContext
    from app.schemas.resource_bundle import (
        BundleImportChoice,
        BundleImportCreate,
        BundleImportRead,
        BundlePreview,
        BundleResource,
        ResourceBundle,
    )
    from app.services.portability import PortabilityService
    from app.services.portability.documents import document_bytes
    from app.services.portability.snapshots import agent_snapshot

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    service = PortabilityService(mock_db_session)
    root = BundleResource(key="workflow/root", kind=BundleResourceKind.WORKFLOW, name="Workflow")
    bundle = ResourceBundle(roots=(root.key,), resources=(root,))
    preview = BundlePreview(bundle=bundle, options=())
    monkeypatch.setattr(service, "preview_import", AsyncMock(return_value=preview))
    assert (
        await service.preview_document(ctx, document_bytes(bundle, "json").decode(), workflow=True)
        == preview
    )
    request = BundleImportCreate(
        operation_id=uuid4(),
        bundle=bundle,
        choices={root.key: BundleImportChoice(action="reuse", destination_id=uuid4())},
    )
    result = BundleImportRead(roots={root.key: uuid4()}, created={}, reused={}, skipped=())
    monkeypatch.setattr(service, "import_bundle", AsyncMock(return_value=result))
    assert await service.import_workflow(ctx, request) == result
    agent_bundle = agent_snapshot(AgentSpec(name="Agent"))
    with pytest.raises(BadRequestError, match="workflow root"):
        await service.preview_document(
            ctx, document_bytes(agent_bundle, "json").decode(), workflow=True
        )
    with pytest.raises(BadRequestError, match="workflow root"):
        await service.import_workflow(ctx, request.model_copy(update={"bundle": agent_bundle}))

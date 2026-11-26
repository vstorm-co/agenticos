"""Reusable event sources must be reconnected before imported drafts can publish."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.schemas.resource_bundle import (
    BundleContentLayer,
    BundleResource,
    BundleResourceKind,
    ResourceBundle,
)
from app.schemas.workflow import StoredWorkflowSettings
from app.services.portability.facade import PortabilityService
from app.services.portability.sources import BundleSources
from app.services.portability.workflows import WorkflowContent, workflow_pins
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio


def source_graph() -> WorkflowGraph:
    node = NodeInstance(
        id=uuid4(),
        definition_id="trigger.webhook",
        definition_version=1,
        config={"source_id": str(uuid4()), "require_source": False},
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=node.id, nodes=(node,))


def test_import_strips_live_source_identity_and_reports_reconnection() -> None:
    graph = source_graph()
    source_id = graph.nodes[0].config["source_id"]
    content = WorkflowContent(name="Signed delivery", graph=graph)
    assert content.graph is not None
    assert content.graph.nodes[0].config == {"require_source": True}
    path = ("graph", "nodes", 0, "config", "source_id")
    assert content.omitted == (path,)
    assert str(source_id) not in content.model_dump_json()
    assert graph.nodes[0].config["source_id"] == source_id
    # Repeated validation retains one omission and never restores the source.
    restored = WorkflowContent.model_validate_json(content.model_dump_json())
    assert restored == content
    assert workflow_pins(restored) == ()
    resource = BundleResource(
        key="workflow/root",
        kind=BundleResourceKind.WORKFLOW,
        name=content.name,
        definition=content.model_dump(mode="json"),
        included=frozenset({BundleContentLayer.DEFINITION}),
    )
    bundle = ResourceBundle(roots=(resource.key,), resources=(resource,))
    receipt = PortabilityService._receipt(
        bundle, {resource.key: {"action": "create", "id": str(uuid4())}}
    )
    assert receipt.omitted_bindings == {resource.key: (path,)}


async def test_export_removes_source_without_mutating_live_workflow(
    mock_db_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = source_graph()
    source_id = graph.nodes[0].config["source_id"]
    identity = uuid4()
    monkeypatch.setattr(
        "app.services.portability.sources.WorkflowRegistryService.get",
        AsyncMock(
            return_value=SimpleNamespace(
                id=identity,
                name="Signed delivery",
                description=None,
                tags=[],
                settings=StoredWorkflowSettings(),
                draft_graph=graph,
            )
        ),
    )
    source = await BundleSources(mock_db_session).read(
        AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"),
        BundleResource(
            key="workflow/root",
            kind=BundleResourceKind.WORKFLOW,
            name="Delivery",
            source_id=identity,
        ),
    )
    assert isinstance(source.content, WorkflowContent)
    assert source.content.graph is not None
    assert source.content.graph.nodes[0].config == {"require_source": True}
    assert str(source_id) not in source.content.model_dump_json()
    assert graph.nodes[0].config["source_id"] == source_id
    assert source.content.omitted == (("graph", "nodes", 0, "config", "source_id"),)


def test_dedicated_webhook_and_unrelated_business_fields_are_unchanged() -> None:
    graph = source_graph()
    dedicated = graph.nodes[0].model_copy(update={"config": {"require_source": False}})
    business = graph.nodes[0].model_copy(
        update={
            "id": uuid4(),
            "definition_id": "debug.echo",
            "config": {"source_id": "business-reference"},
        }
    )
    content = WorkflowContent(
        name="Dedicated endpoint", graph=graph.model_copy(update={"nodes": (dedicated, business)})
    )
    assert content.graph is not None
    assert content.graph.nodes[0].config == {"require_source": False}
    assert content.graph.nodes[1].config == {"source_id": "business-reference"}
    assert content.omitted == ()


async def test_import_preview_shows_reconnect_before_any_import_write(
    mock_db_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = source_graph()
    raw_definition = {"name": "Signed delivery", "graph": graph.model_dump(mode="json")}
    resource = BundleResource(
        key="workflow/root",
        kind=BundleResourceKind.WORKFLOW,
        name="Signed delivery",
        included=frozenset({BundleContentLayer.DEFINITION}),
        definition=raw_definition,
    )
    service = PortabilityService(mock_db_session)
    monkeypatch.setattr(
        service.sources, "read", AsyncMock(side_effect=NotFoundError(message="No source here"))
    )
    preview = await service.preview_import(
        AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"),
        ResourceBundle(roots=(resource.key,), resources=(resource,)),
    )
    definition = preview.bundle.resources[0].definition
    assert definition is not None
    assert str(graph.nodes[0].config["source_id"]) not in str(definition)
    assert definition["omitted"] == [["graph", "nodes", 0, "config", "source_id"]]
    mock_db_session.add.assert_not_called()

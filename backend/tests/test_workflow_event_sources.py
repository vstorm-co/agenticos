"""Shared sources retain workflow authority, JSON bindings and durable admission."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.workflow import Workflow, WorkflowVersion
from app.db.models.workflow_exposure import WorkflowExposure
from app.schemas.workflow import WorkflowPublish
from app.schemas.workflow_exposure import WebhookAdmitted, WebhookSkipped, WorkflowExposureUpdate
from app.services import workflow_exposure as module
from app.services.workflow_exposure import WorkflowExposureService
from app.services.workflow_registry import WorkflowRegistryService
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from app.workflows.nodes._triggers import WebhookTriggerConfig

pytestmark = pytest.mark.anyio


def _node(definition: str, config: dict | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid4(),
        definition_id=definition,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, target: NodeInstance) -> Edge:
    return Edge(
        id=uuid4(),
        source_node_id=source.id,
        source_port="out",
        target_node_id=target.id,
        target_port="in",
    )


@pytest.fixture
def source_api(monkeypatch):
    from app.services.event_sources import EventSourceService

    api = SimpleNamespace(
        require_use=AsyncMock(return_value=SimpleNamespace(is_active=True)),
        bind_workflow=AsyncMock(),
        unbind_workflow=AsyncMock(),
    )
    for name in ("require_use", "bind_workflow", "unbind_workflow"):
        monkeypatch.setattr(EventSourceService, name, getattr(api, name))
    return api


@pytest.fixture
def publisher(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    workflow = Workflow(id=uuid4(), organization_id=ctx.organization_id, status="published")
    entry = _node("trigger.webhook", {"source_id": str(uuid4())})
    graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))
    version = WorkflowVersion(id=uuid4(), version=2, graph=graph.model_dump(mode="json"))
    exposure = WorkflowExposure(
        id=uuid4(),
        organization_id=ctx.organization_id,
        workflow_id=workflow.id,
        workflow_version_id=version.id,
        node_instance_id=entry.id,
        adapter="webhook",
        execution_principal_user_id=ctx.user_id,
        source_id=UUID(entry.config["source_id"]),
        is_active=True,
        run_input={},
        created_at=datetime.now(UTC),
    )

    async def update(db, *, exposure, update_data):
        for name, value in update_data.items():
            setattr(exposure, name, value)
        return exposure

    monkeypatch.setattr(module.workflow_exposure_repo, "update", AsyncMock(side_effect=update))
    monkeypatch.setattr(module, "record_audit", AsyncMock())
    monkeypatch.setattr(
        module.workflow_exposure_repo, "get_by_id", AsyncMock(return_value=exposure)
    )
    monkeypatch.setattr(
        module.workflow_exposure_repo, "get_for_workflow", AsyncMock(return_value=exposure)
    )
    return ctx, workflow, version, exposure


def test_old_webhook_config_stays_dedicated_and_credentials_never_enter_config():
    assert WebhookTriggerConfig.model_validate({}).source_id is None
    with pytest.raises(ValidationError):
        WebhookTriggerConfig.model_validate({"secret": "never store this in the graph"})


@pytest.mark.security
async def test_publish_reuses_source_and_returns_its_url_without_a_secret(publisher, source_api):
    ctx, workflow, version, exposure = publisher
    read, secret = await WorkflowExposureService(MagicMock()).switch_on_webhook(
        ctx, workflow, version, exposure.node_instance_id
    )
    assert secret is None
    assert read.source_id == exposure.source_id
    assert read.webhook_url.endswith(f"/webhooks/sources/{exposure.source_id}")
    assert read.execution_principal_user_id == ctx.user_id
    assert read.workflow_version_id == version.id
    assert "secret" not in str(read.model_dump())
    assert exposure.secret_encrypted is None and exposure.secret_key_version is None
    source_api.bind_workflow.assert_awaited_once_with(ctx, exposure.source_id, exposure.id)


async def test_first_source_publish_creates_a_credential_free_exposure(
    publisher, source_api, monkeypatch
):
    ctx, workflow, version, exposure = publisher
    monkeypatch.setattr(
        module.workflow_exposure_repo, "get_for_workflow", AsyncMock(return_value=None)
    )

    async def create(db, **fields):
        return WorkflowExposure(id=uuid4(), created_at=datetime.now(UTC), **fields)

    monkeypatch.setattr(module.workflow_exposure_repo, "create", AsyncMock(side_effect=create))
    read, secret = await WorkflowExposureService(MagicMock()).switch_on_webhook(
        ctx, workflow, version, exposure.node_instance_id
    )
    assert secret is None and read.source_id == exposure.source_id
    assert read.id != exposure.id


@pytest.mark.security
async def test_returning_to_dedicated_webhook_unsubscribes_and_mints_its_own_secret(
    publisher, source_api
):
    ctx, workflow, version, exposure = publisher
    graph = WorkflowGraph.model_validate(version.graph)
    version.graph = graph.model_copy(
        update={"nodes": (graph.nodes[0].model_copy(update={"config": {}}),)}
    ).model_dump(mode="json")
    read, secret = await WorkflowExposureService(MagicMock()).switch_on_webhook(
        ctx, workflow, version, exposure.node_instance_id
    )
    assert read.source_id is None and secret
    assert read.id == exposure.id
    assert read.webhook_url.endswith(f"/workflow-webhooks/{exposure.id}")
    assert module.WorkflowExposureService._secret_of(exposure) == secret
    source_api.unbind_workflow.assert_awaited_once_with(exposure.id)


@pytest.mark.security
async def test_source_backed_exposure_cannot_use_the_old_ingress_or_rotate_source_credentials(
    publisher, monkeypatch
):
    ctx, workflow, _, exposure = publisher
    service = WorkflowExposureService(MagicMock())
    monkeypatch.setattr(service, "_editable", AsyncMock(return_value=workflow))
    monkeypatch.setattr(service, "_exposure", AsyncMock(return_value=exposure))
    with pytest.raises(NotFoundError):
        await service.receive_webhook(exposure.id, body=b"{}", headers={})
    with pytest.raises(BadRequestError, match="event source"):
        await service.rotate_secret(ctx, workflow.id, exposure.id)


async def test_removing_a_source_entry_unsubscribes_before_deleting_exposure(
    publisher, source_api, monkeypatch
):
    ctx, _, _, exposure = publisher
    deleted = AsyncMock()
    monkeypatch.setattr(module.workflow_exposure_repo, "delete", deleted)
    await WorkflowExposureService(MagicMock())._remove(ctx, exposure)
    source_api.unbind_workflow.assert_awaited_once_with(exposure.id)
    deleted.assert_awaited_once()


@pytest.mark.security
async def test_resuming_a_source_subscription_rechecks_source_use(
    publisher, source_api, monkeypatch
):
    ctx, workflow, _, exposure = publisher
    exposure.is_active = False
    service = WorkflowExposureService(MagicMock())
    monkeypatch.setattr(service, "_editable", AsyncMock(return_value=workflow))
    monkeypatch.setattr(service, "_exposure", AsyncMock(return_value=exposure))
    source_api.require_use.side_effect = AuthorizationError(message="Source access revoked")
    with pytest.raises(AuthorizationError):
        await service.set_active(
            ctx, workflow.id, exposure.id, WorkflowExposureUpdate(is_active=True)
        )
    assert not exposure.is_active


async def test_source_admission_keeps_selected_entry_and_json_shape_and_retry_keeps_one_run(
    publisher, source_api, monkeypatch
):
    ctx, workflow, version, exposure = publisher
    service = WorkflowExposureService(MagicMock())
    run = SimpleNamespace(id=uuid4())
    receipt_id = uuid4()
    admit = AsyncMock(return_value=(run, None))
    monkeypatch.setattr(service, "_fire_context", AsyncMock(return_value=(ctx, workflow, version)))
    monkeypatch.setattr(service, "_spend_delivery_allowance", AsyncMock())
    monkeypatch.setattr(service.runs, "admit_pinned", admit)
    monkeypatch.setattr(module.workflow_exposure_repo, "lock_delivery", AsyncMock())
    monkeypatch.setattr(
        module.workflow_exposure_repo,
        "get_delivery",
        AsyncMock(side_effect=[None, SimpleNamespace(workflow_run_id=run.id)]),
    )
    recorded = AsyncMock()
    monkeypatch.setattr(module.workflow_exposure_repo, "create_delivery", recorded)
    body = {"issue": {"title": "Need help"}, "empty": None, "items": [False, 0]}
    args = {
        "organization_id": ctx.organization_id,
        "source_id": exposure.source_id,
        "receipt_id": receipt_id,
        "body": body,
        "delivery_id": "provider-42",
    }
    first = await service.receive_source_delivery(exposure.id, **args)
    again = await service.receive_source_delivery(exposure.id, **args)
    assert first == WebhookAdmitted(run_id=run.id, duplicate=False)
    assert again == WebhookAdmitted(run_id=run.id, duplicate=True)
    assert admit.await_count == 1
    assert admit.await_args.kwargs["run_input"] == {"body": body, "delivery_id": "provider-42"}
    assert admit.await_args.kwargs["entry_node_id"] == exposure.node_instance_id
    assert recorded.await_args.kwargs["delivery_id"] == f"source:{receipt_id}"
    assert exposure.last_run_id == run.id
    source_api.require_use.assert_awaited_with(ctx, exposure.source_id)


@pytest.mark.security
@pytest.mark.parametrize(
    "changed", ["tenant", "source", "paused", "adapter", "deleted", "authority"]
)
async def test_queued_source_work_rechecks_its_target_before_admission(
    publisher, source_api, monkeypatch, changed
):
    ctx, _, _, exposure = publisher
    organization_id, source_id = ctx.organization_id, exposure.source_id
    if changed == "tenant":
        organization_id = uuid4()
    elif changed == "source":
        source_id = uuid4()
    elif changed == "paused":
        exposure.is_active = False
    elif changed == "adapter":
        exposure.adapter = "schedule"
    elif changed == "deleted":
        monkeypatch.setattr(
            module.workflow_exposure_repo, "get_by_id", AsyncMock(return_value=None)
        )
    service = WorkflowExposureService(MagicMock())
    monkeypatch.setattr(service, "_fire_context", AsyncMock(return_value=None))
    admit = AsyncMock()
    monkeypatch.setattr(service.runs, "admit_pinned", admit)
    args = {
        "organization_id": organization_id,
        "source_id": source_id,
        "receipt_id": uuid4(),
        "body": {},
        "delivery_id": "d1",
    }
    if changed == "authority":
        with pytest.raises(AuthorizationError):
            await service.receive_source_delivery(exposure.id, **args)
    else:
        assert isinstance(
            await service.receive_source_delivery(exposure.id, **args), WebhookSkipped
        )
    admit.assert_not_called()


async def test_paused_source_does_not_turn_off_the_workflow_subscription(
    publisher, source_api, monkeypatch
):
    ctx, workflow, version, exposure = publisher
    source_api.require_use.return_value.is_active = False
    service = WorkflowExposureService(MagicMock())
    monkeypatch.setattr(service, "_fire_context", AsyncMock(return_value=(ctx, workflow, version)))
    assert isinstance(
        await service.receive_source_delivery(
            exposure.id,
            organization_id=ctx.organization_id,
            source_id=exposure.source_id,
            receipt_id=uuid4(),
            body={},
            delivery_id="d1",
        ),
        WebhookSkipped,
    )
    assert exposure.is_active


@pytest.mark.security
async def test_delivery_with_no_retained_principal_cannot_adopt_a_new_publisher(publisher):
    ctx, _, version, exposure = publisher
    service = WorkflowExposureService(MagicMock())
    with pytest.raises(AuthorizationError, match="retained by this delivery"):
        await service.receive_source_delivery(
            exposure.id,
            organization_id=ctx.organization_id,
            source_id=exposure.source_id,
            receipt_id=uuid4(),
            body={},
            delivery_id="d1",
            version_id=version.id,
            principal_user_id=None,
        )


@pytest.mark.security
async def test_source_work_with_a_deleted_publisher_has_no_execution_identity(
    publisher, monkeypatch
):
    ctx, _, _, exposure = publisher
    exposure.execution_principal_user_id = None
    lookup = AsyncMock()
    monkeypatch.setattr(module.member_repo, "get_active", lookup)
    with pytest.raises(AuthorizationError, match="can no longer run"):
        await WorkflowExposureService(MagicMock()).receive_source_delivery(
            exposure.id,
            organization_id=ctx.organization_id,
            source_id=exposure.source_id,
            receipt_id=uuid4(),
            body={},
            delivery_id="d1",
        )
    lookup.assert_not_called()


@pytest.mark.security
@pytest.mark.parametrize("version_state", ["missing", "other_workflow"])
async def test_queued_source_delivery_cannot_run_a_missing_or_unrelated_pinned_version(
    publisher, source_api, monkeypatch, version_state
):
    ctx, workflow, version, exposure = publisher
    version.workflow_id = uuid4()
    monkeypatch.setattr(
        module.member_repo, "get_active", AsyncMock(return_value=SimpleNamespace(role="owner"))
    )
    monkeypatch.setattr(
        module.user_repo,
        "get_by_id",
        AsyncMock(return_value=SimpleNamespace(is_active=True, is_app_admin=False)),
    )
    monkeypatch.setattr(module.workflow_repo, "get", AsyncMock(return_value=workflow))
    monkeypatch.setattr(module, "resolve_access", AsyncMock(return_value=True))
    monkeypatch.setattr(
        module.workflow_repo,
        "get_version",
        AsyncMock(return_value=None if version_state == "missing" else version),
    )
    service = WorkflowExposureService(MagicMock())
    admission = AsyncMock()
    monkeypatch.setattr(service.runs, "admit_pinned", admission)
    with pytest.raises(AuthorizationError, match="can no longer run"):
        await service.receive_source_delivery(
            exposure.id,
            organization_id=ctx.organization_id,
            source_id=exposure.source_id,
            receipt_id=uuid4(),
            body={},
            delivery_id="d1",
            version_id=version.id,
            principal_user_id=ctx.user_id,
        )
    admission.assert_not_called()


@pytest.mark.security
@pytest.mark.parametrize("error", [AuthorizationError, NotFoundError])
async def test_source_publish_reports_revoked_access_on_the_config_field(
    publisher, source_api, error, monkeypatch
):
    ctx, workflow, version, exposure = publisher
    workflow.draft_graph = version.graph
    workflow.draft_revision = 1
    registry = WorkflowRegistryService(MagicMock())
    monkeypatch.setattr(registry, "_load", AsyncMock(return_value=workflow))
    source_api.require_use.side_effect = error(message="Unavailable")
    with pytest.raises(GraphValidationError) as refused:
        await registry.publish(ctx, workflow.id, WorkflowPublish(expected_revision=1))
    assert refused.value.details["fields"] == [
        {
            "field": f"nodes.{exposure.node_instance_id}.config.source_id",
            "message": "Choose an event source you have permission to use",
        }
    ]
    source_api.require_use.assert_awaited_once_with(ctx, exposure.source_id, lock=True)


async def test_shared_response_validation_follows_the_selected_branch(publisher, source_api):
    ctx, _, _, _ = publisher
    source = _node("trigger.webhook", {"source_id": str(uuid4())})
    manual = _node("trigger.manual")
    respond = _node("webhook.respond")
    graph = WorkflowGraph(
        entry_node_id=manual.id,
        nodes=(manual, source, respond),
        edges=(_edge(manual, respond),),
    )
    await validate_graph(MagicMock(), ctx, graph)
    reachable = graph.model_copy(update={"edges": (_edge(source, respond),)})
    with pytest.raises(GraphValidationError, match="asynchronously"):
        await validate_graph(MagicMock(), ctx, reachable)
    dedicated = reachable.model_copy(
        update={"nodes": (manual, source.model_copy(update={"config": {}}), respond)}
    )
    await validate_graph(MagicMock(), ctx, dedicated)


async def test_source_publish_defensively_refuses_a_synchronous_response(publisher, source_api):
    ctx, workflow, version, exposure = publisher
    entry = WorkflowGraph.model_validate(version.graph).nodes[0]
    respond = _node("webhook.respond")
    version.graph = WorkflowGraph(
        entry_node_id=entry.id, nodes=(entry, respond), edges=(_edge(entry, respond),)
    ).model_dump(mode="json")
    with pytest.raises(BadRequestError, match="Respond to webhook"):
        await WorkflowExposureService(MagicMock()).switch_on_webhook(
            ctx, workflow, version, exposure.node_instance_id
        )
    source_api.bind_workflow.assert_not_called()

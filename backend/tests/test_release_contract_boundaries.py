"""Release boundaries preserve reviewed instructions and orphaned delivery semantics."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec, SubagentRef
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("change", ["cycle", "missing", "wrong_agent", "too_many"])
async def test_routine_instruction_review_bounds_delegate_graphs(monkeypatch, change):
    from app.services import routine_actions

    refs = [
        SubagentRef(agent_id=uuid4(), agent_version_id=uuid4())
        for _ in range(65 if change == "too_many" else 1)
    ]
    spec = AgentSpec(name="Root", subagents=refs)

    async def version(_db, identifier, **kwargs):
        ref = next(ref for ref in refs if ref.agent_version_id == identifier)
        if change == "missing":
            return None
        return SimpleNamespace(
            agent_id=uuid4() if change == "wrong_agent" else ref.agent_id,
            spec=AgentSpec(name="Child", subagents=refs if change == "cycle" else []).model_dump(
                mode="json"
            ),
        )

    read = AsyncMock(side_effect=version)
    monkeypatch.setattr(routine_actions.agent_repo, "get_version", read)
    if change == "cycle":
        assert (
            await routine_actions.instruction_fingerprint(
                AsyncMock(), organization_id=uuid4(), spec=spec, project_id=None
            )
            is None
        )
        assert read.await_count == 1
    else:
        with pytest.raises(BadRequestError):
            await routine_actions.instruction_fingerprint(
                AsyncMock(), organization_id=uuid4(), spec=spec, project_id=None
            )


def test_inbox_delivery_changes_the_reviewed_routine_intent():
    from app.db.models.agent_trigger import AgentTrigger
    from app.services.routine_actions import action_intent

    trigger = AgentTrigger(prompt="Check", result_mode="report")
    original = action_intent(trigger)
    trigger.result_mode = "inbox"
    assert action_intent(trigger) != original


async def test_missing_notifications_fail_a_claim_instead_of_attempting_delivery(monkeypatch):
    from app.services import notification_delivery

    now = datetime.now(UTC)
    receipt = MagicMock(id=uuid4(), claimed_at=now, status="pending", channel="email", attempts=1)
    monkeypatch.setattr(
        notification_delivery.notification_repo, "get_delivery", AsyncMock(return_value=receipt)
    )
    monkeypatch.setattr(
        notification_delivery.notification_repo, "get_notification", AsyncMock(return_value=None)
    )
    settle = AsyncMock()
    monkeypatch.setattr(notification_delivery.notification_repo, "settle_delivery", settle)
    assert (
        await notification_delivery.NotificationDeliveryService(AsyncMock()).send_and_settle(
            receipt.id, claimed_at=now
        )
        == "failed"
    )
    assert settle.await_args.kwargs["last_error"] == "notification missing"


@pytest.mark.parametrize("full", [False, True])
async def test_run_retention_drains_device_wait_batches_under_the_same_cutoff(monkeypatch, full):
    from app.services import retention

    db = MagicMock()
    service = retention.RetentionService(db)
    service._purge_batch = AsyncMock(return_value=0)
    monkeypatch.setattr(retention, "MAX_BATCHES", 2)
    deleted = AsyncMock(side_effect=[retention.BATCH, retention.BATCH if full else 0])
    monkeypatch.setattr(retention.retention_repo, "delete_finished_device_waits", deleted)
    result = retention.SweepResult(organization_id=uuid4())
    cutoff = datetime.now(UTC)
    await service._purge("runs", result, cutoff=cutoff)
    assert result.removed["routine_device_waits"] == retention.BATCH * (2 if full else 1)
    assert deleted.await_count == 2
    assert deleted.await_args.kwargs["cutoff"] == cutoff


async def test_maintenance_without_an_attribution_agent_never_spends_tokens():
    from app.services.proactive._thinker import ProactiveThinker

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    assert (
        await ProactiveThinker(AsyncMock()).think(
            ctx, feature="maintenance", output_type=str, instructions="Check", prompt="Check"
        )
        is None
    )


@pytest.mark.parametrize("active", [False, True])
async def test_workflow_email_polling_checks_current_active_provider_exposures(monkeypatch, active):
    from app.services import workflow_exposure

    read = AsyncMock(return_value=[MagicMock()] if active else [])
    monkeypatch.setattr(workflow_exposure.workflow_exposure_repo, "list_active", read)
    result = await workflow_exposure.WorkflowExposureService(AsyncMock()).has_polled_email(
        organization_id=uuid4(), source="gmail"
    )
    assert result is active
    assert read.await_args.kwargs["adapter"] == "gmail"


@pytest.mark.parametrize("same_tenant", [False, True])
async def test_managed_table_scope_overrides_broad_visibility_without_cross_tenant_leaks(
    monkeypatch, same_tenant
):
    from app.core.permissions import Perm
    from app.services import access, task_access

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    resource = SimpleNamespace(
        id=uuid4(),
        organization_id=ctx.organization_id if same_tenant else uuid4(),
        owner_user_id=ctx.user_id,
    )
    monkeypatch.setattr(access, "visible_resource_ids", AsyncMock(return_value={resource.id}))
    check = AsyncMock(return_value=False)
    monkeypatch.setattr(task_access, "table_access", check)
    assert (
        await access.accessible_ids(
            AsyncMock(), ctx, [resource], Perm.TABLES_VIEW, resource_type=access.TABLE
        )
        == set()
    )
    assert check.await_count == int(same_tenant)


@pytest.mark.parametrize("change", ["missing", "tenant"])
async def test_case_task_lock_does_not_touch_another_tenants_table(monkeypatch, change):
    from app.repositories import task, virtual_table_repo

    db = AsyncMock()
    db.get.return_value = None if change == "missing" else SimpleNamespace(organization_id=uuid4())
    monkeypatch.setattr(
        task, "for_outcome", AsyncMock(return_value=SimpleNamespace(board_id=uuid4()))
    )
    read = AsyncMock()
    monkeypatch.setattr(virtual_table_repo, "get_table", read)
    await task.lock_case_task(db, uuid4(), uuid4())
    read.assert_not_awaited()


async def test_a_disappeared_finding_receipt_is_an_explicit_delivery_failure(monkeypatch):
    from app.schemas.routine_notifications import RoutineFinding
    from app.services import routine_delivery

    monkeypatch.setattr(routine_delivery.suggestion_repo, "propose", AsyncMock(return_value=None))
    monkeypatch.setattr(routine_delivery.suggestion_repo, "for_key", AsyncMock(return_value=None))
    with pytest.raises(RuntimeError, match="finding disappeared"):
        await routine_delivery.RoutineFindingService(AsyncMock()).publish(
            run=MagicMock(organization_id=uuid4()),
            user_id=uuid4(),
            origin_id=uuid4(),
            origin_kind="watch",
            item=RoutineFinding(key="mail", revision="v1", title="Review", content="Draft"),
            notify=True,
        )


@pytest.mark.parametrize("status", [None, "resolved"])
async def test_resolving_a_missing_or_already_final_task_case_does_not_move_it(monkeypatch, status):
    from app.repositories import task
    from app.services import outcome

    monkeypatch.setattr(
        task,
        "case",
        AsyncMock(return_value=None if status is None else SimpleNamespace(status=status)),
    )
    move = AsyncMock()
    monkeypatch.setattr(outcome.OutcomeService, "_move", move)
    await outcome.OutcomeService(AsyncMock()).resolve_task(uuid4(), organization_id=uuid4())
    move.assert_not_awaited()


async def test_invalid_finding_source_metadata_is_not_presented_as_a_resumable_draft(monkeypatch):
    from app.services import outcome

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    monkeypatch.setattr(outcome.OutcomeService, "_require_private_chat", AsyncMock())
    monkeypatch.setattr(
        outcome.suggestion_repo,
        "finding_sources",
        AsyncMock(return_value={uuid4(): {"source_item_id": None, "revision": "one"}}),
    )
    assert await outcome.OutcomeService(AsyncMock()).finding_sources(ctx, []) == {}


async def test_a_watch_without_a_source_policy_cannot_lend_an_mcp_tool():
    from pydantic_ai.tools import ToolDefinition

    from app.agents.mcp import MCP_ORIGIN, McpSourceIdentity, McpToolOrigin
    from app.services.routine_authority import RoutineAuthority

    identity = McpSourceIdentity(
        endpoint_hash="a" * 64, authorization_generation=uuid4(), tool_prefix="source"
    )
    authority = RoutineAuthority(
        routine_id=uuid4(),
        organization_id=uuid4(),
        user_id=uuid4(),
        root_agent_id=uuid4(),
        role="owner",
        acts_as_creator=False,
        routine_kind="watch",
    )
    assert not authority.allows_tool(
        ToolDefinition(name="read", metadata={MCP_ORIGIN: McpToolOrigin(uuid4(), identity, "read")})
    )


async def test_matching_mcp_account_without_reviewed_tools_cannot_lend_authority():
    from app.agents.mcp import McpSourceIdentity, McpToolOrigin
    from app.services.routine_authority import RoutineAuthority
    from app.services.routine_sources import RoutineSourcesRequired

    connection = uuid4()
    identity = McpSourceIdentity(
        endpoint_hash="a" * 64, authorization_generation=uuid4(), tool_prefix="source"
    )
    authority = RoutineAuthority(
        routine_id=uuid4(),
        organization_id=uuid4(),
        user_id=uuid4(),
        root_agent_id=uuid4(),
        role="owner",
        acts_as_creator=False,
        mcp_sources={connection: identity},
    )
    with pytest.raises(RoutineSourcesRequired):
        await authority._mcp_in(AsyncMock(), McpToolOrigin(connection, identity, "write"))


async def test_watch_authority_does_not_apply_a_trigger_project_binding():
    from app.services.routine_authority import RoutineAuthority

    authority = RoutineAuthority(
        routine_id=uuid4(),
        organization_id=uuid4(),
        user_id=uuid4(),
        root_agent_id=uuid4(),
        role="owner",
        acts_as_creator=False,
        routine_kind="watch",
    )
    authority.require_project(None)

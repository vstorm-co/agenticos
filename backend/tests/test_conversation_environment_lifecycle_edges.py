"""Lifecycle refusal edges preserve authority, sealed identity and cleanup ownership."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, ConflictError
from app.db.models.agent_run import AgentRun
from app.services import conversation_environments as lifecycle
from app.services.conversation_environment_policy import EnvironmentNotReady
from tests.test_conversation_environment_lifecycle import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_read_and_list_are_passive_even_with_readiness_refusal(case, monkeypatch):
    monkeypatch.setattr(
        lifecycle,
        "settings_for",
        AsyncMock(
            side_effect=EnvironmentNotReady("connection_unavailable", "Connection is paused")
        ),
    )
    read = await case.service.read(case.ctx, case.row.conversation_id, case.row.agent_id, "browser")
    assert read.state == "failed" and read.refusal.code == "connection_unavailable"
    listed = await case.service.list(case.ctx, case.row.conversation_id, case.row.agent_id)
    assert [item.kind for item in listed.items] == ["browser", "desktop"]
    assert all(item.refusal.code == "connection_unavailable" for item in listed.items)
    lifecycle.enqueue.assert_not_awaited()


async def test_changed_binding_is_a_fresh_selection_not_a_stale_handle(case):
    case.row.fingerprint = "replaced-binding"
    read = await case.service.read(case.ctx, case.row.conversation_id, case.row.agent_id, "browser")
    assert read.state == "not_started" and read.id is None
    assert read.refusal.code == "environment_changed"


async def test_ensure_reports_unavailable_configuration_without_admission(case, monkeypatch):
    monkeypatch.setattr(
        lifecycle,
        "authority",
        AsyncMock(side_effect=EnvironmentNotReady("local_device_required", "Local device")),
    )
    read = await case.service.ensure(case.ctx, case.row.conversation_id, "browser", case.request)
    assert read.id is None and read.refusal.code == "local_device_required"
    lifecycle.environments.lock_owner.assert_not_awaited()
    lifecycle.enqueue.assert_not_awaited()


async def test_changed_active_binding_expires_old_admission_before_fresh_admission(case):
    previous = case.row.id
    case.row.fingerprint = "replaced-binding"
    read = await case.service.ensure(case.ctx, case.row.conversation_id, "browser", case.request)
    assert case.row.state == "expired" and read.id != previous
    assert read.state == "starting"


async def test_expired_and_failed_read_shapes_never_offer_control(case):
    case.row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    read = await case.service._read(case.row, case.row.agent_id, "browser", "agent")
    assert read.state == "expired" and not read.can_control
    assert read.refusal.code == "environment_expired"
    case.row.expires_at = datetime.now(UTC) + timedelta(seconds=60)
    case.row.refusal_code = "backend_not_supported"
    read = await case.service._read(case.row, case.row.agent_id, "browser", "agent")
    assert read.refusal.code == "backend_not_supported"
    assert "conversation-" in read.refusal.message
    assert not read.can_control
    case.row.refusal_code = "provisioning_failed"
    read = await case.service._read(case.row, case.row.agent_id, "browser", "agent")
    assert read.refusal.code == "provisioning_failed"


@pytest.mark.parametrize(
    "mutation", ["missing", "state", "user_id", "conversation_id", "agent_id", "expiry"]
)
async def test_claim_refuses_missing_inactive_and_orphaned_admission(case, mutation):
    if mutation == "missing":
        lifecycle.environments.for_worker.return_value = None
    elif mutation == "state":
        case.row.state = "expired"
    elif mutation == "expiry":
        case.row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    else:
        setattr(case.row, mutation, None)
    assert await case.service.claim(case.payload, 1) is None
    if mutation not in ("missing", "state"):
        assert case.row.state == "expired"


async def test_claim_rechecks_locked_admission_after_project_authority_resolution(case):
    lifecycle.environments.for_worker.side_effect = [case.row, None]
    assert await case.service.claim(case.payload, 1) is None


async def test_claim_refuses_changed_config_before_provider_state_is_mutated(case):
    case.row.fingerprint = "changed"
    with pytest.raises(EnvironmentNotReady, match="changed before"):
        await case.service.claim(case.payload, 1)
    assert case.row.provisioning_attempt == 1


@pytest.mark.parametrize(
    "changed",
    [
        None,
        "missing",
        "status",
        "surface",
        "agent_version_id",
        "user_id",
        "agent_id",
        "conversation_id",
    ],
)
async def test_provision_claim_rechecks_real_producer_and_carries_its_identity(
    case, monkeypatch, changed
):
    case.row.source_run_id = uuid4()
    run = AgentRun(
        id=case.row.source_run_id,
        status="running",
        surface="web",
        agent_version_id=case.admitted.version_id,
        user_id=case.row.user_id,
        agent_id=case.row.agent_id,
        conversation_id=case.row.conversation_id,
    )
    if changed not in (None, "missing"):
        setattr(
            run,
            changed,
            "completed" if changed == "status" else "api" if changed == "surface" else uuid4(),
        )
    monkeypatch.setattr(
        lifecycle.run_repo, "get_run", AsyncMock(return_value=None if changed == "missing" else run)
    )
    if changed is None:
        resolved = await case.service.claim(case.payload, 2)
        assert resolved.authority.producer_run_id == case.row.source_run_id
        assert case.row.provisioning_attempt == 2
    else:
        with pytest.raises(AuthorizationError, match="producer is no longer"):
            await case.service.claim(case.payload, 2)
        assert case.row.provisioning_attempt == 1


async def test_claim_without_producer_keeps_manual_admission_independent(case):
    resolved = await case.service.claim(case.payload, 2)
    assert resolved is case.resolved
    assert resolved.authority.producer_run_id is None


@pytest.mark.parametrize("state,sealed", [("failed", False), ("ready", True), ("expired", True)])
async def test_late_store_never_overwrites_terminal_or_existing_journal(case, state, sealed):
    case.row.state = state
    case.row.resource_ciphertext = "existing" if sealed else None
    assert not await case.service.store_resource(case.payload, 1, case.resource, "physical")
    assert case.row.resource_ciphertext == ("existing" if sealed else None)


async def test_replace_and_unseal_refuse_wrong_sealed_resource_identity(case):
    wrong = case.resource.model_copy(update={"organization_id": uuid4()})
    with pytest.raises(ConflictError, match="does not belong"):
        await case.service.replace_resource(case.row, wrong)
    await case.service.replace_resource(case.row, case.resource)
    assert case.service.resource(case.row, case.ctx.organization_id) == case.resource
    case.row.kind = "desktop"
    with pytest.raises(EnvironmentNotReady, match="identity does not match"):
        case.service.resource(case.row, case.ctx.organization_id)
    case.row.resource_ciphertext = None
    with pytest.raises(EnvironmentNotReady, match="no live resource"):
        case.service.resource(case.row, case.ctx.organization_id)


async def test_failed_stale_job_does_not_retire_current_admission(case):
    case.row.revision += 1
    await case.service.failed(case.payload)
    assert case.row.state == "starting"
    lifecycle.enqueue.assert_not_awaited()


async def test_live_lock_loss_is_refused_before_read_or_touch(case):
    lifecycle.environments.owned.side_effect = [case.row, None]
    with pytest.raises(EnvironmentNotReady, match="no longer live"):
        await case.service.live(
            case.ctx, case.row.conversation_id, case.row.id, "agent", lock=True, touch=True
        )


async def test_run_live_carries_actual_adopter_and_touch_is_explicit(case):
    await case.service.store_resource(case.payload, 1, case.resource, "physical")
    case.row.state, case.row.session_lifetime, case.row.source_run_id = "ready", "run", uuid4()
    before = case.row.expires_at
    _, resolved, _ = await case.service.live(
        case.ctx, case.row.conversation_id, case.row.id, "agent"
    )
    assert case.row.expires_at == before
    assert resolved.authority.producer_run_id == case.row.source_run_id
    case.row.expires_at = datetime.now(UTC) + timedelta(seconds=1)
    await case.service.live(
        case.ctx, case.row.conversation_id, case.row.id, "agent", lock=True, touch=True
    )
    assert case.row.expires_at > before


@pytest.mark.parametrize("operation", ["cleanup_resource", "cleaned"])
async def test_stale_or_foreign_cleanup_cannot_touch_new_owner(case, operation):
    case.row.revision += 1
    await getattr(case.service, operation)(case.payload)
    case.db.delete.assert_not_awaited()
    case.db.flush.assert_not_awaited()


async def test_orphan_cleanup_deletes_only_after_its_handle_has_been_cleared(case):
    case.row.user_id = None
    case.row.resource_ciphertext = "sealed"
    case.row.resource_key_version, case.row.resource_key = 1, "physical"
    await case.service.cleaned(case.payload)
    assert case.row.resource_ciphertext is None and case.row.resource_key is None
    case.db.delete.assert_awaited_once_with(case.row)


async def test_cleanup_without_known_handle_expires_without_inventing_resource(case):
    case.row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert await case.service.cleanup_resource(case.payload) is None
    assert case.row.state == "expired"


async def test_passive_ready_read_projects_fresh_control_without_extending_idle(case):
    case.row.state, case.row.resource_key = "ready", "physical"
    before = case.row.expires_at
    for control in ("human", "agent"):
        lifecycle.environments.driver.return_value = SimpleNamespace(
            control=control, lease_until=datetime.now(UTC) + timedelta(minutes=1)
        )
        read = await case.service.read(
            case.ctx, case.row.conversation_id, case.row.agent_id, "browser"
        )
        assert read.state == "ready" and read.control == control
        assert read.can_control is (control == "human")
        assert case.row.expires_at == before
    case.db.flush.assert_not_awaited()


async def test_failed_provision_without_handle_has_no_fabricated_cleanup(case):
    await case.service.failed(case.payload, reason="backend_not_supported")
    assert case.row.state == "failed" and case.row.refusal_code == "backend_not_supported"
    lifecycle.enqueue.assert_not_awaited()


async def test_maintenance_is_queued_in_transaction_and_records_admission_time(case):
    lifecycle.environments.active_for_maintenance.return_value = [case.row]
    await case.service.sweep()
    queued = lifecycle.enqueue.await_args
    assert queued.args[0] is case.db
    assert queued.args[1] == lifecycle.MAINTAIN_CONVERSATION_ENVIRONMENT
    assert queued.args[2] == case.payload
    assert queued.kwargs["dedupe_active"] is True
    assert case.row.last_maintained_at <= datetime.now(UTC)
    case.db.flush.assert_awaited()

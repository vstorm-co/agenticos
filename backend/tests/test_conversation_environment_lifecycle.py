"""Admission and teardown stay durable across cancellation, stale jobs and revocation."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.capabilities.browser_use import WebBrowserConfig
from app.agents.capabilities.browser_use._page import BrowserTarget
from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.conversation import Conversation
from app.db.models.conversation_environment import (
    ConversationEnvironment,
    ConversationEnvironmentDriver,
)
from app.schemas.conversation_environment import ConversationEnvironmentStart
from app.services import conversation_environments as lifecycle
from app.services.conversation_environment_policy import (
    BrowserEnvironmentSettings,
    EnvironmentAuthority,
    EnvironmentNotReady,
)
from app.services.conversation_environment_resources import BrowserEnvironmentResource

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def case(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    conversation = Conversation(
        id=uuid4(), user_id=ctx.user_id, organization_id=ctx.organization_id
    )
    agent = Agent(id=uuid4(), organization_id=ctx.organization_id, name="Browser", slug="browser")
    admitted = EnvironmentAuthority(
        ctx,
        conversation,
        agent,
        uuid4(),
        AgentSpec(name="Browser", instructions="Use the browser"),
        "agent",
        None,
    )
    resolved = BrowserEnvironmentSettings(
        admitted,
        WebBrowserConfig(session_lifetime="conversation"),
        "a" * 64,
        "http://browser:9222",
        None,
    )
    row = ConversationEnvironment(
        id=uuid4(),
        organization_id=ctx.organization_id,
        vault_organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        conversation_id=conversation.id,
        agent_id=agent.id,
        agent_version_id=admitted.version_id,
        kind="browser",
        execution_target="agent",
        state="starting",
        session_lifetime="conversation",
        idle_seconds=900,
        fingerprint=resolved.fingerprint,
        revision=1,
        provisioning_attempt=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    resource = BrowserEnvironmentResource(
        environment_id=row.id,
        organization_id=ctx.organization_id,
        cdp_url="http://browser:9222",
        tabs={"main": BrowserTarget(context_id="owned-context", target_id="owned-target")},
    )
    db = AsyncMock()
    service = lifecycle.ConversationEnvironmentService(db)
    monkeypatch.setattr(lifecycle, "authority", AsyncMock(return_value=admitted))
    monkeypatch.setattr(lifecycle, "settings_for", AsyncMock(return_value=resolved))
    monkeypatch.setattr(lifecycle, "current_actor", AsyncMock(return_value=ctx))
    monkeypatch.setattr(lifecycle, "enqueue", AsyncMock())
    for name, value in [
        ("latest", row),
        ("for_worker", row),
        ("owned", row),
        ("driver", None),
        ("active_count", 0),
        ("lock_owner", None),
        ("sweep_candidates", []),
        ("active_for_maintenance", []),
    ]:
        monkeypatch.setattr(lifecycle.environments, name, AsyncMock(return_value=value))

    async def add(_db, candidate):
        return candidate

    monkeypatch.setattr(lifecycle.environments, "add", add)
    return SimpleNamespace(
        ctx=ctx,
        row=row,
        resource=resource,
        db=db,
        service=service,
        resolved=resolved,
        admitted=admitted,
        payload=service.payload(row),
        request=ConversationEnvironmentStart(agent_id=agent.id),
    )


async def test_ensure_is_idempotent_and_does_not_create_a_run_or_requeue(case):
    first_expiry = case.row.expires_at
    result = await case.service.ensure(case.ctx, case.row.conversation_id, "browser", case.request)
    assert result.id == case.row.id and result.state == "starting"
    assert case.row.expires_at >= first_expiry
    lifecycle.enqueue.assert_not_awaited()
    case.db.commit.assert_not_awaited()


async def test_new_admission_queues_provider_and_delayed_cleanup_in_the_callers_transaction(
    case, monkeypatch
):
    monkeypatch.setattr(lifecycle.environments, "latest", AsyncMock(return_value=None))
    result = await case.service.ensure(case.ctx, case.row.conversation_id, "browser", case.request)
    assert result.state == "starting" and result.id is not None
    calls = lifecycle.enqueue.await_args_list
    assert [call.args[1] for call in calls] == [
        lifecycle.PROVISION_CONVERSATION_ENVIRONMENT,
        lifecycle.CLEANUP_CONVERSATION_ENVIRONMENT,
    ]
    assert calls[1].kwargs["run_after"] == result.expires_at
    case.db.commit.assert_not_awaited()


async def test_capacity_refuses_before_any_provider_job(case, monkeypatch):
    monkeypatch.setattr(lifecycle.environments, "latest", AsyncMock(return_value=None))
    monkeypatch.setattr(lifecycle.environments, "active_count", AsyncMock(return_value=100))
    result = await case.service.ensure(case.ctx, case.row.conversation_id, "browser", case.request)
    assert result.id is None and result.refusal.code == "capacity_reached"
    lifecycle.enqueue.assert_not_awaited()


@pytest.mark.security
async def test_only_the_actual_running_producer_can_skip_a_background_provision_job(
    case, monkeypatch
):
    monkeypatch.setattr(lifecycle.run_repo, "get_run", AsyncMock(return_value=None))
    with pytest.raises(AuthorizationError):
        await case.service.ensure(
            case.ctx, case.row.conversation_id, "browser", case.request, producer_run_id=uuid4()
        )
    lifecycle.enqueue.assert_not_awaited()


async def test_end_never_destroys_an_active_agent_driver(case, monkeypatch):
    case.row.resource_key = "physical"
    held = ConversationEnvironmentDriver(
        resource_key="physical",
        control="agent",
        lease_until=datetime.now(UTC) + timedelta(minutes=1),
    )
    monkeypatch.setattr(lifecycle.environments, "driver", AsyncMock(return_value=held))
    with pytest.raises(ConflictError):
        await case.service.end(case.ctx, case.row.conversation_id, case.row.agent_id, "browser")
    assert case.row.state == "starting"
    lifecycle.enqueue.assert_not_awaited()


@pytest.mark.parametrize("state,target", [("expired", "agent"), ("ready", "project")])
async def test_end_is_idempotent_and_does_not_end_another_selected_target(case, state, target):
    case.row.state, case.row.execution_target = state, target
    await case.service.end(case.ctx, case.row.conversation_id, case.row.agent_id, "browser")
    assert case.row.state == state
    lifecycle.enqueue.assert_not_awaited()


async def test_end_revokes_admission_before_queued_cleanup_and_does_not_unseal(case):
    case.row.resource_ciphertext, case.row.resource_key_version = "not-read-during-end", 1
    await case.service.end(case.ctx, case.row.conversation_id, case.row.agent_id, "browser")
    assert case.row.state == "expired" and case.row.revision == 2
    assert case.row.expires_at <= datetime.now(UTC)
    queued = lifecycle.enqueue.await_args
    assert queued.args[1] == lifecycle.CLEANUP_CONVERSATION_ENVIRONMENT
    assert queued.args[2].revision == 2


@pytest.mark.security
async def test_private_handle_is_sealed_to_tenant_and_resource_identity(case):
    assert await case.service.store_resource(case.payload, 1, case.resource, "physical")
    assert "owned-target" not in case.row.resource_ciphertext
    assert case.service.resource(case.row, case.ctx.organization_id) == case.resource
    with pytest.raises(BadRequestError):
        case.service.resource(case.row, uuid4())
    wrong = case.resource.model_copy(update={"environment_id": uuid4()})
    with pytest.raises(ValueError):
        await case.service.store_resource(case.payload, 1, wrong, "physical")


async def test_provision_finished_after_end_keeps_a_cleanup_journal_but_cannot_become_ready(case):
    case.row.state, case.row.revision = "expired", 2
    assert not await case.service.store_resource(case.payload, 1, case.resource, "physical")
    assert case.row.resource_ciphertext is not None
    assert not await case.service.ready(case.payload, 1)
    assert lifecycle.enqueue.await_args.args[2].revision == 2


@pytest.mark.parametrize("change", ["revision", "attempt", "missing"])
async def test_stale_producer_cannot_overwrite_a_new_journal(case, monkeypatch, change):
    if change == "revision":
        case.row.revision = 3
    elif change == "attempt":
        case.row.provisioning_attempt = 2
    else:
        monkeypatch.setattr(lifecycle.environments, "for_worker", AsyncMock(return_value=None))
    assert not await case.service.store_resource(case.payload, 1, case.resource, "physical")
    assert case.row.resource_ciphertext is None


async def test_ready_requires_the_same_attempt_and_a_persisted_handle(case):
    assert not await case.service.ready(case.payload, 1)
    await case.service.store_resource(case.payload, 1, case.resource, "physical")
    assert not await case.service.ready(case.payload, 2)
    assert await case.service.ready(case.payload, 1)
    assert case.row.state == "ready"


async def test_failed_provision_with_known_resource_queues_cleanup(case):
    await case.service.store_resource(case.payload, 1, case.resource, "physical")
    await case.service.failed(case.payload)
    assert case.row.state == "failed"
    assert case.row.refusal_code == "provisioning_failed"
    assert lifecycle.enqueue.await_args.args[1] == lifecycle.CLEANUP_CONVERSATION_ENVIRONMENT


async def test_cleanup_waits_for_idle_or_explicit_end_then_clears_only_after_provider_success(case):
    await case.service.store_resource(case.payload, 1, case.resource, "physical")
    case.row.state = "ready"
    assert await case.service.cleanup_resource(case.payload) is None
    case.row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    resource = await case.service.cleanup_resource(case.payload)
    assert resource == case.resource and case.row.state == "expired"
    assert case.row.resource_ciphertext is not None
    await case.service.cleaned(case.payload)
    assert case.row.resource_ciphertext is None and case.row.resource_key is None


async def test_active_agent_driver_protects_idle_cleanup_but_not_explicit_end(case, monkeypatch):
    await case.service.store_resource(case.payload, 1, case.resource, "physical")
    case.row.state, case.row.expires_at = "ready", datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setattr(
        lifecycle.environments,
        "driver",
        AsyncMock(
            return_value=ConversationEnvironmentDriver(
                control="agent", lease_until=datetime.now(UTC) + timedelta(minutes=1)
            )
        ),
    )
    assert await case.service.cleanup_resource(case.payload) is None
    assert case.row.expires_at > datetime.now(UTC)
    await case.service.expire(case.row)
    assert await case.service.cleanup_resource(case.service.payload(case.row)) == case.resource


@pytest.mark.security
async def test_live_refuses_expiry_changed_binding_and_unknown_owner(case, monkeypatch):
    await case.service.store_resource(case.payload, 1, case.resource, "physical")
    with pytest.raises(EnvironmentNotReady):
        await case.service.live(case.ctx, case.row.conversation_id, case.row.id, "agent")
    case.row.state = "ready"
    case.row.fingerprint = "changed"
    with pytest.raises(EnvironmentNotReady) as caught:
        await case.service.live(case.ctx, case.row.conversation_id, case.row.id, "agent")
    assert caught.value.refusal.code == "environment_changed"
    monkeypatch.setattr(lifecycle.environments, "owned", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError):
        await case.service.live(case.ctx, case.row.conversation_id, case.row.id, "agent")


async def test_sweep_queues_orphan_cleanup_and_maintenance_without_provider_calls(
    case, monkeypatch
):
    await case.service.store_resource(case.payload, 1, case.resource, "physical")
    case.row.conversation_id = None
    monkeypatch.setattr(
        lifecycle.environments, "sweep_candidates", AsyncMock(return_value=[case.row])
    )
    monkeypatch.setattr(
        lifecycle.environments, "active_for_maintenance", AsyncMock(return_value=[])
    )
    await case.service.sweep()
    assert case.row.state == "expired"
    assert lifecycle.enqueue.await_args.args[1] == lifecycle.CLEANUP_CONVERSATION_ENVIRONMENT


@pytest.mark.parametrize("control", ["human", "agent"])
async def test_idle_sweep_protects_active_agent_work_but_not_an_idle_human_lease(
    case, monkeypatch, control
):
    await case.service.store_resource(case.payload, 1, case.resource, "physical")
    case.row.state = "ready"
    case.row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    held = ConversationEnvironmentDriver(
        control=control, lease_until=datetime.now(UTC) + timedelta(minutes=1)
    )
    monkeypatch.setattr(lifecycle.environments, "driver", AsyncMock(return_value=held))
    monkeypatch.setattr(
        lifecycle.environments, "sweep_candidates", AsyncMock(return_value=[case.row])
    )
    await case.service.sweep()
    if control == "agent":
        assert case.row.state == "ready"
        assert case.row.expires_at > datetime.now(UTC)
        lifecycle.enqueue.assert_not_awaited()
    else:
        assert case.row.state == "expired"
        assert lifecycle.enqueue.await_args.args[1] == lifecycle.CLEANUP_CONVERSATION_ENVIRONMENT


async def test_idle_human_lease_does_not_delay_queued_cleanup(case, monkeypatch):
    await case.service.store_resource(case.payload, 1, case.resource, "physical")
    case.row.state = "ready"
    case.row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    monkeypatch.setattr(
        lifecycle.environments,
        "driver",
        AsyncMock(
            return_value=ConversationEnvironmentDriver(
                control="human", lease_until=datetime.now(UTC) + timedelta(minutes=1)
            )
        ),
    )
    assert await case.service.cleanup_resource(case.payload) == case.resource
    assert case.row.state == "expired"

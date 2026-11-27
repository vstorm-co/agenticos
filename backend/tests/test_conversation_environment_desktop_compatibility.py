"""Ephemeral executor desktops keep legacy runs without advertising manual retention."""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.agents.spec import CapabilityBindingSpec
from app.core.secret_kinds import ApiKeySecret
from app.services import conversation_environment_agent as adapter
from app.services import conversation_environment_policy as policy
from app.services.conversation_environments import ConversationEnvironmentService
from tests import test_conversation_environment_agent_coordinator as coordinator_fixtures
from tests.test_conversation_environment_policy import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.security]
coordinator = coordinator_fixtures.case


def spec(admitted, *, scope="run", mode="sandbox", lifetime="run", key=None):
    return replace(
        admitted,
        spec=admitted.spec.model_copy(
            update={
                "capabilities": [
                    CapabilityBindingSpec(
                        id="sandbox", config={"backend": "service", "session_scope": scope}
                    ),
                    CapabilityBindingSpec(
                        id="computer_use",
                        secret_id=key,
                        config={"desktop": mode, "session_lifetime": lifetime},
                    ),
                ]
            }
        ),
    )


@pytest.mark.parametrize("scope", ["run", "channel"])
async def test_manual_read_reports_ephemeral_scope_refusal_before_connection_or_provider(
    case, monkeypatch, scope
):
    admitted, db = case
    admitted = spec(admitted, scope=scope)
    db.scalar.return_value = None
    monkeypatch.setattr(
        "app.services.conversation_environments.authority", AsyncMock(return_value=admitted)
    )
    connection = AsyncMock()
    monkeypatch.setattr(policy.SandboxConnectionService, "resolve", connection)
    state = await ConversationEnvironmentService(db).read(
        admitted.ctx, admitted.conversation.id, admitted.agent.id, "desktop"
    )
    assert state.state == "failed" and state.refusal.code == "backend_not_supported"
    assert not state.can_control and state.id is None
    connection.assert_not_awaited()
    assert await policy.legacy_run_desktop(db, admitted)


@pytest.mark.parametrize(
    "mode,lifetime,scope",
    [
        ("sandbox", "conversation", "run"),
        ("daemon", "run", "run"),
        ("e2b", "run", "run"),
        ("sandbox", "run", "conversation"),
    ],
)
async def test_retained_or_independent_desktops_never_enter_ephemeral_factory_fallback(
    case, mode, lifetime, scope
):
    admitted, db = case
    assert not await policy.legacy_run_desktop(
        db, spec(admitted, mode=mode, lifetime=lifetime, scope=scope)
    )


@pytest.mark.parametrize("has_key", [False, True])
async def test_auto_desktop_with_e2b_key_remains_on_owned_fenced_path(case, has_key):
    admitted, db = case
    key = uuid4()
    policy.OrganizationSecretService.resolve_for_bindings.return_value = (
        {key: ApiKeySecret(api_key=SecretStr("private-key"))} if has_key else {}
    )
    assert await policy.legacy_run_desktop(db, spec(admitted, mode="auto", key=key)) is (
        not has_key
    )
    assert await policy.legacy_run_desktop(db, spec(admitted, mode="auto"))


async def test_missing_or_disabled_computer_binding_does_not_invent_a_legacy_factory(case):
    admitted, db = case
    assert not await policy.legacy_run_desktop(db, admitted)
    configured = spec(admitted)
    configured.spec.capabilities[-1].enabled = False
    assert not await policy.legacy_run_desktop(db, configured)


async def test_invalid_desktop_config_is_a_controlled_refusal(case):
    admitted, db = case
    configured = spec(admitted)
    configured.spec.capabilities[-1].config = {"desktop": "invalid"}
    with pytest.raises(policy.EnvironmentNotReady):
        await policy.legacy_run_desktop(db, configured)


@pytest.fixture
def owned(coordinator, monkeypatch):
    coordinator.owner.kind = "desktop"
    configured = spec(coordinator.resolved.authority)
    monkeypatch.setattr(adapter, "authority", AsyncMock(return_value=configured))
    return coordinator, configured


async def test_legacy_ephemeral_run_invokes_original_factory_without_owned_admission(
    owned, monkeypatch
):
    item, _ = owned
    fallback = AsyncMock()
    opened = MagicMock()
    monkeypatch.setattr(adapter.runtime, "open_view", opened)
    workspace = MagicMock()
    assert await item.owner.wrap_computer(fallback)(workspace) is fallback.return_value
    fallback.assert_awaited_once_with(workspace)
    item.service.read.assert_not_awaited()
    item.service.ensure.assert_not_awaited()
    adapter.runtime.start_environment.assert_not_awaited()
    item.driver.acquire.assert_not_awaited()
    opened.assert_not_called()


async def test_republished_agent_cannot_fall_back_using_a_previous_run_pin(owned):
    item, _ = owned
    item.owner.version_id = uuid4()
    with pytest.raises(policy.EnvironmentNotReady, match="different published"):
        await item.owner.acquire()
    item.service.ensure.assert_not_awaited()


async def test_supported_shared_run_desktop_still_acquires_fenced_owned_driver(owned):
    item, configured = owned
    configured.spec.capabilities[0].config["session_scope"] = "conversation"
    assert await item.owner.acquire()
    item.driver.acquire.assert_awaited_once()
    assert item.owner.driver is item.driver


async def test_selected_project_executor_never_inherits_agent_ephemeral_scope(case):
    from app.db.models.project import Project

    admitted, db = case
    configured = spec(admitted)
    project = Project(
        id=uuid4(),
        organization_id=admitted.ctx.organization_id,
        name="Shared project",
        backend="service",
        runtime=None,
        sandbox_connection_id=uuid4(),
    )
    configured = replace(configured, execution_target="project", project=project)
    assert not await policy.legacy_run_desktop(db, configured)

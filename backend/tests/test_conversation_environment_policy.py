"""Manual and agent environments resolve current authority, never private handles from UI."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.config import settings
from app.core.exceptions import AuthenticationError, AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret
from app.db.models.agent import Agent
from app.db.models.conversation import Conversation
from app.services import conversation_environment_policy as policy

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def case(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    conversation = Conversation(
        id=uuid4(), organization_id=ctx.organization_id, user_id=ctx.user_id
    )
    agent = Agent(
        id=uuid4(), organization_id=ctx.organization_id, name="Published", slug="published"
    )
    spec = AgentSpec(name="Published", instructions="Use approved tools")
    admitted = policy.EnvironmentAuthority(ctx, conversation, agent, uuid4(), spec, "agent", None)
    monkeypatch.setattr(
        policy.member_repo, "get_active", AsyncMock(return_value=SimpleNamespace(role="owner"))
    )
    monkeypatch.setattr(
        policy.user_repo,
        "get_by_id",
        AsyncMock(return_value=SimpleNamespace(is_active=True, is_app_admin=False)),
    )
    monkeypatch.setattr(
        policy.ConversationService, "get_conversation", AsyncMock(return_value=conversation)
    )
    monkeypatch.setattr(
        policy.AgentRegistryService,
        "get_runnable_spec",
        AsyncMock(return_value=(agent, spec, admitted.version_id)),
    )
    monkeypatch.setattr(policy.ProjectService, "for_run", AsyncMock(return_value=None))
    monkeypatch.setattr(
        policy.OrganizationSecretService, "resolve_for_bindings", AsyncMock(return_value={})
    )
    monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", ["browser"])
    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "http://browser:9222")
    monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", ["desktop"])
    return admitted, AsyncMock()


@pytest.mark.parametrize("missing", ["membership", "user", "inactive"])
async def test_removed_or_inactive_owner_cannot_open_or_keep_control(case, monkeypatch, missing):
    admitted, db = case
    if missing == "membership":
        policy.member_repo.get_active.return_value = None
    elif missing == "user":
        policy.user_repo.get_by_id.return_value = None
    else:
        policy.user_repo.get_by_id.return_value.is_active = False
    with pytest.raises(AuthenticationError):
        await policy.current_actor(db, admitted.ctx.organization_id, admitted.ctx.user_id)


@pytest.mark.parametrize("kind", ["key", "fallback", "anonymous"])
async def test_non_personal_authority_is_refused_before_resource_resolution(case, kind):
    admitted, db = case
    ctx = (
        replace(admitted.ctx, api_key_id=uuid4())
        if kind == "key"
        else replace(admitted.ctx, subject_is_publisher_fallback=True)
        if kind == "fallback"
        else replace(admitted.ctx, user_id=None)
    )
    with pytest.raises(AuthorizationError):
        await policy.authority(
            db, ctx, conversation_id=admitted.conversation.id, agent_id=admitted.agent.id
        )
    policy.AgentRegistryService.get_runnable_spec.assert_not_awaited()


async def test_writable_shared_conversation_does_not_grant_the_owners_private_environment(case):
    admitted, db = case
    admitted.conversation.user_id = uuid4()
    with pytest.raises(AuthorizationError):
        await policy.authority(
            db, admitted.ctx, conversation_id=admitted.conversation.id, agent_id=admitted.agent.id
        )
    policy.AgentRegistryService.get_runnable_spec.assert_not_awaited()


async def test_published_run_access_is_reused_and_unknown_configuration_is_typed(case):
    admitted, db = case
    policy.AgentRegistryService.get_runnable_spec.side_effect = BadRequestError(
        message="Agent disabled"
    )
    with pytest.raises(policy.EnvironmentNotReady) as caught:
        await policy.authority(
            db, admitted.ctx, conversation_id=admitted.conversation.id, agent_id=admitted.agent.id
        )
    assert caught.value.refusal.code == "capability_not_enabled"
    try:
        AgentSpec(name="", instructions="x")
    except ValidationError as invalid:
        policy.AgentRegistryService.get_runnable_spec.side_effect = invalid
    with pytest.raises(policy.EnvironmentNotReady) as caught:
        await policy.authority(
            db, admitted.ctx, conversation_id=admitted.conversation.id, agent_id=admitted.agent.id
        )
    assert caught.value.refusal.code == "connection_unavailable"


async def test_resource_permission_denial_stays_an_authorization_error(case):
    admitted, db = case
    policy.AgentRegistryService.get_runnable_spec.side_effect = AuthorizationError(
        message="Agent run grant revoked"
    )
    with pytest.raises(AuthorizationError):
        await policy.authority(
            db, admitted.ctx, conversation_id=admitted.conversation.id, agent_id=admitted.agent.id
        )


async def test_selected_project_target_requires_an_authorized_executor(case):
    admitted, db = case
    with pytest.raises(policy.EnvironmentNotReady) as caught:
        await policy.authority(
            db,
            admitted.ctx,
            conversation_id=admitted.conversation.id,
            agent_id=admitted.agent.id,
            execution_target="project",
        )
    assert caught.value.refusal.code == "workspace_unavailable"
    project = SimpleNamespace(id=uuid4(), backend="service")
    policy.ProjectService.for_run.return_value = project
    resolved = await policy.authority(
        db,
        admitted.ctx,
        conversation_id=admitted.conversation.id,
        agent_id=admitted.agent.id,
        execution_target="project",
    )
    assert resolved.project is project and resolved.execution_target == "project"


async def test_missing_binding_refuses_without_unsealing_any_secret(case):
    admitted, db = case
    with pytest.raises(policy.EnvironmentNotReady) as caught:
        await policy.settings_for(db, admitted, "browser")
    assert caught.value.refusal.code == "capability_not_enabled"
    policy.OrganizationSecretService.resolve_for_bindings.assert_not_awaited()


@pytest.mark.parametrize(
    "kind,capability,config,reason",
    [
        ("browser", "browser_use", {"connection": "local"}, "local_device_required"),
        ("desktop", "computer_use", {"desktop": "local"}, "local_device_required"),
        (
            "browser",
            "browser_use",
            {"connection": "hosted", "hosted_url": "https://hosted.example"},
            "connection_unavailable",
        ),
        ("browser", "browser_use", {"cdp_url": "http://unapproved:9222"}, "connection_unavailable"),
        (
            "desktop",
            "computer_use",
            {"desktop": "daemon", "daemon_url": "http://desktop:8765"},
            "connection_unavailable",
        ),
        ("desktop", "computer_use", {"desktop": "e2b"}, "connection_unavailable"),
        ("browser", "browser_use", {"session_idle_seconds": 0}, "connection_unavailable"),
    ],
)
async def test_readiness_returns_controlled_refusal_without_provider_io(
    case, kind, capability, config, reason
):
    admitted, db = case
    admitted = replace(
        admitted,
        spec=admitted.spec.model_copy(
            update={"capabilities": [CapabilityBindingSpec(id=capability, config=config)]}
        ),
    )
    with pytest.raises(policy.EnvironmentNotReady) as caught:
        await policy.settings_for(db, admitted, kind)
    assert caught.value.refusal.code == reason


async def test_endpoint_credential_rotation_and_project_generation_change_the_identity(case):
    admitted, db = case
    key_id = uuid4()
    binding = CapabilityBindingSpec(
        id="browser_use", config={"connection": "built_in"}, secret_id=key_id
    )
    admitted = replace(admitted, spec=admitted.spec.model_copy(update={"capabilities": [binding]}))
    policy.OrganizationSecretService.resolve_for_bindings.return_value = {
        key_id: ApiKeySecret(api_key="first-private-token")
    }
    first = await policy.settings_for(db, admitted, "browser")
    assert isinstance(first, policy.BrowserEnvironmentSettings)
    assert first.cdp_url == "http://browser:9222"
    policy.OrganizationSecretService.resolve_for_bindings.return_value = {
        key_id: ApiKeySecret(api_key="rotated-private-token")
    }
    rotated = await policy.settings_for(db, admitted, "browser")
    assert first.fingerprint != rotated.fingerprint
    assert "private-token" not in repr(rotated)
    admitted.conversation.project_id = uuid4()
    project = SimpleNamespace(workspace_generation=uuid4())
    projected = await policy.settings_for(db, replace(admitted, project=project), "browser")
    assert projected.fingerprint != rotated.fingerprint


async def test_daemon_binding_returns_private_credential_only_inside_typed_settings(case):
    admitted, db = case
    key_id = uuid4()
    spec = admitted.spec.model_copy(
        update={
            "capabilities": [
                CapabilityBindingSpec(
                    id="computer_use",
                    secret_id=key_id,
                    config={"desktop": "daemon", "daemon_url": "http://desktop:8765"},
                )
            ]
        }
    )
    policy.OrganizationSecretService.resolve_for_bindings.return_value = {
        key_id: ApiKeySecret(api_key="private-daemon-key")
    }
    resolved = await policy.settings_for(db, replace(admitted, spec=spec), "desktop")
    assert isinstance(resolved, policy.DesktopEnvironmentSettings)
    assert resolved.credential == "private-daemon-key"
    assert "private-daemon-key" not in repr(resolved)


async def test_sandbox_connection_rotation_changes_identity_without_probe_or_default_creation(
    case, monkeypatch
):
    from app.db.models.sandbox_connection import SandboxConnection
    from app.services.sandbox_connection import ResolvedConnection

    admitted, db = case
    connection_id = uuid4()
    spec = admitted.spec.model_copy(
        update={
            "capabilities": [
                CapabilityBindingSpec(id="computer_use", config={"desktop": "sandbox"}),
                CapabilityBindingSpec(
                    id="sandbox", config={"backend": "service", "connection_id": str(connection_id)}
                ),
            ]
        }
    )
    admitted = replace(admitted, spec=spec)
    row = SandboxConnection(
        id=connection_id,
        organization_id=admitted.ctx.organization_id,
        kind="docker",
        base_url="http://original-executor:8080",
        default_runtime="desktop",
        secure_access=False,
    )
    resolve = AsyncMock(return_value=ResolvedConnection(row, "original-private-token"))
    monkeypatch.setattr(policy.SandboxConnectionService, "resolve", resolve)
    first = await policy.settings_for(db, admitted, "desktop")
    resolve.assert_awaited_once_with(admitted.ctx, connection_id, ensure_default=False)
    resolve.return_value = ResolvedConnection(row, "rotated-private-token")
    rotated = await policy.settings_for(db, admitted, "desktop")
    assert first.fingerprint != rotated.fingerprint
    row.base_url = "http://new-executor:8080"
    moved = await policy.settings_for(db, admitted, "desktop")
    assert moved.fingerprint != rotated.fingerprint
    resolve.side_effect = BadRequestError(message="Connection is inactive")
    with pytest.raises(policy.EnvironmentNotReady) as caught:
        await policy.settings_for(db, admitted, "desktop")
    assert caught.value.refusal.code == "connection_unavailable"


async def test_a_desktop_without_an_executor_is_unavailable_without_provider_io(case):
    admitted, db = case
    spec = admitted.spec.model_copy(
        update={
            "capabilities": [
                CapabilityBindingSpec(id="computer_use", config={"desktop": "sandbox"})
            ]
        }
    )
    with pytest.raises(policy.EnvironmentNotReady) as caught:
        await policy.settings_for(db, replace(admitted, spec=spec), "desktop")
    assert caught.value.refusal.code == "workspace_unavailable"


async def test_deployment_browser_endpoint_and_egress_policy_changes_invalidate_old_target(
    case, monkeypatch
):
    admitted, db = case
    admitted = replace(
        admitted,
        spec=admitted.spec.model_copy(
            update={"capabilities": [CapabilityBindingSpec(id="browser_use", config={})]}
        ),
    )
    first = await policy.settings_for(db, admitted, "browser")
    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "http://browser:9333")
    moved = await policy.settings_for(db, admitted, "browser")
    assert moved.fingerprint != first.fingerprint
    monkeypatch.setattr(settings, "BROWSER_EGRESS_PROXY", "http://egress:3128")
    restricted = await policy.settings_for(db, admitted, "browser")
    assert restricted.fingerprint != moved.fingerprint

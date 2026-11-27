"""Observation attaches an exact authorized sandbox without turn admission or recovery."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai.workspaces import WorkspaceRef

from app.agents.capabilities.sandbox import WorkspaceIdentity
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.conversation import Conversation
from app.db.models.sandbox_connection import SandboxConnection
from app.services import sandbox_workspace as workspaces
from app.services.conversation import ConversationService
from app.services.sandbox_connection import ResolvedConnection, SandboxConnectionService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def case(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    conversation = Conversation(
        id=uuid4(), organization_id=ctx.organization_id, user_id=ctx.user_id
    )
    connection = SandboxConnection(
        id=uuid4(),
        organization_id=ctx.organization_id,
        name="Container",
        kind="sandboxd",
        base_url="http://sandbox.invalid",
        secure_access=False,
    )
    resolved = ResolvedConnection(connection, "private-token")
    spec = AgentSpec(
        name="Desktop",
        capabilities=[
            CapabilityBindingSpec(
                id="sandbox",
                config={
                    "backend": "service",
                    "session_scope": "conversation",
                    "connection_id": str(connection.id),
                },
            )
        ],
    )
    identity = WorkspaceIdentity(
        organization_id=ctx.organization_id,
        agent_id=uuid4(),
        run_id=uuid4(),
        conversation_id=conversation.id,
        user_id=str(ctx.user_id),
    )
    db = AsyncMock()
    service = workspaces.SandboxWorkspaceService(db)
    key = service._key(identity, "conversation", "service", connection.id, None)
    row = AgentWorkspace(
        id=uuid4(),
        organization_id=ctx.organization_id,
        agent_id=identity.agent_id,
        conversation_id=conversation.id,
        scope="conversation",
        scope_key=key,
        backend="service",
        connection_id=connection.id,
        session_id="original",
    )
    reader = AsyncMock(return_value=conversation)
    monkeypatch.setattr(ConversationService, "get_conversation", reader)
    monkeypatch.setattr(SandboxConnectionService, "resolve", AsyncMock(return_value=resolved))
    monkeypatch.setattr(
        SandboxConnectionService, "supports_project_filesystem", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(workspaces.workspace_repo, "get", AsyncMock(return_value=row))
    return SimpleNamespace(
        ctx=ctx,
        service=service,
        spec=spec,
        identity=identity,
        row=row,
        reader=reader,
        resolved=resolved,
        ref=WorkspaceRef(provider=f"sandboxd:{connection.id}", id="original"),
    )


async def attach(case):
    return await case.service.attach_live_environment(
        case.ctx,
        spec=case.spec,
        identity=case.identity,
        execution_target="agent",
        workspace_id=case.row.id,
        ref=case.ref,
        connection_fingerprint=case.service.environment_connection_fingerprint(case.resolved),
    )


async def test_observation_uses_exact_ref_without_creating_or_admitting_a_turn(case):
    opened = await attach(case)
    assert opened.workspace.ref == case.ref
    assert opened.row_id == case.row.id
    assert opened.scope_key == case.row.scope_key
    assert case.reader.await_args.kwargs["for_write"] is True
    assert case.reader.await_args.kwargs["turn"] is True
    SandboxConnectionService.resolve.assert_awaited_once_with(
        case.ctx, case.resolved.row.id, ensure_default=False
    )


@pytest.mark.parametrize(
    "changed",
    [
        "conversation",
        "actor",
        "sandbox",
        "connection",
        "missing",
        "key",
        "backend",
        "connection_id",
        "session",
        "provider",
    ],
)
async def test_stale_authority_or_physical_identity_never_substitutes_an_executor(case, changed):
    fingerprint = case.service.environment_connection_fingerprint(case.resolved)
    if changed == "conversation":
        case.identity = replace(case.identity, conversation_id=None)
    elif changed == "actor":
        case.ctx = AuthContext(user_id=None, organization_id=case.ctx.organization_id, role="owner")
    elif changed == "sandbox":
        case.spec = AgentSpec(name="No sandbox")
    elif changed == "connection":
        case.resolved.row.base_url = "http://replacement.invalid"
    elif changed == "missing":
        workspaces.workspace_repo.get.return_value = None
    elif changed == "key":
        case.row.scope_key = "another-owner"
    elif changed == "backend":
        case.row.backend = "state"
    elif changed == "connection_id":
        case.row.connection_id = uuid4()
    elif changed == "session":
        case.row.session_id = "replacement"
    else:
        case.ref = WorkspaceRef(provider="different-provider", id=case.ref.id)
    with pytest.raises(NotFoundError):
        await case.service.attach_live_environment(
            case.ctx,
            spec=case.spec,
            identity=case.identity,
            execution_target="agent",
            workspace_id=case.row.id,
            ref=case.ref,
            connection_fingerprint=fingerprint,
        )


async def test_observer_resolving_a_missing_default_cannot_create_a_deployment_connection(
    case, monkeypatch
):
    from app.core.exceptions import BadRequestError
    from app.services import sandbox_connection as connections

    monkeypatch.setattr(
        connections.sandbox_connection_repo, "get_default", AsyncMock(return_value=None)
    )
    create = AsyncMock(return_value=case.resolved.row)
    monkeypatch.setattr(SandboxConnectionService, "ensure_local_connection", create)
    resolver = SandboxConnectionService(AsyncMock())
    with pytest.raises(BadRequestError):
        await resolver._row_for(case.ctx, None, ensure_default=False)
    create.assert_not_awaited()
    assert await resolver._row_for(case.ctx, None) is case.resolved.row
    create.assert_awaited_once_with(case.ctx.organization_id)


@pytest.mark.parametrize("generation_state", ["same", "changed", "legacy_same", "legacy_moved"])
async def test_effect_free_execution_scope_checks_actual_selected_project_before_any_provider(
    case, monkeypatch, generation_state
):
    from app.db.models.project import Project
    from app.services import project_workspace_guard

    selected = Project(
        id=uuid4(),
        organization_id=case.ctx.organization_id,
        name="Selected executor",
        backend="service",
        sandbox_connection_id=case.resolved.row.id,
        workspace_generation=None if generation_state == "legacy_same" else uuid4(),
        runtime=None,
    )
    project = AsyncMock(return_value=selected)
    monkeypatch.setattr(project_workspace_guard, "project_for_workspace", project)
    generation = (
        None
        if generation_state in ("legacy_same", "legacy_moved")
        else uuid4()
        if generation_state == "changed"
        else selected.workspace_generation
    )
    if generation_state in ("changed", "legacy_moved"):
        with pytest.raises(NotFoundError, match="selected project executor changed"):
            await case.service.resolve_live_execution(
                case.ctx,
                spec=case.spec,
                identity=case.identity,
                execution_target="project",
                selected_project_id=selected.id,
                selected_generation=generation,
            )
        SandboxConnectionService.resolve.assert_not_awaited()
    else:
        result = await case.service.resolve_live_execution(
            case.ctx,
            spec=case.spec,
            identity=case.identity,
            execution_target="project",
            selected_project_id=selected.id,
            selected_generation=generation,
        )
        assert result.scope == "project"
        assert result.identity.project_id == selected.id
        assert result.identity.project_workspace_id == selected.workspace_generation
        assert result.key != case.row.scope_key
        workspaces.workspace_repo.get.assert_not_awaited()
    project.assert_awaited_once_with(case.service.db, case.ctx, selected.id)

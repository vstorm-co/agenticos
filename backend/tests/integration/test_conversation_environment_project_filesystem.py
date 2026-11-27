"""Owned desktop paths retain canonical Project access without borrowing an ended run."""

import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_ai.workspaces import WorkspaceRef
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.audience import RunAudience
from app.agents.capabilities.sandbox import WorkspaceIdentity
from app.agents.capabilities.sandbox._identity import retained_scope_key
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import AuthenticationError, AuthorizationError, NotFoundError
from app.core.secret_kinds import ApiKeySecret
from app.db.models.agent_run import AgentRun
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.conversation import Conversation
from app.db.models.conversation_environment import ConversationEnvironment
from app.db.models.organization import OrganizationMember
from app.db.models.project import Project
from app.db.models.project_filesystem import ProjectFilesystemLease
from app.db.models.sandbox_connection import SandboxConnection
from app.schemas.project import ProjectCreate
from app.schemas.project_filesystem import FsCreate, FsList, FsRead, FsSuccess, FsWrite
from app.schemas.project_filesystem_authority import ProjectFilesystemAuthority
from app.services.conversation_environment_policy import authority, settings_for
from app.services.conversation_environment_project_files import directory
from app.services.conversation_environment_resources import DesktopEnvironmentResource
from app.services.conversation_environments import ConversationEnvironmentService
from app.services.organization_secret import OrganizationSecretService
from app.services.project import ProjectService
from app.services.project_filesystem_bindings import ProjectFilesystemBindingService
from app.services.project_filesystem_gateway import ProjectFilesystemGateway
from app.services.sandbox_connection import SandboxConnectionService
from app.services.sandbox_workspace import SandboxWorkspaceService
from app.worker.jobs import ConversationEnvironmentPayload
from tests.integration.test_agent_attention import _agent, _publish, _run
from tests.integration.test_workflow_exposures import _ctx, _org, _user

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def prepared(db: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    # This is the provider policy boundary only; all identity, Vault, row,
    # published authority, lease and canonical filesystem operations are real.
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        SandboxConnectionService, "supports_project_filesystem", AsyncMock(return_value=True)
    )
    user = await _user(db)
    org = await _org(db, owner=user)
    ctx = _ctx(user, org)
    secret = await OrganizationSecretService(db).create(
        ctx, name="Test sandbox token", value=ApiKeySecret(api_key="test-project-fs-provider-token")
    )
    connection = SandboxConnection(
        organization_id=org.id,
        name="Private Docker",
        kind="docker",
        base_url="http://sandbox.invalid",
        secret_id=secret.id,
        default_runtime="desktop",
        is_active=True,
    )
    db.add(connection)
    await db.flush()
    project_read = await ProjectService(db).create(
        ctx, ProjectCreate(name="Shared canonical files", backend="state")
    )
    project = await db.get(Project, project_read.id)
    assert project is not None
    conversation = Conversation(organization_id=org.id, user_id=user.id, project_id=project.id)
    db.add(conversation)
    await db.flush()
    agent = await _agent(db, org, user, "Desktop filesystem")
    agent.draft_spec = AgentSpec(
        name="Desktop filesystem",
        capabilities=[
            CapabilityBindingSpec(
                id="sandbox",
                config={
                    "backend": "service",
                    "session_scope": "conversation",
                    "connection_id": str(connection.id),
                    "runtime": "desktop",
                },
            ),
            CapabilityBindingSpec(
                id="computer_use", config={"desktop": "sandbox", "session_lifetime": "conversation"}
            ),
        ],
    ).model_dump(mode="json")
    await _publish(db, agent)
    identity = WorkspaceIdentity(
        organization_id=org.id,
        agent_id=agent.id,
        run_id=None,
        conversation_id=conversation.id,
        user_id=str(user.id),
        project_id=project.id,
    )
    key = retained_scope_key(identity, "conversation", "service", connection.id, "desktop")
    workspace = AgentWorkspace(
        organization_id=org.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        scope="conversation",
        scope_key=key,
        backend="service",
        connection_id=connection.id,
        session_id=key,
    )
    db.add(workspace)
    await db.flush()
    resolved = await SandboxConnectionService(db).resolve(ctx, connection.id, ensure_default=False)
    configured = await settings_for(
        db, await authority(db, ctx, conversation_id=conversation.id, agent_id=agent.id), "desktop"
    )
    row = ConversationEnvironment(
        organization_id=org.id,
        vault_organization_id=org.id,
        user_id=user.id,
        conversation_id=conversation.id,
        agent_id=agent.id,
        agent_version_id=agent.current_version_id,
        kind="desktop",
        execution_target="agent",
        session_lifetime="conversation",
        idle_seconds=900,
        state="starting",
        fingerprint=configured.fingerprint,
        revision=1,
        provisioning_attempt=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    db.add(row)
    await db.flush()
    payload = ConversationEnvironmentPayload(
        environment_id=row.id, organization_id=org.id, revision=1
    )
    resource = DesktopEnvironmentResource(
        environment_id=row.id,
        organization_id=org.id,
        backend="sandbox",
        workspace_id=workspace.id,
        workspace_ref=WorkspaceRef(provider=f"sandboxd:{connection.id}", id=key),
        connection_id=connection.id,
        connection_fingerprint=SandboxWorkspaceService.environment_connection_fingerprint(resolved),
        workspace_root="/workspace",
        width=1280,
        height=800,
    )
    environments = ConversationEnvironmentService(db)
    stored = await environments.store_resource(payload, 1, resource, "physical-desktop")
    assert stored
    service = ProjectFilesystemBindingService(db)
    credential = await service.credential(
        organization_id=org.id,
        connection_id=connection.id,
        session_name=key,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
    )
    return SimpleNamespace(**locals())


async def admit(case):
    return await case.service.issue_environment_lease(
        binding_id=case.credential.binding_id,
        payload=case.payload,
        attempt=1,
        project_id=case.project.id,
        generation=case.project.workspace_generation,
    )


async def ready(case, lease):
    case.resource.project_lease_id = lease.id
    stored = await case.environments.store_resource(
        case.payload, 1, case.resource, "physical-desktop"
    )
    assert stored
    became_ready = await case.environments.ready(case.payload, 1)
    assert became_ready
    await case.db.commit()


async def rpc(case, request):
    result = await ProjectFilesystemGateway(case.db).perform(
        case.credential.binding_id, case.credential.token, request
    )
    await case.db.commit()
    return result


async def test_manual_ready_desktop_reads_and_writes_actual_project_bytes_without_creating_runs(
    db, monkeypatch
):
    case = await prepared(db, monkeypatch)
    lease = await admit(case)
    assert await db.scalar(select(func.count()).select_from(AgentRun)) == 0
    # STARTING has a journaled path, but is not filesystem authority yet.
    with pytest.raises(AuthorizationError):
        await ProjectFilesystemGateway(db).perform(
            case.credential.binding_id, case.credential.token, FsList(op="list", path=str(lease.id))
        )
    await ready(case, lease)
    assert (
        await rpc(case, FsCreate(op="create", path=f"{lease.id}/result.bin", exclusive=True))
    ).ok
    data = b"canonical\x00\xff"
    assert (
        await rpc(
            case,
            FsWrite(
                op="write",
                path=f"{lease.id}/result.bin",
                offset=0,
                data=base64.b64encode(data).decode(),
            ),
        )
    ).ok
    result = await rpc(case, FsRead(op="read", path=f"{lease.id}/result.bin", offset=0, count=128))
    assert isinstance(result, FsSuccess) and base64.b64decode(result.data) == data
    assert (
        await SandboxWorkspaceService(db).project_bytes(case.ctx, case.project, path="result.bin")
        == data
    )
    assert (
        await directory(
            db,
            ctx=case.ctx,
            environment_id=case.row.id,
            binding_id=case.credential.binding_id,
            project_id=case.project.id,
            generation=case.project.workspace_generation,
        )
        == lease.path
    )
    assert await db.scalar(select(func.count()).select_from(AgentRun)) == 0


async def test_real_run_lease_ends_while_same_project_desktop_path_stays_authorized(
    db, monkeypatch
):
    case = await prepared(db, monkeypatch)
    run = await _run(
        db, case.agent, status="running", user_id=case.user.id, conversation_id=case.conversation.id
    )
    admission = ProjectFilesystemAuthority(
        actor=case.ctx,
        audience=RunAudience(user_id=case.user.id, shared_transcript=True),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
        conversation_id=case.conversation.id,
        conversation_project_id=case.project.id,
    )
    run_lease = await case.service.issue_lease(
        binding_id=case.credential.binding_id,
        project_id=case.project.id,
        generation=case.project.workspace_generation,
        run_id=run.id,
        authority=admission,
    )
    env_lease = await admit(case)
    assert run_lease.id != env_lease.id
    await ready(case, env_lease)
    run.status = "completed"
    await db.commit()
    with pytest.raises(AuthorizationError, match="no longer active"):
        await ProjectFilesystemGateway(db).perform(
            case.credential.binding_id,
            case.credential.token,
            FsList(op="list", path=str(run_lease.id)),
        )
    assert (await rpc(case, FsList(op="list", path=str(env_lease.id)))).ok
    await case.service.revoke(lease_id=run_lease.id, run_id=run.id, organization_id=case.org.id)
    await db.commit()
    assert (await rpc(case, FsList(op="list", path=str(env_lease.id)))).ok


@pytest.mark.parametrize(
    "refusal", ["expired", "ended", "member", "generation", "connection", "resource", "revoked"]
)
async def test_each_rpc_rechecks_current_environment_project_and_binding_authority(
    db, monkeypatch, refusal
):
    case = await prepared(db, monkeypatch)
    lease = await admit(case)
    await ready(case, lease)
    before = case.row.expires_at
    assert (await rpc(case, FsList(op="list", path=str(lease.id)))).ok
    await db.refresh(case.row)
    assert case.row.expires_at == before
    if refusal == "expired":
        case.row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif refusal == "ended":
        case.row.state = "expired"
    elif refusal == "member":
        await db.execute(
            delete(OrganizationMember).where(
                OrganizationMember.organization_id == case.org.id,
                OrganizationMember.user_id == case.user.id,
            )
        )
    elif refusal == "generation":
        case.project.workspace_generation = uuid4()
    elif refusal == "connection":
        case.connection.default_runtime = "workbench"
    elif refusal == "resource":
        case.resource.project_lease_id = uuid4()
        await case.environments.replace_resource(case.row, case.resource)
    else:
        row = await db.get(ProjectFilesystemLease, lease.id)
        row.revoked_at = datetime.now(UTC)
    await db.commit()
    with pytest.raises(AuthenticationError if refusal == "member" else AuthorizationError):
        await ProjectFilesystemGateway(db).perform(
            case.credential.binding_id, case.credential.token, FsList(op="list", path=str(lease.id))
        )
    root = await rpc(case, FsList(op="list", path="."))
    assert root.ok and root.entries == []


async def test_environment_expiry_is_authoritative_after_real_activity_extends_it(db, monkeypatch):
    case = await prepared(db, monkeypatch)
    lease = await admit(case)
    await ready(case, lease)
    stored = await db.get(ProjectFilesystemLease, lease.id)
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    case.row.expires_at = datetime.now(UTC) + timedelta(minutes=10)
    await db.commit()
    before = case.row.expires_at
    assert (await rpc(case, FsList(op="list", path=str(lease.id)))).ok
    await db.refresh(case.row)
    assert case.row.expires_at == before
    assert [entry.path for entry in (await rpc(case, FsList(op="list", path="."))).entries] == [
        str(lease.id)
    ]


async def test_same_environment_admission_reuses_semantic_authority_without_reassigning_path(
    db, monkeypatch
):
    import json

    case = await prepared(db, monkeypatch)
    lease = await admit(case)
    stored = await db.get(ProjectFilesystemLease, lease.id)
    snapshot = json.loads(stored.authority_json)
    snapshot["granted_scopes"] = list(reversed(snapshot["granted_scopes"]))
    stored.authority_json = json.dumps(snapshot, indent=2, sort_keys=True)
    await db.flush()
    repeated = await admit(case)
    assert repeated.id == lease.id and repeated.path == lease.path
    assert await db.scalar(select(func.count()).select_from(ProjectFilesystemLease)) == 1


async def test_expired_environment_cannot_block_new_manual_path_on_the_same_workspace(
    db, monkeypatch
):
    case = await prepared(db, monkeypatch)
    old = await admit(case)
    await ready(case, old)
    case.row.state = "expired"
    await db.commit()
    row = ConversationEnvironment(
        organization_id=case.org.id,
        vault_organization_id=case.org.id,
        user_id=case.user.id,
        conversation_id=case.conversation.id,
        agent_id=case.agent.id,
        agent_version_id=case.agent.current_version_id,
        kind="desktop",
        execution_target="agent",
        session_lifetime="conversation",
        idle_seconds=900,
        state="starting",
        fingerprint=case.row.fingerprint,
        revision=1,
        provisioning_attempt=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    db.add(row)
    await db.flush()
    case.row = row
    case.payload = case.payload.model_copy(update={"environment_id": row.id})
    case.resource = case.resource.model_copy(
        update={"environment_id": row.id, "project_lease_id": None}
    )
    stored = await case.environments.store_resource(
        case.payload, 1, case.resource, "physical-desktop"
    )
    assert stored
    new = await admit(case)
    assert new.id != old.id
    await ready(case, new)
    with pytest.raises(AuthorizationError):
        await ProjectFilesystemGateway(db).perform(
            case.credential.binding_id, case.credential.token, FsList(op="list", path=str(old.id))
        )
    root = await rpc(case, FsList(op="list", path="."))
    assert [entry.path for entry in root.entries] == [str(new.id)]


async def test_actual_run_project_port_adopts_stable_desktop_path_and_finish_keeps_it_live(
    db, monkeypatch
):
    from contextlib import asynccontextmanager

    from pydantic_ai.workspaces import CommandResult, Workspace

    from app.services import conversation_environment_agent as agent_adapter
    from app.services import conversation_environment_driver as drivers
    from app.services import run_project_workspace as project_port
    from tests.workspaces import document_workspace

    case = await prepared(db, monkeypatch)
    lease = await admit(case)
    await ready(case, lease)
    run = await _run(
        db, case.agent, status="running", user_id=case.user.id, conversation_id=case.conversation.id
    )
    await db.commit()

    @asynccontextmanager
    async def session():
        yield db
        await db.commit()

    for module in (agent_adapter, drivers, project_port):
        monkeypatch.setattr(module, "get_db_context", session)
    calls = []

    class Executor(Workspace):
        async def run(self, command, *, shell=False, env=None, timeout=None, cwd=None):
            calls.append((command, env))
            assert env["PROJECT_DIR"] == lease.path
            assert env["OTHER"] == "preserved"
            assert (
                await rpc(
                    case, FsCreate(op="create", path=f"{lease.id}/from-command", exclusive=True)
                )
            ).ok
            assert (
                await rpc(
                    case,
                    FsWrite(
                        op="write",
                        path=f"{lease.id}/from-command",
                        offset=0,
                        data=base64.b64encode(b"command output").decode(),
                    ),
                )
            ).ok
            return CommandResult(exit_code=0, stdout="written", stderr="")

    adapter = agent_adapter.AgentEnvironment(
        case.ctx,
        conversation_id=case.conversation.id,
        agent_id=case.agent.id,
        version_id=case.agent.current_version_id,
        run_id=run.id,
        target="agent",
        kind="desktop",
    )
    selector = project_port.RunProjectWorkspace(
        Executor(document_workspace()),
        case.ctx,
        audience=RunAudience(user_id=case.user.id, shared_transcript=True),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
        conversation_project_id=case.project.id,
        original_scope="conversation",
        agent_execution_available=True,
        run_id=run.id,
        conversation_id=case.conversation.id,
        filesystem_binding_id=case.credential.binding_id,
    )
    selector.restore(case.project.id, case.project.workspace_generation, "agent")
    selector.environment_project_directory = adapter.project_directory
    selector.finish_environment_project_directory = adapter.finish
    assert adapter.environment_id is None and calls == []
    assert await selector.working_dir()
    assert adapter.environment_id is None and calls == []
    try:
        result = await selector.run(
            "create project output", env={"PROJECT_DIR": "untrusted", "OTHER": "preserved"}
        )
        assert result.exit_code == 0 and len(calls) == 1
        assert adapter.environment_id == case.row.id
        assert selector._project_mount._lease is None
    finally:
        await selector.close_agent(keep_spills=False)
    run.status = "completed"
    await db.commit()
    await db.refresh(case.row)
    assert case.row.state == "ready"
    assert (
        await SandboxWorkspaceService(db).project_bytes(case.ctx, case.project, path="from-command")
        == b"command output"
    )
    assert (
        await rpc(case, FsRead(op="read", path=f"{lease.id}/from-command", offset=0, count=32))
    ).ok
    assert await db.scalar(select(func.count()).select_from(AgentRun)) == 1


@pytest.mark.parametrize("selection", ["project", "generation"])
async def test_directory_selection_change_refuses_without_reassigning_gui_path(
    db, monkeypatch, selection
):
    case = await prepared(db, monkeypatch)
    lease = await admit(case)
    await ready(case, lease)
    with pytest.raises(AuthorizationError, match="different Project mount"):
        await directory(
            db,
            ctx=case.ctx,
            environment_id=case.row.id,
            binding_id=case.credential.binding_id,
            project_id=uuid4() if selection == "project" else case.project.id,
            generation=uuid4() if selection == "generation" else case.project.workspace_generation,
        )
    assert (await rpc(case, FsList(op="list", path=str(lease.id)))).ok
    stored = await db.get(ProjectFilesystemLease, lease.id)
    assert (
        stored.project_id == case.project.id
        and stored.workspace_generation == case.project.workspace_generation
    )


async def test_cross_binding_same_tenant_token_cannot_read_another_environment_path(
    db, monkeypatch
):
    case = await prepared(db, monkeypatch)
    lease = await admit(case)
    await ready(case, lease)
    unrelated = await case.service.credential(
        organization_id=case.org.id,
        connection_id=case.connection.id,
        session_name="unrelated-private-session",
        workspace_id=None,
        conversation_id=case.conversation.id,
    )
    result = await ProjectFilesystemGateway(db).perform(
        unrelated.binding_id, unrelated.token, FsList(op="list", path=str(lease.id))
    )
    assert not result.ok
    assert (await rpc(case, FsList(op="list", path=str(lease.id)))).ok


async def test_current_project_use_grant_is_required_after_owner_role_is_removed(db, monkeypatch):
    from app.db.models.resource_grant import ResourceGrant

    case = await prepared(db, monkeypatch)
    lease = await admit(case)
    await ready(case, lease)
    other = await _user(db)
    db.add(OrganizationMember(organization_id=case.org.id, user_id=other.id, role="owner"))
    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == case.org.id,
            OrganizationMember.user_id == case.user.id,
        )
    )
    member.role = "member"
    case.project.owner_user_id = other.id
    grant = ResourceGrant(
        organization_id=case.org.id,
        resource_type="project",
        resource_id=case.project.id,
        subject_user_id=case.user.id,
        level="use",
        created_by_user_id=other.id,
    )
    db.add(grant)
    await db.commit()
    assert (await rpc(case, FsList(op="list", path=str(lease.id)))).ok
    await db.delete(grant)
    await db.commit()
    # Losing Project use also removes access to this shared conversation.
    with pytest.raises(NotFoundError, match="Conversation not found"):
        await ProjectFilesystemGateway(db).perform(
            case.credential.binding_id, case.credential.token, FsList(op="list", path=str(lease.id))
        )


async def test_cross_tenant_binding_is_refused_before_attempting_resource_unseal(db, monkeypatch):
    case = await prepared(db, monkeypatch)
    other = await _org(db, owner=case.user)
    connection = SandboxConnection(
        organization_id=other.id, name="Other host", kind="docker", is_active=True
    )
    db.add(connection)
    await db.flush()
    foreign = await ProjectFilesystemBindingService(db).credential(
        organization_id=other.id,
        connection_id=connection.id,
        session_name="other-tenant-private-session",
        workspace_id=None,
        conversation_id=None,
    )
    with pytest.raises(AuthorizationError):
        await case.service.issue_environment_lease(
            binding_id=foreign.binding_id,
            payload=case.payload,
            attempt=1,
            project_id=case.project.id,
            generation=case.project.workspace_generation,
        )

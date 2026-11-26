"""A sandbox credential identifies one workspace; only a live run grants Project access."""

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.agents.audience import RunAudience
from app.core.exceptions import AlreadyExistsError, AuthenticationError, AuthorizationError
from app.core.permissions import AuthContext
from app.core.vault import VaultScope, seal, unseal
from app.db.models.agent_run import AgentRun
from app.db.models.project_filesystem import ProjectFilesystemBinding, ProjectFilesystemLease
from app.db.models.sandbox_connection import SandboxConnection
from app.schemas.project_filesystem_authority import (
    ProjectFilesystemAuthority,
    ProjectFilesystemLeaseRead,
)
from app.services import project_filesystem_bindings as module
from app.services.project_filesystem_bindings import ProjectFilesystemBindingService

pytestmark = [pytest.mark.anyio, pytest.mark.security]
TOKEN = "synthetic-workspace-binding-token"


@dataclass
class MountRows:
    actor: AuthContext
    authority: ProjectFilesystemAuthority
    binding: ProjectFilesystemBinding
    connection: SandboxConnection
    run: AgentRun
    lease: ProjectFilesystemLease


def mount_rows() -> MountRows:
    now = datetime.now(UTC)
    actor = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    conversation_id, project_id = uuid4(), uuid4()
    authority = ProjectFilesystemAuthority(
        actor=actor,
        audience=RunAudience(user_id=actor.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
        conversation_project_id=None,
        conversation_id=conversation_id,
    )
    envelope = seal(TOKEN, scope=VaultScope.organization(actor.organization_id))
    connection = SandboxConnection(
        id=uuid4(), organization_id=actor.organization_id, is_active=True
    )
    binding = ProjectFilesystemBinding(
        id=uuid4(),
        organization_id=actor.organization_id,
        connection_id=connection.id,
        workspace_id=uuid4(),
        conversation_id=conversation_id,
        session_name="private-session",
        token_digest=hashlib.sha256(TOKEN.encode()).hexdigest(),
        ciphertext=envelope.ciphertext,
        secret_key_version=envelope.key_version,
        revoked_at=None,
        created_at=now,
    )
    run = AgentRun(
        id=uuid4(),
        agent_id=uuid4(),
        organization_id=actor.organization_id,
        user_id=actor.user_id,
        conversation_id=conversation_id,
        status="running",
    )
    lease = ProjectFilesystemLease(
        id=uuid4(),
        organization_id=actor.organization_id,
        binding_id=binding.id,
        project_id=project_id,
        workspace_generation=uuid4(),
        run_id=run.id,
        actor_id=actor.user_id,
        authority_json=authority.model_dump_json(),
        expires_at=now + timedelta(seconds=90),
        revoked_at=None,
        created_at=now,
    )
    return MountRows(actor, authority, binding, connection, run, lease)


@dataclass
class BindingFixture:
    rows: MountRows
    service: ProjectFilesystemBindingService
    lookup: AsyncMock
    session: AsyncMock
    insert: AsyncMock
    live: AsyncMock
    create: AsyncMock
    run_lookup: AsyncMock
    connection_lookup: AsyncMock


@pytest.fixture
def binding(monkeypatch: pytest.MonkeyPatch) -> BindingFixture:
    rows = mount_rows()
    lookup, session = AsyncMock(return_value=rows.binding), AsyncMock(return_value=rows.binding)
    insert, live = AsyncMock(), AsyncMock(return_value=[])

    async def created(_db: object, *, lease: ProjectFilesystemLease) -> ProjectFilesystemLease:
        return lease

    create = AsyncMock(side_effect=created)
    run_lookup = AsyncMock(return_value=rows.run)
    connection_lookup = AsyncMock(return_value=rows.connection)
    for name, mock in {
        "binding_by_id": lookup,
        "binding_for_session": session,
        "insert_binding": insert,
        "live_leases": live,
        "create_lease": create,
    }.items():
        monkeypatch.setattr(module.binding_repo, name, mock)
    monkeypatch.setattr(module.run_repo, "get_run", run_lookup)
    monkeypatch.setattr(module.connection_repo, "get", connection_lookup)
    return BindingFixture(
        rows,
        ProjectFilesystemBindingService(AsyncMock()),
        lookup,
        session,
        insert,
        live,
        create,
        run_lookup,
        connection_lookup,
    )


async def test_existing_credential_is_reused_without_exposing_plaintext_in_repr(
    binding: BindingFixture,
) -> None:
    row = binding.rows.binding
    credential = await binding.service.credential(
        organization_id=row.organization_id,
        connection_id=row.connection_id,
        session_name=row.session_name,
        workspace_id=row.workspace_id,
        conversation_id=row.conversation_id,
    )
    assert credential.binding_id == row.id and credential.token.get_secret_value() == TOKEN
    assert TOKEN not in repr(credential) and TOKEN not in repr(row)
    binding.insert.assert_not_awaited()
    proof = await binding.service.proof(row.id, SecretStr(TOKEN))
    assert proof.model_dump() == {
        "binding_id": row.id,
        "session_name": "private-session",
        "tenant": str(row.organization_id),
        "mount_path": "/project",
    }
    assert TOKEN not in proof.model_dump_json()


async def test_racing_insert_returns_the_winning_encrypted_session_token(
    binding: BindingFixture,
) -> None:
    row = binding.rows.binding
    binding.session.side_effect = [None, row]
    credential = await binding.service.credential(
        organization_id=row.organization_id,
        connection_id=row.connection_id,
        session_name=row.session_name,
        workspace_id=row.workspace_id,
        conversation_id=row.conversation_id,
    )
    inserted: ProjectFilesystemBinding = binding.insert.await_args.kwargs["row"]
    candidate = unseal(
        inserted.ciphertext,
        scope=VaultScope.organization(row.organization_id),
        key_version=inserted.secret_key_version,
    )
    assert candidate != TOKEN and candidate not in inserted.ciphertext
    assert inserted.token_digest == hashlib.sha256(candidate.encode()).hexdigest()
    assert credential.token.get_secret_value() == TOKEN
    binding.session.side_effect = [None, None]
    with pytest.raises(RuntimeError, match="session identity"):
        await binding.service.credential(
            organization_id=row.organization_id,
            connection_id=row.connection_id,
            session_name=row.session_name,
            workspace_id=row.workspace_id,
            conversation_id=row.conversation_id,
        )


@pytest.mark.parametrize("change", ["revoked", "workspace", "conversation"])
async def test_reused_binding_cannot_be_revived_or_retargeted(
    binding: BindingFixture, change: str
) -> None:
    row = binding.rows.binding
    if change == "revoked":
        row.revoked_at = datetime.now(UTC)
    elif change == "workspace":
        row.workspace_id = uuid4()
    else:
        row.conversation_id = uuid4()
    with pytest.raises(AuthorizationError, match="identity changed"):
        await binding.service.credential(
            organization_id=row.organization_id,
            connection_id=row.connection_id,
            session_name=row.session_name,
            workspace_id=uuid4(),
            conversation_id=uuid4(),
        )
    binding.insert.assert_not_awaited()


@pytest.mark.parametrize(
    "failure", ["missing", "no_token", "wrong_token", "revoked", "connection_missing", "inactive"]
)
async def test_credentials_and_current_connection_are_checked_before_any_project_disclosure(
    binding: BindingFixture, failure: str
) -> None:
    row = binding.rows.binding
    token: SecretStr | None = SecretStr(TOKEN)
    if failure == "missing":
        binding.lookup.return_value = None
    elif failure == "no_token":
        token = None
    elif failure == "wrong_token":
        token = SecretStr("another-workspace-token")
    elif failure == "revoked":
        row.revoked_at = datetime.now(UTC)
    elif failure == "connection_missing":
        binding.connection_lookup.return_value = None
    else:
        binding.rows.connection.is_active = False
    with pytest.raises(AuthenticationError):
        await binding.service.authenticate(row.id, token)
    if failure in {"missing", "no_token", "wrong_token", "revoked"}:
        binding.connection_lookup.assert_not_awaited()


async def issue(
    binding: BindingFixture, authority: ProjectFilesystemAuthority | None = None
) -> ProjectFilesystemLeaseRead:
    rows = binding.rows
    return await binding.service.issue_lease(
        binding_id=rows.binding.id,
        project_id=rows.lease.project_id,
        generation=rows.lease.workspace_generation,
        run_id=rows.run.id,
        authority=authority or rows.authority,
    )


async def test_new_lease_has_an_immutable_run_path_and_a_bounded_expiry(
    binding: BindingFixture,
) -> None:
    before = datetime.now(UTC)
    view = await issue(binding)
    lease: ProjectFilesystemLease = binding.create.await_args.kwargs["lease"]
    assert view.path == f"/project/{lease.id}"
    assert (
        before + timedelta(seconds=89)
        < lease.expires_at
        < datetime.now(UTC) + timedelta(seconds=91)
    )
    assert (
        ProjectFilesystemAuthority.model_validate_json(lease.authority_json)
        == binding.rows.authority
    )
    assert TOKEN not in lease.authority_json and TOKEN not in repr(lease)
    binding.live.return_value = [lease]
    again = await issue(binding)
    assert again.id == view.id and binding.create.await_count == 1
    lease.workspace_generation = uuid4()
    with pytest.raises(AlreadyExistsError):
        await issue(binding)


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "revoked",
        "tenant",
        "conversation",
        "anonymous",
        "publisher",
        "room",
        "scope",
        "run_missing",
        "run_stopped",
        "run_owner",
        "run_conversation",
    ],
)
async def test_a_workspace_binding_never_grants_a_lease_without_a_matching_private_run(
    binding: BindingFixture, failure: str
) -> None:
    rows = binding.rows
    authority = rows.authority
    if failure == "missing":
        binding.lookup.return_value = None
    elif failure == "revoked":
        rows.binding.revoked_at = datetime.now(UTC)
    elif failure == "tenant":
        rows.binding.organization_id = uuid4()
    elif failure == "conversation":
        rows.binding.conversation_id = uuid4()
    elif failure == "anonymous":
        authority = authority.model_copy(update={"actor": replace(rows.actor, user_id=None)})
    elif failure == "publisher":
        authority = authority.model_copy(
            update={"actor": replace(rows.actor, subject_is_publisher_fallback=True)}
        )
    elif failure == "room":
        authority = authority.model_copy(
            update={
                "audience": RunAudience(user_id=rows.actor.user_id, room_key="room:slack:shared")
            }
        )
    elif failure == "scope":
        authority = authority.model_copy(update={"granted_scopes": frozenset()})
    elif failure == "run_missing":
        binding.run_lookup.return_value = None
    elif failure == "run_stopped":
        rows.run.status = "awaiting_approval"
    elif failure == "run_owner":
        rows.run.user_id = uuid4()
    else:
        rows.run.conversation_id = uuid4()
    with pytest.raises(AuthorizationError, match="cannot mount"):
        await issue(binding, authority)
    binding.create.assert_not_awaited()


async def test_expired_lease_cannot_be_renewed_and_revoke_is_run_scoped(
    binding: BindingFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    renew = AsyncMock(return_value=False)
    revoke = AsyncMock()
    monkeypatch.setattr(module.binding_repo, "renew_lease", renew)
    monkeypatch.setattr(module.binding_repo, "revoke_lease", revoke)
    kwargs = {
        "lease_id": uuid4(),
        "run_id": binding.rows.run.id,
        "organization_id": binding.rows.actor.organization_id,
    }
    with pytest.raises(AuthorizationError, match="expired"):
        await binding.service.renew(**kwargs)
    renew.return_value = True
    await binding.service.renew(**kwargs)
    assert renew.await_args.kwargs["expires_at"] > renew.await_args.kwargs["now"]
    await binding.service.revoke(**kwargs)
    assert {key: revoke.await_args.kwargs[key] for key in kwargs} == kwargs

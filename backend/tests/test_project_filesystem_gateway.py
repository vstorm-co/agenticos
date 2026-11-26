"""A mounted path must lose access when its live run or current authority changes."""

import errno
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.agents.audience import RunAudience
from app.core.exceptions import AuthorizationError, ConcurrentChangeError, NotFoundError
from app.db.models.conversation import Conversation
from app.db.models.project import Project
from app.schemas.project_filesystem import (
    FsEntry,
    FsFailure,
    FsList,
    FsRead,
    FsRename,
    FsStat,
    FsSuccess,
    FsWrite,
)
from app.services import project_filesystem_bindings as bindings_module
from app.services import project_filesystem_gateway as module
from app.services import run_project_workspace as authority_module
from app.services.project_filesystem_gateway import ProjectFilesystemGateway
from tests.test_project_filesystem_bindings import TOKEN, MountRows, mount_rows

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@dataclass
class GatewayFixture:
    rows: MountRows
    gateway: ProjectFilesystemGateway
    project: Project
    conversation: Conversation
    member: AsyncMock
    guard: AsyncMock
    run: AsyncMock
    leases: AsyncMock
    active: AsyncMock
    shared: AsyncMock
    conversations: AsyncMock
    routine: AsyncMock
    perform: AsyncMock


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> GatewayFixture:
    rows = mount_rows()
    project = Project(
        id=rows.lease.project_id,
        organization_id=rows.actor.organization_id,
        workspace_generation=rows.lease.workspace_generation,
    )
    conversation = Conversation(
        id=rows.binding.conversation_id,
        organization_id=rows.actor.organization_id,
        user_id=rows.actor.user_id,
        project_id=None,
    )
    member = AsyncMock(return_value=SimpleNamespace(role="member", is_app_admin=False))
    guard, run = AsyncMock(return_value=project), AsyncMock(return_value=rows.run)
    leases, active = AsyncMock(return_value=rows.lease), AsyncMock(return_value=[rows.lease])
    shared, conversations = AsyncMock(return_value=False), AsyncMock(return_value=conversation)
    routine = AsyncMock(return_value=None)
    perform = AsyncMock(return_value=FsSuccess(data="YQ==", eof=True))
    monkeypatch.setattr(module.binding_repo, "binding_by_id", AsyncMock(return_value=rows.binding))
    monkeypatch.setattr(
        bindings_module.connection_repo, "get", AsyncMock(return_value=rows.connection)
    )
    monkeypatch.setattr(module.binding_repo, "lease_for_binding", leases)
    monkeypatch.setattr(module.binding_repo, "live_leases", active)
    monkeypatch.setattr(module.run_repo, "get_run", run)
    monkeypatch.setattr(module.conversation_repo, "get_conversation_by_id", conversations)
    monkeypatch.setattr(module.share_repo, "has_edit_share", shared)
    monkeypatch.setattr(authority_module, "member_context", member)
    monkeypatch.setattr(authority_module, "project_for_workspace", guard)
    monkeypatch.setattr(module.RoutineAuthority, "capture", routine)
    monkeypatch.setattr(module.ProjectFilesystemService, "perform", perform)
    return GatewayFixture(
        rows,
        ProjectFilesystemGateway(AsyncMock()),
        project,
        conversation,
        member,
        guard,
        run,
        leases,
        active,
        shared,
        conversations,
        routine,
        perform,
    )


async def read(gateway: GatewayFixture, *, path: str | None = None) -> FsSuccess | FsFailure:
    return await gateway.gateway.perform(
        gateway.rows.binding.id,
        SecretStr(TOKEN),
        FsRead(op="read", path=path or f"{gateway.rows.lease.id}/report.txt", offset=0, count=1),
    )


async def test_each_read_rechecks_current_membership_before_dispatch(
    gateway: GatewayFixture,
) -> None:
    response = await read(gateway)
    assert isinstance(response, FsSuccess) and response.data == "YQ=="
    dispatched = gateway.perform.await_args
    assert dispatched.args[0].role == "member" and not dispatched.args[0].is_app_admin
    assert dispatched.args[1:3] == (gateway.project.id, gateway.project.workspace_generation)
    assert dispatched.args[3].path == "report.txt" and dispatched.kwargs == {"writable": True}
    gateway.member.return_value = None
    with pytest.raises(AuthorizationError, match="membership"):
        await read(gateway)
    assert gateway.perform.await_count == 1 and gateway.member.await_count == 2


async def test_workspace_token_does_not_widen_read_only_scope(gateway: GatewayFixture) -> None:
    authority = gateway.rows.authority.model_copy(
        update={"granted_scopes": frozenset({"projects:read"})}
    )
    gateway.rows.lease.authority_json = authority.model_dump_json()
    await gateway.gateway.perform(
        gateway.rows.binding.id,
        SecretStr(TOKEN),
        FsWrite(op="write", path=f"{gateway.rows.lease.id}/file", data="eA=="),
    )
    assert gateway.perform.await_args.kwargs["writable"] is False


@pytest.mark.parametrize(
    "path",
    [
        "not-a-uuid/file",
        "../file",
        "/etc/passwd",
        "dead\x00path",
        "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF/file",
    ],
)
async def test_paths_cannot_escape_the_lease_namespace(gateway: GatewayFixture, path: str) -> None:
    response = await read(gateway, path=path)
    assert isinstance(response, FsFailure) and response.errno == errno.ENOENT
    gateway.leases.assert_not_awaited()
    gateway.perform.assert_not_awaited()


async def test_unknown_lease_is_stale_without_project_disclosure(gateway: GatewayFixture) -> None:
    gateway.leases.return_value = None
    response = await read(gateway)
    assert isinstance(response, FsFailure) and response.errno == errno.ESTALE
    gateway.guard.assert_not_awaited()
    gateway.perform.assert_not_awaited()


@pytest.mark.parametrize(
    "failure",
    [
        "expired",
        "revoked",
        "tenant",
        "actor",
        "run_missing",
        "run_stopped",
        "run_actor",
        "run_conversation",
        "audience",
        "scope",
        "generation",
        "project_revoked",
    ],
)
async def test_existing_paths_fail_closed_when_authority_changes(
    gateway: GatewayFixture, failure: str
) -> None:
    rows = gateway.rows
    authority = rows.authority
    exception = AuthorizationError
    if failure == "expired":
        rows.lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif failure == "revoked":
        rows.lease.revoked_at = datetime.now(UTC)
    elif failure == "tenant":
        authority = authority.model_copy(
            update={"actor": replace(rows.actor, organization_id=uuid4())}
        )
    elif failure == "actor":
        authority = authority.model_copy(update={"actor": replace(rows.actor, user_id=uuid4())})
    elif failure == "run_missing":
        gateway.run.return_value = None
    elif failure == "run_stopped":
        rows.run.status = "completed"
    elif failure == "run_actor":
        rows.run.user_id = uuid4()
    elif failure == "run_conversation":
        rows.run.conversation_id = uuid4()
    elif failure == "audience":
        authority = authority.model_copy(
            update={
                "audience": RunAudience(
                    user_id=rows.actor.user_id, room_key="room:mattermost:shared"
                )
            }
        )
    elif failure == "scope":
        authority = authority.model_copy(update={"granted_scopes": frozenset()})
    elif failure == "generation":
        gateway.project.workspace_generation = uuid4()
        exception = ConcurrentChangeError
    else:
        gateway.guard.side_effect = NotFoundError(message="Project not found")
        exception = NotFoundError
    rows.lease.authority_json = authority.model_dump_json()
    with pytest.raises(exception):
        await read(gateway)
    gateway.perform.assert_not_awaited()


@pytest.mark.parametrize("failure", ["admission", "missing", "tenant", "moved", "owner", "shared"])
async def test_live_conversation_changes_revoke_private_project_access(
    gateway: GatewayFixture, failure: str
) -> None:
    if failure == "admission":
        gateway.rows.lease.authority_json = gateway.rows.authority.model_copy(
            update={"conversation_id": uuid4()}
        ).model_dump_json()
    elif failure == "missing":
        gateway.conversations.return_value = None
    elif failure == "tenant":
        gateway.conversation.organization_id = uuid4()
    elif failure == "moved":
        gateway.conversation.project_id = uuid4()
    elif failure == "owner":
        gateway.conversation.user_id = uuid4()
    else:
        gateway.shared.return_value = True
    with pytest.raises(AuthorizationError):
        await read(gateway)
    gateway.perform.assert_not_awaited()


async def test_nonconversation_and_same_project_admissions_remain_bounded(
    gateway: GatewayFixture,
) -> None:
    rows = gateway.rows
    rows.binding.conversation_id = None
    rows.run.conversation_id = None
    rows.lease.authority_json = rows.authority.model_copy(
        update={"conversation_id": None}
    ).model_dump_json()
    await read(gateway)
    gateway.conversations.assert_not_awaited()
    rows.binding.conversation_id = gateway.conversation.id
    rows.run.conversation_id = gateway.conversation.id
    gateway.conversation.project_id = gateway.project.id
    rows.lease.authority_json = rows.authority.model_copy(
        update={
            "conversation_project_id": gateway.project.id,
            "audience": RunAudience(user_id=rows.actor.user_id, shared_transcript=True),
        }
    ).model_dump_json()
    await read(gateway)
    gateway.shared.assert_not_awaited()


async def test_routine_constraints_are_checked_before_filesystem_dispatch(
    gateway: GatewayFixture,
) -> None:
    gateway.routine.return_value = SimpleNamespace(
        require_project=MagicMock(side_effect=AuthorizationError(message="Routine source changed"))
    )
    with pytest.raises(AuthorizationError, match="Routine source changed"):
        await read(gateway)
    gateway.perform.assert_not_awaited()


async def test_root_shows_only_authorized_directories_and_refuses_mutation(
    gateway: GatewayFixture,
) -> None:
    binding = gateway.rows.binding
    for path in ("", ".", "/"):
        root = await gateway.gateway.perform(
            binding.id, SecretStr(TOKEN), FsStat(op="stat", path=path)
        )
        assert (
            isinstance(root, FsSuccess)
            and root.entry is not None
            and root.entry.path == "."
            and root.entry.is_dir
        )
    listed = await gateway.gateway.perform(binding.id, SecretStr(TOKEN), FsList(op="list"))
    assert (
        isinstance(listed, FsSuccess)
        and listed.entries is not None
        and [e.path for e in listed.entries] == [str(gateway.rows.lease.id)]
    )
    gateway.member.return_value = None
    listed = await gateway.gateway.perform(binding.id, SecretStr(TOKEN), FsList(op="list"))
    assert isinstance(listed, FsSuccess) and listed.entries == []
    refused = await gateway.gateway.perform(
        binding.id, SecretStr(TOKEN), FsWrite(op="write", path=".", data="")
    )
    assert isinstance(refused, FsFailure) and refused.errno == errno.EROFS
    gateway.perform.assert_not_awaited()


async def test_rename_confines_both_paths_to_the_same_lease_and_prefixes_results(
    gateway: GatewayFixture,
) -> None:
    rows = gateway.rows
    for destination in (f"{uuid4()}/other", "../escape"):
        response = await gateway.gateway.perform(
            rows.binding.id,
            SecretStr(TOKEN),
            FsRename(op="rename", path=f"{rows.lease.id}/source", destination=destination),
        )
        assert isinstance(response, FsFailure) and response.errno == errno.EXDEV
    gateway.perform.assert_not_awaited()
    gateway.perform.return_value = FsSuccess(
        entry=FsEntry(path="target", is_dir=False, size=1, mode=0o600)
    )
    response = await gateway.gateway.perform(
        rows.binding.id,
        SecretStr(TOKEN),
        FsRename(
            op="rename", path=f"{rows.lease.id}/source", destination=f"{rows.lease.id}/target"
        ),
    )
    assert (
        isinstance(response, FsSuccess)
        and response.entry is not None
        and response.entry.path == f"{rows.lease.id}/target"
    )
    assert gateway.perform.await_args.args[3].destination == "target"
    gateway.perform.return_value = FsSuccess(
        entries=[
            FsEntry(path=".", is_dir=True, size=0, mode=0o755),
            FsEntry(path="file", is_dir=False, size=0, mode=0o644),
        ]
    )
    response = await gateway.gateway.perform(
        rows.binding.id, SecretStr(TOKEN), FsList(op="list", path=str(rows.lease.id))
    )
    assert (
        isinstance(response, FsSuccess)
        and response.entries is not None
        and [e.path for e in response.entries] == [str(rows.lease.id), f"{rows.lease.id}/file"]
    )
    gateway.perform.return_value = FsFailure(errno=errno.EIO, message="Provider failed")
    assert isinstance(await read(gateway), FsFailure)

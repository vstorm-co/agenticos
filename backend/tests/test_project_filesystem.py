"""Filesystem RPCs mutate the authoritative tree, not a run-local snapshot."""

import base64
import errno
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError
from pydantic_ai.workspaces import LocalWorkspaceBackend, Workspace
from pydantic_ai_backends.workspaces import StateWorkspaceBackend

from app.agents.capabilities.sandbox._capped import CappedStateBackend
from app.core.exceptions import AuthorizationError, ConcurrentChangeError, ExternalServiceError
from app.core.permissions import AuthContext
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.project import Project
from app.schemas.project_filesystem import CHUNK_BYTES, FsRequest, FsStoredAttributes
from app.services import project_filesystem as module
from app.services.project_filesystem import ProjectFilesystemService
from app.services.sandbox_workspace import OpenWorkspace, WorkspaceFlushFailure

pytestmark = pytest.mark.anyio
_REQUEST = TypeAdapter(FsRequest)
_ATTRS = TypeAdapter(dict[str, FsStoredAttributes])


@pytest.fixture(params=["state", "service"])
def fs(request, monkeypatch, tmp_path):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    project = Project(id=uuid4(), organization_id=ctx.organization_id, workspace_generation=uuid4())
    guard = AsyncMock(return_value=project)
    monkeypatch.setattr(module, "project_for_workspace", guard)
    files, directories, attributes = {}, set(), {}
    row = AgentWorkspace(id=uuid4())
    service = ProjectFilesystemService(AsyncMock())
    opened = []

    async def open_project(*args):
        if request.param == "state":
            document = CappedStateBackend(dict(files), directories, max_bytes=1024**2)
            # Supply a fixed state ref: construction without it allocates a fresh document.
            from pydantic_ai.messages import WorkspaceRef

            workspace = Workspace(
                StateWorkspaceBackend(
                    {"project": document}, ref=WorkspaceRef(provider="state", id="project")
                )
            )
        else:
            document = None
            workspace = Workspace(LocalWorkspaceBackend(tmp_path))
        handle = OpenWorkspace(
            workspace=workspace,
            kind=request.param,
            scope="project",
            scope_key="project",
            row_id=row.id,
            document=document,
        )
        opened.append(handle)
        return handle

    async def close(handle):
        if handle.document is not None:
            files.clear()
            files.update(handle.document.files)
            directories.clear()
            directories.update(handle.document.directories)
        return

    async def metadata(*args, **kwargs):
        return row, _ATTRS.validate_python(attributes)

    async def save_metadata(db, row, values):
        attributes.clear()
        attributes.update(_ATTRS.dump_python(values, mode="json"))

    monkeypatch.setattr(service.workspaces, "open_project", AsyncMock(side_effect=open_project))
    monkeypatch.setattr(service.workspaces, "close", AsyncMock(side_effect=close))
    monkeypatch.setattr(module.repo, "metadata", metadata)
    monkeypatch.setattr(module.repo, "save_metadata", save_metadata)
    monkeypatch.setattr(module.repo, "save_file_timestamp", AsyncMock())

    async def call(op, path=".", writable=True, **fields):
        return await service.perform(
            ctx,
            project.id,
            project.workspace_generation,
            _REQUEST.validate_python({"op": op, "path": path, **fields}),
            writable=writable,
        )

    return SimpleNamespace(
        call=call,
        service=service,
        project=project,
        ctx=ctx,
        guard=guard,
        files=files,
        directories=directories,
        attributes=attributes,
        root=tmp_path,
        kind=request.param,
        opened=opened,
    )


def b64(data):
    return base64.b64encode(data).decode()


async def test_binary_write_offsets_truncate_and_read_are_visible_to_next_request(fs):
    assert (await fs.call("create", "file.bin", mode=0o600)).entry.mode == 0o600
    assert (await fs.call("write", "file.bin", offset=2, data=b64(b"\xff\x00"))).written == 2
    read = await fs.call("read", "file.bin", offset=1, count=2)
    assert base64.b64decode(read.data) == b"\x00\xff" and not read.eof
    await fs.call("truncate", "file.bin", size=6)
    read = await fs.call("read", "file.bin", offset=0, count=10)
    assert base64.b64decode(read.data) == b"\x00\x00\xff\x00\x00\x00" and read.eof
    await fs.call("truncate", "file.bin", size=1)
    assert (await fs.call("stat", "file.bin")).entry.size == 1
    await fs.call("write", "file.bin", offset=0, data="")
    assert (await fs.call("stat", "file.bin")).entry.size == 1
    assert fs.service.workspaces.close.await_count == len(fs.opened)


async def test_atomic_rename_replaces_files_and_preserves_empty_directories_modes_and_bytes(fs):
    await fs.call("mkdir", "old", mode=0o700)
    await fs.call("mkdir", "old/empty", mode=0o701)
    await fs.call("create", "old/a", mode=0o640)
    await fs.call("write", "old/a", data=b64(b"\x00\xff"))
    await fs.call("rename", "old", destination="new")
    assert (await fs.call("stat", "new/empty")).entry.mode == 0o701
    assert (await fs.call("stat", "new/a")).entry.mode == 0o640
    assert (await fs.call("stat", "old")).errno == errno.ENOENT
    await fs.call("create", "replace")
    await fs.call("rename", "new/a", destination="replace")
    assert base64.b64decode((await fs.call("read", "replace")).data) == b"\x00\xff"
    assert (await fs.call("rename", "replace", destination="replace")).ok
    await fs.call("remove", "new/empty", directory=True)
    await fs.call("remove", "new", directory=True)
    assert [e.path for e in (await fs.call("list")).entries] == ["replace"]


async def test_setattr_uses_real_or_persisted_metadata(fs):
    await fs.call("create", "file")
    stamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    result = await fs.call("setattr", "file", mode=0o711, modified_at=stamp.isoformat())
    assert result.entry.mode == 0o711 and result.entry.modified_at == stamp
    assert (await fs.call("stat", "file")).entry.modified_at == stamp
    assert (await fs.call("setattr", "file")).ok
    await fs.call("create", "file", mode=0o777)
    assert (await fs.call("stat", "file")).entry.mode == 0o711


@pytest.mark.security
@pytest.mark.parametrize(
    "path",
    [
        "/absolute",
        "../escape",
        "a/../b",
        "a//b",
        "a/./b",
        "a\\b",
        ".agenticos/private",
        "skills/private",
        "tool_output/private",
        " white ",
    ],
)
async def test_mount_paths_never_escape_or_reach_platform_files(fs, path):
    result = await fs.call("stat", path)
    assert result.errno == errno.EACCES
    fs.service.workspaces.open_project.assert_not_awaited()


@pytest.mark.security
async def test_read_only_generation_and_membership_are_rechecked_before_every_operation(fs):
    assert (await fs.call("create", "file", writable=False)).errno == errno.EROFS
    fs.project.workspace_generation = uuid4()
    with pytest.raises(ConcurrentChangeError):
        await fs.service.perform(
            fs.ctx, fs.project.id, uuid4(), _REQUEST.validate_python({"op": "stat"}), writable=True
        )
    fs.guard.side_effect = AuthorizationError(message="Revoked")
    with pytest.raises(AuthorizationError):
        await fs.call("stat")
    fs.service.workspaces.open_project.assert_not_awaited()


async def test_file_and_directory_failures_are_explicit_without_recursive_removal(fs):
    assert (await fs.call("read", "missing")).errno == errno.ENOENT
    assert (await fs.call("create", "missing/file")).errno == errno.ENOENT
    await fs.call("mkdir", "dir")
    await fs.call("create", "dir/file")
    assert (await fs.call("remove", "dir", directory=True)).errno == errno.ENOTEMPTY
    assert (await fs.call("remove", "dir")).errno == errno.EISDIR
    assert (await fs.call("remove", "dir/file", directory=True)).errno == errno.ENOTDIR
    assert (await fs.call("read", "dir")).errno == errno.EISDIR
    assert (await fs.call("list", "dir/file")).errno == errno.ENOTDIR
    assert (await fs.call("stat", "dir/file/child")).errno == errno.ENOTDIR
    assert (await fs.call("create", "dir/file", exclusive=True)).errno == errno.EEXIST
    assert (await fs.call("mkdir", "dir/file")).errno == errno.EEXIST
    assert (await fs.call("create", "dir/file/child")).errno == errno.ENOTDIR
    assert (await fs.call("rename", "dir", destination="dir/child")).errno == errno.EINVAL
    assert (await fs.call("rename", "dir/file", destination="dir")).errno == errno.EISDIR
    assert (await fs.call("rename", "dir", destination="dir/file")).errno in (
        errno.EINVAL,
        errno.ENOTDIR,
    )
    assert (await fs.call("remove")).errno == errno.EBUSY
    assert (await fs.call("write", "dir/file", data="%%%")).errno == errno.EINVAL
    assert (await fs.call("stat", "dir/file")).ok


async def test_chunk_boundaries_and_sparse_offsets(fs):
    await fs.call("create", "large")
    data = b"x" * CHUNK_BYTES
    assert (
        await fs.call("write", "large", offset=CHUNK_BYTES + 3, data=b64(data))
    ).written == CHUNK_BYTES
    read = await fs.call("read", "large", offset=CHUNK_BYTES + 3, count=CHUNK_BYTES)
    assert base64.b64decode(read.data) == data and read.eof


async def test_native_symlinks_are_refused_without_following_them(fs, tmp_path):
    if fs.kind != "service":
        pytest.skip("Native filesystem symlinks")
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (outside / "secret").write_bytes(b"private")
    (fs.root / "link").symlink_to(outside, target_is_directory=True)
    assert (await fs.call("read", "link/secret")).errno in (errno.ELOOP, errno.ENOTDIR)
    assert (await fs.call("stat", "link")).errno == errno.ELOOP
    assert (await fs.call("create", "link/other")).errno in (errno.ELOOP, errno.ENOTDIR)
    assert not (outside / "other").exists()


async def test_flush_failure_is_not_acknowledged_as_a_success(fs):
    fs.service.workspaces.close.return_value = None
    fs.service.workspaces.close.side_effect = None
    fs.service.workspaces.close.return_value = WorkspaceFlushFailure(
        ExternalServiceError(message="Flush failed")
    )
    with pytest.raises(ExternalServiceError, match="Flush failed"):
        await fs.call("create", "file")


def test_request_boundaries_are_explicit():
    for value in (
        {"op": "read", "count": CHUNK_BYTES + 1},
        {"op": "write", "offset": -1, "data": ""},
        {"op": "mkdir", "mode": 0o1000},
        {"op": "setattr", "modified_at": "2026-01-01T00:00:00"},
    ):
        with pytest.raises(ValidationError):
            _REQUEST.validate_python(value)


@pytest.mark.security
async def test_listing_hides_platform_directories_but_keeps_legitimate_nested_names(fs):
    if fs.kind == "state":
        from pydantic_ai_backends import StateBackend

        document = StateBackend()
        document.write_bytes("skills/private", b"private")
        document.write_bytes(".agenticos/private", b"private")
        fs.files.update(document.files)
    else:
        (fs.root / "skills").mkdir()
        (fs.root / "skills" / "private").write_bytes(b"private")
        (fs.root / ".agenticos").mkdir()
    assert (await fs.call("list")).entries == []
    await fs.call("mkdir", "public")
    await fs.call("create", "public/skills")
    assert [e.path for e in (await fs.call("list", "public")).entries] == ["public/skills"]


async def test_storage_limit_and_invalid_decoded_chunk_never_modify_existing_data(fs, monkeypatch):
    await fs.call("create", "file")
    await fs.call("write", "file", data=b64(b"safe"))
    oversized = b64(b"x" * (CHUNK_BYTES + 1))
    assert (await fs.call("write", "file", data=oversized)).errno == errno.EFBIG
    assert (await fs.call("write", "file", offset=2**31 - 1, data=b64(b"x"))).errno == errno.EFBIG
    if fs.kind == "state":
        monkeypatch.setattr(module.settings, "SANDBOX_STATE_MAX_BYTES", 100)
        assert (await fs.call("truncate", "file", size=101)).errno == errno.ENOSPC
    assert base64.b64decode((await fs.call("read", "file")).data) == b"safe"


async def test_rename_directory_collision_is_refused_and_empty_target_is_replaced(fs):
    await fs.call("mkdir", "source")
    await fs.call("mkdir", "target")
    await fs.call("create", "target/file")
    assert (await fs.call("rename", "source", destination="target")).errno == errno.ENOTEMPTY
    await fs.call("remove", "target/file")
    assert (await fs.call("rename", "source", destination="target")).ok
    assert (await fs.call("stat", "source")).errno == errno.ENOENT


async def test_state_requires_an_authoritative_row_and_native_requires_an_executor(fs):
    original = fs.service.workspaces.open_project.side_effect

    async def missing_row(*args):
        opened = await original(*args)
        opened.row_id = None
        return opened

    if fs.kind == "state":
        fs.service.workspaces.open_project.side_effect = missing_row
        with pytest.raises(RuntimeError, match="document and row"):
            await fs.call("stat")
    else:
        from pydantic_ai.workspaces import Workspace
        from pydantic_ai_backends.workspaces import StateWorkspaceBackend

        async def no_commands(*args):
            opened = await original(*args)
            opened.workspace = Workspace(StateWorkspaceBackend({}))
            return opened

        fs.service.workspaces.open_project.side_effect = no_commands
        assert (await fs.call("stat")).errno == errno.EOPNOTSUPP


async def test_native_worker_failure_does_not_become_empty_success(fs, monkeypatch):
    if fs.kind != "service":
        pytest.skip("Native executor failure")
    from pydantic_ai.workspaces import CommandResult

    original = fs.service.workspaces.open_project.side_effect

    async def failing(*args):
        opened = await original(*args)
        monkeypatch.setattr(
            opened.workspace,
            "run",
            AsyncMock(return_value=CommandResult(stdout="", stderr="worker failed", exit_code=127)),
        )
        return opened

    fs.service.workspaces.open_project.side_effect = failing
    with pytest.raises(ExternalServiceError, match="worker failed"):
        await fs.call("stat")


async def test_state_rename_size_refusal_preserves_original_tree(fs, monkeypatch):
    await fs.call("create", "short")
    if fs.kind == "state":
        from app.agents.capabilities.sandbox._capped import document_size

        monkeypatch.setattr(
            module.settings, "SANDBOX_STATE_MAX_BYTES", document_size(fs.files, fs.directories) + 1
        )
        assert (
            await fs.call("rename", "short", destination="a-much-longer-filename")
        ).errno == errno.ENOSPC
        assert (await fs.call("stat", "short")).ok
    else:
        assert (await fs.call("rename", "short", destination="a-much-longer-filename")).ok


async def test_regular_file_mtime_tracks_ordinary_writes_after_explicit_setattr(fs):
    if fs.kind != "state":
        pytest.skip("Stored FileData is the state authority")
    await fs.call("create", "binary")
    await fs.call("write", "binary", data=b64(b"\xff\x00"))
    stamp = datetime(2020, 1, 1, tzinfo=UTC)
    before = dict(fs.files["/binary"])
    await fs.call("setattr", "binary", modified_at=stamp.isoformat(), mode=0o700)
    assert fs.files["/binary"]["content"] == before["content"]
    assert fs.files["/binary"]["encoding"] == before["encoding"]
    assert fs.files["/binary"]["created_at"] == before["created_at"]
    from pydantic_ai_backends import StateBackend

    ordinary = StateBackend(dict(fs.files), fs.directories)
    ordinary.write_bytes("binary", b"\x00\xffnew")
    fs.files.clear()
    fs.files.update(ordinary.files)
    current = (await fs.call("stat", "binary")).entry
    assert current.modified_at == datetime.fromisoformat(fs.files["/binary"]["modified_at"])
    assert current.modified_at != stamp and current.mode == 0o700


async def test_exclusive_create_verifier_is_durable_and_never_truncates_a_replay(fs):
    verifier = b64(b"12345678")
    if fs.kind == "service":
        support = await fs.service.exclusive_create_support(
            fs.ctx, fs.project.id, fs.project.workspace_generation, writable=True
        )
        if not support.ok:
            assert support.errno in (errno.ENOTSUP, errno.EOPNOTSUPP)
            assert (await fs.call("create", "file", exclusive=True, verifier=verifier)).errno in (
                errno.ENOTSUP,
                errno.EOPNOTSUPP,
            )
            assert (await fs.call("stat", "file")).errno == errno.ENOENT
            return
    assert (await fs.call("create", "file", exclusive=True, verifier=verifier)).ok
    await fs.call("write", "file", data=b64(b"do not truncate"))
    assert (await fs.call("create", "file", exclusive=True, verifier=verifier)).ok
    assert base64.b64decode((await fs.call("read", "file")).data) == b"do not truncate"
    assert (
        await fs.call("create", "file", exclusive=True, verifier=b64(b"87654321"))
    ).errno == errno.EEXIST
    # A writer using the ordinary storage API can remove/recreate without touching RPC metadata.
    if fs.kind == "state":
        from pydantic_ai_backends import StateBackend

        document = StateBackend(dict(fs.files), fs.directories)
        document.remove("file")
        document.write_bytes("file", b"recreated by another API")
        fs.files.clear()
        fs.files.update(document.files)
    else:
        (fs.root / "file").unlink()
        (fs.root / "file").write_bytes(b"recreated by another API")
    assert (
        await fs.call("create", "file", exclusive=True, verifier=verifier)
    ).errno == errno.EEXIST
    assert base64.b64decode((await fs.call("read", "file")).data) == b"recreated by another API"


async def test_guarded_setattr_bundles_size_mode_and_time_without_mutating_on_mismatch(fs):
    await fs.call("create", "file")
    await fs.call("write", "file", data=b64(b"abcdef"))
    before = (await fs.call("stat", "file")).entry
    stale = datetime(2000, 1, 1, tzinfo=UTC)
    refused = await fs.call(
        "setattr",
        "file",
        size=1,
        mode=0o777,
        modified_at=stale.isoformat(),
        guard_modified_at=stale.isoformat(),
    )
    assert refused.errno == 10002
    assert refused.message == "File attributes changed"
    assert (await fs.call("stat", "file")).entry == before
    accepted = await fs.call(
        "setattr",
        "file",
        size=3,
        mode=0o700,
        modified_at=stale.isoformat(),
        guard_modified_at=before.modified_at.isoformat(),
    )
    assert accepted.ok and accepted.entry.size == 3 and accepted.entry.mode == 0o700
    assert accepted.entry.modified_at == stale
    assert base64.b64decode((await fs.call("read", "file")).data) == b"abc"
    # Same-size setattr must still persist its intentional timestamp.
    accepted = await fs.call("setattr", "file", size=3, modified_at=before.modified_at.isoformat())
    assert accepted.entry.modified_at == before.modified_at
    if fs.kind == "state":
        accepted = await fs.call("setattr", "file", size=2)
        assert accepted.entry.size == 2


async def test_setattr_quota_refusal_preserves_the_original_file_and_mode(fs, monkeypatch):
    if fs.kind != "state":
        pytest.skip("State quota")
    await fs.call("create", "file", mode=0o640)
    await fs.call("write", "file", data=b64(b"original"))
    monkeypatch.setattr(module.settings, "SANDBOX_STATE_MAX_BYTES", 3)
    refused = await fs.call("setattr", "file", size=4, mode=0o777)
    assert refused.errno == errno.ENOSPC
    assert base64.b64decode((await fs.call("read", "file")).data) == b"original"
    assert (await fs.call("stat", "file")).entry.mode == 0o640


def test_exclusive_verifier_and_guard_schema_refuse_ambiguous_values():
    for fields in (
        {"op": "create", "exclusive": True, "verifier": "%%%"},
        {"op": "create", "exclusive": True, "verifier": b64(b"x")},
        {"op": "create", "verifier": b64(b"12345678")},
        {"op": "setattr", "guard_modified_at": "2020-01-01T00:00:00"},
    ):
        with pytest.raises(ValidationError):
            _REQUEST.validate_python(fields)
    assert _REQUEST.validate_python({"op": "create", "verifier": None}).verifier is None


async def test_create_attributes_preserve_existing_content_without_size_and_apply_explicit_size(fs):
    stamp = datetime(2020, 1, 1, tzinfo=UTC)
    created = await fs.call("create", "file", mode=0o600, size=3, modified_at=stamp.isoformat())
    assert (
        created.entry.size == 3
        and created.entry.mode == 0o600
        and created.entry.modified_at == stamp
    )
    await fs.call("write", "file", data=b64(b"abc"))
    assert (await fs.call("create", "file", mode=0o777)).ok
    assert base64.b64decode((await fs.call("read", "file")).data) == b"abc"
    assert (await fs.call("stat", "file")).entry.mode == 0o600
    await fs.call("create", "file", modified_at=stamp.isoformat())
    assert base64.b64decode((await fs.call("read", "file")).data) == b"abc"
    assert (await fs.call("stat", "file")).entry.modified_at == stamp
    assert (await fs.call("create", "file", size=0)).entry.size == 0
    created = await fs.call("mkdir", "dir", modified_at=stamp.isoformat())
    assert created.entry.modified_at == stamp


async def test_state_timestamp_quota_failure_rolls_back_payload_mutation(fs, monkeypatch):
    if fs.kind != "state":
        pytest.skip("State metadata quota")
    from app.agents.capabilities.sandbox._capped import document_size

    await fs.call("create", "file")
    await fs.call("write", "file", data=b64(b"original"))
    fs.files["/file"] = {**fs.files["/file"], "modified_at": "2020-01-01T00:00:00Z"}
    maximum = document_size(fs.files, fs.directories)
    monkeypatch.setattr(module.settings, "SANDBOX_STATE_MAX_BYTES", maximum)
    stamp = datetime(2025, 1, 1, 0, 0, 0, 123456, tzinfo=UTC)
    assert (await fs.call("setattr", "file", modified_at=stamp.isoformat())).errno == errno.ENOSPC
    assert (await fs.call("create", "file", size=maximum + 1)).errno == errno.ENOSPC
    assert (await fs.call("create", "file", modified_at=stamp.isoformat())).errno == errno.ENOSPC
    assert base64.b64decode((await fs.call("read", "file")).data) == b"original"


def test_create_and_mkdir_timestamps_require_timezone():
    for fields in (
        {"op": "create", "modified_at": "2020-01-01T00:00:00"},
        {"op": "mkdir", "modified_at": "2020-01-01T00:00:00"},
    ):
        with pytest.raises(ValidationError):
            _REQUEST.validate_python(fields)
    assert _REQUEST.validate_python({"op": "create", "modified_at": None}).modified_at is None
    assert _REQUEST.validate_python({"op": "mkdir", "modified_at": None}).modified_at is None


async def test_non_ascii_base64_is_a_defined_invalid_request(fs):
    assert (await fs.call("write", "file", data="żółć")).errno == errno.EINVAL
    fs.service.workspaces.open_project.assert_not_awaited()


async def test_native_binary_chunk_does_not_exceed_linux_per_argument_exec_limits(fs, monkeypatch):
    if fs.kind != "service":
        pytest.skip("Native argv transport")
    original_open = fs.service.workspaces.open_project.side_effect

    async def guarded_open(*args):
        opened = await original_open(*args)
        original_run = opened.workspace.run

        async def guarded_run(command, **kwargs):
            assert max(len(part.encode()) for part in command) < 131072
            return await original_run(command, **kwargs)

        monkeypatch.setattr(opened.workspace, "run", guarded_run)
        return opened

    fs.service.workspaces.open_project.side_effect = guarded_open
    await fs.call("create", "file")
    payload = b"\x00\xff" * (CHUNK_BYTES // 2)
    assert (await fs.call("write", "file", data=b64(payload))).written == CHUNK_BYTES
    assert base64.b64decode((await fs.call("read", "file", count=CHUNK_BYTES)).data) == payload


@pytest.mark.security
async def test_renaming_a_platform_ancestor_cannot_reveal_or_replace_hidden_files(fs):
    if fs.kind == "state":
        from pydantic_ai_backends import StateBackend

        document = StateBackend()
        document.write_bytes("workspace/.agenticos/private", b"private")
        fs.files.update(document.files)
    else:
        (fs.root / "workspace" / ".agenticos").mkdir(parents=True)
        (fs.root / "workspace" / ".agenticos" / "private").write_bytes(b"private")
    assert (await fs.call("list", "workspace")).entries == []
    assert (await fs.call("rename", "workspace", destination="public")).errno == errno.EACCES
    await fs.call("mkdir", "public")
    assert (await fs.call("rename", "public", destination="workspace")).errno == errno.EACCES
    assert (await fs.call("rename", "public", destination=".")).errno == errno.EBUSY
    assert (await fs.call("stat", "public")).ok


async def test_exclusive_probe_is_authorized_and_never_publishes_a_file(fs):
    result = await fs.service.exclusive_create_support(
        fs.ctx, fs.project.id, fs.project.workspace_generation, writable=True
    )
    assert result.ok or (fs.kind == "service" and result.errno in (errno.ENOTSUP, errno.EOPNOTSUPP))
    assert (await fs.call("list")).entries == []
    fs.service.workspaces.open_project.reset_mock()
    result = await fs.service.exclusive_create_support(
        fs.ctx, fs.project.id, fs.project.workspace_generation, writable=False
    )
    assert result.errno == errno.EROFS
    with pytest.raises(ConcurrentChangeError):
        await fs.service.exclusive_create_support(fs.ctx, fs.project.id, uuid4(), writable=True)
    fs.service.workspaces.open_project.assert_not_awaited()


async def test_native_exclusive_replay_is_bound_to_the_name_and_ordinary_create_has_no_marker(fs):
    if fs.kind != "service":
        pytest.skip("Native inode markers")
    support = await fs.service.exclusive_create_support(
        fs.ctx, fs.project.id, fs.project.workspace_generation, writable=True
    )
    if not support.ok:
        assert support.errno in (errno.ENOTSUP, errno.EOPNOTSUPP)
        return
    verifier = b64(b"12345678")
    await fs.call("create", "original", exclusive=True, verifier=verifier)
    await fs.call("rename", "original", destination="renamed")
    assert (
        await fs.call("create", "renamed", exclusive=True, verifier=verifier)
    ).errno == errno.EEXIST
    await fs.call("create", "ordinary")
    assert (
        await fs.call("create", "ordinary", exclusive=True, verifier=verifier)
    ).errno == errno.EEXIST
    await fs.call("mkdir", "directory")
    assert (
        await fs.call("create", "directory", exclusive=True, verifier=verifier)
    ).errno == errno.EEXIST


async def test_native_missing_xattr_support_fails_before_publication_and_cleans_only_its_stage(
    fs, monkeypatch
):
    if fs.kind != "service":
        pytest.skip("Native feature refusal")
    staging = fs.root / ".agenticos" / "projectfs-create"
    staging.mkdir(parents=True)
    (staging / "another-job").write_bytes(b"keep")
    script = module._NATIVE.replace(
        "os.setxattr(staged,_MARKER,marker)", "raise OSError(errno.ENOTSUP,'No xattr support')"
    )
    monkeypatch.setattr(module, "_NATIVE", script)
    result = await fs.service.exclusive_create_support(
        fs.ctx, fs.project.id, fs.project.workspace_generation, writable=True
    )
    assert result.errno in (errno.ENOTSUP, errno.EOPNOTSUPP)
    result = await fs.call("create", "never-published", exclusive=True, verifier=b64(b"12345678"))
    assert result.errno in (errno.ENOTSUP, errno.EOPNOTSUPP)
    assert not (fs.root / "never-published").exists()
    assert [p.name for p in staging.iterdir()] == ["another-job"]
    assert (staging / "another-job").read_bytes() == b"keep"
    assert (await fs.call("create", "ordinary")).ok


async def test_feature_probe_does_not_acknowledge_flush_failure(fs):
    fs.service.workspaces.close.side_effect = None
    fs.service.workspaces.close.return_value = WorkspaceFlushFailure(
        ExternalServiceError(message="Flush failed")
    )
    with pytest.raises(ExternalServiceError, match="Flush failed"):
        await fs.service.exclusive_create_support(
            fs.ctx, fs.project.id, fs.project.workspace_generation, writable=True
        )


@pytest.mark.parametrize(
    "operation,fields",
    [
        ("read", {}),
        ("write", {"data": b64(b"no")}),
        ("truncate", {"size": 0}),
        ("create", {}),
        ("create", {"exclusive": True, "verifier": b64(b"12345678")}),
        ("setattr", {"mode": 0o600}),
    ],
)
async def test_native_fifo_is_refused_without_waiting_for_another_process(fs, operation, fields):
    if fs.kind != "service":
        pytest.skip("Native special file")
    import asyncio
    import os

    os.mkfifo(fs.root / "pipe")
    response = await asyncio.wait_for(fs.call(operation, "pipe", **fields), timeout=2)
    assert not response.ok
    assert response.errno in (errno.ENOTSUP, errno.EOPNOTSUPP, errno.EEXIST)


async def test_native_probe_refuses_missing_atomic_link_support_and_cleans_its_files(
    fs, monkeypatch
):
    if fs.kind != "service":
        pytest.skip("Native hard-link support")
    # Keep this failure independent of the host Python's optional xattr APIs.
    script = (
        module._NATIVE.replace(
            "if not hasattr(os,'setxattr') or not hasattr(os,'getxattr'):", "if False:"
        )
        .replace("os.setxattr(staged,_MARKER,marker)", "None")
        .replace("if os.getxattr(staged,_MARKER)!=marker:", "if False:")
        .replace(
            "os.link(temporary,probe_name,src_dir_fd=staging,dst_dir_fd=staging,follow_symlinks=False)",
            "raise OSError(errno.ENOTSUP,'No atomic hard links')",
        )
    )
    monkeypatch.setattr(module, "_NATIVE", script)
    result = await fs.service.exclusive_create_support(
        fs.ctx, fs.project.id, fs.project.workspace_generation, writable=True
    )
    assert not result.ok and result.errno in (errno.ENOTSUP, errno.EOPNOTSUPP)
    assert list((fs.root / ".agenticos" / "projectfs-create").iterdir()) == []

"""The same workspace tools operate on only the resolved paired device."""

import base64
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic_ai.workspaces import (
    Workspace,
    WorkspaceReadOnlyError,
    WorkspaceTimeoutError,
    WorkspaceUnavailableError,
    WrapperWorkspace,
)

from app.schemas.local_target import LocalMode, LocalTarget
from app.services.channels.attachments import files_written, workspace_snapshot
from app.services.device_hub import workspace as module
from app.services.device_hub.exceptions import (
    DeviceCallFailed,
    DeviceCallTimedOut,
    DeviceUnavailable,
)

pytestmark = pytest.mark.anyio


async def test_file_and_shell_operations_keep_the_native_root_and_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, user = uuid4(), uuid4()
    target = LocalTarget(folder="/work", mode="read_only")
    workspace = module.DeviceWorkspace(session, user, target)
    call = AsyncMock(return_value={})
    monkeypatch.setattr(module._hub, "call", call)
    assert workspace.session_id == session
    assert workspace.ref.id == f"{session}:/work"
    assert await workspace.working_dir() == "/work"
    call.return_value = {"data": base64.b64encode(b"hello").decode()}
    assert await workspace.read_bytes("a") == b"hello"
    await workspace.write_bytes("a", b"new")
    assert call.call_args.args[2] == {
        "root": "/work",
        "mode": "read_only",
        "path": "a",
        "data": "bmV3",
    }
    call.return_value = {"name": "a", "path": "/work/a", "is_dir": False, "size": 3}
    assert (await workspace.stat("a")).size == 3
    call.return_value = {"entries": [{"name": "d", "path": "/work/d", "is_dir": True}, "bad"]}
    assert len(await workspace.list_dir(".")) == 1
    await workspace.make_dir("d")
    await workspace.remove("a")
    call.return_value = {"exists": True}
    assert await workspace.exists("d")
    call.return_value = {"path": "/work/d"}
    assert await workspace.realpath("d") == "/work/d"
    call.return_value = {"exit_code": 0, "stdout": "done", "stderr": ""}
    assert (await workspace.run(["echo", "hi"], timeout=3, env={"A": "B"})).stdout == "done"
    assert call.call_args.kwargs["timeout"] == 13
    await workspace.run("pwd", shell=True)  # noqa: S604 - the device transport is mocked; no shell runs
    assert call.call_args.args[2]["command"] == "pwd"
    assert call.call_args.args[0] == session


async def test_reconnection_uses_the_same_owner_and_device_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, user = uuid4(), uuid4()
    workspace = module.DeviceWorkspace(session, user, LocalTarget(folder="/work"))
    call = AsyncMock(side_effect=[DeviceUnavailable(message="offline"), {"exists": True}])
    wait = AsyncMock(return_value=object())
    monkeypatch.setattr(module._hub, "call", call)
    monkeypatch.setattr(module._hub, "wait_for", wait)
    assert await workspace.exists("a")
    assert wait.call_args.args == (user, session)
    assert [invocation.args[0] for invocation in call.call_args_list] == [session, session]
    call.side_effect = DeviceUnavailable(message="offline")
    wait.return_value = None
    with pytest.raises(WorkspaceUnavailableError):
        await workspace.exists("a")


@pytest.mark.parametrize(
    "kind, expected",
    [
        ("not_found", FileNotFoundError),
        ("is_dir", IsADirectoryError),
        ("read_only", WorkspaceReadOnlyError),
        ("denied", PermissionError),
        ("timeout", WorkspaceTimeoutError),
        ("unexpected", OSError),
    ],
)
async def test_native_refusals_remain_workspace_errors(
    monkeypatch: pytest.MonkeyPatch, kind: str, expected: type[Exception]
) -> None:
    monkeypatch.setattr(
        module._hub,
        "call",
        AsyncMock(side_effect=DeviceCallFailed(message="refused", details={"kind": kind})),
    )
    workspace = module.DeviceWorkspace(uuid4(), uuid4(), LocalTarget(folder="/work"))
    with pytest.raises(expected, match="refused"):
        await workspace.remove("a")
    monkeypatch.setattr(
        module._hub, "call", AsyncMock(side_effect=DeviceCallTimedOut(message="late"))
    )
    with pytest.raises(WorkspaceTimeoutError, match="late"):
        await workspace.exists("a")


@pytest.mark.parametrize("mode", ["read_only", "workspace_write", "full_access"])
async def test_automatic_snapshots_never_ask_to_run_a_command_on_the_persons_computer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: LocalMode
) -> None:
    session, user = uuid4(), uuid4()
    (tmp_path / ".existing").write_text("private", encoding="utf-8")
    (tmp_path / "reports").mkdir()
    operations: list[str] = []

    async def rpc(
        device: UUID, op: str, args: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        assert device == session
        assert args["root"] == str(tmp_path)
        assert args["mode"] == mode
        assert timeout > 0
        operations.append(op)
        path = args["path"]
        assert isinstance(path, str)
        target = Path(path)
        if op == "fs.list":
            return {
                "entries": [
                    {
                        "name": entry.name,
                        "path": str(entry),
                        "is_dir": entry.is_dir(),
                        "size": entry.stat().st_size,
                    }
                    for entry in target.iterdir()
                ]
            }
        assert op == "fs.read", "An automatic snapshot must not execute a shell command"
        return {"data": base64.b64encode(target.read_bytes()).decode()}

    monkeypatch.setattr(module._hub, "call", rpc)
    device = module.DeviceWorkspace(session, user, LocalTarget(folder=str(tmp_path), mode=mode))
    workspace = WrapperWorkspace(Workspace(device))
    before = await workspace_snapshot(workspace)
    assert before == {str(tmp_path / ".existing")}
    (tmp_path / "reports" / "answer.txt").write_text("done", encoding="utf-8")
    delivered = await files_written(workspace, before)
    assert [(file.filename, file.content) for file in delivered.attachments] == [
        ("answer.txt", b"done")
    ]
    assert set(operations) == {"fs.list", "fs.read"}


async def test_whole_computer_never_collects_home_directory_as_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grant, chat = uuid4(), uuid4()
    target = LocalTarget(folder="/Users/person", mode="full_access", computer_grant=grant)
    with pytest.raises(WorkspaceUnavailableError, match="conversation"):
        module.DeviceWorkspace(uuid4(), uuid4(), target)
    device = module.DeviceWorkspace(uuid4(), uuid4(), target, conversation_id=chat)
    call = AsyncMock(return_value={"exists": True})
    monkeypatch.setattr(module._hub, "call", call)
    workspace = WrapperWorkspace(Workspace(device))
    assert await workspace_snapshot(workspace) is None
    assert not (await files_written(workspace, None)).attachments
    call.assert_not_awaited()
    assert await device.exists("/another/volume/file.txt")
    args = call.call_args.args[2]
    assert args["computer_grant"] == str(grant)
    assert args["conversation_id"] == str(chat)
    assert args["path"] == "/another/volume/file.txt"


def test_whole_computer_target_requires_full_access_and_a_working_directory() -> None:
    from pydantic import ValidationError

    for payload in [
        {"folder": "/home", "mode": "read_only"},
        {"browser": True, "mode": "full_access"},
    ]:
        with pytest.raises(ValidationError, match="Whole-computer access"):
            LocalTarget.model_validate({**payload, "computer_grant": str(uuid4())})

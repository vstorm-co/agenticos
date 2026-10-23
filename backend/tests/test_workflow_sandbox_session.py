"""The sandboxd session a workflow script step talks to: what each call becomes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.workspaces import CommandResult, FileEntry

from app.workflows.nodes import _sandbox_job as job

pytestmark = pytest.mark.anyio


@pytest.fixture
def session() -> tuple[job._Sandbox, MagicMock, MagicMock]:
    backend = MagicMock(purge=AsyncMock())
    files = MagicMock(
        exists=AsyncMock(return_value=True),
        write_bytes=AsyncMock(),
        read_bytes=AsyncMock(return_value=b"data"),
        list_dir=AsyncMock(return_value=[FileEntry(name="a", path="/a", is_dir=False, size=1)]),
        run=AsyncMock(return_value=CommandResult(exit_code=3, stdout="out ", stderr="err")),
    )
    with patch.object(job, "Workspace", return_value=files):
        return job._Sandbox(backend), files, backend


async def test_files_and_commands_go_through_the_workspace(session) -> None:
    sandbox, files, _backend = session

    assert await sandbox.exists("/a") is True
    await sandbox.write("/t", "text")
    await sandbox.write("/b", b"\x00")
    assert await sandbox.read_bytes("/a") == b"data"
    assert [entry.path for entry in await sandbox.list_dir("/")] == ["/a"]

    assert [call.args for call in files.write_bytes.await_args_list] == [
        ("/t", b"text"),
        ("/b", b"\x00"),
    ]


async def test_a_line_runs_under_sh_and_answers_both_streams(session) -> None:
    """Under `sh -c` as an argument list: the line is this module's own, and no
    shell flag is needed to run it."""
    sandbox, files, _backend = session

    assert await sandbox.shell("echo hi") == (3, "out err")
    files.run.assert_awaited_once_with(["sh", "-c", "echo hi"])


async def test_purging_gives_the_session_back(session) -> None:
    sandbox, _files, backend = session

    await sandbox.purge()

    backend.purge.assert_awaited_once_with()

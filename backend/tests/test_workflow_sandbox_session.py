"""The sandboxd session a workflow script step talks to: what each call becomes."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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
        return (
            job._Sandbox(
                backend,
                MagicMock(aclose=AsyncMock()),
                job._CappedTransport(httpx.MockTransport(lambda _: httpx.Response(200))),
            ),
            files,
            backend,
        )


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


async def test_a_growing_native_read_stops_before_the_rest_of_the_stream_is_consumed() -> None:
    from collections.abc import AsyncIterator

    class Growing(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.chunks_read = 0
            self.closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            for _ in range(100):
                self.chunks_read += 1
                yield b"abcd"

        async def aclose(self) -> None:
            self.closed = True

    growing = Growing()
    transport = job._CappedTransport(
        httpx.MockTransport(lambda _: httpx.Response(200, stream=growing))
    )
    transport.read_limit = 6
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(job._TooLarge):
            await client.post("https://sandbox.example/sessions/job/files/read")
    assert growing.chunks_read == 2
    assert growing.closed


async def test_the_sandbox_client_is_closed_when_the_attempt_ends(session) -> None:
    sandbox, _files, _backend = session
    await sandbox.close()
    sandbox._client.aclose.assert_awaited_once()


async def test_a_native_file_at_the_exact_byte_limit_is_returned_and_other_requests_keep_their_budget() -> (
    None
):
    transport = job._CappedTransport(
        httpx.MockTransport(lambda _: httpx.Response(200, content=b"data"))
    )
    transport.read_limit = 4
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post("https://sandbox.example/sessions/job/files/read")
        assert response.content == b"data"
        transport.read_limit = 0
        metadata = await client.post("https://sandbox.example/sessions/job/files/stat")
        assert metadata.content == b"data"


async def test_a_shell_fallback_read_still_obeys_the_remaining_file_budget(session) -> None:
    sandbox, _files, _backend = session
    with pytest.raises(job._TooLarge):
        await sandbox.read_bytes("/a", max_bytes=3)


async def test_outputs_added_after_measurement_are_refused_before_their_bytes_are_read(
    session, monkeypatch
) -> None:
    sandbox, files, _backend = session
    files.read_bytes.side_effect = lambda path: (
        b'{"ok":true}' if path.endswith("result.json") else b""
    )
    monkeypatch.setattr(job, "MAX_OUTPUT_FILES", 0)
    with patch.object(job, "_measure", new=AsyncMock()), pytest.raises(job._TooLarge):
        await job._collect(sandbox)
    assert [call.args[0] for call in files.read_bytes.await_args_list] == [
        f"{job.ROOT}/result.json",
        f"{job.ROOT}/log.txt",
    ]

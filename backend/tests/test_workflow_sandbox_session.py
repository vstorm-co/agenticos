"""The sandboxd session a workflow script step talks to: what each call becomes."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic_ai.workspaces import CommandResult, FileEntry

from app.workflows.contracts.results import Failed
from app.workflows.nodes import _sandbox_job as job
from app.workflows.nodes.code_python_sandbox._handler import PYTHON

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


@pytest.mark.security
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


@pytest.mark.security
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


def _answered(status: int, body: bytes, path: str = "/sessions") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", f"http://sandboxd:8080{path}")
    response = httpx.Response(status, content=body, request=request)
    return httpx.HTTPStatusError("refused", request=request, response=response)


async def _run_against(error: Exception) -> Failed:
    current = MagicMock(idempotency_key="key", node_run_id="run", organization_id="org")
    with (
        patch.object(job.context, "current", return_value=current),
        patch.object(job, "_connection", new=AsyncMock(return_value=MagicMock(kind="docker"))),
        patch.object(job, "_open", side_effect=error),
    ):
        failed = await job.run_job(
            PYTHON,
            code="1",
            timeout_seconds=1,
            connection_id=None,
            runtime=None,
            args={},
            input_files=(),
        )
    assert isinstance(failed, Failed)
    return failed


async def test_a_host_start_failure_has_a_safe_diagnosis(caplog) -> None:
    """A 502 from opening a session carries the cause; reporting it as unreachable hid it."""
    cause = "Could not start sandbox: [Errno 13] Permission denied: '/tmp/ws/key'"
    failed = await _run_against(_answered(502, f'{{"detail": "{cause}"}}'.encode()))
    assert failed.error.code == "SANDBOX_START_FAILED"
    assert "workspace directory permissions" in failed.error.message
    assert cause not in failed.error.message
    assert cause.split("'")[1] not in caplog.text
    assert failed.error.retryable


async def test_a_long_refusal_uses_a_controlled_message() -> None:
    failed = await _run_against(_answered(502, b'{"detail": "' + b"x" * 5000 + b'"}'))
    assert "Check the sandbox host's logs" in failed.error.message
    assert "x" * 50 not in failed.error.message


@pytest.mark.parametrize(
    "error",
    [
        _answered(503, b'{"detail": "draining"}'),
        _answered(502, b'{"detail": "gone"}', path="/sessions/abc/run"),
        httpx.ConnectError("refused"),
    ],
)
async def test_anything_else_is_still_a_host_that_could_not_be_reached(error: Exception) -> None:
    failed = await _run_against(error)
    assert failed.error.code == "SANDBOX_UNREACHABLE"
    assert failed.error.retryable


@pytest.mark.parametrize(
    "body", [b"<html>Bad Gateway</html>", b"[]", b'{"detail":""}', b"x" * 20000]
)
async def test_an_unstructured_start_failure_keeps_the_startup_code(body: bytes) -> None:
    failed = await _run_against(_answered(502, body))
    assert failed.error.code == "SANDBOX_START_FAILED"
    assert "Check the sandbox host's logs" in failed.error.message


@pytest.mark.parametrize(
    "detail", ["image build failed: token=secret", "password=secret /host/private\\file"]
)
async def test_host_diagnostics_stay_out_of_the_result_and_log(detail: str, caplog) -> None:
    import json

    failed = await _run_against(_answered(502, json.dumps({"detail": detail}).encode()))
    assert "secret" not in failed.error.message
    assert "secret" not in caplog.text


@pytest.mark.parametrize("encoding", ["identity", "gzip"])
async def test_error_bodies_are_bounded_before_parsing_and_always_closed(encoding: str) -> None:
    from collections.abc import AsyncIterator

    class Growing(httpx.AsyncByteStream):
        chunks_read = 0
        closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            for _ in range(100):
                self.chunks_read += 1
                yield b"x" * 4096

        async def aclose(self) -> None:
            self.closed = True

    stream = Growing()
    transport = job._CappedTransport(
        httpx.MockTransport(
            lambda _: httpx.Response(
                502,
                headers={"content-encoding": encoding, "content-length": "409600"},
                stream=stream,
            )
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post("http://sandboxd:8080/sessions")
    assert response.status_code == 502
    assert response.content == b""
    assert stream.chunks_read <= 5
    assert stream.closed


async def test_a_small_error_body_is_available_for_classification() -> None:
    transport = job._CappedTransport(
        httpx.MockTransport(
            lambda _: httpx.Response(
                502, json={"detail": "Permission denied"}, headers={"retry-after": "5"}
            )
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post("http://sandboxd:8080/sessions")
    assert response.json() == {"detail": "Permission denied"}
    assert response.headers["retry-after"] == "5"

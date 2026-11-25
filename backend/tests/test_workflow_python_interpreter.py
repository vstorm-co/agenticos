"""A workflow host call is a durable yield, not an in-process Python callback."""

import shutil
from functools import partial
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from pydantic_monty import AsyncFutureSnapshot, AsyncMonty, AsyncMontySession

from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.contracts.script import ScriptActionRequest, ScriptResume
from app.workflows.nodes.code_python_actions import _handler
from app.workflows.nodes.code_python_simple import PythonSimpleInput
from app.workflows.python_actions import PythonActionsConfig

pytestmark = pytest.mark.anyio


async def segment(code: str, *, resume: ScriptResume | None = None) -> NodeResult:
    config = PythonActionsConfig(code=code, actions={"echo": {"type": "debug.echo"}})
    with patch.object(
        context, "current", return_value=Mock(node_run_id=uuid4(), script_resume=resume)
    ):
        return await _handler.handle(config, PythonSimpleInput(args={"items": [1, 2]}))


async def test_the_interpreter_continues_the_loop_in_a_new_session_after_each_call():
    code = "out = []\nfor i in args['items']:\n print(i)\n out.append(echo(message=str(i))['echoed'])\nout"
    result = await segment(code)
    for index, expected in enumerate(["1", "2"]):
        assert isinstance(result, ScriptActionRequest)
        assert (result.index, result.alias, result.inputs) == (index, "echo", {"message": expected})
        result = await segment(
            code,
            resume=ScriptResume(
                checkpoint=result.checkpoint,
                index=index,
                alias="echo",
                stdout=result.stdout,
                output={"echoed": expected},
            ),
        )
    assert isinstance(result, Completed)
    assert result.output.result == ["1", "2"]
    assert result.output.stdout == "1\n2\n"


@pytest.mark.parametrize(
    ("code", "failure"),
    [
        ("missing()", "PYTHON_ACTION_UNKNOWN"),
        ("echo(42)", "PYTHON_ACTION_ARGUMENTS"),
        ("echo(message={1, 2})", "PYTHON_ACTION_ARGUMENTS"),
        ("echo(message=float('inf'))", "PYTHON_ACTION_ARGUMENTS"),
        ("{1, 2}", "PYTHON_OUTPUT_NOT_JSON"),
        ("not_a_variable", "PYTHON_ERROR"),
        ("open('/forbidden').read()", "PYTHON_ERROR"),
    ],
)
async def test_invalid_calls_never_yield_a_request(code: str, failure: str):
    result = await segment(code)
    assert isinstance(result, Failed)
    assert result.error.code == failure
    assert not result.error.retryable


async def test_clips_prints_across_segments():
    result = await segment("print('x' * 9000)\n42")
    assert isinstance(result, Completed)
    assert result.output.result == 42
    assert len(result.output.stdout) == _handler.MAX_OUTPUT_CHARS


@pytest.mark.parametrize("damage", ["runtime", "digest", "alias", "encoding"])
async def test_invalid_checkpoint_does_not_restart_the_script(damage: str) -> None:
    code = "echo(message='first')"
    first = await segment(code)
    assert isinstance(first, ScriptActionRequest)
    runtime, digest, data = first.checkpoint.split(":")
    state = ScriptResume(
        index=0,
        alias="wrong" if damage == "alias" else "echo",
        stdout="",
        output={},
        checkpoint=":".join(
            [
                "wrong" if damage == "runtime" else runtime,
                "wrong" if damage == "digest" else digest,
                "!" if damage == "encoding" else data,
            ]
        ),
    )
    result = await segment(code, resume=state)
    assert isinstance(result, Failed)
    assert result.error.code == "PYTHON_CHECKPOINT_INVALID"
    assert result.error.bypassable is False
    assert not result.error.retryable
    if damage == "runtime":
        assert result.error.message == (
            "The checkpoint was saved by another interpreter version. Use Retry from failed step."
        )
    else:
        assert "another interpreter version" not in result.error.message


async def test_call_limit_stops_before_the_next_action(monkeypatch):
    monkeypatch.setattr(_handler, "MAX_ACTION_CALLS", 0)
    result = await segment("echo()")
    assert isinstance(result, Failed)
    assert result.error.code == "PYTHON_ACTION_LIMIT"


async def test_overlarge_snapshot_stops_before_dispatch(monkeypatch):
    monkeypatch.setattr(_handler, "_MAX_SNAPSHOT", 10)
    result = await segment("echo()")
    assert isinstance(result, Failed)
    assert result.error.code == "PYTHON_CHECKPOINT_TOO_LARGE"


async def test_no_script_fails_cleanly():
    result = await _handler.handle(None, None)
    assert isinstance(result, Failed)
    assert result.error.code == "PYTHON_NOT_CONFIGURED"


@pytest.mark.parametrize("restoring", [False, True], ids=["new-segment", "at-checkpoint"])
async def test_a_worker_that_exits_without_an_answer_is_a_sandbox_failure(monkeypatch, restoring):
    binary = shutil.which("false")
    if not binary:
        pytest.skip("Needs a worker process that immediately exits")
    code = "echo(message='hello')['echoed']" if restoring else "'hello'"
    saved = None
    if restoring:
        request = await segment(code)
        assert isinstance(request, ScriptActionRequest)
        saved = ScriptResume(
            index=request.index,
            alias=request.alias,
            checkpoint=request.checkpoint,
            stdout=request.stdout,
            output={"echoed": "hello"},
        )
    with monkeypatch.context() as unavailable:
        unavailable.setattr(_handler, "AsyncMonty", partial(AsyncMonty, binary_path=binary))
        outcome = await segment(code, resume=saved)
    assert isinstance(outcome, Failed)
    assert outcome.error.code == "PYTHON_SANDBOX_FAILED"
    assert outcome.error.retryable
    retried = await segment(code, resume=saved)
    assert isinstance(retried, Completed)
    assert retried.output.result == "hello"


async def test_a_script_can_handle_ordinary_monty_refusals():
    answer = await segment(
        "try:\n missing_name\nexcept NameError:\n pass\n"
        "try:\n open('/forbidden')\nexcept Exception:\n pass\n42"
    )
    assert isinstance(answer, Completed)
    assert answer.output.result == 42


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("echo(message='x' * 1000)", "PYTHON_ACTION_INPUT_TOO_LARGE"),
        ("'x' * 1000", "NODE_OUTPUT_TOO_LARGE"),
    ],
)
async def test_oversized_inline_values_fail_before_handoff(monkeypatch, code: str, error: str):
    monkeypatch.setattr(_handler.settings, "WORKFLOW_NODE_MAX_OUTPUT_BYTES", 500)
    result = await segment(code)
    assert isinstance(result, Failed)
    assert result.error.code == error


async def test_a_pending_parallel_future_is_not_dispatched():
    session = AsyncMock(spec=AsyncMontySession)
    future = Mock(spec=AsyncFutureSnapshot)
    session.feed_start = AsyncMock(return_value=future)
    result = await _handler._segment(
        session, PythonActionsConfig(code="42"), PythonSimpleInput(), None
    )
    assert isinstance(result, Failed)
    assert result.error.code == "PYTHON_ACTION_ASYNC"
    future.resume_auto.assert_not_called()

"""Schema admission has a real deadline, bounded concurrency and reaped children."""

import asyncio
import io
import json
import os
import resource
import sys
import weakref
from unittest.mock import AsyncMock

import anyio
import pytest

from app.core.exceptions import RateLimitError
from app.services.workflow_execution import input_validation
from app.services.workflow_execution.exceptions import WorkflowInputValidationUnavailableError
from app.workflows.contracts import input_schema, input_schema_worker
from app.workflows.contracts.input_schema import MAX_SCHEMA_BYTES, check_input_schema

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_launcher_preserves_supported_resource_limits(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    limits: list[tuple[int, tuple[int, int]]] = []
    launched: list[tuple[str, list[str]]] = []

    def set_limit(kind: int, value: tuple[int, int]) -> None:
        limits.append((kind, value))

    def launch(executable: str, arguments: list[str]) -> None:
        launched.append((executable, arguments))

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(sys, "argv", ["launcher", "3", "268435456", "python", "-I"])
    monkeypatch.setattr(resource, "getrlimit", lambda kind: (resource.RLIM_INFINITY,) * 2)
    monkeypatch.setattr(resource, "setrlimit", set_limit)
    monkeypatch.setattr(os, "execv", launch)
    exec(input_validation._LAUNCHER, {})  # noqa: S102 - exercise the repository-owned launcher
    expected = [(resource.RLIMIT_CPU, (3, 3))]
    if platform == "linux":
        expected.append((resource.RLIMIT_AS, (268435456, 268435456)))
    assert limits == expected
    assert launched == [("python", ["python", "-I"])]


def test_linux_memory_limit_failure_does_not_start_an_unbounded_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def set_limit(kind: int, value: tuple[int, int]) -> None:
        if kind == resource.RLIMIT_AS:
            raise ValueError("Memory limit refused")

    def launch(executable: str, arguments: list[str]) -> None:
        pytest.fail("A validator without its required limits must not start")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "argv", ["launcher", "3", "268435456", "python", "-I"])
    monkeypatch.setattr(resource, "getrlimit", lambda kind: (resource.RLIM_INFINITY,) * 2)
    monkeypatch.setattr(resource, "setrlimit", set_limit)
    monkeypatch.setattr(os, "execv", launch)
    with pytest.raises(ValueError, match="Memory limit refused"):
        exec(input_validation._LAUNCHER, {})  # noqa: S102 - exercise the repository-owned launcher


@pytest.mark.parametrize("character", ["x", "界"])
def test_oversized_schema_is_refused_before_publication(character: str) -> None:
    with pytest.raises(ValueError, match=f"at most {MAX_SCHEMA_BYTES} bytes"):
        check_input_schema({"description": character * MAX_SCHEMA_BYTES})


class ChildReady:
    def __init__(self, child: Child) -> None:
        self.child = child

    async def readline(self) -> bytes:
        self.child.ready_requested.set()
        await self.child.ready_gate.wait()
        return self.child.ready_line


class Child:
    def __init__(
        self,
        stdout: bytes = b"[]",
        *,
        returncode: int = 0,
        blocked: bool = False,
        ready: bool = True,
        ready_line: bytes = input_schema_worker.READY_LINE,
    ) -> None:
        self.output = stdout
        self.stdout = ChildReady(self)
        self.ready_line = ready_line
        self.ready_gate = asyncio.Event()
        self.ready_requested = asyncio.Event()
        if ready:
            self.ready_gate.set()
        self.exit_code = returncode
        self.returncode: int | None = None
        self.killed = False
        self.gate_locked_at_kill: bool | None = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.done = asyncio.Event()
        if not blocked:
            self.release.set()

    async def communicate(self, data: bytes) -> tuple[bytes, None]:
        assert json.loads(data).keys() == {"schema", "input"}
        assert self.ready_gate.is_set(), "Evaluation began before the validator was ready"
        self.started.set()
        await self.release.wait()
        self.returncode = self.exit_code
        self.done.set()
        return self.output, None

    def kill(self) -> None:
        self.gate_locked_at_kill = input_validation._gate().locked()
        self.killed = True
        self.returncode = -9
        self.done.set()

    async def wait(self) -> int:
        await self.done.wait()
        assert self.returncode is not None
        return self.returncode


def answer(output: io.BytesIO) -> bytes:
    ready, _, response = output.getvalue().partition(b"\n")
    assert ready + b"\n" == input_schema_worker.READY_LINE
    return response


def test_worker_returns_only_safe_constraint_errors() -> None:
    request = {
        "schema": {"properties": {"name": {"type": "integer"}}},
        "input": {"name": "private-input"},
    }
    output = io.BytesIO()
    input_schema_worker.main(io.BytesIO(json.dumps(request).encode()), output)
    assert json.loads(answer(output)) == [
        {"field": "name", "message": "Must be of type integer", "type": "type"}
    ]
    assert b"private-input" not in answer(output)


def test_worker_refuses_oversized_protocol_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(input_schema_worker, "MAX_REQUEST_BYTES", 4)
    output = io.BytesIO()
    input_schema_worker.main(io.BytesIO(b"too large"), output)
    assert json.loads(answer(output)) == input_schema_worker.validation_limit()


def test_worker_bounds_the_encoded_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(input_schema_worker, "MAX_RESPONSE_BYTES", 4)
    request = {"schema": {"required": ["missing"]}, "input": {}}
    output = io.BytesIO()
    input_schema_worker.main(io.BytesIO(json.dumps(request).encode()), output)
    assert json.loads(answer(output)) == input_schema_worker.validation_limit()


async def test_valid_and_invalid_nested_inputs_use_the_same_contract() -> None:
    schema = {
        "$defs": {"name": {"type": "string", "minLength": 2}},
        "properties": {"names": {"type": "array", "items": {"$ref": "#/$defs/name"}}},
    }
    assert await input_validation.schema_problems(schema, {"names": ["Ada"]}) == []
    assert await input_validation.schema_problems(schema, {"names": ["x"]}) == [
        {
            "field": "names.0",
            "message": "Must contain at least 2 characters",
            "type": "minLength",
        }
    ]


async def test_oversized_request_starts_no_child(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(input_validation, "MAX_REQUEST_BYTES", 1)
    spawn = AsyncMock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    assert await input_validation.schema_problems({}, {}) == input_schema_worker.validation_limit()
    spawn.assert_not_awaited()


async def test_deadline_kills_and_reaps_the_child(monkeypatch: pytest.MonkeyPatch) -> None:
    child = Child(blocked=True)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=child))
    monkeypatch.setattr(input_validation, "VALIDATION_SECONDS", 0.01)
    assert await input_validation.schema_problems({}, {}) == input_schema_worker.validation_limit()
    assert child.killed and child.done.is_set()


async def test_slow_process_spawn_reports_start_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    cancelled = asyncio.Event()

    async def slow_start(*args: object, **kwargs: object) -> Child:
        try:
            await anyio.sleep(10)
        finally:
            cancelled.set()
        raise AssertionError("The startup deadline must cancel this wait")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow_start)
    monkeypatch.setattr(input_validation, "STARTUP_SECONDS", 0.01)
    with pytest.raises(WorkflowInputValidationUnavailableError) as refused:
        await input_validation.schema_problems({}, {})
    assert refused.value.status_code == 503
    assert refused.value.details == {"reason": "start_timeout"}
    assert cancelled.is_set()


async def test_child_that_never_becomes_ready_is_killed_and_reaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Child(ready=False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=child))
    monkeypatch.setattr(input_validation, "STARTUP_SECONDS", 0.01)
    with pytest.raises(WorkflowInputValidationUnavailableError) as refused:
        await input_validation.schema_problems({}, {})
    assert refused.value.details == {"reason": "start_timeout"}
    assert child.killed and child.done.is_set()
    assert not input_validation._gate().locked()


async def test_slow_startup_does_not_consume_the_evaluation_allowance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Child(ready=False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=child))
    monkeypatch.setattr(input_validation, "STARTUP_SECONDS", 5)
    monkeypatch.setattr(input_validation, "VALIDATION_SECONDS", 0.05)

    async def become_ready_after_the_evaluation_allowance() -> None:
        await child.ready_requested.wait()
        await anyio.sleep(0.2)
        child.ready_gate.set()

    async with anyio.create_task_group() as group:
        group.start_soon(become_ready_after_the_evaluation_allowance)
        assert await input_validation.schema_problems({}, {}) == []
    assert not child.killed


async def test_evaluation_deadline_starts_after_the_ready_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Child(blocked=True)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=child))
    monkeypatch.setattr(input_validation, "STARTUP_SECONDS", 5)
    monkeypatch.setattr(input_validation, "VALIDATION_SECONDS", 0.05)
    assert await input_validation.schema_problems({}, {}) == input_schema_worker.validation_limit()
    assert child.started.is_set() and child.killed and child.done.is_set()


@pytest.mark.parametrize("ready_line", [b"", b"not-ready\n"])
async def test_child_that_exits_or_misreports_before_ready_is_a_start_failure(
    monkeypatch: pytest.MonkeyPatch, ready_line: bytes
) -> None:
    child = Child(ready_line=ready_line)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=child))
    with pytest.raises(WorkflowInputValidationUnavailableError) as refused:
        await input_validation.schema_problems({}, {"value": "private-input"})
    assert refused.value.details == {"reason": "start_failed"}
    assert not child.started.is_set() and child.killed and child.done.is_set()
    assert "private" not in str(refused.value)


async def test_cancellation_while_waiting_for_ready_reaps_child_before_releasing_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Child(ready=False)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=child))
    monkeypatch.setattr(input_validation, "MAX_VALIDATIONS", 1)
    monkeypatch.setattr(input_validation, "_gates", weakref.WeakKeyDictionary())
    async with anyio.create_task_group() as group:
        group.start_soon(input_validation.schema_problems, {}, {})
        await child.ready_requested.wait()
        group.cancel_scope.cancel()
    assert child.killed and child.done.is_set()
    assert child.gate_locked_at_kill is True
    assert not input_validation._gate().locked()


async def test_cpu_limit_covers_startup_and_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    spawn = AsyncMock(return_value=Child())
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(input_validation, "STARTUP_SECONDS", 3)
    monkeypatch.setattr(input_validation, "VALIDATION_SECONDS", 1.5)
    assert await input_validation.schema_problems({}, {}) == []
    cpu, memory = spawn.await_args.args[3:5]
    assert cpu == "6"
    assert memory == str(input_validation._ADDRESS_SPACE_BYTES)


async def test_cleanup_reaps_a_child_that_already_exited() -> None:
    child = await asyncio.create_subprocess_exec(input_validation.sys.executable, "-c", "pass")
    await child.wait()
    await input_validation._kill_and_reap(child)
    assert child.returncode == 0


async def test_saturation_refuses_without_starting_another_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Child(blocked=True)
    spawn = AsyncMock(return_value=child)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(input_validation, "MAX_VALIDATIONS", 1)
    monkeypatch.setattr(input_validation, "_gates", weakref.WeakKeyDictionary())

    async def validate() -> None:
        assert await input_validation.schema_problems({}, {}) == []

    async with anyio.create_task_group() as group:
        group.start_soon(validate)
        await child.started.wait()
        with pytest.raises(RateLimitError) as refused:
            await input_validation.schema_problems({}, {})
        assert refused.value.status_code == 429
        assert refused.value.details["stage"] == "workflow_input_validation"
        assert spawn.await_count == 1
        child.release.set()
    assert await input_validation.schema_problems({}, {}) == []


async def test_cancellation_stops_child_before_releasing_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Child(blocked=True)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=child))
    async with anyio.create_task_group() as group:
        group.start_soon(input_validation.schema_problems, {}, {})
        await child.started.wait()
        group.cancel_scope.cancel()
    assert child.killed and child.done.is_set()
    assert not input_validation._gate().locked()


async def test_launch_failure_has_no_submitted_data_in_the_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", AsyncMock(side_effect=OSError("private-error"))
    )
    with pytest.raises(WorkflowInputValidationUnavailableError) as refused:
        await input_validation.schema_problems({}, {"value": "private-input"})
    assert refused.value.status_code == 503
    assert refused.value.details == {"reason": "not_started"}
    assert "private" not in str(refused.value.details)


@pytest.mark.parametrize(
    ("output", "returncode", "reason"),
    [
        (b"[]", 1, "failed"),
        (b"private-invalid-output", 0, "invalid_output"),
        (b"[{}]", 0, "invalid_output"),
        (b"x" * (input_validation.MAX_RESPONSE_BYTES + 1), 0, "invalid_output"),
    ],
)
async def test_failed_or_malformed_child_answers_do_not_admit_input(
    monkeypatch: pytest.MonkeyPatch, output: bytes, returncode: int, reason: str
) -> None:
    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=Child(output, returncode=returncode)),
    )
    with pytest.raises(WorkflowInputValidationUnavailableError) as refused:
        await input_validation.schema_problems({}, {})
    assert refused.value.details == {"reason": reason}
    assert "private" not in str(refused.value)


async def test_exponential_reference_work_does_not_block_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definitions = {"d30": {"type": "object"}}
    for index in range(29, -1, -1):
        definitions[f"d{index}"] = {
            "allOf": [{"$ref": f"#/$defs/d{index + 1}"}, {"$ref": f"#/$defs/d{index + 1}"}]
        }
    schema = {"$defs": definitions, "$ref": "#/$defs/d0"}
    monkeypatch.setattr(input_validation, "VALIDATION_SECONDS", 1)
    alive = 0
    finished = asyncio.Event()

    async def heartbeat() -> None:
        nonlocal alive
        while not finished.is_set():
            alive += 1
            await anyio.sleep(0.01)

    async with anyio.create_task_group() as group:
        group.start_soon(heartbeat)
        problems = await input_validation.schema_problems(schema, {})
        finished.set()
    assert problems == input_schema_worker.validation_limit()
    assert alive > 1


@pytest.mark.parametrize("stage", ["check_input_schema", "schema_input_problems", "encode"])
def test_worker_memory_exhaustion_returns_a_preallocated_resource_refusal(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    request = json.dumps(
        {"schema": {"type": "object"}, "input": {"secret": "private-input"}}
    ).encode()

    def exhaust(*args: object, **kwargs: object) -> None:
        raise MemoryError("private allocator detail")

    if stage == "encode":
        monkeypatch.setattr(json, "dumps", exhaust)
    else:
        monkeypatch.setattr(input_schema, stage, exhaust)
    output = io.BytesIO()
    input_schema_worker.main(io.BytesIO(request), output)
    assert json.loads(answer(output)) == input_schema_worker.validation_limit()
    assert b"private" not in answer(output)

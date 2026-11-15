"""The bounded subprocess schema validator, and above all its isolation.

A hostile MCP schema's `pattern` can hang `jsonschema` on the GIL. The parent
(`app.agents.tool_schema_validation`) runs the check in a killed-on-timeout
child (`app.agents._schema_validator_worker`). These tests cover the worker's
pure functions directly, the parent's protocol handling against a fake child,
and the real subprocess paths - a pathological pattern, a refusal to fetch
remote references, and kill/reap on timeout and cancellation.
"""

import asyncio
import contextlib
import io
import json
import os
import resource
import runpy
import sys
from itertools import pairwise
from pathlib import Path
from typing import cast

import pytest
from jsonschema import validators
from jsonschema.exceptions import ValidationError
from pydantic import JsonValue
from referencing import Registry

from app.agents import _schema_validator_worker as worker
from app.agents import tool_schema_validation as module
from app.agents.tool_schema_validation import SchemaProblem, SchemaValidationUnavailable

pytestmark = pytest.mark.anyio


class _FakeWriter:
    def __init__(self) -> None:
        self.written = b""

    def write(self, data: bytes) -> None:
        self.written += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


class _FakeReader:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)

    async def read(self, n: int) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""


class _FakeProc:
    def __init__(self, *, chunks: list[bytes] | None = None, returncode: int = 0) -> None:
        self.stdin = _FakeWriter()
        self.stdout = _FakeReader(chunks or [])
        self.returncode = returncode
        self.killed = False

    async def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.killed = True


def _errors(schema: dict[str, JsonValue], instance: dict[str, JsonValue]) -> list[ValidationError]:
    validator = validators.validator_for(schema)
    validator.check_schema(schema)
    checker = validator(schema, registry=Registry())
    return list(checker.iter_errors(instance))


async def _wait_gone(pid: int, timeout: float = 5.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        await asyncio.sleep(0.02)
    return False


async def _bounded_completion(
    tasks: list[asyncio.Task[list[SchemaProblem]]], processes: list[asyncio.subprocess.Process]
) -> None:
    """Fail a broken cleanup promptly, and drain its pipes so pytest can exit."""
    _, pending = await asyncio.wait(tasks, timeout=3.0)
    if not pending:
        return
    for proc in processes:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        if proc.stdout is not None:
            await proc.stdout.read()
        await proc.wait()
    for task in pending:
        task.cancel()
    await asyncio.wait(pending, timeout=1.0)
    pytest.fail("schema validation did not finish cleanup within three seconds")


def test_trim_schema_keeps_only_formatting_constraints() -> None:
    schema = {
        "type": "string",
        "format": "uuid",
        "pattern": "(a+)+b",
        "description": "a large description",
        "default": "value",
        "items": {"type": "string", "format": "email"},
        "anyOf": [{"type": "array", "description": "drop"}, {"type": "null"}, True],
    }
    assert worker._trim_schema(schema) == {
        "type": "string",
        "format": "uuid",
        "items": {"type": "string", "format": "email"},
        "anyOf": [{"type": "array"}, {"type": "null"}],
    }


def test_trim_schema_of_a_boolean_or_absent_schema_is_empty() -> None:
    assert worker._trim_schema(True) == {}
    assert worker._trim_schema(None) == {}


def test_local_schema_resolves_a_defs_reference_or_falls_back() -> None:
    root: dict[str, JsonValue] = {"$defs": {"Field": {"type": "string"}}}
    assert worker._local_schema(root, {"$ref": "#/$defs/Field"}) == {"type": "string"}
    assert worker._local_schema(root, {"$ref": "#/$defs/Missing"}) == {}
    assert worker._local_schema({}, {"$ref": "#/$defs/Field"}) == {}
    assert worker._local_schema(root, {"type": "string"}) == {"type": "string"}


def test_property_schema_looks_up_one_property_safely() -> None:
    assert worker._property_schema(None, "x") == {}
    assert worker._property_schema({}, "x") == {}
    assert worker._property_schema({"properties": {}}, "x") == {}
    assert worker._property_schema({"properties": {"x": None}}, "x") == {}
    assert worker._property_schema({"properties": {"x": {"type": "string"}}}, "x") == {
        "type": "string"
    }


def test_cpu_seconds_reads_the_argument_or_defaults() -> None:
    assert worker._cpu_seconds(["w", "7"]) == 7
    assert worker._cpu_seconds(["w"]) == worker.DEFAULT_CPU_SECONDS
    assert worker._cpu_seconds(["w", "nonsense"]) == worker.DEFAULT_CPU_SECONDS


def test_apply_limits_skips_zero_and_applies_an_infinite_hard_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(resource, "getrlimit", lambda res: (0, resource.RLIM_INFINITY))
    monkeypatch.setattr(resource, "setrlimit", lambda res, limits: calls.append((res, limits[0])))

    worker._apply_limits(0)

    # The zero CPU bound is skipped; only the address-space bound is applied.
    assert calls == [(resource.RLIMIT_AS, worker.MEMORY_LIMIT_BYTES)]


def test_apply_limits_caps_each_bound_at_the_finite_hard_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(resource, "getrlimit", lambda res: (0, 100))
    monkeypatch.setattr(resource, "setrlimit", lambda res, limits: calls.append((res, limits[0])))

    worker._apply_limits(1)

    assert calls == [(resource.RLIMIT_CPU, 1), (resource.RLIMIT_AS, 100)]


def test_apply_limits_swallows_a_limit_the_host_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resource, "getrlimit", lambda res: (0, resource.RLIM_INFINITY))

    def rejected(res: int, limits: tuple[int, int]) -> None:
        raise OSError("unsupported")

    monkeypatch.setattr(resource, "setrlimit", rejected)

    worker._apply_limits(1)  # both limits raise; nothing escapes


def test_read_request_parses_json_and_defers_shape_validation() -> None:
    assert worker._read_request(io.StringIO("not json")) is None
    assert worker._read_request(io.StringIO("[1, 2]")) == [1, 2]
    assert worker._read_request(io.StringIO('{"schema": 1, "arguments": {}}')) == {
        "schema": 1,
        "arguments": {},
    }
    assert worker._read_request(io.StringIO('{"schema": {}, "arguments": []}')) == {
        "schema": {},
        "arguments": [],
    }


def test_handle_reports_invalid_schema_for_a_bad_request() -> None:
    assert worker._handle(None) == {"ok": False, "error": "invalid_schema"}
    assert worker._handle({"schema": []}) == {"ok": False, "error": "invalid_schema"}


def test_validate_reports_an_uncheckable_schema() -> None:
    result = worker._validate({"type": 42}, {})
    assert result == {"ok": False, "error": "invalid_schema"}


def test_validate_reports_an_unresolvable_reference() -> None:
    schema = {"type": "object", "properties": {"x": {"$ref": "https://example.com/x.json"}}}
    assert worker._validate(schema, {"x": 1}) == {"ok": False, "error": "invalid_schema"}


def test_validate_caps_problems_at_ten() -> None:
    schema = {"type": "object", "additionalProperties": {"type": "string"}}
    arguments = {f"field{index}": {"not": "a string"} for index in range(15)}
    result = worker._validate(schema, arguments)
    assert result["ok"] is True
    problems = cast(list[dict[str, JsonValue]], result["problems"])
    assert len(problems) == worker.MAX_PROBLEMS


def test_expand_a_required_error_into_one_problem_per_missing_field() -> None:
    schema: dict[str, JsonValue] = {
        "type": "object",
        "required": ["name", "age"],
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
    }
    error, *_ = _errors(schema, {})
    problems = worker._expand(error, schema)
    assert [p["path"] for p in problems] == [["name"], ["age"]]
    assert all(p["validator"] == "required" for p in problems)
    assert [p["missing"] for p in problems] == [["name"], ["age"]]
    assert [p["schema"] for p in problems] == [{"type": "string"}, {"type": "integer"}]


def test_expand_a_non_required_error_is_one_problem_at_its_path() -> None:
    schema: dict[str, JsonValue] = {"type": "object", "properties": {"x": {"type": "string"}}}
    (error,) = _errors(schema, {"x": 5})
    problems = worker._expand(error, schema)
    assert problems == [{"path": ["x"], "validator": "type", "schema": {"type": "string"}}]


def test_main_reads_a_request_and_writes_a_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "_apply_limits", lambda cpu: None)
    stdin = io.StringIO('{"schema": {"type": "object"}, "arguments": {}}')
    stdout = io.StringIO()
    assert worker.main(["worker", "5"], stdin, stdout) == 0
    assert json.loads(stdout.getvalue()) == {"ok": True, "problems": []}


def test_run_as_a_script_reads_argv_and_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resource, "getrlimit", lambda res: (0, resource.RLIM_INFINITY))
    monkeypatch.setattr(resource, "setrlimit", lambda res, limits: None)
    monkeypatch.setattr(sys, "argv", ["worker", "5"])
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"schema": {}, "arguments": {}}'))
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    with pytest.raises(SystemExit) as exited:
        runpy.run_path(worker.__file__, run_name="__main__")

    assert exited.value.code == 0
    assert json.loads(stdout.getvalue()) == {"ok": True, "problems": []}


def test_encode_request_refuses_an_oversized_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "REQUEST_MAX_BYTES", 10)
    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        module._encode_request({"type": "object"}, {"value": "x" * 20})
    assert excinfo.value.reason == "invalid_schema"


def test_parse_response_maps_a_non_ok_response_to_invalid_schema() -> None:
    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        module._parse_response({"ok": False, "error": "invalid_schema"})
    assert excinfo.value.reason == "invalid_schema"


def test_parse_response_requires_a_problems_list() -> None:
    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        module._parse_response({"ok": True})
    assert excinfo.value.reason == "worker_failed"


def test_parse_response_preserves_mixed_object_and_array_paths() -> None:
    response: dict[str, JsonValue] = {
        "ok": True,
        "problems": [
            {"path": ["x"], "validator": "type", "schema": {"type": "string"}},
            {"path": [1, "bad"], "validator": "type", "schema": {}},
        ],
    }
    problems = module._parse_response(response)
    assert problems == [
        SchemaProblem(path=["x"], validator="type", schema={"type": "string"}),
        SchemaProblem(path=[1, "bad"], validator="type", schema={}),
    ]


@pytest.mark.security
@pytest.mark.parametrize(
    "problem",
    [
        "not-a-dict",
        {"path": None, "validator": "type", "schema": {}},
        {"path": ["x"], "validator": 3, "schema": {}},
        {"path": ["x"], "validator": "type", "schema": 3},
        {"path": ["x"], "validator": "required", "schema": {}, "missing": [3]},
    ],
)
def test_a_malformed_problem_cannot_turn_an_invalid_call_into_success(problem: JsonValue) -> None:
    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        module._parse_response({"ok": True, "problems": [problem]})
    assert excinfo.value.reason == "worker_failed"


def test_path_rejects_non_string_or_integer_parts() -> None:
    assert module._path(["a", 1]) == ["a", 1]
    assert module._path(["a", 1.5]) is None
    assert module._path(["a", True]) is None
    assert module._path("a") is None


def test_strings_requires_every_item_be_a_string() -> None:
    assert module._strings(["a", "b"]) == ["a", "b"]
    assert module._strings(["a", 1]) is None
    assert module._strings("a") is None


async def test_read_bounded_reads_to_eof_and_flags_overflow() -> None:
    reader = _FakeReader([b"abc", b"def", b"ghi"])
    data, exceeded = await module._read_bounded(cast(asyncio.StreamReader, reader), 5)
    assert data == b"abcdef"
    assert exceeded is True

    data, exceeded = await module._read_bounded(cast(asyncio.StreamReader, _FakeReader([b"ok"])), 5)
    assert data == b"ok"
    assert exceeded is False


async def test_transfer_writes_and_parses_a_reply() -> None:
    proc = _FakeProc(chunks=[b'{"ok": true, "problems": []}'])
    response = await module._transfer(cast(asyncio.subprocess.Process, proc), b"{}")
    assert response == {"ok": True, "problems": []}
    assert proc.stdin.written == b"{}"


async def test_transfer_refuses_a_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(returncode=3)
    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        await module._transfer(cast(asyncio.subprocess.Process, proc), b"{}")
    assert excinfo.value.reason == "worker_failed"


async def test_transfer_refuses_a_malformed_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    for chunks in ([b"not json"], [b"[]"], [b"\xff"]):
        proc = _FakeProc(chunks=chunks)
        with pytest.raises(SchemaValidationUnavailable) as excinfo:
            await module._transfer(cast(asyncio.subprocess.Process, proc), b"{}")
        assert excinfo.value.reason == "worker_failed"


async def test_transfer_refuses_an_oversized_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "RESPONSE_MAX_BYTES", 4)
    proc = _FakeProc(chunks=[b"x" * 20])
    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        await module._transfer(cast(asyncio.subprocess.Process, proc), b"{}")
    assert excinfo.value.reason == "worker_failed"


async def test_settle_spawn_returns_the_process_or_none() -> None:
    proc = _FakeProc()

    async def spawn() -> asyncio.subprocess.Process:
        return cast(asyncio.subprocess.Process, proc)

    done = asyncio.ensure_future(spawn())
    await asyncio.sleep(0)
    assert await module._settle_spawn(done) is proc

    async def failing() -> asyncio.subprocess.Process:
        raise OSError("boom")

    failed = asyncio.ensure_future(failing())
    await asyncio.sleep(0)
    assert await module._settle_spawn(failed) is None

    gate = asyncio.Event()

    async def slow() -> asyncio.subprocess.Process:
        await gate.wait()
        return cast(asyncio.subprocess.Process, proc)

    pending = asyncio.ensure_future(slow())
    settling = asyncio.ensure_future(module._settle_spawn(pending))
    await asyncio.sleep(0)
    gate.set()
    assert await settling is proc


async def test_kill_and_reap_tolerates_an_already_exited_child() -> None:
    class ExitedProc(_FakeProc):
        def kill(self) -> None:
            raise ProcessLookupError

    proc = ExitedProc()
    await module._kill_and_reap(cast(asyncio.subprocess.Process, proc))
    assert proc.returncode == 0


async def test_reap_on_cancel_finishes_despite_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProc()
    started = asyncio.Event()
    real_kill = module._kill_and_reap

    async def slow_kill(p: asyncio.subprocess.Process) -> None:
        started.set()
        await asyncio.sleep(0.05)
        await real_kill(p)

    monkeypatch.setattr(module, "_kill_and_reap", slow_kill)

    task = asyncio.ensure_future(module._reap_on_cancel(cast(asyncio.subprocess.Process, proc)))
    await started.wait()
    task.cancel()
    await task  # the cancellation is absorbed and the cleanup still completes
    assert proc.killed is True


async def test_the_slot_is_released_after_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = asyncio.Semaphore(1)
    monkeypatch.setattr(module, "_semaphore", lambda: gate)
    monkeypatch.setattr(module, "DEFAULT_TIMEOUT_SECONDS", 5.0)
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"x": {"$ref": "https://example.com/x.json"}},
    }
    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        await module.validate_tool_schema(schema, {"x": 1})
    assert excinfo.value.reason == "invalid_schema"
    assert not gate.locked()


async def test_valid_arguments_validate_cleanly() -> None:
    schema: dict[str, JsonValue] = {"type": "object", "properties": {"name": {"type": "string"}}}
    assert await module.validate_tool_schema(schema, {"name": "ok"}) == []


async def test_an_invalid_argument_reports_a_trimmed_problem() -> None:
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "a big description"}},
    }
    problems = await module.validate_tool_schema(schema, {"name": 5})
    assert problems == [SchemaProblem(path=["name"], validator="type", schema={"type": "string"})]
    assert "a big description" not in json.dumps([p.schema for p in problems])


async def test_a_required_field_reports_its_missing_name() -> None:
    schema: dict[str, JsonValue] = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    problems = await module.validate_tool_schema(schema, {})
    assert problems == [
        SchemaProblem(
            path=["name"], validator="required", schema={"type": "string"}, missing=["name"]
        )
    ]


async def test_a_benign_pattern_is_still_enforced() -> None:
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"x": {"type": "string", "pattern": "^[a-z]+$"}},
    }
    assert await module.validate_tool_schema(schema, {"x": "abc"}) == []
    problems = await module.validate_tool_schema(schema, {"x": "ABC"})
    assert problems == [SchemaProblem(path=["x"], validator="pattern", schema={"type": "string"})]


@pytest.mark.security
async def test_a_remote_reference_is_refused_without_io(tmp_path: Path) -> None:
    secret = tmp_path / "schema.json"
    secret.write_text('{"type": "string", "const": "secret-file-content"}')
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"x": {"$ref": secret.as_uri()}},
    }
    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        await module.validate_tool_schema(schema, {"x": "anything"})
    assert excinfo.value.reason == "invalid_schema"
    assert "secret-file-content" not in str(excinfo.value)


@pytest.mark.security
async def test_a_pathological_pattern_times_out_without_blocking_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "DEFAULT_TIMEOUT_SECONDS", 0.7)
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"x": {"type": "string", "pattern": "(a+)+b"}},
    }
    arguments: dict[str, JsonValue] = {"x": "a" * 40 + "c"}

    task = asyncio.ensure_future(module.validate_tool_schema(schema, arguments))
    loop = asyncio.get_running_loop()
    stamps = [loop.time()]
    for _ in range(15):
        await asyncio.sleep(0.02)
        stamps.append(loop.time())
    assert not task.done()
    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        await task
    assert excinfo.value.reason == "timeout"
    assert max(after - before for before, after in pairwise(stamps)) < 0.2
    assert loop.time() - stamps[0] < 2.0


async def test_a_hung_child_is_killed_on_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pidfile = tmp_path / "pid.txt"
    script = tmp_path / "hang.py"
    script.write_text(
        f"import os, time\nopen({str(pidfile)!r}, 'w').write(str(os.getpid()))\ntime.sleep(3600)\n"
    )
    monkeypatch.setattr(module, "_WORKER_PATH", script)
    monkeypatch.setattr(module, "DEFAULT_TIMEOUT_SECONDS", 0.3)

    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        await module.validate_tool_schema({}, {})

    assert excinfo.value.reason == "timeout"
    assert await _wait_gone(int(pidfile.read_text()))


async def test_cancellation_reaps_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pidfile = tmp_path / "pid.txt"
    script = tmp_path / "hang.py"
    script.write_text(
        f"import os, time\nopen({str(pidfile)!r}, 'w').write(str(os.getpid()))\ntime.sleep(3600)\n"
    )
    monkeypatch.setattr(module, "_WORKER_PATH", script)
    monkeypatch.setattr(module, "DEFAULT_TIMEOUT_SECONDS", 60.0)

    task = asyncio.ensure_future(module.validate_tool_schema({}, {}))
    for _ in range(500):
        if pidfile.exists() and pidfile.read_text():
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await _wait_gone(int(pidfile.read_text()))


async def test_a_worker_that_crashes_is_worker_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "crash.py"
    script.write_text("raise RuntimeError('boom')\n")
    monkeypatch.setattr(module, "_WORKER_PATH", script)

    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        await module.validate_tool_schema({}, {})

    assert excinfo.value.reason == "worker_failed"
    assert "boom" not in str(excinfo.value)


@pytest.mark.security
async def test_repeated_cancellation_drains_a_full_pipe_before_releasing_the_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "flood.py"
    script.write_text("import os\nwhile True:\n    os.write(1, b'x' * 65536)\n")
    monkeypatch.setattr(module, "_WORKER_PATH", script)
    monkeypatch.setattr(module, "DEFAULT_TIMEOUT_SECONDS", 30.0)
    semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(module, "_semaphore", lambda: semaphore)
    processes: list[asyncio.subprocess.Process] = []
    spawned = asyncio.Event()
    cleanup_started = asyncio.Event()
    cleanup_release = asyncio.Event()
    real_spawn = module._spawn
    real_kill = module._kill_and_reap

    async def capture_spawn(deadline: float) -> asyncio.subprocess.Process:
        proc = await real_spawn(deadline)
        processes.append(proc)
        spawned.set()
        return proc

    async def delayed_kill(proc: asyncio.subprocess.Process) -> None:
        cleanup_started.set()
        await cleanup_release.wait()
        await real_kill(proc)

    monkeypatch.setattr(module, "_spawn", capture_spawn)
    monkeypatch.setattr(module, "_kill_and_reap", delayed_kill)
    task = asyncio.create_task(module.validate_tool_schema({}, {}))
    try:
        await asyncio.wait_for(spawned.wait(), timeout=2.0)
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.wait_for(cleanup_started.wait(), timeout=2.0)
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        task.cancel()
        cleanup_release.set()
        await _bounded_completion([task], processes)

    with pytest.raises(asyncio.CancelledError):
        await task
    assert await _wait_gone(processes[0].pid)
    assert not semaphore.locked()


@pytest.mark.security
async def test_cancellation_racing_spawn_reaps_the_eventual_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "hang.py"
    script.write_text("import time\ntime.sleep(3600)\n")
    monkeypatch.setattr(module, "_WORKER_PATH", script)
    semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(module, "_semaphore", lambda: semaphore)
    real_create = asyncio.create_subprocess_exec
    processes: list[asyncio.subprocess.Process] = []
    spawned = asyncio.Event()
    release = asyncio.Event()

    async def gated_create(
        program: str, *args: str, **kwargs: object
    ) -> asyncio.subprocess.Process:
        proc = await real_create(program, *args, **kwargs)
        processes.append(proc)
        spawned.set()
        await release.wait()
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", gated_create)
    task = asyncio.create_task(module.validate_tool_schema({}, {}))
    try:
        await asyncio.wait_for(spawned.wait(), timeout=2.0)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        task.cancel()
        release.set()
        await _bounded_completion([task], processes)

    with pytest.raises(asyncio.CancelledError):
        await task
    assert await _wait_gone(processes[0].pid)
    assert not semaphore.locked()


@pytest.mark.security
async def test_admission_caps_live_children_and_cancellation_releases_every_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "hang.py"
    script.write_text("import time\ntime.sleep(3600)\n")
    monkeypatch.setattr(module, "_WORKER_PATH", script)
    monkeypatch.setattr(module, "DEFAULT_TIMEOUT_SECONDS", 30.0)
    semaphore = asyncio.Semaphore(2)
    monkeypatch.setattr(module, "_semaphore", lambda: semaphore)
    processes: list[asyncio.subprocess.Process] = []
    full = asyncio.Event()
    real_spawn = module._spawn

    async def capture_spawn(deadline: float) -> asyncio.subprocess.Process:
        proc = await real_spawn(deadline)
        processes.append(proc)
        if len(processes) == 2:
            full.set()
        return proc

    monkeypatch.setattr(module, "_spawn", capture_spawn)
    tasks = [asyncio.create_task(module.validate_tool_schema({}, {})) for _ in range(5)]
    try:
        await asyncio.wait_for(full.wait(), timeout=2.0)
        await asyncio.sleep(0.05)
        assert len(processes) == 2
    finally:
        for task in tasks:
            task.cancel()
        await _bounded_completion(tasks, processes)

    for task in tasks:
        with pytest.raises(asyncio.CancelledError):
            await task
    assert all([await _wait_gone(proc.pid) for proc in processes])
    await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
    await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
    semaphore.release()
    semaphore.release()


@pytest.mark.security
async def test_waiting_for_a_slot_counts_against_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semaphore = asyncio.Semaphore(0)
    monkeypatch.setattr(module, "_semaphore", lambda: semaphore)
    monkeypatch.setattr(module, "DEFAULT_TIMEOUT_SECONDS", 0.03)
    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        await module.validate_tool_schema({}, {})
    assert excinfo.value.reason == "timeout"
    assert semaphore.locked()


def test_a_host_without_resource_uses_the_parents_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "resource", None)
    worker._apply_limits(1)


def test_required_problems_are_not_duplicated_for_multiple_missing_fields() -> None:
    result = worker._validate({"type": "object", "required": ["first", "second"]}, {})
    problems = cast(list[dict[str, JsonValue]], result["problems"])
    assert [problem["path"] for problem in problems] == [["first"], ["second"]]


@pytest.mark.security
@pytest.mark.parametrize("kind", ["cyclic", "deep"])
def test_an_unserializable_schema_is_refused_before_starting_a_child(kind: str) -> None:
    schema: dict[str, JsonValue] = {}
    if kind == "cyclic":
        schema["cycle"] = schema
    else:
        nested: JsonValue = {}
        for _ in range(1200):
            nested = {"child": nested}
        schema["nested"] = nested
    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        module._encode_request(schema, {})
    assert excinfo.value.reason == "invalid_schema"


async def test_an_unexpected_cleanup_failure_is_not_silently_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing(proc: asyncio.subprocess.Process) -> None:
        raise RuntimeError("cleanup bug")

    monkeypatch.setattr(module, "_kill_and_reap", failing)
    with pytest.raises(RuntimeError, match="cleanup bug"):
        await module._reap_on_cancel(cast(asyncio.subprocess.Process, _FakeProc()))


async def test_an_early_pipe_failure_is_reaped_and_classified_as_worker_failed() -> None:
    class BrokenWriter(_FakeWriter):
        async def drain(self) -> None:
            raise BrokenPipeError

    proc = _FakeProc()
    proc.stdin = BrokenWriter()
    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        await module._exchange(
            cast(asyncio.subprocess.Process, proc), b"{}", asyncio.get_running_loop().time() + 1
        )
    assert excinfo.value.reason == "worker_failed"
    assert proc.killed


async def test_a_child_that_cannot_start_is_worker_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_spawn(program: str, *args: str, **kwargs: object) -> asyncio.subprocess.Process:
        raise OSError("private executable path")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_spawn)
    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        await module.validate_tool_schema({}, {})
    assert excinfo.value.reason == "worker_failed"
    assert "private executable path" not in str(excinfo.value)


async def test_a_spawn_failure_after_the_deadline_still_reports_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def delayed_failure(
        program: str, *args: str, **kwargs: object
    ) -> asyncio.subprocess.Process:
        await asyncio.sleep(0.05)
        raise OSError("delayed startup failure")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_failure)
    monkeypatch.setattr(module, "DEFAULT_TIMEOUT_SECONDS", 0.02)
    with pytest.raises(SchemaValidationUnavailable) as excinfo:
        await module.validate_tool_schema({}, {})
    assert excinfo.value.reason == "timeout"

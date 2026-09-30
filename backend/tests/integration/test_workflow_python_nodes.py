"""The two Python steps, driven through the dispatcher (#1791).

`code.python.simple` runs in the real Monty sandbox. `code.python.sandbox`
runs against an in-memory stand-in for a `sandboxd` session, so what is proved
is the job protocol: launch once, check on every later dispatch, reconnect to
the same session after a worker died, finish a half-done launch, and import
what the job left behind.
"""

from __future__ import annotations

import itertools
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.exceptions import BadRequestError
from app.db.models.workflow_file import WorkflowFile
from app.db.models.workflow_run import DispatchOutbox, ResourceRef, WorkflowRun, WorkflowRunStatus
from app.schemas.sandbox_connection import SandboxConnectionCreate
from app.services.file_storage import LocalFileStorage
from app.workflows.contracts.io import Binding, FileRef, LiteralValue, NodeOutputRef
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.nodes import _sandbox_job as job
from app.workflows.nodes.code_javascript_sandbox import _handler as js_node
from app.workflows.nodes.code_python_sandbox import _handler as sandbox_node
from tests.integration.workflow_run_support import SeededRun, drive, seed_member, seed_run

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def storage(tmp_path: Path) -> Iterator[LocalFileStorage]:
    local = LocalFileStorage(tmp_path)
    with (
        patch("app.workflows.files.get_file_storage", return_value=local),
        patch("app.services.file_storage.get_file_storage", return_value=local),
    ):
        yield local


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _chain(step: NodeInstance, *bindings: Binding) -> WorkflowGraph:
    entry, output = _node("core.input"), _node("core.output")
    nodes = (entry, step, output)
    return WorkflowGraph(
        entry_node_id=entry.id,
        nodes=nodes,
        edges=tuple(
            Edge(
                id=uuid.uuid4(),
                source_node_id=a.id,
                source_port="out",
                target_node_id=b.id,
                target_port="in",
            )
            for a, b in itertools.pairwise(nodes)
        ),
        bindings=(
            *bindings,
            Binding(
                target_node_id=output.id,
                target_field="structured",
                source=NodeOutputRef(node_id=step.id, port="out"),
            ),
        ),
    )


def _literal(node: NodeInstance, field: str, value: Any) -> Binding:
    return Binding(target_node_id=node.id, target_field=field, source=LiteralValue(value=value))


async def _failed_code(seeded: SeededRun) -> str:
    run = await drive(seeded)
    assert run.status == WorkflowRunStatus.FAILED.value, run.status
    assert run.error is not None
    return run.error["code"]


class TestTheMontyScript:
    async def test_the_last_expression_over_the_bound_args_is_the_result(self, engine):
        step = _node(
            "code.python.simple", {"code": "print('scored')\nsum(args['s']) / len(args['s'])"}
        )
        run = await drive(
            await seed_run(engine, _chain(step, _literal(step, "args", {"s": [2, 4]})))
        )
        assert run.output["structured"] == {"result": 3.0, "stdout": "scored\n"}

    async def test_a_script_with_nothing_bound_reads_empty_args(self, engine):
        step = _node("code.python.simple", {"code": "len(args)"})
        run = await drive(await seed_run(engine, _chain(step)))
        assert run.output["structured"]["result"] == 0

    @pytest.mark.parametrize(
        ("code", "error"),
        [
            ("{1, 2}", "PYTHON_OUTPUT_NOT_JSON"),
            ("undefined_name", "PYTHON_ERROR"),
            ("def (", "PYTHON_ERROR"),
        ],
        ids=["a-set", "a-name-error", "a-syntax-error"],
    )
    async def test_a_script_that_fails_or_answers_no_json_fails_the_step(self, engine, code, error):
        seeded = await seed_run(engine, _chain(_node("code.python.simple", {"code": code})))
        assert await _failed_code(seeded) == error

    async def test_a_step_with_no_script_says_so(self):
        from app.workflows.nodes.code_python_simple import _handler

        result = await _handler.handle(None, None)
        assert result.error.code == "PYTHON_NOT_CONFIGURED"


class _Session:
    """One `sandboxd` session, in memory: files, and a job that runs when told to."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.launches = 0
        self.stopped = False
        self.fail_write = False
        self.exec_exit = 0
        # What the job's files measure as, when a test wants them to look smaller
        # than they are - a file still growing after it was measured.
        self.measured_as: str | None = None
        self.reads: list[str] = []
        self.commands: list[str] = []

    # The `RemoteSandbox` surface the step uses.
    def exists(self, path: str) -> bool:
        return path in self.files

    def write(self, path: str, content: str | bytes) -> SimpleNamespace:
        if self.fail_write:
            return SimpleNamespace(path=None, error="disk full")
        self.files[path] = content.encode() if isinstance(content, str) else content
        return SimpleNamespace(path=path, error=None)

    def execute(self, command: str) -> SimpleNamespace:
        self.commands.append(command)
        if self.exec_exit:
            return SimpleNamespace(output="boom", exit_code=self.exec_exit, truncated=False)
        if "wc -c" in command:
            return SimpleNamespace(output=self._measured(), exit_code=0, truncated=False)
        if f"{job.ROOT}/job.pid" not in self.files:
            self.launches += 1
            self.files[f"{job.ROOT}/job.pid"] = b"42"
        return SimpleNamespace(output="", exit_code=0, truncated=False)

    def read_bytes(self, path: str) -> bytes:
        self.reads.append(path)
        return self.files[path]

    def _measured(self) -> str:
        if self.measured_as is not None:
            return self.measured_as
        root = job.ROOT
        outputs = [data for path, data in self.files.items() if path.startswith(f"{root}/outputs/")]
        size = {
            name: len(self.files.get(f"{root}/{name}", b"")) for name in ("result.json", "log.txt")
        }
        return (
            f"{len(outputs)}\n{sum(map(len, outputs))}\n{size['result.json']}\n{size['log.txt']}\n"
        )

    def ls_info(self, path: str) -> list[dict[str, Any]]:
        prefix = path.rstrip("/") + "/"
        found = [p for p in self.files if p.startswith(prefix)]
        entries = [{"path": p, "is_dir": False, "name": p.rsplit("/", 1)[-1]} for p in found]
        return [*entries, {"path": prefix + "sub", "is_dir": True, "name": "sub"}]

    def stop(self, purge: bool = False) -> None:
        self.stopped = purge

    def finish(
        self,
        answer: dict[str, Any],
        *,
        log: bytes = b"done\n",
        outputs: dict[str, bytes] | None = None,
    ) -> None:
        """What the runner leaves behind when the script ends."""
        root = job.ROOT
        self.files[f"{root}/result.json"] = json.dumps(answer).encode()
        self.files[f"{root}/log.txt"] = log
        for name, data in (outputs or {}).items():
            self.files[f"{root}/outputs/{name}"] = data
        self.files[f"{root}/done"] = b"done"


@pytest.fixture
def host() -> Iterator[dict[str, _Session]]:
    """Sessions by key - one per step, however many dispatches open it."""
    sessions: dict[str, _Session] = {}

    def open_session(_resolved: Any, key: str, _runtime: Any, _tenant: str) -> _Session:
        return sessions.setdefault(key, _Session())

    resolved = SimpleNamespace(kind="docker")
    with (
        patch.object(job, "_open", side_effect=open_session),
        patch.object(job, "_connection", new=AsyncMock(return_value=resolved)),
    ):
        yield sessions


async def _due_now(seeded: SeededRun) -> None:
    """Bring the step's next check forward, as the backoff passing would."""
    async with seeded.factory() as db:
        await db.execute(
            update(DispatchOutbox)
            .where(DispatchOutbox.workflow_run_id == seeded.run.id)
            .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()


def _sandbox_step(**config: Any) -> NodeInstance:
    return _node("code.python.sandbox", {"code": "result = 1", **config})


class TestTheSandboxJob:
    async def test_it_launches_once_is_checked_on_and_imports_what_the_job_made(self, engine, host):
        step = _sandbox_step()
        seeded = await seed_run(engine, _chain(step, _literal(step, "args", {"n": 2})))

        run = await drive(seeded)
        assert run.status == WorkflowRunStatus.WAITING_RETRY.value
        (session,) = host.values()
        assert session.launches == 1
        assert json.loads(session.files[f"{job.ROOT}/args.json"]) == {"n": 2}

        await _due_now(seeded)
        assert (await drive(seeded)).status == WorkflowRunStatus.WAITING_RETRY.value
        assert session.launches == 1

        session.finish({"ok": True, "result": {"rows": 3}}, outputs={"report.csv": b"a,b\n1,2\n"})
        await _due_now(seeded)
        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        answer = run.output["structured"]
        assert answer["result"] == {"rows": 3} and answer["stdout_tail"] == "done\n"
        (produced,) = answer["output_files"]
        async with seeded.factory() as db:
            names = sorted(
                row.filename for row in (await db.execute(select(WorkflowFile))).scalars().all()
            )
        assert names == ["log.txt", "report.csv"]
        assert produced["content_type"] == "text/plain"
        assert session.stopped is True and len(host) == 1

    async def test_a_launch_cut_short_before_it_started_is_completed_not_waited_on(
        self, engine, host
    ):
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        key = job.session_key(f"{seeded.org.id}:{seeded.run.id}:{seeded.graph.nodes[1].id}:[]")
        # A worker that staged the script and died before starting it.
        half = host.setdefault(key, _Session())
        half.files[f"{job.ROOT}/main.py"] = b"result = 1"

        await drive(seeded)

        assert half.launches == 1 and len(host) == 1

    async def test_a_job_past_its_time_is_stopped(self, engine, host):
        seeded = await seed_run(engine, _chain(_sandbox_step(timeout_seconds=60)))
        await drive(seeded)
        (session,) = host.values()
        session.files[f"{job.ROOT}/started_at"] = (
            (datetime.now(UTC) - timedelta(minutes=5)).isoformat().encode()
        )
        await _due_now(seeded)
        assert await _failed_code(seeded) == "PYTHON_SANDBOX_TIMEOUT"
        assert session.stopped is True

    @pytest.mark.parametrize(
        ("answer", "code"),
        [
            ({"ok": False, "error": "ZeroDivisionError: division by zero"}, "PYTHON_ERROR"),
            ({"ok": False, "not_json": True, "error": "set"}, "PYTHON_OUTPUT_NOT_JSON"),
        ],
        ids=["an-exception", "not-json"],
    )
    async def test_a_script_that_failed_fails_the_step_with_its_log_kept(
        self, engine, host, answer, code
    ):
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish(answer)
        await _due_now(seeded)
        assert await _failed_code(seeded) == code
        async with seeded.factory() as db:
            (log,) = (await db.execute(select(WorkflowFile))).scalars().all()
        assert log.filename == "log.txt"

    async def test_a_job_that_wrote_too_much_imports_nothing(self, engine, host, monkeypatch):
        monkeypatch.setattr(job, "MAX_OUTPUT_FILES", 1)
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish({"ok": True, "result": None}, outputs={"a": b"1", "b": b"2"})
        await _due_now(seeded)
        assert await _failed_code(seeded) == "PYTHON_OUTPUT_TOO_LARGE"
        async with seeded.factory() as db:
            assert (await db.execute(select(WorkflowFile))).scalars().all() == []

    async def test_leftovers_over_the_bounds_are_refused_before_any_is_fetched(
        self, engine, host, monkeypatch
    ):
        monkeypatch.setattr(job, "MAX_LOG_BYTES", 4)
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish({"ok": True, "result": None}, log=b"far too chatty")
        await _due_now(seeded)

        assert await _failed_code(seeded) == "PYTHON_OUTPUT_TOO_LARGE"
        assert session.reads == [] and session.stopped is True

    async def test_a_file_that_grew_after_it_was_measured_is_still_refused(
        self, engine, host, monkeypatch
    ):
        monkeypatch.setattr(job, "MAX_OUTPUT_BYTES", 8)
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish({"ok": True, "result": None}, outputs={"big.bin": b"x" * 64})
        session.measured_as = "1\n0\n0\n0\n"
        await _due_now(seeded)

        assert await _failed_code(seeded) == "PYTHON_OUTPUT_TOO_LARGE"
        async with seeded.factory() as db:
            assert (await db.execute(select(WorkflowFile))).scalars().all() == []

    async def test_leftovers_that_cannot_be_measured_are_checked_again_later(self, engine, host):
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish({"ok": True, "result": None})
        session.measured_as = "not a number"
        await _due_now(seeded)

        run = await drive(seeded)
        assert run.status == WorkflowRunStatus.WAITING_RETRY.value
        assert session.reads == [] and session.stopped is False

    async def test_a_job_with_no_log_answers_with_an_empty_one(self, engine, host):
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish({"ok": True, "result": 7})
        del session.files[f"{job.ROOT}/log.txt"]
        await _due_now(seeded)
        run = await drive(seeded)
        assert run.output["structured"]["stdout_tail"] == ""

    async def test_a_host_that_cannot_stage_or_start_is_retried(self, engine, host):
        for failure in ("write", "exec"):
            host.clear()
            seeded = await seed_run(engine, _chain(_sandbox_step()))
            session = host.setdefault(
                job.session_key(f"{seeded.org.id}:{seeded.run.id}:{seeded.graph.nodes[1].id}:[]"),
                _Session(),
            )
            session.fail_write = failure == "write"
            session.exec_exit = 1 if failure == "exec" else 0
            run = await drive(seeded)
            assert run.status == WorkflowRunStatus.WAITING_RETRY.value
            assert session.launches == 0

    async def test_the_run_s_input_files_are_staged_by_name(self, engine, host, storage):
        member = await _member(engine)
        earlier = await seed_run(engine, _chain(_node("debug.echo")), member=member)
        ref = await _stored(engine, storage, earlier.run, b"a,b\n", "text/csv", "leads.csv")
        step = _sandbox_step()
        seeded = await seed_run(
            engine,
            _chain(
                step,
                Binding(
                    target_node_id=step.id,
                    target_field="files",
                    source=LiteralValue(value=[ref.model_dump(mode="json")]),
                ),
            ),
            member=member,
        )
        await _import(seeded, ref)
        await drive(seeded)
        (session,) = host.values()
        assert session.files[f"{job.ROOT}/inputs/00-leads.csv"] == b"a,b\n"

    @pytest.mark.security
    async def test_a_file_the_run_was_not_given_is_never_staged(self, engine, host, storage):
        other = await seed_run(engine, _chain(_node("debug.echo")))
        ref = await _stored(engine, storage, other.run, b"secret", "text/plain", "x.txt")
        step = _sandbox_step()
        seeded = await seed_run(
            engine,
            _chain(
                step,
                Binding(
                    target_node_id=step.id,
                    target_field="files",
                    source=LiteralValue(value=[ref.model_dump(mode="json")]),
                ),
            ),
        )
        assert await _failed_code(seeded) == "FILE_NOT_FOUND"
        (session,) = host.values()
        assert session.launches == 0

    async def test_inputs_over_the_limit_are_refused(self, engine, host, storage, monkeypatch):
        monkeypatch.setattr(job, "MAX_INPUT_BYTES", 5)
        member = await _member(engine)
        earlier = await seed_run(engine, _chain(_node("debug.echo")), member=member)
        refs = [
            await _stored(engine, storage, earlier.run, b"1234", "text/plain", None)
            for _ in range(2)
        ]
        step = _sandbox_step()
        seeded = await seed_run(
            engine,
            _chain(
                step,
                Binding(
                    target_node_id=step.id,
                    target_field="files",
                    source=LiteralValue(value=[r.model_dump(mode="json") for r in refs]),
                ),
            ),
            member=member,
        )
        for ref in refs:
            await _import(seeded, ref)
        assert await _failed_code(seeded) == "FILE_TOO_LARGE"


class TestTheSandboxHost:
    async def test_a_host_that_is_not_there_is_retried(self, engine):
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        resolved = SimpleNamespace(kind="docker")

        def unreachable(*_args: Any) -> Any:
            raise RuntimeError("Could not reach the sandbox service")

        with (
            patch.object(job, "_connection", new=AsyncMock(return_value=resolved)),
            patch.object(job, "_open", side_effect=unreachable),
        ):
            run = await drive(seeded)
        assert run.status == WorkflowRunStatus.WAITING_RETRY.value

    async def test_no_usable_connection_or_the_wrong_kind_fails_clearly(self, engine):
        for connection, code in [
            (
                AsyncMock(side_effect=BadRequestError(message="No sandbox connection")),
                "SANDBOX_UNAVAILABLE",
            ),
            (AsyncMock(return_value=SimpleNamespace(kind="daytona")), "SANDBOX_UNAVAILABLE"),
        ]:
            seeded = await seed_run(engine, _chain(_sandbox_step()))
            with patch.object(job, "_connection", new=connection):
                assert await _failed_code(seeded) == code

    async def test_the_real_connection_is_resolved_for_the_run_s_member(self, engine):
        seeded = await seed_run(engine, _chain(_sandbox_step()))
        assert await _failed_code(seeded) == "SANDBOX_UNAVAILABLE"

    async def test_publishing_checks_the_author_s_connection(self, engine):
        member = await _member(engine)
        seeded = await seed_run(engine, _chain(_node("debug.echo")), member=member)
        config = sandbox_node.PythonSandboxConfig(code="result = 1")
        async with async_sessionmaker(engine)() as db:
            (problem,) = await sandbox_node.check_resources(db, seeded.ctx, config)
            assert problem[0] == "connection_id"
            assert await sandbox_node.check_resources(db, seeded.ctx, MagicMock()) == []
            with patch.object(
                job.SandboxConnectionService,
                "resolve",
                new=AsyncMock(return_value=SimpleNamespace(kind="daytona")),
            ):
                (wrong,) = await sandbox_node.check_resources(db, seeded.ctx, config)
                assert "sandboxd" in wrong[1]
            with patch.object(
                job.SandboxConnectionService,
                "resolve",
                new=AsyncMock(return_value=SimpleNamespace(kind="docker")),
            ):
                assert await sandbox_node.check_resources(db, seeded.ctx, config) == []

    async def test_a_session_is_opened_on_the_connection_s_address_and_runtime(self):
        resolved = SimpleNamespace(
            token="t", row=SimpleNamespace(base_url="http://sandboxd:8080", default_runtime="py")
        )
        with patch("pydantic_ai_backends.remote.RemoteSandbox") as remote:
            job._open(resolved, "wf-key", None, "org")
        assert remote.call_args.kwargs["session_id"] == "wf-key"
        assert remote.call_args.kwargs["runtime"] == "py"

    async def test_a_step_with_no_script_says_so(self):
        result = await sandbox_node.handle(None, None)
        assert result.error.code == "PYTHON_NOT_CONFIGURED"


def _js_step(**config: Any) -> NodeInstance:
    return _node("code.javascript.sandbox", {"code": "return args.n * 2;", **config})


class TestTheJavaScriptJob:
    """The same job protocol, run by Node: what differs is what is staged and started."""

    async def test_it_stages_a_node_runner_and_answers_with_what_the_script_returned(
        self, engine, host
    ):
        step = _js_step()
        seeded = await seed_run(engine, _chain(step, _literal(step, "args", {"n": 2})))

        assert (await drive(seeded)).status == WorkflowRunStatus.WAITING_RETRY.value
        (session,) = host.values()
        assert session.files[f"{job.ROOT}/main.js"] == b"return args.n * 2;"
        assert session.files[f"{job.ROOT}/run.js"] == js_node.RUNNER.encode()
        assert any("nohup node run.js" in command for command in session.commands)

        session.finish({"ok": True, "result": 4}, log=b"logged\n")
        await _due_now(seeded)
        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        answer = run.output["structured"]
        assert answer["result"] == 4 and answer["stdout_tail"] == "logged\n"

    @pytest.mark.parametrize(
        ("answer", "code"),
        [
            ({"ok": False, "error": "TypeError: bad"}, "JAVASCRIPT_ERROR"),
            ({"ok": False, "not_json": True, "error": "bigint"}, "JAVASCRIPT_OUTPUT_NOT_JSON"),
        ],
        ids=["a-throw", "not-json"],
    )
    async def test_a_script_that_failed_fails_with_its_own_code(self, engine, host, answer, code):
        seeded = await seed_run(engine, _chain(_js_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish(answer)
        await _due_now(seeded)
        assert await _failed_code(seeded) == code

    async def test_a_job_past_its_time_says_it_was_javascript(self, engine, host):
        seeded = await seed_run(engine, _chain(_js_step(timeout_seconds=60)))
        await drive(seeded)
        (session,) = host.values()
        session.files[f"{job.ROOT}/started_at"] = (
            (datetime.now(UTC) - timedelta(minutes=5)).isoformat().encode()
        )
        await _due_now(seeded)
        assert await _failed_code(seeded) == "JAVASCRIPT_SANDBOX_TIMEOUT"

    async def test_a_job_over_its_bounds_says_it_was_javascript(self, engine, host, monkeypatch):
        monkeypatch.setattr(job, "MAX_OUTPUT_FILES", 0)
        seeded = await seed_run(engine, _chain(_js_step()))
        await drive(seeded)
        (session,) = host.values()
        session.finish({"ok": True, "result": 1}, outputs={"a.txt": b"a"})
        await _due_now(seeded)
        assert await _failed_code(seeded) == "JAVASCRIPT_OUTPUT_TOO_LARGE"

    async def test_publishing_checks_the_author_s_connection_and_needs_a_script(self, engine):
        member = await _member(engine)
        seeded = await seed_run(engine, _chain(_node("debug.echo")), member=member)
        config = js_node.JavaScriptSandboxConfig(code="return 1;")
        async with async_sessionmaker(engine)() as db:
            (problem,) = await js_node.check_resources(db, seeded.ctx, config)
            assert problem[0] == "connection_id"
            assert await js_node.check_resources(db, seeded.ctx, MagicMock()) == []
        result = await js_node.handle(None, None)
        assert result.error.code == "JAVASCRIPT_NOT_CONFIGURED"


def test_a_script_runs_on_the_kind_a_sandboxd_connection_is_registered_as():
    # Regression: the steps once asked for a kind "sandboxd" that no connection
    # can be registered as, so every real host was refused as unavailable.
    kinds = get_args(SandboxConnectionCreate.model_fields["kind"].annotation)
    assert job.SANDBOXD_KIND in kinds
    assert "daytona" in kinds and job.SANDBOXD_KIND != "daytona"


async def _member(engine: AsyncEngine):
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        member = await seed_member(db)
        await db.commit()
    return member


async def _stored(
    engine: AsyncEngine,
    storage: LocalFileStorage,
    run: WorkflowRun,
    data: bytes,
    content_type: str,
    filename: str | None,
) -> FileRef:
    file_id = uuid.uuid4()
    path = f"workflow-files/{run.organization_id}/{run.id}/{file_id}"
    await storage.save_at(path, data)
    async with async_sessionmaker(engine)() as db:
        db.add(
            WorkflowFile(
                id=file_id,
                organization_id=run.organization_id,
                workflow_run_id=run.id,
                storage_path=path,
                content_type=content_type,
                byte_size=len(data),
                filename=filename,
            )
        )
        await db.commit()
    return FileRef(file_id=file_id, content_type=content_type, byte_size=len(data))


async def _import(seeded: SeededRun, ref: FileRef) -> None:
    async with seeded.factory() as db:
        db.add(
            ResourceRef(
                organization_id=seeded.org.id,
                workflow_run_id=seeded.run.id,
                kind="file",
                ref=ref.model_dump(mode="json"),
            )
        )
        await db.commit()

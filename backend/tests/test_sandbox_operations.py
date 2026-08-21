"""What an agent did in a sandbox, recorded here rather than in the service.

The service's own log is a 200-entry ring buffer in its process memory, so what it
dropped cannot be asked for and a restart loses every log on the host
(agenticos#1061). These are the two halves of the answer: the wrapper that records
an operation, and the read that pages through it.

The property that matters most is what is *not* written. These rows are readable by
everyone who can see the sandbox, so a file's contents or a command's output in one
would turn an audit into a way to read somebody's work - and the service draws that
line deliberately, so the product has to as well.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.sandbox._recording import RecordingBackend

pytestmark = pytest.mark.anyio


class _Recorded:
    """A session that keeps what was added, which is the whole assertion."""

    def __init__(self) -> None:
        self.rows: list[object] = []

    def add(self, row: object) -> None:
        self.rows.append(row)


def _wrap(backend: object, db: _Recorded | None = None) -> tuple[RecordingBackend, _Recorded]:
    session = db or _Recorded()
    return (
        RecordingBackend(
            backend,
            db=session,  # type: ignore[arg-type]  - only `add` is used
            organization_id=uuid.uuid4(),
            session_key="xc-1",
            agent_id=uuid.uuid4(),
        ),
        session,
    )


class TestWhatIsRecorded:
    async def test_a_write_records_its_path_and_never_its_content(self):
        """The single most important assertion in this file."""
        backend = MagicMock()
        backend.write = MagicMock(return_value=SimpleNamespace(error=None))
        recorder, session = _wrap(backend)

        recorder.write("uploads/report.csv", "month,total\\njan,10")

        [row] = session.rows
        assert row.op == "write"
        assert row.target == "uploads/report.csv"
        assert "month" not in row.detail
        assert "jan" not in row.detail

    async def test_a_command_records_itself_and_never_its_output(self):
        backend = MagicMock()
        backend.execute = MagicMock(
            return_value=SimpleNamespace(exit_code=0, output="root:x:0:0:root:/root:/bin/sh")
        )
        recorder, session = _wrap(backend)

        recorder.execute("cat /etc/passwd")

        [row] = session.rows
        assert row.target == "cat /etc/passwd"
        assert "root" not in row.detail

    async def test_a_read_records_a_size_rather_than_the_bytes(self):
        backend = MagicMock()
        backend.read = MagicMock(return_value="a secret the model asked for")
        recorder, session = _wrap(backend)

        recorder.read("notes.md")

        [row] = session.rows
        assert row.detail == "28 bytes"
        assert "secret" not in row.detail

    async def test_a_listing_records_how_many_it_found(self):
        backend = MagicMock()
        backend.ls_info = MagicMock(return_value=[{"path": "a"}, {"path": "b"}])
        recorder, session = _wrap(backend)

        recorder.ls_info(".")

        assert session.rows[0].detail == "2 results"

    async def test_the_agent_and_the_run_are_named(self):
        """The two facts the service's own log cannot carry, and the two somebody
        auditing a sandbox actually asks for."""
        backend = MagicMock()
        backend.write = MagicMock(return_value=SimpleNamespace(error=None))
        recorder, session = _wrap(backend)
        run = uuid.uuid4()
        recorder.run_id = run

        recorder.write("a.txt", "x")

        assert session.rows[0].run_id == run
        assert session.rows[0].agent_id is not None

    async def test_a_command_longer_than_the_column_is_truncated_not_dropped(self):
        """A command is whatever the model wrote. A log that lost an operation
        because its command was long would be missing the very entry somebody came
        for."""
        backend = MagicMock()
        backend.execute = MagicMock(return_value=SimpleNamespace(exit_code=0, output=""))
        recorder, session = _wrap(backend)

        recorder.execute("echo " + "x" * 5_000)

        assert len(session.rows[0].target) == 512

    async def test_a_non_string_target_is_recorded_as_something(self):
        backend = MagicMock()
        backend.read = MagicMock(return_value="")
        recorder, session = _wrap(backend)

        recorder.read(None)

        assert session.rows[0].target == "None"

    async def test_a_call_with_no_arguments_records_an_empty_target(self):
        backend = MagicMock()
        backend.ls_info = MagicMock(return_value=[])
        recorder, session = _wrap(backend)

        recorder.ls_info()

        assert session.rows[0].target == ""


class TestWhatIsNotRecorded:
    async def test_a_question_is_delegated_untouched(self):
        """`exists` is a question rather than an operation, and a log full of them
        would bury the writes somebody came to read."""
        backend = MagicMock()
        backend.exists = MagicMock(return_value=True)
        recorder, session = _wrap(backend)

        assert recorder.exists("a.txt") is True
        assert session.rows == []

    async def test_a_plain_attribute_passes_through(self):
        backend = SimpleNamespace(session_id="xc-1")
        recorder, _ = _wrap(backend)

        assert recorder.session_id == "xc-1"


class TestFailuresAndShapes:
    async def test_a_refused_write_is_recorded_as_a_failure(self):
        """A full document answers rather than raising, so reading every
        non-exception as a success would record a write that never happened."""
        backend = MagicMock()
        backend.write = MagicMock(return_value=SimpleNamespace(error="workspace is full"))
        recorder, session = _wrap(backend)

        recorder.write("a.txt", "x")

        assert session.rows[0].ok is False
        # And not the backend's own words: `refused`, written here.
        assert session.rows[0].detail == "refused"

    async def test_a_raising_call_is_recorded_and_re_raised(self):
        backend = MagicMock()
        backend.execute = MagicMock(side_effect=RuntimeError("the host went away"))
        recorder, session = _wrap(backend)

        with pytest.raises(RuntimeError):
            recorder.execute("ls")

        assert session.rows[0].ok is False
        # The class, not the message: a shell's message is its output.
        assert session.rows[0].detail == "RuntimeError"
        assert "went away" not in session.rows[0].detail

    async def test_an_async_backend_stays_async(self):
        """A container's is synchronous and `ensure_async` wraps it later; a
        `StateBackend`'s is plain. Returning the wrong shape for `execute` made
        `asyncio.to_thread` hand back a coroutine nobody awaited, so the prune
        never ran and its caller read the missing exit code as success."""
        backend = MagicMock()
        backend.write = AsyncMock(return_value=SimpleNamespace(error=None))
        recorder, session = _wrap(backend)

        await recorder.write("a.txt", "x")

        assert session.rows[0].op == "write"

    async def test_an_async_failure_is_recorded_and_re_raised(self):
        backend = MagicMock()
        backend.write = AsyncMock(side_effect=ValueError("no"))
        recorder, session = _wrap(backend)

        with pytest.raises(ValueError):
            await recorder.write("a.txt", "x")

        assert session.rows[0].detail == "ValueError"

    async def test_a_sync_call_is_not_turned_into_a_coroutine(self):
        import inspect

        backend = MagicMock()
        backend.execute = MagicMock(return_value=SimpleNamespace(exit_code=0, output=""))
        recorder, _ = _wrap(backend)

        answered = recorder.execute("ls")

        assert not inspect.isawaitable(answered)
        assert answered.exit_code == 0

    async def test_a_session_that_refuses_the_row_does_not_fail_the_operation(self):
        """The log is an audit and the operation is the work: losing an entry is a
        log line, not a reason to fail an agent's write."""

        class _Broken:
            def add(self, row: object) -> None:
                raise RuntimeError("no session")

        backend = MagicMock()
        backend.write = MagicMock(return_value=SimpleNamespace(error=None))
        recorder = RecordingBackend(
            backend,
            db=_Broken(),  # type: ignore[arg-type]
            organization_id=uuid.uuid4(),
            session_key="xc-1",
            agent_id=None,
        )

        written = recorder.write("a.txt", "x")
        assert written.error is None

    async def test_a_nonzero_exit_is_recorded_as_a_failure_with_its_status(self):
        """`false`, a failing compiler, a refused script: a command's failure is
        its exit code, carried without an `error` and without an exception - and
        an audit log that painted those green would say the sandbox did what it
        visibly did not. The numeric status is the one safe detail (#423)."""
        backend = MagicMock()
        backend.execute = MagicMock(return_value=SimpleNamespace(exit_code=2, output="boom"))
        recorder, session = _wrap(backend)

        recorder.execute("false")

        assert session.rows[0].ok is False
        assert session.rows[0].detail == "exit 2"
        assert "boom" not in session.rows[0].detail

    async def test_the_run_the_workspace_was_opened_for_names_every_row(self):
        """The runner mints the run row before it opens the workspace, so the id
        rides in at construction - without it every row said run_id=null and an
        auditor could not link an operation to the execution that performed it."""
        run_id = uuid.uuid4()
        backend = MagicMock()
        backend.write = MagicMock(return_value=SimpleNamespace(error=None))
        session = _Recorded()
        recorder = RecordingBackend(
            backend,
            db=session,  # type: ignore[arg-type]
            organization_id=uuid.uuid4(),
            session_key="xc-1",
            agent_id=None,
            run_id=run_id,
        )

        recorder.write("a.txt", "x")

        assert session.rows[0].run_id == run_id


class TestReadingTheLog:
    def _service(self, rows: list[object], *, total: int = 0):
        from app.services.sandbox_connection import SandboxConnectionService

        return SandboxConnectionService(MagicMock()), rows, total

    async def _read(self, rows, total, names=None, **kwargs):
        from app.core.permissions import AuthContext, OrgRoleName
        from app.services.sandbox_connection import SandboxConnectionService

        service = SandboxConnectionService(MagicMock())
        ctx = AuthContext(
            user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER.value
        )
        with (
            patch("app.services.sandbox_connection.sandbox_operation_repo") as repo,
            patch("app.services.sandbox_connection.agent_repo") as agents,
        ):
            repo.list_for_session = AsyncMock(return_value=(rows, total))
            repo.operations_seen = AsyncMock(return_value=["execute", "write"])
            agents.get_many = AsyncMock(return_value=names or {})
            return await service.operations(ctx, **kwargs), repo

    def _row(self, **overrides):
        fields: dict[str, object] = {
            "id": uuid.uuid4(),
            "created_at": datetime.now(UTC),
            "op": "write",
            "target": "a.txt",
            "ok": True,
            "detail": "",
            "duration_ms": 12,
            "session_key": "xc-1",
            "agent_id": None,
            "run_id": None,
        }
        fields.update(overrides)
        return SimpleNamespace(**fields)

    async def test_it_answers_a_page_and_a_total(self):
        """The total is what makes the pager honest - the service's own log could
        only say how much of its buffer was left."""
        read, _ = await self._read([self._row()], 137)

        assert len(read.items) == 1
        assert read.total == 137

    async def test_the_filter_offers_only_the_operations_the_log_holds(self):
        read, _ = await self._read([], 0)

        assert read.operations == ["execute", "write"]

    async def test_the_agents_name_is_resolved_for_the_page(self):
        agent_id = uuid.uuid4()
        read, _ = await self._read(
            [self._row(agent_id=agent_id)], 1, names={agent_id: SimpleNamespace(name="jarvis")}
        )

        assert read.items[0].agent_name == "jarvis"

    async def test_an_agent_deleted_since_still_leaves_its_operations_readable(self):
        """`SET NULL` on the FK, and the read must survive it: the record of what
        happened is the point of recording it."""
        read, _ = await self._read([self._row(agent_id=uuid.uuid4())], 1, names={})

        assert read.items[0].agent_name is None

    async def test_the_filters_reach_the_query_rather_than_the_page(self):
        """Which is the difference this table exists for: the dialog's search and
        filter narrow a query, not an array the client already holds."""
        _, repo = await self._read(
            [], 0, session_key="xc-9", op="execute", failed_only=True, query="rm", skip=50
        )

        asked = repo.list_for_session.await_args.kwargs
        assert asked["session_key"] == "xc-9"
        assert asked["op"] == "execute"
        assert asked["failed_only"] is True
        assert asked["query"] == "rm"
        assert asked["skip"] == 50


class TestRetention:
    async def test_the_sweep_deletes_past_the_window(self):
        from app.db.models.sandbox_operation import OPERATION_RETENTION_DAYS
        from app.worker.tasks import trigger_tasks

        session = MagicMock()

        class _Ctx:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *exc):
                return False

        with (
            patch.object(trigger_tasks, "get_worker_db_context", lambda: _Ctx()),
            patch("app.repositories.sandbox_operation.delete_older_than") as sweep,
        ):
            sweep.return_value = 4
            await trigger_tasks.sweep_sandbox_operations_flow()

        cutoff = sweep.await_args.kwargs["cutoff"]
        expected = datetime.now(UTC) - timedelta(days=OPERATION_RETENTION_DAYS)
        assert abs((cutoff - expected).total_seconds()) < 60

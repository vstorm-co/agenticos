"""What an agent did in a sandbox, recorded here rather than in the service.

The service's own log is a 200-entry ring buffer in its process memory, so what it
dropped cannot be asked for and a restart loses every log on the host
(agenticos#1061). These are the two halves of the answer: the wrapper that records
an operation, and the read that pages through it.

The property that matters most is what is *not* written. These rows are readable by
everyone who can see the sandbox, so a file's contents or a command's output in one
would turn an audit into a way to read somebody's work - and the service draws that
line deliberately, so the product has to as well.

The recorder wraps a real local workspace in a temporary directory: what it records
is what a real backend answered, including the way a real one fails.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.workspaces import (
    LocalWorkspaceBackend,
    Workspace,
    WorkspaceTimeoutError,
    WorkspaceUnavailableError,
)

from app.agents.capabilities.sandbox._recording import RecordingWorkspace
from app.db.models.sandbox_operation import SandboxOperation

pytestmark = pytest.mark.anyio


class _Recorded:
    """A session that keeps what was added, which is the whole assertion."""

    def __init__(self) -> None:
        self.rows: list[SandboxOperation] = []

    def add(self, row: SandboxOperation) -> None:
        self.rows.append(row)


def _wrap(
    root: Path, db: _Recorded | None = None, *, run_id: uuid.UUID | None = None
) -> tuple[RecordingWorkspace, _Recorded]:
    session = db or _Recorded()
    return (
        RecordingWorkspace(
            Workspace(LocalWorkspaceBackend(root)),
            db=session,  # type: ignore[arg-type]  - only `add` is used
            organization_id=uuid.uuid4(),
            session_key="xc-1",
            agent_id=uuid.uuid4(),
            run_id=run_id,
        ),
        session,
    )


class TestWhatIsRecorded:
    async def test_a_write_records_its_path_and_never_its_content(self, tmp_path: Path):
        """The single most important assertion in this file."""
        recorder, session = _wrap(tmp_path)

        await recorder.write_text("report.csv", "month,total\njan,10")

        (row,) = session.rows
        assert row.op == "write"
        assert row.target == "report.csv"
        assert row.ok is True
        assert row.detail == "18 bytes"
        assert "jan" not in f"{row.target}{row.detail}"

    async def test_a_command_records_itself_and_never_its_output(self, tmp_path: Path):
        recorder, session = _wrap(tmp_path)

        result = await recorder.run(["echo", "a secret the command printed"])

        assert "secret" in result.stdout
        (row,) = session.rows
        assert row.op == "execute"
        assert row.target == "echo 'a secret the command printed'"
        assert row.detail == ""

    async def test_a_shell_command_is_recorded_as_written(self, tmp_path: Path):
        """The console's `execute` hands the model's command to a shell as one
        string, so that string is the operation."""
        recorder, session = _wrap(tmp_path)

        await recorder.run("ls | wc -l", shell=True)  # noqa: S604 - the shell form is the case under test

        assert session.rows[0].target == "ls | wc -l"

    async def test_a_read_records_a_size_rather_than_the_bytes(self, tmp_path: Path):
        (tmp_path / "notes.txt").write_text("a secret the model asked for")
        recorder, session = _wrap(tmp_path)

        assert await recorder.read_text("notes.txt") == "a secret the model asked for"

        (row,) = session.rows
        assert (row.op, row.target, row.detail) == ("read", "notes.txt", "28 bytes")

    async def test_a_listing_records_how_many_it_found(self, tmp_path: Path):
        (tmp_path / "a").write_text("")
        (tmp_path / "b").write_text("")
        recorder, session = _wrap(tmp_path)

        await recorder.list_dir(".")

        assert (session.rows[0].op, session.rows[0].detail) == ("ls_info", "2 results")

    async def test_a_directory_made_and_a_path_removed_are_operations(self, tmp_path: Path):
        """Both change the workspace, which is what the log is for."""
        recorder, session = _wrap(tmp_path)

        await recorder.make_dir("out")
        await recorder.remove("out")

        assert [(row.op, row.target, row.ok) for row in session.rows] == [
            ("mkdir", "out", True),
            ("remove", "out", True),
        ]

    async def test_the_agent_and_the_run_are_named(self, tmp_path: Path):
        """The run every row is attributed to rides in at construction: the runner
        mints the run row before it opens the workspace, and without it every row
        said run_id=null and an auditor could not link an operation to the
        execution that performed it."""
        run_id = uuid.uuid4()
        recorder, session = _wrap(tmp_path, run_id=run_id)

        await recorder.write_text("a.txt", "x")

        (row,) = session.rows
        assert row.run_id == run_id
        assert row.agent_id is not None
        assert row.session_key == "xc-1"

    async def test_a_command_longer_than_the_column_is_truncated_not_dropped(self, tmp_path: Path):
        """A log that dropped an operation because its command was long would be
        missing exactly the entry somebody is looking for."""
        recorder, session = _wrap(tmp_path)

        await recorder.run(["true", "x" * 2000])

        assert len(session.rows[0].target) == 512


class TestWhatIsNotRecorded:
    async def test_a_question_is_not_an_operation(self, tmp_path: Path):
        """`exists` and `stat` ask about the workspace without changing or reading
        it, and a log full of them would bury the writes somebody came to read."""
        (tmp_path / "a.txt").write_text("x")
        recorder, session = _wrap(tmp_path)

        assert await recorder.exists("a.txt") is True
        assert (await recorder.stat("a.txt")).size == 1

        assert session.rows == []

    async def test_the_wrapped_workspace_is_still_what_is_attached(self, tmp_path: Path):
        """Recording changes what is logged, not which workspace the run is in."""
        inner = Workspace(LocalWorkspaceBackend(tmp_path))
        recorder = RecordingWorkspace(
            inner,
            db=_Recorded(),  # type: ignore[arg-type]
            organization_id=uuid.uuid4(),
            session_key="xc-1",
            agent_id=None,
        )

        assert recorder.ref == inner.ref
        assert recorder.backend is inner.backend


class TestFailures:
    async def test_a_refused_operation_is_recorded_and_re_raised(self, tmp_path: Path):
        """By its class: the message of a filesystem error names the path, and the
        message of a client's error can carry the failing request (#423)."""
        recorder, session = _wrap(tmp_path)

        with pytest.raises(FileNotFoundError):
            await recorder.read_bytes("missing.txt")

        (row,) = session.rows
        assert (row.op, row.ok, row.detail) == ("read", False, "FileNotFoundError")

    async def test_a_command_that_times_out_records_the_class_and_not_its_output(
        self, tmp_path: Path
    ):
        """A timeout carries what the command had printed so far; the row must not."""
        recorder, session = _wrap(tmp_path)

        with pytest.raises(WorkspaceTimeoutError):
            await recorder.run(["sh", "-c", "echo partial secret; sleep 5"], timeout=0.5)

        (row,) = session.rows
        assert (row.ok, row.detail) == (False, "WorkspaceTimeoutError")

    async def test_a_nonzero_exit_is_recorded_as_a_failure_with_its_status(self, tmp_path: Path):
        """`false`, a failing compiler, a refused script: a command's failure is
        its exit code, carried without an exception - and an audit log that painted
        those green would say the sandbox did what it visibly did not. The numeric
        status is the one safe detail (#423)."""
        recorder, session = _wrap(tmp_path)

        result = await recorder.run(["sh", "-c", "echo boom; exit 2"])

        assert result.exit_code == 2
        (row,) = session.rows
        assert (row.ok, row.detail) == (False, "exit 2")

    async def test_a_session_that_refuses_the_row_does_not_fail_the_operation(self, tmp_path: Path):
        """The log is an audit and the operation is the work: losing an entry is a
        log line, not a reason to fail an agent's write."""

        class _Broken(_Recorded):
            def add(self, row: SandboxOperation) -> None:
                raise RuntimeError("no session")

        recorder, _ = _wrap(tmp_path, db=_Broken())

        await recorder.write_text("a.txt", "x")

        assert (tmp_path / "a.txt").read_text() == "x"


class TestALostSession:
    @pytest.mark.parametrize(
        ("question", "args"),
        [
            ("working_dir", ()),
            ("stat", ("a.txt",)),
            ("exists", ("a.txt",)),
            ("realpath", ("a.txt",)),
        ],
    )
    async def test_a_question_that_finds_the_session_gone_marks_it_lost(
        self, tmp_path: Path, question: str, args: tuple[str, ...]
    ):
        """The console's permission guard asks these before every read and write, so
        a session purged mid-turn is often first seen by one of them; a close that
        missed it would keep the session for the next turn to fail on again."""
        recorder, session = _wrap(tmp_path)
        gone = AsyncMock(side_effect=WorkspaceUnavailableError("purged"))

        with (
            patch.object(recorder.wrapped, question, gone),
            pytest.raises(WorkspaceUnavailableError),
        ):
            await getattr(recorder, question)(*args)

        assert recorder.lost
        assert session.rows == []


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

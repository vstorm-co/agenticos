"""What the CSV export builds, and what it refuses.

Which rows a `WHERE` returns is `tests/integration/test_run_export.py`'s question;
this layer proves the shape of the file and the two refusals a mocked session can
answer on its own: an export with no date range, and one over the row cap. The
`Scope.OWN` floor is proven here as *the filter the service hands the repository*
and in integration as *the rows that come back* - a colleague's absent from both.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import ExportTooLargeError, ValidationError
from app.core.permissions import AuthContext, Scope
from app.repositories import agent_run_repo
from app.repositories.agent_run import ApprovalFilters, RunFilters
from app.services import run_export
from app.services.run_export import MAX_EXPORT_ROWS, RunExportService

pytestmark = pytest.mark.anyio

_WINDOW = (datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 31, tzinfo=UTC))


def _ctx(scope: Scope, *, user_id=None, org_id=None) -> MagicMock:
    """An auth context whose `runs:view` reaches exactly `scope`.

    A mock because no built-in role holds `runs:view` below `ALL` yet - the
    member/viewer scope decision (#45 §4) is what lands that - and the floor has
    to be correct the day it does. The real derivation is `permissions.py`'s to
    test; here it is only the input to `_own_floor`.
    """
    ctx = MagicMock(spec=AuthContext)
    ctx.scope_for.return_value = scope
    ctx.subject_id = user_id or uuid4()
    ctx.organization_id = org_id or uuid4()
    return ctx


def _service(monkeypatch) -> RunExportService:
    monkeypatch.setattr(run_export, "record_audit", AsyncMock())
    return RunExportService(MagicMock())


def _parsed(content: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(content)))


def _run(**overrides) -> SimpleNamespace:
    row = {
        "id": uuid4(),
        "agent_id": uuid4(),
        "agent_version_id": uuid4(),
        "parent_run_id": None,
        "subagent_task_id": None,
        "user_id": uuid4(),
        "surface": "web",
        "status": "completed",
        "model_label": "GPT-4.1",
        "provider": "openai",
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_usd": Decimal("0.1234"),
        "cost_is_partial": False,
        "started_at": _WINDOW[0],
        "ended_at": _WINDOW[1],
        "error": None,
    }
    row.update(overrides)
    return SimpleNamespace(**row)


# -- the cell/row helpers -----------------------------------------------------


class TestCells:
    def test_a_formula_leading_cell_is_neutralised(self):
        """A cell opening on `=` is a formula in a spreadsheet, so it is quoted."""
        assert run_export._escape("=cmd()") == "'=cmd()"

    def test_a_plain_cell_is_left_alone(self):
        assert run_export._escape("openai") == "openai"

    def test_a_negative_number_stays_summable(self):
        """A leading `-` is a formula prefix only on a string; a number keeps it,
        so a credit exports as `-1.50` a spreadsheet sums rather than quoted text."""
        assert run_export._cell(Decimal("-1.50")) == "-1.50"

    def test_none_is_an_empty_cell_not_the_word_none(self):
        assert run_export._cell(None) == ""

    def test_a_bool_is_lowercase_words(self):
        assert (run_export._cell(True), run_export._cell(False)) == ("true", "false")

    def test_a_datetime_is_iso(self):
        assert run_export._cell(_WINDOW[0]) == "2026-08-01T00:00:00+00:00"

    def test_tool_args_are_json_sorted(self):
        assert run_export._json_args({"b": 1, "a": 2}) == '{"a": 2, "b": 1}'


# -- the two refusals ---------------------------------------------------------


class TestRefusals:
    async def test_an_export_with_no_range_is_refused(self, monkeypatch):
        service = _service(monkeypatch)
        with pytest.raises(ValidationError) as exc:
            await service.export_runs(
                _ctx(Scope.ALL),
                agent_id=None,
                parent_run_id=None,
                include_delegations=False,
                filters=RunFilters(started_from=None, started_to=None),
            )
        assert exc.value.details == {"missing": ["from", "to"]}

    async def test_a_half_open_range_names_the_missing_end(self, monkeypatch):
        service = _service(monkeypatch)
        with pytest.raises(ValidationError) as exc:
            await service.export_runs(
                _ctx(Scope.ALL),
                agent_id=None,
                parent_run_id=None,
                include_delegations=False,
                filters=RunFilters(started_from=_WINDOW[0], started_to=None),
            )
        assert exc.value.details == {"missing": ["to"]}

    async def test_over_the_cap_is_refused_not_truncated(self, monkeypatch):
        service = _service(monkeypatch)
        monkeypatch.setattr(
            agent_run_repo,
            "list_runs",
            AsyncMock(return_value=([_run()], MAX_EXPORT_ROWS + 1)),
        )
        with pytest.raises(ExportTooLargeError) as exc:
            await service.export_runs(
                _ctx(Scope.ALL),
                agent_id=None,
                parent_run_id=None,
                include_delegations=False,
                filters=RunFilters(started_from=_WINDOW[0], started_to=_WINDOW[1]),
            )
        assert exc.value.details == {
            "row_count": MAX_EXPORT_ROWS + 1,
            "max_rows": MAX_EXPORT_ROWS,
        }
        assert str(MAX_EXPORT_ROWS) in exc.value.message


# -- the runs export ----------------------------------------------------------


class TestRunsExport:
    async def test_the_file_has_a_header_and_a_row_per_run(self, monkeypatch):
        service = _service(monkeypatch)
        run = _run()
        monkeypatch.setattr(agent_run_repo, "list_runs", AsyncMock(return_value=([run], 1)))

        result = await service.export_runs(
            _ctx(Scope.ALL),
            agent_id=None,
            parent_run_id=None,
            include_delegations=False,
            filters=RunFilters(started_from=_WINDOW[0], started_to=_WINDOW[1]),
        )

        rows = _parsed(result.content)
        assert rows[0] == run_export._RUNS_HEADER
        assert rows[1][0] == str(run.id)
        assert result.row_count == 1
        assert result.filename.startswith("runs_export_")
        assert result.filename.endswith(".csv")

    async def test_a_wholly_unpriced_run_is_marked_not_read_as_free(self, monkeypatch):
        """Its cost exports as its real 0, beside `cost_is_partial=true` - the pair
        is what stops a spreadsheet reading the zero as free."""
        service = _service(monkeypatch)
        run = _run(cost_usd=Decimal("0"), cost_is_partial=True)
        monkeypatch.setattr(agent_run_repo, "list_runs", AsyncMock(return_value=([run], 1)))

        result = await service.export_runs(
            _ctx(Scope.ALL),
            agent_id=None,
            parent_run_id=None,
            include_delegations=False,
            filters=RunFilters(started_from=_WINDOW[0], started_to=_WINDOW[1]),
        )

        header, row = _parsed(result.content)[0], _parsed(result.content)[1]
        assert row[header.index("cost_usd")] == "0"
        assert row[header.index("cost_is_partial")] == "true"

    async def test_a_negative_cost_exports_as_a_plain_summable_number(self, monkeypatch):
        """A credit or adjustment exports as `-1.50`, not the quoted `'-1.50` a
        leading `-` earns a string - the sum-safety the export exists for."""
        service = _service(monkeypatch)
        run = _run(cost_usd=Decimal("-1.50"))
        monkeypatch.setattr(agent_run_repo, "list_runs", AsyncMock(return_value=([run], 1)))

        result = await service.export_runs(
            _ctx(Scope.ALL),
            agent_id=None,
            parent_run_id=None,
            include_delegations=False,
            filters=RunFilters(started_from=_WINDOW[0], started_to=_WINDOW[1]),
        )

        header, row = _parsed(result.content)[0], _parsed(result.content)[1]
        assert row[header.index("cost_usd")] == "-1.50"

    async def test_an_orphaned_delegation_handle_is_withheld(self, monkeypatch):
        """A row with a task id but no parent named a transcript that went with the
        parent - the same handle `AgentRunRead` withholds, withheld here too."""
        service = _service(monkeypatch)
        run = _run(parent_run_id=None, subagent_task_id="4f2a1b8c")
        monkeypatch.setattr(agent_run_repo, "list_runs", AsyncMock(return_value=([run], 1)))

        result = await service.export_runs(
            _ctx(Scope.ALL),
            agent_id=None,
            parent_run_id=None,
            include_delegations=False,
            filters=RunFilters(started_from=_WINDOW[0], started_to=_WINDOW[1]),
        )

        header, row = _parsed(result.content)[0], _parsed(result.content)[1]
        assert row[header.index("subagent_task_id")] == ""

    async def test_a_delegation_keeps_its_handle(self, monkeypatch):
        service = _service(monkeypatch)
        parent = uuid4()
        run = _run(parent_run_id=parent, subagent_task_id="4f2a1b8c")
        monkeypatch.setattr(agent_run_repo, "list_runs", AsyncMock(return_value=([run], 1)))

        result = await service.export_runs(
            _ctx(Scope.ALL),
            agent_id=None,
            parent_run_id=None,
            include_delegations=True,
            filters=RunFilters(started_from=_WINDOW[0], started_to=_WINDOW[1]),
        )

        header, row = _parsed(result.content)[0], _parsed(result.content)[1]
        assert row[header.index("subagent_task_id")] == "4f2a1b8c"
        assert row[header.index("parent_run_id")] == str(parent)

    async def test_an_org_wide_caller_is_not_pinned_to_their_own_rows(self, monkeypatch):
        service = _service(monkeypatch)
        list_runs = AsyncMock(return_value=([], 0))
        monkeypatch.setattr(agent_run_repo, "list_runs", list_runs)
        asked = uuid4()

        await service.export_runs(
            _ctx(Scope.ALL),
            agent_id=None,
            parent_run_id=None,
            include_delegations=False,
            filters=RunFilters(started_from=_WINDOW[0], started_to=_WINDOW[1], user_id=asked),
        )

        # Scope.ALL leaves the caller's own `user_id` filter untouched.
        assert list_runs.await_args.kwargs["filters"].user_id == asked

    async def test_an_own_scoped_caller_is_pinned_to_their_own_rows(self, monkeypatch):
        """The floor overwrites any `user_id` the caller passed - a scope cannot be
        widened by a query parameter."""
        service = _service(monkeypatch)
        list_runs = AsyncMock(return_value=([], 0))
        monkeypatch.setattr(agent_run_repo, "list_runs", list_runs)
        me = uuid4()
        ctx = _ctx(Scope.OWN, user_id=me)

        await service.export_runs(
            ctx,
            agent_id=None,
            parent_run_id=None,
            include_delegations=False,
            filters=RunFilters(started_from=_WINDOW[0], started_to=_WINDOW[1], user_id=uuid4()),
        )

        assert list_runs.await_args.kwargs["filters"].user_id == me

    async def test_the_export_writes_an_audit_entry(self, monkeypatch):
        audit = AsyncMock()
        monkeypatch.setattr(run_export, "record_audit", audit)
        monkeypatch.setattr(
            agent_run_repo,
            "list_runs",
            AsyncMock(return_value=([_run()], 1)),
        )
        service = RunExportService(MagicMock())
        ctx = _ctx(Scope.OWN, user_id=uuid4())

        await service.export_runs(
            ctx,
            agent_id=ctx.subject_id,
            parent_run_id=None,
            include_delegations=False,
            filters=RunFilters(
                started_from=_WINDOW[0],
                started_to=_WINDOW[1],
                statuses=["failed"],
                surface="slack",
            ),
        )

        entry = audit.await_args.kwargs
        assert entry["action"] == "runs.export"
        assert entry["details"]["scope"] == "own"
        assert entry["details"]["row_count"] == 1
        # Named, not valued: the fields that narrowed it, not what they were set to.
        # `user_id` is among them because the OWN floor pinned it.
        assert entry["details"]["filters"] == ["agent_id", "statuses", "surface", "user_id"]


# -- the approvals export -----------------------------------------------------


class TestApprovalsExport:
    def _approval(self, **overrides) -> SimpleNamespace:
        row = {
            "id": uuid4(),
            "run_id": uuid4(),
            "agent_id": uuid4(),
            "agent_name": "Clerk",
            "tool_id": "send_email",
            "tool_args": {"to": "a@b.co"},
            "subagent_name": None,
            "subagent_agent_id": None,
            "status": "pending",
            "triggered_by_user_id": uuid4(),
            "triggered_by_email": "who@example.com",
            "decided_by_user_id": None,
            "decided_by_email": None,
            "decided_at": None,
            "note": None,
            "created_at": _WINDOW[0],
        }
        row.update(overrides)
        return SimpleNamespace(**row)

    async def test_the_record_exports_with_its_resolved_emails(self, monkeypatch):
        service = _service(monkeypatch)
        approval = self._approval()
        monkeypatch.setattr(
            agent_run_repo, "list_approvals", AsyncMock(return_value=([approval], 1))
        )

        result = await service.export_approvals(
            _ctx(Scope.ALL),
            filters=ApprovalFilters(
                statuses=["approved"], created_from=_WINDOW[0], created_to=_WINDOW[1]
            ),
            oldest_first=True,
        )

        rows = _parsed(result.content)
        assert rows[0] == run_export._APPROVALS_HEADER
        header = rows[0]
        assert rows[1][header.index("triggered_by_email")] == "who@example.com"
        assert rows[1][header.index("tool_args")] == '{"to": "a@b.co"}'
        assert result.filename.startswith("approvals_export_")

    async def test_a_missing_range_is_refused(self, monkeypatch):
        service = _service(monkeypatch)
        with pytest.raises(ValidationError):
            await service.export_approvals(
                _ctx(Scope.ALL),
                filters=ApprovalFilters(created_from=None, created_to=None),
                oldest_first=True,
            )

    async def test_over_the_cap_is_refused(self, monkeypatch):
        service = _service(monkeypatch)
        monkeypatch.setattr(
            agent_run_repo,
            "list_approvals",
            AsyncMock(return_value=([self._approval()], MAX_EXPORT_ROWS + 1)),
        )
        with pytest.raises(ExportTooLargeError):
            await service.export_approvals(
                _ctx(Scope.ALL),
                filters=ApprovalFilters(
                    triggered_by_user_id=uuid4(),
                    created_from=_WINDOW[0],
                    created_to=_WINDOW[1],
                ),
                oldest_first=False,
            )


# -- the spend export ---------------------------------------------------------


class TestSpendExport:
    def _agent_row(self, **overrides) -> SimpleNamespace:
        row = {
            "agent_id": uuid4(),
            "agent_name": "Clerk",
            "cost_usd": Decimal("1.50"),
            "run_count": 40,
            "partial_run_count": 3,
            "month_to_date_usd": Decimal("2.00"),
            "monthly_cap_usd": None,
        }
        row.update(overrides)
        return SimpleNamespace(**row)

    async def test_one_row_per_agent_with_the_partial_count(self, monkeypatch):
        service = _service(monkeypatch)
        by_agent = AsyncMock(return_value=[self._agent_row()])
        monkeypatch.setattr(agent_run_repo, "spend_by_agent", by_agent)

        result = await service.export_spend(_ctx(Scope.ALL), since=_WINDOW[0], until=_WINDOW[1])

        rows = _parsed(result.content)
        assert rows[0] == run_export._SPEND_HEADER
        assert rows[1][run_export._SPEND_HEADER.index("partial_run_count")] == "3"
        # An org-wide caller is not pinned to a user.
        assert by_agent.await_args.kwargs["user_id"] is None
        assert result.filename.startswith("spend_export_")

    async def test_the_current_month_columns_are_left_off(self, monkeypatch):
        """`cost_usd` reads the window while month-to-date and cap read the calendar
        month; two dollar columns on two time bases in one file are a footgun, so
        the export carries only the window figures."""
        service = _service(monkeypatch)
        monkeypatch.setattr(
            agent_run_repo, "spend_by_agent", AsyncMock(return_value=[self._agent_row()])
        )

        result = await service.export_spend(_ctx(Scope.ALL), since=_WINDOW[0], until=_WINDOW[1])

        header = _parsed(result.content)[0]
        assert "month_to_date_usd" not in header
        assert "monthly_cap_usd" not in header

    async def test_an_own_scoped_caller_sums_only_their_own_runs(self, monkeypatch):
        service = _service(monkeypatch)
        by_agent = AsyncMock(return_value=[])
        monkeypatch.setattr(agent_run_repo, "spend_by_agent", by_agent)
        me = uuid4()

        await service.export_spend(_ctx(Scope.OWN, user_id=me), since=_WINDOW[0], until=_WINDOW[1])

        assert by_agent.await_args.kwargs["user_id"] == me

    async def test_a_missing_range_is_refused(self, monkeypatch):
        service = _service(monkeypatch)
        with pytest.raises(ValidationError):
            await service.export_spend(_ctx(Scope.ALL), since=None, until=_WINDOW[1])

    async def test_over_the_cap_is_refused(self, monkeypatch):
        service = _service(monkeypatch)
        monkeypatch.setattr(
            agent_run_repo,
            "spend_by_agent",
            AsyncMock(return_value=[self._agent_row() for _ in range(MAX_EXPORT_ROWS + 1)]),
        )
        with pytest.raises(ExportTooLargeError) as exc:
            await service.export_spend(_ctx(Scope.ALL), since=_WINDOW[0], until=_WINDOW[1])
        # A spend row is an agent, so the refusal does not send the caller to
        # narrow a date range that would not shorten it.
        assert "date range" not in exc.value.message
        assert "agent" in exc.value.message

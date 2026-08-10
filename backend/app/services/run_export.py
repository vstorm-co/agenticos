"""CSV export of run history, the approvals record and the spend breakdown.

Everything the Activity page shows on screen, taken off it: the rows somebody
reconciles against an invoice, hands to finance, or attaches to an audit. The
endpoint is the easy part; the six questions a bulk read of `agent_runs` raises
are the design, and each one is answered here rather than in the route.

**Tenancy.** An export carries the same gate as the tab it comes from - runs and
spend on `runs:view`, approvals on `approvals:decide` - and, for the two on
`runs:view`, the same `Scope.OWN` floor: a caller whose `runs:view` reaches
less than the whole organization exports only their own rows. The floor is a
`WHERE` in the query (:meth:`_own_floor` feeds a `user_id` clause), never a
filter applied after the fetch, so it cannot be widened by a query parameter -
a caller who also passes `user_id` has it overwritten with their own.

**Size.** No ceiling by nature, so one by design: a **mandatory date range**
refused when absent, and a **row cap** refused above it - `ExportTooLargeError`
naming the count and telling the caller to narrow the range. Not a streaming
response holding a connection while it serialises three years of history, and
not a silent truncation: a trimmed CSV is worse than a refused one, because a
spreadsheet sums whatever arrives. The cap is what lets this build the whole body
in memory on the request's own session and write the audit entry before the
response leaves, rather than on a `StreamingDBSession` that resolves too late to
record anything.

**Partial cost.** `cost_is_partial` is its own column on the runs export and
`partial_run_count` its own column on the spend export, so a floor survives a
spreadsheet sum. A run whose only model was unpriced exports its real
`cost_usd` - `0` - beside `cost_is_partial=true`, never a bare `0` a
reader takes for free.

**Delegated runs.** The runs export defaults to top-level rows only, exactly as
`GET /runs` does, so summing `cost_usd` gives the organization's bill and not
double it. The stance is in the file, not only the docs: every row carries a
`parent_run_id` column, blank for a run somebody started and set for a
delegation - so a reader who opts into `include_delegations` can see which rows
would double-count if summed whole.

**PII.** Each export ships exactly the identity its tab already shows and no
more. The runs table shows a `user_id` and no name, so the runs export ships
the UUID alone - a CSV of who-ran-what with names resolved is the per-person
table #37 refused, arriving as a download. The approvals queue already resolves
the two emails on screen, so the approvals export keeps them.

**Audit.** Every export writes one `audit_log` entry: a privileged bulk read,
cheap to record now and impossible to reconstruct later. The entry names the
window, the filters that were applied and the row count - never the request body
or a resolved row.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.audit import record_audit
from app.core.exceptions import ExportTooLargeError, ValidationError
from app.core.permissions import Perm, Scope
from app.repositories import agent_run_repo
from app.repositories.agent_run import ApprovalFilters, RunFilters
from app.services.spend import month_start

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.permissions import AuthContext
    from app.db.models.agent_run import AgentRun
    from app.repositories.agent_run import AgentSpendRow, ApprovalRow

# The most rows one export may return. A bulk read of `agent_runs` has no natural
# ceiling, so this is the one by design: the whole body is built in memory on the
# request's session, and a cap is what keeps that bounded and lets the audit entry
# commit before the response is written. Above it the request is refused, never
# trimmed - see `ExportTooLargeError`.
MAX_EXPORT_ROWS = 10_000

# A leading one of these turns a CSV cell into a formula in Excel and Sheets, so a
# value that opens with one is prefixed with a quote. The same set the ratings
# export guards against; a cost or an id never starts with one, but a tool
# argument, an agent name or a decision note can.
_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

_RUNS_HEADER = [
    "run_id",
    "agent_id",
    "agent_version_id",
    # The delegation stance, stated in the file: blank for a run somebody started,
    # set for a delegation whose cost is already inside its parent's row.
    "parent_run_id",
    "subagent_task_id",
    # PII: the identity the runs table shows, which is the id and not a name.
    "user_id",
    "surface",
    "status",
    "model_label",
    "provider",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "cost_is_partial",
    "started_at",
    "ended_at",
    "error",
]

_APPROVALS_HEADER = [
    "approval_id",
    "run_id",
    "agent_id",
    "agent_name",
    "tool_id",
    "tool_args",
    "subagent_name",
    "subagent_agent_id",
    "status",
    "triggered_by_user_id",
    "triggered_by_email",
    "decided_by_user_id",
    "decided_by_email",
    "decided_at",
    "note",
    "created_at",
]

_SPEND_HEADER = [
    "agent_id",
    "agent_name",
    "cost_usd",
    "run_count",
    "partial_run_count",
    "month_to_date_usd",
    "monthly_cap_usd",
]


@dataclass(frozen=True)
class ExportResult:
    """A finished CSV body and the name it should download as.

    Attributes:
        content: The whole CSV, header row included.
        filename: What the browser saves it as, stamped with the export instant.
        row_count: How many data rows it holds, for the audit entry and the tests.
    """

    content: str
    filename: str
    row_count: int


def _escape(value: str) -> str:
    """Neutralise a cell a spreadsheet would otherwise read as a formula."""
    if value and value[0] in _CSV_INJECTION_PREFIXES:
        return "'" + value
    return value


def _cell(value: object) -> str:
    """One value as text, with `None` an empty cell rather than the word "None"."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    return _escape(str(value))


def _write(header: list[str], rows: list[list[object]]) -> str:
    """Header plus rows as one RFC 4180 document, quoting and escaping via `csv`."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(value) for value in row])
    return buffer.getvalue()


class RunExportService:
    """CSV exports of run history, approvals and spend, gated and audited.

    Attributes:
        db: The request-scoped session. The whole export is read and the audit
            entry written on it, both before the response leaves - which the row
            cap is what makes safe.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _own_floor(self, ctx: AuthContext) -> UUID | None:
        """The subject to pin the query to, or `None` for an organization-wide read.

        `None` when the caller holds `runs:view` at `Scope.ALL` (an app admin
        included, whose context holds every permission at that scope); their own
        id otherwise, which pins every row to runs they ran. The route has already
        refused a caller who holds `runs:view` at no scope at all.
        """
        if ctx.scope_for(Perm.RUNS_VIEW) >= Scope.ALL:
            return None
        return ctx.subject_id

    def _require_range(
        self, start: datetime | None, end: datetime | None
    ) -> tuple[datetime, datetime]:
        """The window, or a refusal naming the bound that is missing.

        Returns the two bounds narrowed to non-null, so a caller that needs a
        concrete window (the spend query does) reads it off the result rather
        than re-checking what this already proved.

        Raises:
            ValidationError: When either end is absent. A range is what bounds the
                read; without one an export is the whole table.
        """
        if start is None or end is None:
            missing = [name for name, value in (("from", start), ("to", end)) if value is None]
            raise ValidationError(
                message="An export needs a date range - pass both a start and an end.",
                details={"missing": missing},
            )
        return start, end

    def _guard_cap(self, total: int) -> None:
        """Refuse above the row cap rather than truncate to it.

        Raises:
            ExportTooLargeError: When the match exceeds :data:`MAX_EXPORT_ROWS`.
                The message names both numbers and points at the date range,
                because narrowing it is the control that actually shrinks the
                match.
        """
        if total > MAX_EXPORT_ROWS:
            raise ExportTooLargeError(
                message=(
                    f"This export matches {total} rows, more than the "
                    f"{MAX_EXPORT_ROWS} an export may return. Narrow the date "
                    "range and try again."
                ),
                details={"row_count": total, "max_rows": MAX_EXPORT_ROWS},
            )

    @staticmethod
    def _stamp(kind: str, now: datetime) -> str:
        return f"{kind}_export_{now.strftime('%Y%m%d_%H%M%S')}.csv"

    async def export_runs(
        self,
        ctx: AuthContext,
        *,
        agent_id: UUID | None,
        parent_run_id: UUID | None,
        include_delegations: bool,
        filters: RunFilters,
    ) -> ExportResult:
        """Run history as CSV, over exactly the rows `GET /runs` would list.

        The same filters, the same top-level-only default and the same
        organization scope as the list route, so the file is *what is on screen*
        rather than a second query with its own semantics. The date range in
        `filters` is mandatory here where it is optional there, and the caller's
        `user_id` is overwritten with their own when the `Scope.OWN` floor binds.
        """
        self._require_range(filters.started_from, filters.started_to)
        floor = self._own_floor(ctx)
        applied = filters if floor is None else replace(filters, user_id=floor)

        items, total = await agent_run_repo.list_runs(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            parent_run_id=parent_run_id,
            include_delegations=include_delegations,
            filters=applied,
            skip=0,
            limit=MAX_EXPORT_ROWS,
        )
        self._guard_cap(total)

        content = _write(_RUNS_HEADER, [_run_row(run) for run in items])
        now = datetime.now(UTC)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="runs.export",
            target_type="agent_run",
            details={
                "started_from": _cell(applied.started_from),
                "started_to": _cell(applied.started_to),
                "row_count": len(items),
                "scope": "own" if floor is not None else "organization",
                "include_delegations": include_delegations,
                "filters": _applied_run_filters(agent_id, parent_run_id, applied),
            },
        )
        return ExportResult(
            content=content, filename=self._stamp("runs", now), row_count=len(items)
        )

    async def export_approvals(
        self,
        ctx: AuthContext,
        *,
        filters: ApprovalFilters,
        oldest_first: bool,
    ) -> ExportResult:
        """The approvals record as CSV, over exactly the rows `GET /approvals` lists.

        Gated on `approvals:decide` at the route, which is organization-wide, so
        there is no `Scope.OWN` floor to apply - an approver sees the whole queue.
        The two emails are kept because the queue already resolves them on screen.
        """
        self._require_range(filters.created_from, filters.created_to)

        items, total = await agent_run_repo.list_approvals(
            self.db,
            organization_id=ctx.organization_id,
            filters=filters,
            oldest_first=oldest_first,
            skip=0,
            limit=MAX_EXPORT_ROWS,
        )
        self._guard_cap(total)

        content = _write(_APPROVALS_HEADER, [_approval_row(row) for row in items])
        now = datetime.now(UTC)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="approvals.export",
            target_type="tool_approval",
            details={
                "created_from": _cell(filters.created_from),
                "created_to": _cell(filters.created_to),
                "row_count": len(items),
                "filters": _applied_approval_filters(filters),
            },
        )
        return ExportResult(
            content=content, filename=self._stamp("approvals", now), row_count=len(items)
        )

    async def export_spend(
        self,
        ctx: AuthContext,
        *,
        since: datetime | None,
        until: datetime | None,
    ) -> ExportResult:
        """The per-agent spend breakdown as CSV, over the window the tab shows.

        One row per agent, the Spend tab's main table: its window share (top-level
        runs only, so the column sums to the bill), the runs behind it, how many
        could not be priced, its own calendar month and its cap. The `Scope.OWN`
        floor pins the sums to the caller's own runs when it binds.
        """
        since, until = self._require_range(since, until)
        floor = self._own_floor(ctx)

        rows = await agent_run_repo.spend_by_agent(
            self.db,
            organization_id=ctx.organization_id,
            since=since,
            until=until,
            month_since=month_start(),
            user_id=floor,
        )
        self._guard_cap(len(rows))

        content = _write(_SPEND_HEADER, [_spend_row(row) for row in rows])
        now = datetime.now(UTC)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="spend.export",
            target_type="agent_run",
            details={
                "started_from": _cell(since),
                "started_to": _cell(until),
                "row_count": len(rows),
                "scope": "own" if floor is not None else "organization",
            },
        )
        return ExportResult(
            content=content, filename=self._stamp("spend", now), row_count=len(rows)
        )


def _run_row(run: AgentRun) -> list[object]:
    """One run as a row, with the orphaned-delegation handle withheld.

    `subagent_task_id` is blanked whenever `parent_run_id` is null, the same
    guarantee `AgentRunRead` makes: deleting a parent nulls `parent_run_id` but
    leaves the handle, and a delegation handle that reaches no parent is worse
    than none. Every surface follows the rule; a CSV is a surface.
    """
    task_id = run.subagent_task_id if run.parent_run_id is not None else None
    return [
        run.id,
        run.agent_id,
        run.agent_version_id,
        run.parent_run_id,
        task_id,
        run.user_id,
        run.surface,
        run.status,
        run.model_label,
        run.provider,
        run.input_tokens,
        run.output_tokens,
        run.cost_usd,
        run.cost_is_partial,
        run.started_at,
        run.ended_at,
        run.error,
    ]


def _approval_row(row: ApprovalRow) -> list[object]:
    return [
        row.id,
        row.run_id,
        row.agent_id,
        row.agent_name,
        row.tool_id,
        _json_args(row.tool_args),
        row.subagent_name,
        row.subagent_agent_id,
        row.status,
        row.triggered_by_user_id,
        row.triggered_by_email,
        row.decided_by_user_id,
        row.decided_by_email,
        row.decided_at,
        row.note,
        row.created_at,
    ]


def _spend_row(row: AgentSpendRow) -> list[object]:
    return [
        row.agent_id,
        row.agent_name,
        row.cost_usd,
        row.run_count,
        row.partial_run_count,
        row.month_to_date_usd,
        row.monthly_cap_usd,
    ]


def _json_args(args: dict[str, object]) -> str:
    """A tool call's arguments as a JSON string in one cell.

    JSON rather than a Python `repr`, so the arguments an approval authorised
    read back the way they were sent - and `csv` quotes the commas and quotes
    inside it, so the cell survives whatever the arguments contain.
    """
    return json.dumps(args, default=str, sort_keys=True)


def _applied_run_filters(
    agent_id: UUID | None, parent_run_id: UUID | None, filters: RunFilters
) -> list[str]:
    """The names of the filters that narrowed a run export, for the audit entry.

    Names, not values: the audit trail records that the export was narrowed by
    `status` and `surface`, not what to - the same rule an audit of an update
    records the fields touched rather than the body submitted.
    """
    named = {
        "agent_id": agent_id is not None,
        "parent_run_id": parent_run_id is not None,
        "statuses": bool(filters.statuses),
        "surface": filters.surface is not None,
        "user_id": filters.user_id is not None,
        "environment_id": filters.environment_id is not None,
        "exposure_id": filters.exposure_id is not None,
        "agent_version_id": filters.agent_version_id is not None,
        "took_over_ms": filters.took_over_ms is not None,
        "rated": filters.rated is not None,
    }
    return sorted(name for name, present in named.items() if present)


def _applied_approval_filters(filters: ApprovalFilters) -> list[str]:
    named = {
        "statuses": bool(filters.statuses),
        "triggered_by_user_id": filters.triggered_by_user_id is not None,
    }
    return sorted(name for name, present in named.items() if present)

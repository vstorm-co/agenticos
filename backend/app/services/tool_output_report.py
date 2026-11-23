"""How much of a run's input is tool output it had already sent, estimated from records.

A tool result stays in a run's history, so every later model request carries it
again. Nothing records that per result, so this report estimates it from three
things that are recorded:

- `tool_calls.result`, measured by length, is what the model received - after
  `tool_output_limits`, which is why a spilled result counts at its preview's size;
- the run manifest's request waterfall (`app/agents/manifest.py`) says how many
  requests the run made and which tool names each response called, so a result
  is carried by every request after the one that called it;
- the manifest's per-request input is the run's own: a delegate records its own
  manifest, so nothing a delegate spent is in its parent's figures here, even
  though `agent_runs.input_tokens` adds it in.

The manifest keeps tool names, not call ids, and a turn's calls share one
timestamp, so where one tool ran several times in a run its results' positions
are unknown and are averaged. The report says how many calls that touched.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import all_capabilities
from app.agents.capabilities.compaction import CompactionConfig
from app.agents.capabilities.tool_output_limits import ToolOutputLimitsConfig
from app.core.exceptions import NotFoundError, ValidationError
from app.repositories import organization_repo
from app.repositories import tool_output_report as report_repo
from app.repositories.tool_output_report import CallSize, RecordedRequest, ReportRun

CHARS_PER_TOKEN = 4
PACK_THRESHOLD = 10_000
FULL_SENDS = 2
PLACEHOLDERS: dict[str, int] = {"1.3 KB": 1_300, "3.5 KB": 3_500}
CLEARING_STRATEGIES = frozenset({"clear_tool_results", "tiered"})
MCP = "mcp"
UNREGISTERED = "(other)"
BATCH = 500

_LIMITS_DEFAULT = str(ToolOutputLimitsConfig.model_fields["action"].default)
_COMPACTION_DEFAULT = str(CompactionConfig.model_fields["strategy"].default)


@dataclass(frozen=True)
class Distribution:
    """A set of counts at a glance: how many, and where its middle and tail sit."""

    count: int
    p50: int
    p90: int
    p99: int
    max: int


@dataclass(frozen=True)
class SizeRow:
    """Result sizes, in characters, for one agent, capability or tool."""

    name: str
    sizes: Distribution
    over_threshold: int


@dataclass(frozen=True)
class ResendRow:
    """One agent under one pair of bindings: what it re-sent, and what packing would save."""

    agent: str
    tool_output_limits: str
    compaction: str
    overstated: bool
    runs: int
    runs_with_manifest: int
    resent_tokens: int
    own_input_tokens: int
    share: float | None
    cache_read_tokens: int
    cache_write_tokens: int
    saving_tokens: dict[str, int]
    saving_share: dict[str, float | None]


@dataclass(frozen=True)
class Matching:
    """How the tool calls were placed in their run's request waterfall."""

    exact: int
    averaged: int
    unmatched: int
    without_manifest: int


@dataclass(frozen=True)
class ToolOutputReport:
    """Everything the report prints, as numbers and names only."""

    organization_id: UUID
    started_from: date
    ended: date
    include_eval: bool
    include_tests: bool
    runs: int
    runs_with_manifest: int
    tool_calls: int
    turns_per_run: Distribution
    calls_per_run: Distribution
    requests_per_run: Distribution
    by_agent: list[SizeRow]
    by_capability: list[SizeRow]
    by_tool: list[SizeRow]
    resend: list[ResendRow]
    matching: Matching


@dataclass(frozen=True)
class RunEstimate:
    """One run's re-sent characters and projected savings, and how its calls matched."""

    resent_chars: float
    saving_chars: dict[str, float]
    exact: int
    averaged: int
    unmatched: int


def distribution(values: Iterable[int]) -> Distribution:
    """Nearest-rank percentiles; all zero for nothing."""
    ordered = sorted(values)
    if not ordered:
        return Distribution(0, 0, 0, 0, 0)

    def rank(quantile: float) -> int:
        return ordered[max(math.ceil(quantile * len(ordered)) - 1, 0)]

    return Distribution(len(ordered), rank(0.5), rank(0.9), rank(0.99), ordered[-1])


def estimate_run(calls: Sequence[CallSize], requests: Sequence[RecordedRequest]) -> RunEstimate:
    """What one run carried again, from its calls and its manifest's requests.

    A call made by the response to request `i` is carried by every request after
    it. Its results are matched to requests by tool name; a name whose calls sit
    in different requests is averaged over them. Packing is projected as #2137
    designs it: a result over `PACK_THRESHOLD` goes in full on `FULL_SENDS`
    requests and as a placeholder on every one after.
    """
    ordered = sorted(requests, key=lambda request: request.index)
    later: dict[str, list[int]] = defaultdict(list)
    for position, request in enumerate(ordered):
        for name in request.tool_calls:
            later[name].append(len(ordered) - 1 - position)
    sizes: dict[str, list[int]] = defaultdict(list)
    for call in calls:
        sizes[call.tool_name].append(call.size)

    resent = 0.0
    saving = dict.fromkeys(PLACEHOLDERS, 0.0)
    exact = averaged = unmatched = 0
    for name, results in sizes.items():
        positions = later.get(name)
        if not positions:
            unmatched += len(results)
            continue
        if len(positions) == len(results) and len(set(positions)) == 1:
            exact += len(results)
        else:
            averaged += len(results)
        carried = sum(positions) / len(positions)
        packed = sum(max(position - FULL_SENDS, 0) for position in positions) / len(positions)
        resent += sum(results) * carried
        for label, placeholder in PLACEHOLDERS.items():
            over = sum(size - placeholder for size in results if size > PACK_THRESHOLD)
            saving[label] += over * packed
    return RunEstimate(resent, saving, exact, averaged, unmatched)


def bindings_of(capabilities: Sequence[object] | None) -> tuple[str, str]:
    """How a spec bound `tool_output_limits` and `compaction`: its action and strategy, or none."""
    limits = compaction = "none"
    for binding in capabilities or []:
        if not isinstance(binding, dict) or binding.get("enabled", True) is False:
            continue
        config = binding.get("config") or {}
        if binding.get("id") == "tool_output_limits":
            limits = str(config.get("action") or _LIMITS_DEFAULT)
        elif binding.get("id") == "compaction":
            compaction = str(config.get("strategy") or _COMPACTION_DEFAULT)
    return limits, compaction


def _capability_of_tool() -> dict[str, str]:
    owners: dict[str, str] = {}
    for capability in all_capabilities():
        for tool in capability.tools:
            owners.setdefault(tool.id, capability.id)
    return owners


def _share(part: float, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _size_rows(groups: dict[str, list[int]], top: int) -> list[SizeRow]:
    rows = [
        SizeRow(name, distribution(sizes), sum(size > PACK_THRESHOLD for size in sizes))
        for name, sizes in groups.items()
    ]
    rows.sort(key=lambda row: (-sum(groups[row.name]), row.name))
    return rows[:top]


@dataclass
class _Totals:
    runs: int = 0
    with_manifest: int = 0
    resent_chars: float = 0.0
    own_input: int = 0
    cache_read: int = 0
    cache_write: int = 0
    saving_chars: dict[str, float] = field(default_factory=lambda: dict.fromkeys(PLACEHOLDERS, 0.0))


class ToolOutputReportService:
    """Builds the re-sent tool output report for one organization and a window."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def build(
        self,
        organization_id: UUID,
        *,
        started_from: date,
        ended: date,
        include_eval: bool = False,
        include_tests: bool = False,
        top: int = 20,
    ) -> ToolOutputReport:
        """Read the window's runs, calls and manifests and estimate what was re-sent.

        Raises:
            ValidationError: The window ends before it starts.
            NotFoundError: There is no such organization.
        """
        if ended < started_from:
            raise ValidationError(
                message="The window ends before it starts",
                details={"from": started_from.isoformat(), "to": ended.isoformat()},
            )
        if await organization_repo.get_by_id(self.db, organization_id) is None:
            raise NotFoundError(
                message="Organization not found", details={"organization_id": organization_id}
            )
        runs = await report_repo.list_runs(
            self.db,
            organization_id=organization_id,
            started_from=datetime.combine(started_from, time.min, UTC),
            started_before=datetime.combine(ended + timedelta(days=1), time.min, UTC),
            include_eval=include_eval,
            include_tests=include_tests,
        )
        calls: dict[UUID, list[CallSize]] = defaultdict(list)
        requests: dict[UUID, list[RecordedRequest]] = defaultdict(list)
        turns: dict[UUID, int] = {}
        for start in range(0, len(runs), BATCH):
            ids = [run.id for run in runs[start : start + BATCH]]
            for call in await report_repo.list_call_sizes(
                self.db, organization_id=organization_id, run_ids=ids
            ):
                calls[call.run_id].append(call)
            for request in await report_repo.list_requests(
                self.db, organization_id=organization_id, run_ids=ids
            ):
                requests[request.run_id].append(request)
            turns.update(
                await report_repo.count_turns(self.db, organization_id=organization_id, run_ids=ids)
            )
        versions = await report_repo.list_version_capabilities(
            self.db,
            organization_id=organization_id,
            version_ids=sorted({run.agent_version_id for run in runs if run.agent_version_id}),
        )
        return self._assemble(
            organization_id,
            started_from=started_from,
            ended=ended,
            include_eval=include_eval,
            include_tests=include_tests,
            top=top,
            runs=runs,
            calls=calls,
            requests=requests,
            turns=turns,
            versions=versions,
        )

    @staticmethod
    def _assemble(
        organization_id: UUID,
        *,
        started_from: date,
        ended: date,
        include_eval: bool,
        include_tests: bool,
        top: int,
        runs: Sequence[ReportRun],
        calls: dict[UUID, list[CallSize]],
        requests: dict[UUID, list[RecordedRequest]],
        turns: dict[UUID, int],
        versions: dict[UUID, list[dict[str, Any]]],
    ) -> ToolOutputReport:
        owners = _capability_of_tool()
        by_agent: dict[str, list[int]] = defaultdict(list)
        by_capability: dict[str, list[int]] = defaultdict(list)
        by_tool: dict[str, list[int]] = defaultdict(list)
        totals: dict[tuple[str, str, str], _Totals] = defaultdict(_Totals)
        exact = averaged = unmatched = without_manifest = 0
        for run in runs:
            run_calls = calls.get(run.id, [])
            for call in run_calls:
                capability = MCP if call.is_mcp else owners.get(call.tool_id or "", UNREGISTERED)
                by_agent[run.agent_name].append(call.size)
                by_capability[capability].append(call.size)
                by_tool[call.tool_name].append(call.size)
            capabilities = (
                run.test_capabilities
                if run.test_capabilities is not None
                else versions.get(run.agent_version_id)
                if run.agent_version_id
                else None
            )
            limits, compaction = bindings_of(capabilities)
            bucket = totals[(run.agent_name, limits, compaction)]
            bucket.runs += 1
            run_requests = requests.get(run.id, [])
            if not run_requests:
                without_manifest += len(run_calls)
                continue
            bucket.with_manifest += 1
            estimate = estimate_run(run_calls, run_requests)
            exact += estimate.exact
            averaged += estimate.averaged
            unmatched += estimate.unmatched
            bucket.resent_chars += estimate.resent_chars
            bucket.own_input += sum(request.input_tokens for request in run_requests)
            bucket.cache_read += sum(request.cache_read_tokens for request in run_requests)
            bucket.cache_write += sum(request.cache_write_tokens for request in run_requests)
            for label, saved in estimate.saving_chars.items():
                bucket.saving_chars[label] += saved

        resend = [
            ResendRow(
                agent=agent,
                tool_output_limits=limits,
                compaction=compaction,
                overstated=compaction in CLEARING_STRATEGIES,
                runs=bucket.runs,
                runs_with_manifest=bucket.with_manifest,
                resent_tokens=round(bucket.resent_chars / CHARS_PER_TOKEN),
                own_input_tokens=bucket.own_input,
                share=_share(bucket.resent_chars / CHARS_PER_TOKEN, bucket.own_input),
                cache_read_tokens=bucket.cache_read,
                cache_write_tokens=bucket.cache_write,
                saving_tokens={
                    label: round(saved / CHARS_PER_TOKEN)
                    for label, saved in bucket.saving_chars.items()
                },
                saving_share={
                    label: _share(saved / CHARS_PER_TOKEN, bucket.own_input)
                    for label, saved in bucket.saving_chars.items()
                },
            )
            for (agent, limits, compaction), bucket in totals.items()
        ]
        resend.sort(key=lambda row: (-row.saving_tokens[next(iter(PLACEHOLDERS))], row.agent))
        return ToolOutputReport(
            organization_id=organization_id,
            started_from=started_from,
            ended=ended,
            include_eval=include_eval,
            include_tests=include_tests,
            runs=len(runs),
            runs_with_manifest=sum(1 for run in runs if requests.get(run.id)),
            tool_calls=sum(len(run_calls) for run_calls in calls.values()),
            turns_per_run=distribution(turns.get(run.id, 0) for run in runs),
            calls_per_run=distribution(len(calls.get(run.id, [])) for run in runs),
            requests_per_run=distribution(
                len(requests[run.id]) for run in runs if requests.get(run.id)
            ),
            by_agent=_size_rows(by_agent, top),
            by_capability=_size_rows(by_capability, top),
            by_tool=_size_rows(by_tool, top),
            resend=resend,
            matching=Matching(exact, averaged, unmatched, without_manifest),
        )


def as_json(report: ToolOutputReport) -> dict[str, Any]:
    """The report as plain JSON values."""
    data = asdict(report)
    data["organization_id"] = str(report.organization_id)
    data["started_from"] = report.started_from.isoformat()
    data["ended"] = report.ended.isoformat()
    data["assumptions"] = assumptions(report)
    return data


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def assumptions(report: ToolOutputReport) -> list[str]:
    """What the figures assume, and what they cannot say."""
    matched = report.matching
    placed = matched.exact + matched.averaged + matched.unmatched
    return [
        "Sizes are the characters each model received, after tool_output_limits.",
        f"Tokens are estimated as characters / {CHARS_PER_TOKEN}.",
        "Model requests come from each run's manifest; "
        f"{report.runs - report.runs_with_manifest} run(s) without one are left out "
        "of the re-send estimate.",
        "A result is counted once for every request after the one that called it. "
        f"Calls placed exactly: {_percent(_share(matched.exact, placed))}; averaged over a "
        f"tool that ran more than once: {_percent(_share(matched.averaged, placed))}; "
        f"not found in the manifest: {_percent(_share(matched.unmatched, placed))}.",
        "A run's share is of its own model requests' input. A delegate is a run of its own "
        "and is never added to its parent.",
        "Not measured: how replacing results would change prompt caching. Cache reads and "
        "writes are shown as recorded.",
        "Compaction that clears tool results (clear_tool_results, tiered) stops re-sending "
        "them before a run ends, so those rows are overstated (marked !).",
        f"Projection: a result over {PACK_THRESHOLD:,} characters is sent in full "
        f"{FULL_SENDS} times, then as a placeholder of " + " or ".join(PLACEHOLDERS) + ".",
    ]


def _distribution_line(label: str, value: Distribution) -> str:
    return (
        f"  {label:<20} n={value.count:<7} p50={value.p50:<8} p90={value.p90:<8} "
        f"p99={value.p99:<8} max={value.max}"
    )


def render_text(report: ToolOutputReport) -> str:
    """The report as plain text for a terminal."""
    lines = [
        f"Re-sent tool output, organization {report.organization_id}, "
        f"{report.started_from.isoformat()} to {report.ended.isoformat()}",
        f"Eval runs {'included' if report.include_eval else 'excluded'}; Builder test runs "
        f"{'included' if report.include_tests else 'excluded'}.",
        f"Runs: {report.runs}, with a manifest: {report.runs_with_manifest}. "
        f"Tool calls: {report.tool_calls}.",
    ]
    if not report.runs:
        lines.append("No runs in this window.")
        return "\n".join(lines)
    lines += ["", "Assumptions:"] + [f"  - {line}" for line in assumptions(report)]
    lines += [
        "",
        "Per run:",
        _distribution_line("turns", report.turns_per_run),
        _distribution_line("tool calls", report.calls_per_run),
        _distribution_line("model requests", report.requests_per_run),
    ]
    for title, rows in (
        ("Result size in characters, by agent:", report.by_agent),
        ("Result size in characters, by capability:", report.by_capability),
        ("Result size in characters, by tool:", report.by_tool),
    ):
        lines += ["", title]
        lines += [
            _distribution_line(row.name, row.sizes) + f" over_{PACK_THRESHOLD}={row.over_threshold}"
            for row in rows
        ]
    labels = list(PLACEHOLDERS)
    lines += [
        "",
        "Re-sent by agent (tokens; tool_output_limits / compaction):",
        "  "
        + "  ".join(
            [
                "agent",
                "limits/compaction",
                "runs",
                "re-sent",
                "own input",
                "share",
                "cache read",
                "cache write",
            ]
            + [f"save {label}" for label in labels]
        ),
    ]
    for row in report.resend:
        mark = " !" if row.overstated else ""
        savings = "  ".join(
            f"{row.saving_tokens[label]} ({_percent(row.saving_share[label])})" for label in labels
        )
        lines.append(
            f"  {row.agent}{mark}  {row.tool_output_limits}/{row.compaction}  "
            f"{row.runs_with_manifest}/{row.runs}  {row.resent_tokens}  {row.own_input_tokens}  "
            f"{_percent(row.share)}  {row.cache_read_tokens}  {row.cache_write_tokens}  {savings}"
        )
    return "\n".join(lines)

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

A follow-up run in a conversation can also carry earlier runs' results in its
history. How much of the stored history reached a request is not recorded, so
that part is reported apart, as an upper bound.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ask_user import ASK_USER_TOOL
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
NONE = "none"
UNKNOWN = "unknown"
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
    """One agent under one pair of bindings: what it re-sent, and what packing would save.

    Runs on platform instructions are a row of their own, named by `system_role`
    with no `agent_id`, because their work is not the agent that started them.
    `inherited_tokens` is what earlier runs of the same conversations got back
    from tools, counted on every request of the follow-up run: an upper bound.
    """

    agent: str
    agent_id: str | None
    system_role: str | None
    tool_output_limits: str
    compaction: str
    overstated: bool
    runs: int
    runs_estimated: int
    resent_tokens: int
    inherited_tokens: int
    own_input_tokens: int
    share: float | None
    share_with_inherited: float | None
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
    left_out: int


@dataclass(frozen=True)
class LeftOut:
    """Runs left out of the re-send estimate, and why.

    A run without a conversation records no tool results; a run that waited on an
    approval or a question keeps only its last segment's requests in its manifest.
    """

    without_transcript: int
    without_manifest: int
    waited: int


@dataclass(frozen=True)
class ToolOutputReport:
    """Everything the report prints, as numbers and names only."""

    organization_id: UUID
    started_from: date
    ended: date
    include_eval: bool
    include_tests: bool
    runs: int
    runs_estimated: int
    tool_calls: int
    turns_per_run: Distribution
    calls_per_run: Distribution
    requests_per_run: Distribution
    by_agent: list[SizeRow]
    by_capability: list[SizeRow]
    by_tool: list[SizeRow]
    resend: list[ResendRow]
    left_out: LeftOut
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
    in different requests is averaged over them. Packing is projected as a result
    over `PACK_THRESHOLD` going in full on `FULL_SENDS` requests and as a
    placeholder on every one after.
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
    """How a spec bound `tool_output_limits` and `compaction`: its action and strategy, or none.

    No spec at all - a run whose published version was deleted - is unknown, not
    a spec that bound neither.
    """
    if capabilities is None:
        return UNKNOWN, UNKNOWN
    limits = compaction = NONE
    for binding in capabilities:
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


def printable(label: str) -> str:
    """A stored name made safe for a terminal: control and format characters escaped.

    Agent and tool names are written by members, so a newline could forge a row of
    the report and an escape sequence could drive the operator's terminal.
    """
    return "".join(
        char if char.isprintable() else char.encode("unicode_escape").decode("ascii")
        for char in label
    )


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
    label: str = ""
    agent_id: str | None = None
    system_role: str | None = None
    runs: int = 0
    estimated: int = 0
    resent_chars: float = 0.0
    inherited_chars: float = 0.0
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
        inherited: dict[UUID, int] = {}
        parked: set[UUID] = set()
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
            inherited.update(
                await report_repo.list_inherited_sizes(
                    self.db, organization_id=organization_id, run_ids=ids
                )
            )
            parked |= await report_repo.list_parked(
                self.db, organization_id=organization_id, run_ids=ids, question_tool=ASK_USER_TOOL
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
            inherited=inherited,
            parked=parked,
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
        inherited: dict[UUID, int],
        parked: set[UUID],
    ) -> ToolOutputReport:
        owners = _capability_of_tool()
        agents_named: dict[str, set[UUID]] = defaultdict(set)
        for run in runs:
            agents_named[run.agent_name].add(run.agent_id)
        by_agent: dict[str, list[int]] = defaultdict(list)
        by_capability: dict[str, list[int]] = defaultdict(list)
        by_tool: dict[str, list[int]] = defaultdict(list)
        totals: dict[tuple[str, str, str], _Totals] = defaultdict(_Totals)
        exact = averaged = unmatched = left_calls = 0
        without_transcript = without_manifest = waited = 0
        for run in runs:
            if run.system_role:
                key, name = f"role:{run.system_role}", f"platform: {run.system_role}"
            else:
                key, name = f"agent:{run.agent_id}", run.agent_name
                if len(agents_named[run.agent_name]) > 1:
                    name = f"{run.agent_name} [{str(run.agent_id)[:8]}]"
            run_calls = calls.get(run.id, [])
            for call in run_calls:
                capability = MCP if call.is_mcp else owners.get(call.tool_id or "", UNREGISTERED)
                by_agent[name].append(call.size)
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
            bucket = totals[(key, limits, compaction)]
            bucket.label = name
            bucket.agent_id = None if run.system_role else str(run.agent_id)
            bucket.system_role = run.system_role
            bucket.runs += 1
            run_requests = requests.get(run.id, [])
            if run.conversation_id is None:
                without_transcript += 1
            elif not run_requests:
                without_manifest += 1
            elif run.id in parked:
                waited += 1
            else:
                bucket.estimated += 1
                estimate = estimate_run(run_calls, run_requests)
                exact += estimate.exact
                averaged += estimate.averaged
                unmatched += estimate.unmatched
                bucket.resent_chars += estimate.resent_chars
                bucket.inherited_chars += inherited.get(run.id, 0) * len(run_requests)
                bucket.own_input += sum(request.input_tokens for request in run_requests)
                bucket.cache_read += sum(request.cache_read_tokens for request in run_requests)
                bucket.cache_write += sum(request.cache_write_tokens for request in run_requests)
                for label, saved in estimate.saving_chars.items():
                    bucket.saving_chars[label] += saved
                continue
            left_calls += len(run_calls)

        resend = [
            ResendRow(
                agent=bucket.label,
                agent_id=bucket.agent_id,
                system_role=bucket.system_role,
                tool_output_limits=limits,
                compaction=compaction,
                overstated=compaction != NONE,
                runs=bucket.runs,
                runs_estimated=bucket.estimated,
                resent_tokens=round(bucket.resent_chars / CHARS_PER_TOKEN),
                inherited_tokens=round(bucket.inherited_chars / CHARS_PER_TOKEN),
                own_input_tokens=bucket.own_input,
                share=_share(bucket.resent_chars / CHARS_PER_TOKEN, bucket.own_input),
                share_with_inherited=_share(
                    min(
                        (bucket.resent_chars + bucket.inherited_chars) / CHARS_PER_TOKEN,
                        bucket.own_input,
                    ),
                    bucket.own_input,
                ),
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
            for (_, limits, compaction), bucket in totals.items()
        ]
        resend.sort(key=lambda row: (-row.saving_tokens[next(iter(PLACEHOLDERS))], row.agent))
        return ToolOutputReport(
            organization_id=organization_id,
            started_from=started_from,
            ended=ended,
            include_eval=include_eval,
            include_tests=include_tests,
            runs=len(runs),
            runs_estimated=sum(row.runs_estimated for row in resend),
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
            left_out=LeftOut(without_transcript, without_manifest, waited),
            matching=Matching(exact, averaged, unmatched, left_calls),
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
    left = report.left_out
    placed = matched.exact + matched.averaged + matched.unmatched
    return [
        (
            "Sizes are the characters each model received, after tool_output_limits. A failed "
            "call stores a short notice instead of what the model was sent, so it counts at the "
            "notice's size."
        ),
        f"Tokens are estimated as characters / {CHARS_PER_TOKEN}.",
        (
            "Model requests come from each run's manifest. Left out of the re-send estimate: "
            f"{left.without_transcript} run(s) outside a conversation, which record no tool "
            f"results (eval runs among them); {left.without_manifest} without a manifest; "
            f"{left.waited} that waited on an approval or a question, whose manifest keeps "
            "only the last segment."
        ),
        (
            "A result is counted once for every request after the one that called it. "
            f"Calls placed exactly: {_percent(_share(matched.exact, placed))}; averaged over a "
            f"tool that ran more than once: {_percent(_share(matched.averaged, placed))}; "
            f"not found in the manifest: {_percent(_share(matched.unmatched, placed))}."
        ),
        (
            "Inherited is what earlier runs of the same conversation got back from tools, "
            "counted on every request of the follow-up run. It is an upper bound: stored "
            "history is trimmed to a size limit, and a conversation with other authors "
            "replays its transcript, which holds no results."
        ),
        (
            "A run's share is of its own model requests' input. A delegate is a run of its own "
            "and is never added to its parent."
        ),
        (
            "Runs on platform instructions (maintenance, briefings, channel decisions) are "
            "shown as platform: <role>, not under the agent that started them."
        ),
        (
            "Not measured: how replacing results would change prompt caching. Cache reads and "
            "writes are shown as recorded."
        ),
        (
            "Compaction can summarize, drop or clear results before a run ends, so rows with "
            "any compaction binding are overstated (marked !). unknown is a run whose published "
            "version was deleted."
        ),
        (
            f"Projection: a result over {PACK_THRESHOLD:,} characters is sent in full "
            f"{FULL_SENDS} times, then as a placeholder of " + " or ".join(PLACEHOLDERS) + "."
        ),
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
        f"Runs: {report.runs}, estimated: {report.runs_estimated}. "
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
            _distribution_line(printable(row.name), row.sizes)
            + f" over_{PACK_THRESHOLD}={row.over_threshold}"
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
                "inherited (at most)",
                "own input",
                "share",
                "with inherited",
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
            f"  {printable(row.agent)}{mark}  "
            f"{printable(row.tool_output_limits)}/{printable(row.compaction)}  "
            f"{row.runs_estimated}/{row.runs}  {row.resent_tokens}  {row.inherited_tokens}  "
            f"{row.own_input_tokens}  {_percent(row.share)}  {_percent(row.share_with_inherited)}  "
            f"{row.cache_read_tokens}  {row.cache_write_tokens}  {savings}"
        )
    return "\n".join(lines)

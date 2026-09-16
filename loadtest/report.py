"""Turning a run into something a person can act on.

Markdown, written to stdout and redirected into `loadtest/results/`, because the
audience for a load result is a reviewer reading a pull request rather than a
dashboard nobody has. Three sections, in the order the questions get asked:

1. what was run - the hardware, the mix, the phases, and what could not be
   measured;
2. what happened - per workload, per phase;
3. whether it passed - each proposed threshold, with the sample count beside it.

The third is last on purpose. A verdict at the top invites somebody to read only
that, and the sample counts underneath it are what say whether a tail is a
finding or three requests.
"""

from __future__ import annotations

import platform
from collections.abc import Iterable

from metrics import RunSummary, Sample, WorkloadSummary, summarize
from probes import Probes, peak_pool
from probes import summarize as summarize_resources
from scenario import Phase, WorkloadShare
from thresholds import Verdict, judge


def machine() -> str:
    """What this ran on, as one line, because a number without it means nothing."""
    return f"{platform.platform()} · {platform.machine()} · Python {platform.python_version()}"


def _row(entry: WorkloadSummary) -> str:
    return (
        f"| `{entry.workload}` | {entry.total} | {entry.failed} "
        f"| {entry.error_rate * 100:.2f}% "
        f"| {entry.latency.p50:.0f} | {entry.latency.p95:.0f} | {entry.latency.p99:.0f} "
        f"| {entry.latency.worst:.0f} |"
    )


def _workload_table(summary: RunSummary) -> list[str]:
    lines = [
        "| Workload | Calls | Failed | Error rate | p50 ms | p95 ms | p99 ms | Worst ms |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines.extend(_row(entry) for entry in summary.workloads)
    return lines


def _first_token_table(summary: RunSummary) -> list[str]:
    streams = [entry for entry in summary.workloads if entry.first_token.count]
    if not streams:
        return []
    lines = [
        "",
        "Time to first token, which is the half of a stream a person feels:",
        "",
        "| Workload | Streams | p50 ms | p95 ms | p99 ms |",
        "|---|---|---|---|---|",
    ]
    lines.extend(
        f"| `{entry.workload}` | {entry.first_token.count} | {entry.first_token.p50:.0f} "
        f"| {entry.first_token.p95:.0f} | {entry.first_token.p99:.0f} |"
        for entry in streams
    )
    return lines


def _failures(summary: RunSummary) -> list[str]:
    named = [
        (entry.workload, reason, count)
        for entry in summary.workloads
        for reason, count in entry.failures
    ]
    if not named:
        return ["", "No request failed.", ""]
    lines = ["", "### What failed", "", "| Workload | Reason | Count |", "|---|---|---|"]
    lines.extend(f"| `{workload}` | {reason} | {count} |" for workload, reason, count in named)
    return lines


def _verdicts(verdicts: Iterable[Verdict]) -> list[str]:
    lines = [
        "",
        "## Against the proposed thresholds",
        "",
        "These are **proposed**, not agreed - see `docs/load-testing.md`. The sample",
        "count is beside each one because a tail described by four requests is not a",
        "finding.",
        "",
        "| Workload | Metric | Limit | Measured | Samples | |",
        "|---|---|---|---|---|---|",
    ]
    for verdict in verdicts:
        threshold = verdict.threshold
        unit = "%" if threshold.unit == "fraction" else " ms"
        scale = 100 if threshold.unit == "fraction" else 1
        mark = "pass" if verdict.met else "**FAIL**"
        if verdict.counted == 0:
            mark = "**not measured**"
        lines.append(
            f"| `{threshold.workload}` | {threshold.metric} "
            f"| {threshold.limit * scale:.2f}{unit} | {verdict.measured * scale:.2f}{unit} "
            f"| {verdict.counted} | {mark} |"
        )
    return lines


def render(
    samples: list[Sample],
    *,
    phases: tuple[Phase, ...],
    mix: tuple[WorkloadShare, ...],
    probes: Probes,
    seconds: float,
    title: str,
    topology: str,
) -> str:
    """The whole report for one run."""
    whole = summarize(samples, label="whole run", seconds=seconds)
    sustained = [sample for sample in samples if sample.phase == "sustain"]
    sustain_seconds = next((phase.seconds for phase in phases if phase.name == "sustain"), 0.0)
    steady = summarize(sustained, label="sustain", seconds=sustain_seconds)
    cpu, peak_rss, final_rss = summarize_resources(probes.resources)
    connections, active = peak_pool(probes.pools)

    lines = [
        f"# {title}",
        "",
        f"- **Machine** — {machine()}",
        f"- **Topology** — {topology}",
        f"- **Duration** — {seconds:.0f}s over {len(phases)} phases",
        f"- **Requests** — {whole.total} offered, {whole.failed} failed",
        "",
        "## The workload",
        "",
        "| Workload | Share | What it is |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| `{entry.name}` | {entry.share * 100:.0f}% | {entry.description} |" for entry in mix
    )
    lines.extend(["", "| Phase | Seconds | Offered per second | Why |", "|---|---|---|---|"])
    lines.extend(
        f"| `{phase.name}` | {phase.seconds:.0f} | {phase.rate_per_second:.0f} | {phase.note} |"
        for phase in phases
    )

    lines.extend(["", "## The sustained phase", "", "Every threshold is judged against this one."])
    lines.extend(["", f"Throughput: **{steady.throughput:.1f} requests a second** completed.", ""])
    lines.extend(_workload_table(steady))
    lines.extend(_first_token_table(steady))
    lines.extend(_failures(steady))

    lines.extend(["", "## The whole run, every phase together", ""])
    lines.extend(_workload_table(whole))
    lines.extend(_failures(whole))

    lines.extend(["", "## The machine while it ran", ""])
    if probes.resources:
        lines.append(
            f"- Peak CPU **{cpu:.0f}%** of one core; peak resident memory **{peak_rss:.0f} MB**, "
            f"finishing at **{final_rss:.0f} MB**."
        )
    if probes.pools:
        lines.append(
            f"- Peak database connections **{connections}**, of which **{active}** executing at once."
        )
    for missing in probes.unavailable:
        lines.append(f"- Not measured: {missing}.")
    if not probes.resources and not probes.pools and not probes.unavailable:
        lines.append("- Nothing was sampled; the run measured requests only.")

    lines.extend(_verdicts(judge(steady)))
    lines.append("")
    return "\n".join(lines)

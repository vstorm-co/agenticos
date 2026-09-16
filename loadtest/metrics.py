"""What a load run measured, and how the numbers are arrived at.

Kept apart from the driver because a harness that computes its own verdict is a
harness nobody can check. Everything here is a pure function over recorded
samples: percentiles, rates, and the comparison against the thresholds. The
driver records; this decides what the recording means.

**Percentiles are nearest-rank, not interpolated.** An interpolated p99 over
ninety samples is a number between two measurements that nothing actually
observed, which is the wrong shape for a latency claim: the honest answer to
"what did the 99th percentile request take" is the time some request took. The
count is reported beside every percentile so a reader can see when a tail is
being described by three samples.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from statistics import fmean


@dataclass(frozen=True)
class Sample:
    """One request, as the driver saw it."""

    workload: str
    phase: str
    started_at: float
    """Seconds since the run began, so a sample can be placed in its phase."""

    duration_ms: float
    ok: bool
    status: int | None = None
    """The HTTP status, or None for a socket that never produced one."""

    first_token_ms: float | None = None
    """Time to the first streamed token. None for anything that does not stream."""

    detail: str = ""
    """What went wrong, for a failed sample. Grouped in the report."""


@dataclass
class Recorder:
    """Collects samples during a run."""

    samples: list[Sample] = field(default_factory=list)

    def record(self, sample: Sample) -> None:
        self.samples.append(sample)

    def for_workload(self, workload: str) -> list[Sample]:
        return [sample for sample in self.samples if sample.workload == workload]

    def for_phase(self, phase: str) -> list[Sample]:
        return [sample for sample in self.samples if sample.phase == phase]


def percentile(values: Sequence[float], fraction: float) -> float:
    """The nearest-rank percentile of `values`, or 0.0 when there are none.

    Nearest rank: sort, take the value at ceil(fraction * n). Every answer is a
    measurement rather than a point between two of them.
    """
    if not values:
        return 0.0
    if not 0.0 < fraction <= 1.0:
        raise ValueError("A percentile is a fraction in (0, 1].")
    ordered = sorted(values)
    rank = math.ceil(fraction * len(ordered))
    return ordered[rank - 1]


@dataclass(frozen=True)
class Latencies:
    """The distribution of one measurement, and how many went into it."""

    count: int
    p50: float
    p90: float
    p95: float
    p99: float
    mean: float
    worst: float

    @classmethod
    def of(cls, values: Sequence[float]) -> Latencies:
        if not values:
            return cls(count=0, p50=0.0, p90=0.0, p95=0.0, p99=0.0, mean=0.0, worst=0.0)
        return cls(
            count=len(values),
            p50=percentile(values, 0.50),
            p90=percentile(values, 0.90),
            p95=percentile(values, 0.95),
            p99=percentile(values, 0.99),
            mean=fmean(values),
            worst=max(values),
        )


@dataclass(frozen=True)
class WorkloadSummary:
    """What one workload did over one window."""

    workload: str
    total: int
    failed: int
    latency: Latencies
    first_token: Latencies
    failures: tuple[tuple[str, int], ...]
    """Each distinct failure detail and how often it happened, commonest first."""

    @property
    def error_rate(self) -> float:
        """The share of attempts that did not succeed, as a fraction."""
        return self.failed / self.total if self.total else 0.0


@dataclass(frozen=True)
class RunSummary:
    """A whole run, or one phase of it."""

    label: str
    seconds: float
    workloads: tuple[WorkloadSummary, ...]

    @property
    def total(self) -> int:
        return sum(entry.total for entry in self.workloads)

    @property
    def failed(self) -> int:
        return sum(entry.failed for entry in self.workloads)

    @property
    def error_rate(self) -> float:
        return self.failed / self.total if self.total else 0.0

    @property
    def throughput(self) -> float:
        """Completed requests a second across every workload."""
        return self.total / self.seconds if self.seconds > 0 else 0.0

    def workload(self, name: str) -> WorkloadSummary | None:
        return next((entry for entry in self.workloads if entry.workload == name), None)


def summarize(samples: Iterable[Sample], *, label: str, seconds: float) -> RunSummary:
    """Fold samples into per-workload distributions.

    Latency is measured over **successful** samples only. A request that was
    refused in 3 ms is not a fast request, and letting it into the distribution
    is how a run that fell over reports its best percentiles ever; the failures
    are counted separately and named.
    """
    collected = list(samples)
    names = sorted({sample.workload for sample in collected})
    summaries = []
    for name in names:
        rows = [sample for sample in collected if sample.workload == name]
        good = [sample for sample in rows if sample.ok]
        bad = [sample for sample in rows if not sample.ok]
        reasons: dict[str, int] = {}
        for sample in bad:
            reason = sample.detail or (f"HTTP {sample.status}" if sample.status else "no response")
            reasons[reason] = reasons.get(reason, 0) + 1
        summaries.append(
            WorkloadSummary(
                workload=name,
                total=len(rows),
                failed=len(bad),
                latency=Latencies.of([sample.duration_ms for sample in good]),
                first_token=Latencies.of(
                    [sample.first_token_ms for sample in good if sample.first_token_ms is not None]
                ),
                failures=tuple(sorted(reasons.items(), key=lambda pair: (-pair[1], pair[0]))),
            )
        )
    return RunSummary(label=label, seconds=seconds, workloads=tuple(summaries))

"""What this suite calls a pass, and why each number is where it is.

NFA-004's acceptance asks for *agreed* success thresholds. These are **proposed**
rather than agreed: they are stated here so that a run has a verdict instead of a
wall of numbers, and so that the conversation about them is about a specific
figure rather than about whether there should be one. Nothing here is a
commitment made on anyone's behalf, and `docs/load-testing.md` says so in the
same words.

Two of them are borrowed and marked: the standard-query latency target belongs to
NFA-001, and the 1000-user figure to NFA-006. Neither is proven by a run on one
machine, which is why this module carries the first and not the second - a
threshold nothing here can measure would be a threshold that passes by not being
checked.

Each threshold names the workload it judges, because one number over a mixed run
is meaningless: an upload and a list are not the same request, and a p95 across
both describes neither.
"""

from __future__ import annotations

from dataclasses import dataclass

from metrics import RunSummary


@dataclass(frozen=True)
class Threshold:
    """One claim a run either meets or does not."""

    workload: str
    metric: str
    """`p95`, `p99`, `first_token_p95` or `error_rate`."""

    limit: float
    unit: str
    rationale: str


@dataclass(frozen=True)
class Verdict:
    """What a run did against one threshold."""

    threshold: Threshold
    measured: float
    met: bool
    counted: int
    """How many samples the measurement rests on. A tail described by four
    requests is a tail nobody should act on, and the report prints this beside
    the verdict rather than leaving it to be inferred."""


PROPOSED: tuple[Threshold, ...] = (
    Threshold(
        workload="api_read",
        metric="p95",
        limit=300.0,
        unit="ms",
        rationale=(
            "An ordinary authenticated list - agents, runs, conversations. It is one "
            "query behind a permission check, so anything above this is the platform "
            "queueing rather than the work taking that long. NFA-001's standard-query "
            "target is the outward-facing sibling of this number."
        ),
    ),
    Threshold(
        workload="api_read",
        metric="error_rate",
        limit=0.001,
        unit="fraction",
        rationale=(
            "A read that fails is a read nothing excused. One in a thousand leaves "
            "room for a connection recycled mid-request and for nothing else."
        ),
    ),
    Threshold(
        workload="chat_stream",
        metric="first_token_p95",
        limit=1500.0,
        unit="ms",
        rationale=(
            "Measured against the stub model, so this is the platform's share of "
            "time to first token: the socket, the auth, the spec load, the capability "
            "build and the run row. A provider adds its own and is measured separately."
        ),
    ),
    Threshold(
        workload="chat_stream",
        metric="error_rate",
        limit=0.01,
        unit="fraction",
        rationale=(
            "A dropped socket costs a person their answer. Higher than the read "
            "ceiling because a stream has more to go wrong in and a reconnect is a "
            "designed path, not because a disconnect is acceptable."
        ),
    ),
    Threshold(
        workload="agent_run",
        metric="p95",
        limit=5000.0,
        unit="ms",
        rationale=(
            "A whole non-streaming run against the stub, end to end. It bounds the "
            "run path rather than the model: budgets checked, the spec resolved, the "
            "row written twice, and the answer serialized."
        ),
    ),
    Threshold(
        workload="rag_query",
        metric="p95",
        limit=1200.0,
        unit="ms",
        rationale=(
            "Retrieval on a seeded collection: one embedding call to the stub and one "
            "vector search. The embedding is local, so what this bounds is pgvector "
            "and the pool in front of it."
        ),
    ),
    Threshold(
        workload="ingest",
        metric="error_rate",
        limit=0.0,
        unit="fraction",
        rationale=(
            "An upload that is accepted and then lost is the worst failure on this "
            "list, because nothing tells the person. Zero, and a run that cannot hold "
            "it says how many it dropped."
        ),
    ),
    Threshold(
        workload="trigger_fire",
        metric="error_rate",
        limit=0.0,
        unit="fraction",
        rationale=(
            "A webhook that answers 2xx has taken responsibility for the event. What "
            "this bounds is admission, not the run it dispatches - the worker's own "
            "latency is measured where the worker is, and this suite does not claim it."
        ),
    ),
)


def measure(summary: RunSummary, threshold: Threshold) -> Verdict:
    """What a run did against one threshold.

    A workload that produced no samples is *not* a pass. A run that skipped a
    scenario and reported green for it is the failure this whole file exists to
    avoid, so an absent workload reads as unmet with a count of zero, and the
    report says which.
    """
    entry = summary.workload(threshold.workload)
    if entry is None or entry.total == 0:
        return Verdict(threshold=threshold, measured=0.0, met=False, counted=0)

    if threshold.metric == "error_rate":
        measured = entry.error_rate
        counted = entry.total
    elif threshold.metric == "first_token_p95":
        measured = entry.first_token.p95
        counted = entry.first_token.count
    else:
        measured = getattr(entry.latency, threshold.metric)
        counted = entry.latency.count

    if counted == 0:
        return Verdict(threshold=threshold, measured=0.0, met=False, counted=0)
    return Verdict(
        threshold=threshold, measured=measured, met=measured <= threshold.limit, counted=counted
    )


def judge(summary: RunSummary) -> tuple[Verdict, ...]:
    """Every proposed threshold, measured against this run."""
    return tuple(measure(summary, threshold) for threshold in PROPOSED)

"""What the run does, in what proportions, and over what shape of time.

The mix is here rather than in the driver because it is the part a reader has to
agree with. NFA-004 asks for representative workloads with their proportions and
arrival rate stated, and "representative" is a claim about this product: an
AgenticOS deployment is mostly people reading lists, some of them talking to an
agent, a few of them uploading a document, and a steady trickle of events firing
routines nobody is watching. The proportions below say that in numbers, and
`docs/load-testing.md` says where they came from so that somebody who disagrees
can change one line and re-run.

**Arrival rate, not a thread pool.** The driver opens requests on a schedule
rather than keeping N workers busy, which is the difference between measuring a
system and measuring your own client: a closed loop of workers slows its own
arrival rate exactly when the server slows down, so a server that has fallen over
reports a comfortable latency and a throughput that quietly halved. An open
arrival model keeps offering work at the stated rate and lets the queue grow,
which is the thing under test.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Phase:
    """One stretch of a run, at one arrival rate."""

    name: str
    seconds: float
    rate_per_second: float
    """Requests offered a second, across the whole mix."""

    note: str


@dataclass(frozen=True)
class WorkloadShare:
    """One workload, and how much of the mix it is."""

    name: str
    share: float
    description: str


MIX: tuple[WorkloadShare, ...] = (
    WorkloadShare(
        name="api_read",
        share=0.45,
        description=(
            "Authenticated list reads - agents, runs, conversations. The console's "
            "own traffic and the bulk of any deployment's request count."
        ),
    ),
    WorkloadShare(
        name="chat_stream",
        share=0.20,
        description=(
            "A chat turn over the WebSocket, streamed. One in five of these is "
            "cancelled part-way, because a person changing their mind mid-answer is "
            "ordinary and the socket teardown is what it exercises."
        ),
    ),
    WorkloadShare(
        name="agent_run",
        share=0.15,
        description=(
            "POST /agents/{id}/run - the non-streaming API path another system uses. "
            "Same runner, same budget check, same rows, no socket."
        ),
    ),
    WorkloadShare(
        name="rag_query",
        share=0.12,
        description="Retrieval against a seeded collection: one embedding, one vector search.",
    ),
    WorkloadShare(
        name="ingest",
        share=0.05,
        description=(
            "A small document uploaded into the collection. Rarer than the rest by a "
            "long way, and the most expensive thing in the mix per request."
        ),
    ),
    WorkloadShare(
        name="trigger_fire",
        share=0.03,
        description=(
            "A webhook firing a routine. What is measured is admission - the run it "
            "dispatches belongs to the worker, and this suite does not claim its latency."
        ),
    ),
)

PHASES: tuple[Phase, ...] = (
    Phase(
        name="ramp",
        seconds=60.0,
        rate_per_second=4.0,
        note="Arrival climbs to the sustained rate, so a cold cache is not measured as steady state.",
    ),
    Phase(
        name="sustain",
        seconds=180.0,
        rate_per_second=12.0,
        note="The number every threshold is judged against. Long enough for a pool to settle.",
    ),
    Phase(
        name="burst",
        seconds=45.0,
        rate_per_second=36.0,
        note="Three times the sustained rate, which is what a scheduled fan-out looks like.",
    ),
    Phase(
        name="recover",
        seconds=60.0,
        rate_per_second=12.0,
        note=(
            "Back to the sustained rate. A platform that recovers and one that stays "
            "degraded look identical during the burst and different here."
        ),
    ),
)

CANCELLED_STREAM_SHARE = 0.20
"""How many chat turns are abandoned before the answer finishes."""


def normalized(mix: tuple[WorkloadShare, ...] = MIX) -> tuple[WorkloadShare, ...]:
    """The mix with its shares scaled to sum to one.

    A mix is edited by hand and hands do not add up to 1.0. Scaling rather than
    refusing keeps a one-line edit usable, and the report prints the normalised
    shares so a reader sees what actually ran rather than what was typed.
    """
    total = sum(entry.share for entry in mix)
    if total <= 0:
        raise ValueError("A workload mix needs at least one workload with a positive share.")
    return tuple(
        WorkloadShare(name=entry.name, share=entry.share / total, description=entry.description)
        for entry in mix
    )


def schedule(phases: tuple[Phase, ...] = PHASES) -> tuple[tuple[str, float, float], ...]:
    """Each phase as (name, starts_at, ends_at) seconds from the run's beginning."""
    marks = []
    elapsed = 0.0
    for phase in phases:
        marks.append((phase.name, elapsed, elapsed + phase.seconds))
        elapsed += phase.seconds
    return tuple(marks)


def phase_at(seconds: float, phases: tuple[Phase, ...] = PHASES) -> Phase | None:
    """Which phase a moment falls in, or None once the run is over."""
    elapsed = 0.0
    for phase in phases:
        if seconds < elapsed + phase.seconds:
            return phase
        elapsed += phase.seconds
    return None


PHI = 0.6180339887498949
"""The golden ratio's fractional part, which is what spaces the mix out.

Deterministic rather than random, so two runs at the same rate issue the same
number of uploads and a difference between them is the platform's. And a
low-discrepancy sequence rather than a plain cycle: walking the mix in order
would send forty-five reads, then twenty streams, then fifteen runs, which is
four different workloads in sequence rather than one mixed workload. Multiples of
PHI modulo one never fall in the same place twice and converge on the stated
proportions from the first few dozen requests, so any window of the run looks
like the mix.
"""


def pick(index: int, mix: tuple[WorkloadShare, ...]) -> str:
    """Which workload the `index`-th request of the run is."""
    position = (index * PHI) % 1.0
    running = 0.0
    for entry in mix:
        running += entry.share
        if position < running:
            return entry.name
    return mix[-1].name

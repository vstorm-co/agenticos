"""How two eval arms compare: per case, per tag, and as one verdict.

Pure arithmetic over outcomes the scorers already produced, kept apart from the
service that gathers them so every rule here can be checked without a database.

The rules are the ones a gate can trust:

* **An outcome is pass, fail or undecided.** An agent that crashed failed the
  case. A case nothing grades is ungraded; one a provider or a scorer failed
  on, or whose tries tied, is incomplete. Neither is ever counted as a pass,
  and both are counted beside the pass rate rather than dropped.
* **A flip is confirmed only when it reproduces.** A case that changed outcome
  is rerun; it stays a regression (or a fix) only if every rerun repeats it on
  the side it was rerun on.
* **A verdict rests on confirmed flips.** One confirmed regression makes the
  candidate worse, confirmed fixes alone make it better, both make it mixed.
  An exact McNemar test over the confirmed flips says separately whether the
  candidate is better or worse overall, which a handful of flips cannot show.
* **A case settles on the majority of its attempts.** A case that was rerun
  passes or fails as most of its decided attempts did, unless a person decided
  its first answer; the pass rate counts settled outcomes, and the first
  answers' rate is kept beside it.
* **Quality and efficiency are separate axes.** Cost, tokens and latency are
  reported beside the pass rate, each as better, worse or unchanged within a
  tolerance, and never folded into it.
"""

import enum
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal
from uuid import UUID

type Outcome = bool | None


class CaseState(enum.StrEnum):
    """How one attempt came out, and when undecided, why."""

    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    """Something failed on it - the provider, a scorer, the run itself - or it never ran."""

    UNGRADED = "ungraded"
    """It was answered, and nothing the dataset grades with applies to it."""


class Flip(enum.StrEnum):
    """How one case moved from the baseline to the candidate."""

    REGRESSION = "regression"
    FIXED = "fixed"
    UNCHANGED = "unchanged"
    INCOMPLETE = "incomplete"


class Verdict(enum.StrEnum):
    """What the quality axis says about the candidate as a whole."""

    BETTER = "better"
    WORSE = "worse"
    MIXED = "mixed"
    NO_DIFFERENCE = "no_difference"
    INVALID = "invalid"


class Trend(enum.StrEnum):
    """Where one efficiency metric moved, within the tolerance."""

    BETTER = "better"
    WORSE = "worse"
    UNCHANGED = "unchanged"
    UNKNOWN = "unknown"


def classify(baseline: Outcome, candidate: Outcome) -> Flip:
    """The flip between two outcomes of the same case."""
    if baseline is None or candidate is None:
        return Flip.INCOMPLETE
    if baseline and not candidate:
        return Flip.REGRESSION
    if candidate and not baseline:
        return Flip.FIXED
    return Flip.UNCHANGED


@dataclass(frozen=True)
class PairedCase:
    """One case's outcomes on both sides, its reruns included.

    Attributes:
        case_id: The stable case id both sides were matched on.
        baseline: The baseline's first attempt.
        candidate: The candidate's first attempt.
        baseline_reruns: The baseline's confirmation attempts - empty when the
            baseline is a past run, which cannot be rerun.
        candidate_reruns: The candidate's confirmation attempts.
        tags: The case's tags, for the per-tag breakdown.
    """

    case_id: UUID
    baseline: Outcome
    candidate: Outcome
    baseline_reruns: tuple[Outcome, ...] = ()
    candidate_reruns: tuple[Outcome, ...] = ()
    tags: tuple[str, ...] = ()

    @property
    def flip(self) -> Flip:
        return classify(self.baseline, self.candidate)

    @property
    def confirmed(self) -> bool:
        """Whether every rerun repeated the flip on the side it was rerun on.

        A flip nobody reran is unconfirmed, whatever it looks like.
        """
        if self.flip not in (Flip.REGRESSION, Flip.FIXED) or not self.candidate_reruns:
            return False
        return all(run is self.candidate for run in self.candidate_reruns) and all(
            run is self.baseline for run in self.baseline_reruns
        )


def mcnemar_p(regressions: int, fixed: int) -> float:
    """Two-sided exact McNemar p-value for the discordant pairs.

    Under no difference each flip is a fair coin between the two directions,
    so the p-value is a binomial tail doubled and capped at one.
    """
    flips = regressions + fixed
    if flips == 0:
        return 1.0
    fewer = min(regressions, fixed)
    tail = sum(math.comb(flips, k) for k in range(fewer + 1)) / 2**flips
    return min(1.0, 2 * tail)


@dataclass(frozen=True)
class QualityVerdict:
    """What the confirmed flips say about the candidate.

    Attributes:
        verdict: Worse with a confirmed regression beyond the tolerance, better
            with confirmed fixes alone, mixed with both.
        p_value: The McNemar p-value over the confirmed flips, or `None` with
            none to test.
        overall: Which way the candidate moved as a whole, when the test can
            tell - `None` when the flips are too few to say.
    """

    verdict: Verdict
    p_value: float | None = None
    overall: Literal["better", "worse"] | None = None


def quality_verdict(
    cases: Sequence[PairedCase], *, alpha: float, invalid: bool = False, tolerance: int = 0
) -> QualityVerdict:
    """The candidate's verdict on quality.

    `invalid` is set when the two sides were scored by different judges or
    scoring, which no arithmetic can repair. `tolerance` is how many confirmed
    regressions the verdict lets pass.
    """
    if invalid:
        return QualityVerdict(Verdict.INVALID)
    confirmed = [case for case in cases if case.confirmed]
    regressions = sum(1 for case in confirmed if case.flip is Flip.REGRESSION)
    fixed = len(confirmed) - regressions
    if regressions + fixed == 0:
        return QualityVerdict(Verdict.NO_DIFFERENCE)
    p = mcnemar_p(regressions, fixed)
    overall: Literal["better", "worse"] | None = (
        None if p >= alpha else "worse" if regressions > fixed else "better"
    )
    broke = regressions > tolerance
    if broke and fixed:
        verdict = Verdict.MIXED
    elif broke:
        verdict = Verdict.WORSE
    elif fixed:
        verdict = Verdict.BETTER
    else:
        verdict = Verdict.NO_DIFFERENCE
    return QualityVerdict(verdict, p, overall)


def settle(outcomes: Sequence[Outcome]) -> Outcome:
    """How a case came out over all its attempts: as most of its decided ones did.

    A tie, or nothing decided, leaves it undecided.
    """
    passed = sum(1 for outcome in outcomes if outcome is True)
    failed = sum(1 for outcome in outcomes if outcome is False)
    if passed == failed:
        return None
    return passed > failed


@dataclass(frozen=True)
class Attempt:
    """One case's first scored attempt on one arm, and how its reruns came out."""

    outcome: Outcome
    cost_usd: Decimal | None = None
    tokens: int | None = None
    latency_ms: int | None = None
    tags: tuple[str, ...] = ()
    reruns: tuple[Outcome, ...] = ()
    by_person: bool = False
    ungraded: bool = False
    """Undecided because nothing could grade it, rather than because something failed."""
    crashed: bool = False
    """The agent's run failed before it answered, rather than answering wrong."""

    @property
    def settled(self) -> Outcome:
        """A person's decision on the first answer settles the case; else the majority."""
        return self.outcome if self.by_person else settle((self.outcome, *self.reruns))


@dataclass(frozen=True)
class ArmSummary:
    """Both axes for one arm: quality over settled outcomes, efficiency over first attempts.

    Attributes:
        cases: How many cases were attempted.
        passed: How many settled as passed.
        failed: How many settled as failed.
        incomplete: How many could not be decided because something failed on
            them, or their tries tied.
        ungraded: How many could not be decided because nothing grades them.
        crashed: How many first answers the agent's run failed before giving.
        pass_rate: `passed` over the decided cases, or `None` with none decided.
        first_pass_rate: The same over first attempts alone, reruns aside.
        cost_usd: What the attempts cost together.
        cost_per_pass: `cost_usd` over `passed`, or `None` with nothing passed.
        avg_tokens: Mean tokens per attempt that recorded any.
        p50_ms: Median latency.
        p95_ms: 95th percentile latency.
        by_tag: The same summary per tag.
    """

    cases: int
    passed: int
    failed: int
    incomplete: int
    ungraded: int
    crashed: int
    pass_rate: float | None
    first_pass_rate: float | None
    cost_usd: Decimal
    cost_per_pass: Decimal | None
    avg_tokens: float | None
    p50_ms: float | None
    p95_ms: float | None
    by_tag: dict[str, ArmSummary] = field(default_factory=dict)


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Linear interpolation between closest ranks, as Postgres' `percentile_cont`."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize(attempts: Sequence[Attempt], *, with_tags: bool = True) -> ArmSummary:
    """Both axes over a set of attempts, and per tag when asked."""
    settled = [a.settled for a in attempts]
    passed = sum(1 for outcome in settled if outcome is True)
    failed = sum(1 for outcome in settled if outcome is False)
    decided = passed + failed
    ungraded = sum(
        1 for a, outcome in zip(attempts, settled, strict=True) if outcome is None and a.ungraded
    )
    first_passed = sum(1 for a in attempts if a.outcome is True)
    first_decided = first_passed + sum(1 for a in attempts if a.outcome is False)
    cost = sum((a.cost_usd for a in attempts if a.cost_usd is not None), Decimal(0))
    tokens = [a.tokens for a in attempts if a.tokens is not None]
    latencies = [float(a.latency_ms) for a in attempts if a.latency_ms is not None]
    by_tag: dict[str, ArmSummary] = {}
    if with_tags:
        for tag in sorted({tag for a in attempts for tag in a.tags}):
            by_tag[tag] = summarize([a for a in attempts if tag in a.tags], with_tags=False)
    return ArmSummary(
        cases=len(attempts),
        passed=passed,
        failed=failed,
        incomplete=len(attempts) - decided - ungraded,
        ungraded=ungraded,
        crashed=sum(1 for a in attempts if a.crashed),
        pass_rate=passed / decided if decided else None,
        first_pass_rate=first_passed / first_decided if first_decided else None,
        cost_usd=cost,
        cost_per_pass=cost / passed if passed else None,
        avg_tokens=sum(tokens) / len(tokens) if tokens else None,
        p50_ms=percentile(latencies, 0.5),
        p95_ms=percentile(latencies, 0.95),
        by_tag=by_tag,
    )


def trend(
    baseline: float | Decimal | None,
    candidate: float | Decimal | None,
    *,
    tolerance: float,
    lower_is_better: bool = True,
) -> Trend:
    """Where one metric moved, treating a relative change within `tolerance` as none."""
    if baseline is None or candidate is None:
        return Trend.UNKNOWN
    before, after = float(baseline), float(candidate)
    if before == after:
        return Trend.UNCHANGED
    change = (after - before) / abs(before) if before else math.copysign(math.inf, after)
    if abs(change) <= tolerance:
        return Trend.UNCHANGED
    improved = change < 0 if lower_is_better else change > 0
    return Trend.BETTER if improved else Trend.WORSE


@dataclass(frozen=True)
class EfficiencyTrends:
    """The efficiency axis: each metric's direction from baseline to candidate."""

    cost_per_pass: Trend
    avg_tokens: Trend
    p50_ms: Trend
    p95_ms: Trend


def efficiency(
    baseline: ArmSummary, candidate: ArmSummary, *, tolerance: float
) -> EfficiencyTrends:
    """The efficiency axis between two arm summaries."""
    return EfficiencyTrends(
        cost_per_pass=trend(baseline.cost_per_pass, candidate.cost_per_pass, tolerance=tolerance),
        avg_tokens=trend(baseline.avg_tokens, candidate.avg_tokens, tolerance=tolerance),
        p50_ms=trend(baseline.p50_ms, candidate.p50_ms, tolerance=tolerance),
        p95_ms=trend(baseline.p95_ms, candidate.p95_ms, tolerance=tolerance),
    )


def flips_by_tag(cases: Iterable[PairedCase]) -> dict[str, dict[Flip, int]]:
    """How many cases flipped each way, per tag."""
    counts: dict[str, dict[Flip, int]] = {}
    for case in cases:
        for tag in case.tags:
            per_tag = counts.setdefault(tag, dict.fromkeys(Flip, 0))
            per_tag[case.flip] += 1
    return counts

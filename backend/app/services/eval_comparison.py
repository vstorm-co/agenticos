"""How two eval arms compare: per case, per tag, and as one verdict.

Comparison arithmetic over outcomes the scorers already produced, kept apart from the
service that gathers them so every rule can be checked without the application database.

The rules are the ones a gate can trust:

* **An outcome is pass, fail or undecided.** An agent that crashed failed the
  case. A case nothing grades is ungraded; one a provider or a scorer failed
  on, or whose tries tied, is incomplete. Neither is ever counted as a pass,
  and both are counted beside the pass rate rather than dropped.
* **A flip is confirmed only when it reproduces on both sides.** A case that
  changed outcome is rerun on the candidate and on the baseline; it stays a
  regression (or a fix) only if every rerun repeats it on the side it was rerun
  on. A baseline nobody reran confirms nothing, however it came out once -
  unless it is the candidate itself at an earlier time, the same spec on the
  same model, whose reruns would only be the candidate's again.
* **A criterion moves as a case flips.** Each check, judge criterion, expected
  call and reference grade is compared on its own over the same cases. A case
  that still fails can so show what a change fixed in it.
* **A family moves across cases.** The criteria of one family - every case's
  "total including VAT" check - pass in a case when all of them pass there, and
  the family is compared case by case. Its direction is settled by an exact
  McNemar test over its own flipped cases when they are enough to tell; only a
  family that moved and is not settled sends its flipped cases to be asked
  again, and then counts what the reruns repeated. A family that moved on fewer
  than two cases decides nothing.
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
import sqlite3
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from contextlib import closing
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
        baseline_reruns: The baseline's confirmation attempts - empty for a
            baseline that was never rerun, which leaves every flip unconfirmed.
        candidate_reruns: The candidate's confirmation attempts.
        tags: The case's tags, for the per-tag breakdown.
    """

    case_id: UUID
    baseline: Outcome
    candidate: Outcome
    baseline_reruns: tuple[Outcome, ...] = ()
    candidate_reruns: tuple[Outcome, ...] = ()
    tags: tuple[str, ...] = ()
    drift: bool = False
    """The baseline is the candidate's own spec and model, answering at an earlier time."""

    @property
    def flip(self) -> Flip:
        return classify(self.baseline, self.candidate)

    @property
    def confirmed(self) -> bool:
        """Whether every rerun repeated the flip on the side it was rerun on.

        A flip either side was not rerun on is unconfirmed, whatever it looks like.
        """
        return reproduced(
            self.baseline,
            self.candidate,
            self.baseline_reruns,
            self.candidate_reruns,
            drift=self.drift,
        )


def reproduced(
    baseline: Outcome,
    candidate: Outcome,
    baseline_reruns: Sequence[Outcome],
    candidate_reruns: Sequence[Outcome],
    *,
    drift: bool,
) -> bool:
    """Whether a flip between two outcomes held on every rerun of the side it was rerun on.

    A flip either side was not rerun on is unconfirmed; `drift` stands in for a
    baseline that is the candidate itself at an earlier time.
    """
    if classify(baseline, candidate) not in (Flip.REGRESSION, Flip.FIXED):
        return False
    if not candidate_reruns or not (baseline_reruns or drift):
        return False
    return all(run is candidate for run in candidate_reruns) and all(
        run is baseline for run in baseline_reruns
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
    criteria: tuple[int, int] | None = None
    """Of the first answer's required criteria that decided, how many passed and how many
    there were; `None` with none decided."""

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
        criteria_passed: First answers' required criteria that passed, summed over cases.
        criteria_graded: First answers' required criteria that decided, summed over cases.
        partial_credit: The mean, over cases with a criterion decided, of the share of
            its criteria that passed - a question passing six of seven counts 6/7.
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
    criteria_passed: int = 0
    criteria_graded: int = 0
    partial_credit: float | None = None
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
    criteria = [a.criteria for a in attempts if a.criteria is not None and a.criteria[1]]
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
        criteria_passed=sum(passed for passed, _ in criteria),
        criteria_graded=sum(graded for _, graded in criteria),
        partial_credit=sum(passed / graded for passed, graded in criteria) / len(criteria)
        if criteria
        else None,
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


type Criterion = tuple[str, str]
"""A graded criterion: the scorer kind and the name it grades under."""

type Grades = Mapping[Criterion, Outcome]
"""How one attempt came out on each criterion that graded it."""


_STATUS_OUTCOME: dict[object, bool] = {"pass": True, "fail": False}


def _required(
    results: Iterable[Mapping[str, object]],
) -> Iterable[tuple[Criterion, Mapping[str, object]]]:
    """Each required result under the criterion it grades.

    Two results under one scorer and name - two schema checks at one path - are
    told apart by their order, which the same scoring repeats on every answer.
    Repeats get an unused numbered suffix without overwriting a criterion whose
    literal name includes it.
    """
    required = [result for result in results if result.get("required") is not False]
    original_names = {(str(result["scorer"]), str(result["name"])) for result in required}
    taken: set[Criterion] = set()
    seen: Counter[Criterion] = Counter()
    for result in required:
        criterion = (str(result["scorer"]), str(result["name"]))
        seen[criterion] += 1
        if seen[criterion] > 1:
            original = criterion
            criterion = (original[0], f"{original[1]} #{seen[original]}")
            # A literal criterion name may already use the generated suffix.
            while criterion in original_names or criterion in taken:
                seen[original] += 1
                criterion = (original[0], f"{original[1]} #{seen[original]}")
        taken.add(criterion)
        yield criterion, result


def grades(results: Iterable[Mapping[str, object]]) -> dict[Criterion, Outcome]:
    """A stored score's required results as criterion outcomes.

    A skipped or failed scorer decides none. An optional result is left out, as
    `case_passed` leaves it out of the question.
    """
    return {
        criterion: _STATUS_OUTCOME.get(result.get("status"))
        for criterion, result in _required(results)
    }


def families(results: Iterable[Mapping[str, object]]) -> dict[Criterion, str]:
    """The family each required result's check named, keyed as `grades` keys them.

    A result whose check named none is left out: it is a family of its own.
    """
    return {
        criterion: str(result["family"])
        for criterion, result in _required(results)
        if result.get("family")
    }


@dataclass(frozen=True)
class PairedGrades:
    """One case's criterion outcomes on both sides, its reruns included.

    Confirmed as `PairedCase` is: the reruns of each side repeat the criterion's flip.
    `named` is the family each criterion's check named in this case, from either
    side's scores: a side scored before families existed names none, and the other
    side's names hold for both.
    """

    baseline: Grades
    candidate: Grades
    baseline_reruns: tuple[Grades, ...] = ()
    candidate_reruns: tuple[Grades, ...] = ()
    drift: bool = False
    named: Mapping[Criterion, str] = field(default_factory=dict)

    def flip(self, criterion: Criterion) -> Flip:
        return classify(self.baseline.get(criterion), self.candidate.get(criterion))

    def confirmed(self, criterion: Criterion) -> bool:
        return reproduced(
            self.baseline.get(criterion),
            self.candidate.get(criterion),
            tuple(run.get(criterion) for run in self.baseline_reruns),
            tuple(run.get(criterion) for run in self.candidate_reruns),
            drift=self.drift,
        )


@dataclass(frozen=True)
class CriterionMove:
    """How one criterion came out on the cases both sides graded on it.

    Attributes:
        scorer: The scorer kind grading it.
        name: The name it is graded under.
        graded: Cases whose first answer it graded on both sides.
        baseline_passed: Of those, how many the baseline's first answer passed.
        candidate_passed: Of those, how many the candidate's first answer passed.
        fixed_confirmed: Cases it went from fail to pass on, repeated by every rerun.
        broken_confirmed: Cases it went from pass to fail on, repeated by every rerun.
        fixed_unconfirmed: Cases it looked fixed on once, and the reruns did not repeat.
        broken_unconfirmed: Cases it looked broken on once, and the reruns did not repeat.
    """

    scorer: str
    name: str
    graded: int
    baseline_passed: int
    candidate_passed: int
    fixed_confirmed: int
    broken_confirmed: int
    fixed_unconfirmed: int = 0
    broken_unconfirmed: int = 0

    @property
    def worse(self) -> bool:
        """A confirmed break, as one confirmed regression makes a candidate worse."""
        return self.broken_confirmed > 0

    @property
    def better(self) -> bool:
        """Confirmed fixes alone, and no fewer passes than before."""
        return (
            not self.worse
            and self.fixed_confirmed > 0
            and self.candidate_passed >= self.baseline_passed
        )


MIN_FAMILY_CASES = 2
"""Cases a family must have moved on to decide anything; one case is one answer."""


def family_of(criterion: Criterion, named: Mapping[Criterion, str]) -> str:
    """The family a criterion is counted in: the one its check named, else its own name."""
    return named.get(criterion, criterion[1])


def family_outcomes(graded: Grades, named: Mapping[Criterion, str]) -> dict[str, Outcome]:
    """How each family came out in one answer: passed when every criterion of it passed.

    One failed criterion fails the family; with none failed, one undecided leaves it
    undecided.
    """
    members: dict[str, list[Outcome]] = {}
    for criterion, outcome in graded.items():
        members.setdefault(family_of(criterion, named), []).append(outcome)
    return {
        family: False if False in outcomes else None if None in outcomes else True
        for family, outcomes in members.items()
    }


@dataclass(frozen=True)
class FamilyMove:
    """How one family came out on the cases both sides graded it on, first answers counted.

    Attributes:
        family: The family's name - the one its checks named, or a lone criterion's.
        criteria: The criteria counted in it, by name, sorted.
        cases: Cases whose first answer graded it on both sides.
        baseline_passed: Of those, how many the baseline passed.
        candidate_passed: Of those, how many the candidate passed.
        fixed: Cases it went from fail to pass on in the first answers.
        broken: Cases it went from pass to fail on in the first answers.
        fixed_confirmed: Of `fixed`, those every rerun on both sides repeated.
        broken_confirmed: Of `broken`, those every rerun on both sides repeated.
        p_value: The exact McNemar p-value over `fixed` and `broken`.
        settled: Whether its flipped cases are enough on their own to tell its
            direction, at the significance the comparison was made with.
    """

    family: str
    criteria: tuple[str, ...]
    cases: int
    baseline_passed: int
    candidate_passed: int
    fixed: int
    broken: int
    fixed_confirmed: int
    broken_confirmed: int
    p_value: float
    settled: bool

    @property
    def moved(self) -> bool:
        """Whether it flipped on enough cases to decide anything."""
        return self.fixed + self.broken >= MIN_FAMILY_CASES

    @property
    def fixed_held(self) -> int:
        """Fixed cases that count: every flipped one when settled, else the confirmed ones."""
        return self.fixed if self.settled else self.fixed_confirmed

    @property
    def broken_held(self) -> int:
        """Broken cases that count: every flipped one when settled, else the confirmed ones."""
        return self.broken if self.settled else self.broken_confirmed

    @property
    def needs_reruns(self) -> bool:
        """Moved, and only asking its flipped cases again can tell which way."""
        return self.moved and not self.settled

    @property
    def worse(self) -> bool:
        """More cases held broken than fixed, on at least two cases."""
        return self.broken_held >= MIN_FAMILY_CASES and self.broken_held > self.fixed_held

    @property
    def better(self) -> bool:
        """More cases held fixed than broken, on at least two, and no fewer passes."""
        return (
            self.fixed_held >= MIN_FAMILY_CASES
            and self.fixed_held > self.broken_held
            and self.candidate_passed >= self.baseline_passed
        )


MAX_COMPARED_CRITERIA = 200
"""Criteria a comparison reports. A dataset's per-case checks can name thousands."""

MAX_COMPARED_FAMILIES = 200
"""Families a comparison reports. Per-case checks that name no family are one each."""


@dataclass(frozen=True)
class CriterionComparison:
    """Bounded detail and normalized confirmed movement over every graded pair.

    Attributes:
        moves: The criteria kept, by scorer and then name.
        change: Confirmed fixes less confirmed breaks, over every criterion graded.
        families: The families kept, by name.
        undecided: Every family that moved and that its first answers cannot settle,
            however many families were kept.
    """

    moves: list[CriterionMove]
    change: float
    families: list[FamilyMove] = field(default_factory=list)
    undecided: frozenset[str] = frozenset()


_MOVE_UPSERT = (
    "INSERT INTO moves VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT (scorer, name) DO UPDATE SET "
    "graded = graded + excluded.graded, "
    "baseline_passed = baseline_passed + excluded.baseline_passed, "
    "candidate_passed = candidate_passed + excluded.candidate_passed, "
    "fixed_confirmed = fixed_confirmed + excluded.fixed_confirmed, "
    "broken_confirmed = broken_confirmed + excluded.broken_confirmed, "
    "fixed_unconfirmed = fixed_unconfirmed + excluded.fixed_unconfirmed, "
    "broken_unconfirmed = broken_unconfirmed + excluded.broken_unconfirmed"
)

_FAMILY_UPSERT = (
    "INSERT INTO families VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT (family) DO UPDATE SET "
    "cases = cases + excluded.cases, "
    "baseline_passed = baseline_passed + excluded.baseline_passed, "
    "candidate_passed = candidate_passed + excluded.candidate_passed, "
    "fixed = fixed + excluded.fixed, "
    "broken = broken + excluded.broken, "
    "fixed_confirmed = fixed_confirmed + excluded.fixed_confirmed, "
    "broken_confirmed = broken_confirmed + excluded.broken_confirmed"
)


def compare_criteria(
    cases: Iterable[PairedGrades],
    *,
    alpha: float,
    limit: int = MAX_COMPARED_CRITERIA,
    family_limit: int = MAX_COMPARED_FAMILIES,
) -> CriterionComparison:
    """The criteria and families graded on both sides of some case.

    Past `limit` criteria or `family_limit` families, the ones that decide a
    verdict are kept first - every one worse, then better, then any other that
    moved, then the ones failing most often - so a verdict read from the kept
    list is the one the whole list gives. A family's direction is settled at
    `alpha`.
    """
    if not 0 <= limit <= MAX_COMPARED_CRITERIA:
        raise ValueError("Criterion response limit must be between 0 and 200")
    if not 0 <= family_limit <= MAX_COMPARED_FAMILIES:
        raise ValueError("Family response limit must be between 0 and 200")
    # A private, automatically deleted scratch database spills beyond its 2 MiB
    # cache. A dict of every distinct criterion can exhaust a worker on valid data.
    with closing(sqlite3.connect("")) as scratch:
        scratch.execute("PRAGMA cache_size = -2048")
        scratch.execute("PRAGMA temp_store = FILE")
        scratch.execute("PRAGMA journal_mode = OFF")
        scratch.execute("PRAGMA synchronous = OFF")
        scratch.create_function("mcnemar_p", 2, mcnemar_p, deterministic=True)
        scratch.execute(
            "CREATE TABLE moves (scorer TEXT, name TEXT, graded INTEGER, "
            "baseline_passed INTEGER, candidate_passed INTEGER, fixed_confirmed INTEGER, "
            "broken_confirmed INTEGER, fixed_unconfirmed INTEGER, broken_unconfirmed INTEGER, "
            "PRIMARY KEY (scorer, name)) WITHOUT ROWID"
        )
        scratch.execute(
            "CREATE TABLE families (family TEXT PRIMARY KEY, cases INTEGER, "
            "baseline_passed INTEGER, candidate_passed INTEGER, fixed INTEGER, broken INTEGER, "
            "fixed_confirmed INTEGER, broken_confirmed INTEGER) WITHOUT ROWID"
        )
        scratch.execute(
            "CREATE TABLE members (family TEXT, name TEXT, PRIMARY KEY (family, name)) "
            "WITHOUT ROWID"
        )
        for case in cases:
            scratch.executemany(_MOVE_UPSERT, _criterion_contributions(case))
            scratch.executemany(_FAMILY_UPSERT, _family_contributions(case))
            scratch.executemany(
                "INSERT OR IGNORE INTO members VALUES (?, ?)",
                {
                    (family_of(criterion, case.named), criterion[1])
                    for criterion in case.baseline
                    if criterion in case.candidate
                },
            )
        # Aggregate before limiting detail, so selection sees every criterion.
        scratch.row_factory = _criterion_change_row
        change: float = scratch.execute(
            "SELECT coalesce(sum(fixed_confirmed - broken_confirmed), 0), "
            "coalesce(sum(graded), 0) FROM moves"
        ).fetchone()
        scratch.row_factory = _criterion_move_row
        # Rank and limit before constructing response objects. Name tie-breaks
        # match the former stable sort, including criteria with equal counts.
        moves = sorted(
            scratch.execute(
                "SELECT * FROM moves ORDER BY "
                "(broken_confirmed = 0), "
                "NOT (broken_confirmed = 0 AND fixed_confirmed > 0 "
                "AND candidate_passed >= baseline_passed), "
                "NOT (fixed_unconfirmed OR broken_unconfirmed OR fixed_confirmed), "
                "candidate_passed - graded, scorer, name LIMIT ?",
                (limit,),
            ),
            key=lambda move: (move.scorer, move.name),
        )
        scratch.row_factory = None
        judging = {"minimum": MIN_FAMILY_CASES, "alpha": alpha}
        # Settled and held as `FamilyMove` reads them, so ranking here keeps what it would.
        scratch.execute(
            "CREATE TABLE judged AS SELECT *, "
            "CASE WHEN settled THEN fixed ELSE fixed_confirmed END AS fixed_held, "
            "CASE WHEN settled THEN broken ELSE broken_confirmed END AS broken_held "
            "FROM (SELECT *, fixed + broken >= :minimum "
            "AND mcnemar_p(broken, fixed) < :alpha AS settled FROM families)",
            judging,
        )
        kept = scratch.execute(
            "SELECT family, cases, baseline_passed, candidate_passed, fixed, broken, "
            "fixed_confirmed, broken_confirmed FROM judged ORDER BY "
            "NOT (broken_held >= :minimum AND broken_held > fixed_held), "
            "NOT (fixed_held >= :minimum AND fixed_held > broken_held "
            "AND candidate_passed >= baseline_passed), "
            "NOT (fixed OR broken), candidate_passed - cases, family LIMIT :limit",
            {"minimum": MIN_FAMILY_CASES, "limit": family_limit},
        ).fetchall()
        family_list = [
            _family_move(row, criteria=_members(scratch, row[0]), alpha=alpha)
            for row in sorted(kept)
        ]
        undecided = frozenset(
            family
            for (family,) in scratch.execute(
                "SELECT family FROM judged WHERE fixed + broken >= ? AND NOT settled",
                (MIN_FAMILY_CASES,),
            )
        )
        return CriterionComparison(
            moves=moves, change=change, families=family_list, undecided=undecided
        )


def _criterion_change_row(_cursor: sqlite3.Cursor, row: tuple[int, int]) -> float:
    # Our aggregate SELECT always returns one pair of integer sums, including empty input.
    moved, graded = row
    return moved / graded if graded else 0.0


type _CriterionContribution = tuple[str, str, int, int, int, int, int, int, int]


def _criterion_contributions(case: PairedGrades) -> Iterable[_CriterionContribution]:
    """One case's contribution to each criterion it graded on both sides."""
    for (scorer, name), before in case.baseline.items():
        criterion = (scorer, name)
        after = case.candidate.get(criterion)
        if before is None or after is None:
            continue
        flip = case.flip(criterion)
        confirmed = case.confirmed(criterion)
        fixed = flip is Flip.FIXED
        broken = flip is Flip.REGRESSION
        yield (
            scorer,
            name,
            1,
            int(before),
            int(after),
            int(fixed and confirmed),
            int(broken and confirmed),
            int(fixed and not confirmed),
            int(broken and not confirmed),
        )


def _criterion_move_row(_cursor: sqlite3.Cursor, row: _CriterionContribution) -> CriterionMove:
    # The SELECT reads exactly the nine columns of our private scratch table.
    return CriterionMove(*row)


type _FamilyContribution = tuple[str, int, int, int, int, int, int, int]


def _family_contributions(case: PairedGrades) -> Iterable[_FamilyContribution]:
    """One case's contribution to each family it graded on both sides."""
    before = family_outcomes(case.baseline, case.named)
    after = family_outcomes(case.candidate, case.named)
    before_reruns = [family_outcomes(run, case.named) for run in case.baseline_reruns]
    after_reruns = [family_outcomes(run, case.named) for run in case.candidate_reruns]
    for family, was in before.items():
        now = after.get(family)
        if was is None or now is None:
            continue
        flip = classify(was, now)
        fixed = flip is Flip.FIXED
        broken = flip is Flip.REGRESSION
        confirmed = reproduced(
            was,
            now,
            tuple(run.get(family) for run in before_reruns),
            tuple(run.get(family) for run in after_reruns),
            drift=case.drift,
        )
        yield (
            family,
            1,
            int(was),
            int(now),
            int(fixed),
            int(broken),
            int(fixed and confirmed),
            int(broken and confirmed),
        )


def _members(scratch: sqlite3.Connection, family: str) -> tuple[str, ...]:
    rows = scratch.execute("SELECT name FROM members WHERE family = ? ORDER BY name", (family,))
    return tuple(name for (name,) in rows)


def _family_move(
    row: _FamilyContribution, *, criteria: tuple[str, ...], alpha: float
) -> FamilyMove:
    (
        family,
        cases,
        baseline_passed,
        candidate_passed,
        fixed,
        broken,
        fixed_confirmed,
        broken_confirmed,
    ) = row
    p = mcnemar_p(broken, fixed)
    return FamilyMove(
        family=family,
        criteria=criteria,
        cases=cases,
        baseline_passed=baseline_passed,
        candidate_passed=candidate_passed,
        fixed=fixed,
        broken=broken,
        fixed_confirmed=fixed_confirmed,
        broken_confirmed=broken_confirmed,
        p_value=p,
        settled=fixed + broken >= MIN_FAMILY_CASES and p < alpha,
    )


def family_flipped(
    baseline: Grades, candidate: Grades, named: Mapping[Criterion, str], among: Collection[str]
) -> bool:
    """Whether a family in `among` came out the other way in this case."""
    before = family_outcomes(baseline, named)
    after = family_outcomes(candidate, named)
    return any(
        classify(before[family], after.get(family)) in (Flip.REGRESSION, Flip.FIXED)
        for family in among
        if family in before
    )


def criteria_count(graded: Grades) -> tuple[int, int] | None:
    """How many of an answer's decided criteria passed, and how many decided; `None` with none."""
    decided = [outcome for outcome in graded.values() if outcome is not None]
    return (sum(decided), len(decided)) if decided else None

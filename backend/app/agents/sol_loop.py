"""A sol-loop review: one reviewer judges the work, in rounds, until it passes.

The shape is Theo's tstack sol-loop skill, as a domain module with no database
and no service imports, so it can be tested without a run: one reviewer - the
operator's Sol model, resolved by the runner - reviews the work in rounds. Round
1 is full; later rounds check only changed code and open findings. The agent
fixes what the reviewer found between rounds and calls again, until the loop
stops.

Three rules from the skill are load-bearing here and worth stating where the
code enforces them:

- **Budget end is not approval.** :func:`round_satisfied` needs an APPROVE on
  the current diff with no blocker or should open. A round that runs out of
  budget with either still open records `budget_exhausted` and is not
  satisfied.
- **Stop early on nits only.** A round whose findings are all nits stops the
  loop with `nits_only` - declined nits need no new round.
- **An unavailable reviewer is reported, never substituted.** A reviewer with
  no model, or whose review raises - including a budget cap skipping the call -
  records as `unavailable` with the reason, and the round stops with
  `reviewer_unavailable`. Substituting another model would review with a
  reviewer the operator did not choose.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai.models import Model

FindingSeverity = Literal["blocker", "should", "nit"]
"""How much a finding holds the work: `blocker` is an intended case wrong,
`should` is a real bug callers will hit, `nit` is the rest."""

FindingOutcome = Literal["agree-fixed", "disagree-with-evidence", "decline-nit"]
"""What the agent did with a finding: fixed it, disputed it with evidence, or
declined it as a nit. Recorded only as the agent passes it in - never guessed."""

StopReason = Literal["approved", "nits_only", "budget_exhausted", "stuck", "reviewer_unavailable"]
"""Why the loop stopped. `budget_exhausted` and `stuck` are not approval."""

# `VERDICT: APPROVE` or `VERDICT: CHANGES`, the reply format from the skill.
_VERDICT_RE = re.compile(r"VERDICT:\s*(APPROVE|CHANGES)", re.IGNORECASE)

# `S1 [blocker] path/to/file.py:123 claim. Fix: suggestion`, the finding
# format from the skill. The file token is non-greedy so `file:line` splits
# right, and `Fix:` only splits when it carries a colon - "Fix the typo" stays
# part of the claim.
_FINDING_RE = re.compile(
    r"^(S\d+)\s+\[(blocker|should|nit)\]\s+(\S+?)(?::(\d+))?\s+(.*?)(?:\s+Fix:\s*(.+))?$"
)

_KNOWN_OUTCOMES = frozenset({"agree-fixed", "disagree-with-evidence", "decline-nit"})


_SEVERITIES: dict[str, FindingSeverity] = {
    "blocker": "blocker",
    "should": "should",
    "nit": "nit",
}
"""The severities a finding line may carry, so a parsed one is one of them."""


class SolLoopFinding(BaseModel):
    """One finding in a review, with a stable id the ledger tracks.

    The id is stable across rounds: a finding re-raised after the agent
    disputed it is the same finding, which is what makes a dispute after two
    replies detectable instead of a fresh complaint.
    """

    id: str
    severity: FindingSeverity
    claim: str
    file: str = ""
    line: int | None = None
    fix: str = ""
    outcome: FindingOutcome | None = None


class SolLoopReview(BaseModel):
    """What the reviewer's ambient call answers.

    The verdict is optional on purpose: a reviewer that gives none parses as
    `no_verdict`, never as an error and never as approval. The caller may still
    find one in the prose with :func:`parse_verdict`, and findings in the prose
    with :func:`parse_findings`.
    """

    verdict: Literal["APPROVE", "CHANGES"] | None = None
    findings: list[SolLoopFinding] = []
    summary: str = ""


@dataclass
class ResolvedSolLoopReviewer:
    """The loop's one reviewer, with its model resolved - or why there is none."""

    name: str
    provider: str
    model_label: str
    model: Model | None
    unavailable_reason: str | None = None


@dataclass
class SolLoopRound:
    """One review pass: the reviewer's verdict and findings, in round order."""

    round_no: int
    scope: str = "full"
    verdict: str = "no_verdict"
    model: str = ""
    findings: list[SolLoopFinding] = field(default_factory=list)
    dispositions: dict[str, str] = field(default_factory=dict)
    stop_reason: StopReason | None = None
    reason: str | None = None

    def satisfied(self) -> bool:
        """Whether this round closes the loop."""
        return round_satisfied(self)

    def to_record(self) -> dict[str, Any]:
        """The round as the run manifest stores it, JSON through and through."""
        return {
            "round": self.round_no,
            "scope": self.scope,
            "verdict": self.verdict,
            "model": self.model,
            "findings": [
                {
                    "id": finding.id,
                    "severity": finding.severity,
                    "file": finding.file,
                    "line": finding.line,
                    "claim": finding.claim,
                    "fix": finding.fix,
                    "outcome": finding.outcome,
                }
                for finding in self.findings
            ],
            "dispositions": dict(self.dispositions),
            "stop_reason": self.stop_reason,
            "reason": self.reason,
            "satisfied": self.satisfied(),
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> SolLoopRound:
        """The inverse of :meth:`to_record`, for re-rendering recorded rounds."""
        return cls(
            round_no=int(record.get("round", 0)),
            scope=str(record.get("scope", "full")),
            verdict=str(record.get("verdict", "no_verdict")),
            model=str(record.get("model", "")),
            findings=[
                SolLoopFinding(
                    id=str(finding.get("id", "")),
                    severity=finding.get("severity", "should"),
                    claim=str(finding.get("claim", "")),
                    file=str(finding.get("file", "")),
                    line=finding.get("line"),
                    fix=str(finding.get("fix", "")),
                    outcome=finding.get("outcome"),
                )
                for finding in record.get("findings") or []
            ],
            dispositions=dict(record.get("dispositions") or {}),
            stop_reason=record.get("stop_reason"),
            reason=record.get("reason"),
        )


def parse_verdict(text: str) -> Literal["APPROVE", "CHANGES"] | None:
    """The `VERDICT: APPROVE|CHANGES` line in `text`, or `None` without one.

    Case-insensitive on the marker, so a reviewer writing `verdict: approve`
    still counts. Anything else - no verdict at all - is `None`, so a missing
    verdict is a fact about the review rather than a failure to parse it.
    """
    match = _VERDICT_RE.search(text or "")
    if match is None:
        return None
    value = match.group(1).upper()
    return "APPROVE" if value == "APPROVE" else "CHANGES"


def parse_findings(text: str) -> list[SolLoopFinding]:
    """The `S<n> [severity] file:line claim. Fix: ...` lines in `text`.

    Lines that do not match the format are skipped, not forced into findings:
    a reviewer thinking aloud is not a finding. A finding without a line
    reads with `line` as `None`, and one without a `Fix:` reads with an empty
    fix rather than an invented one.
    """
    findings: list[SolLoopFinding] = []
    for line in (text or "").splitlines():
        match = _FINDING_RE.match(line.strip())
        if match is None:
            continue
        finding_id, severity, file, line_no, claim, fix = match.groups()
        findings.append(
            SolLoopFinding(
                id=finding_id,
                severity=_SEVERITIES[severity],
                claim=claim.strip(),
                file=file,
                line=int(line_no) if line_no is not None else None,
                fix=(fix or "").strip(),
            )
        )
    return findings


def round_scope(round_no: int) -> str:
    """The scope a round reviews: round 1 is full, later rounds changed-only."""
    return "full" if round_no <= 1 else "changed-only"


def round_satisfied(round_: SolLoopRound) -> bool:
    """Whether this round closes the loop.

    APPROVE on the current diff, with no blocker or should open. A round with
    no verdict satisfies nothing, and an APPROVE that still lists a blocker or
    a should is a reviewer contradicting itself, not an approval.
    """
    if round_.verdict != "APPROVE":
        return False
    return not any(finding.severity in ("blocker", "should") for finding in round_.findings)


def stop_reason_for(
    round_: SolLoopRound,
    max_rounds: int,
    disputed_ids: frozenset[str] = frozenset(),
) -> StopReason | None:
    """Why this round stops the loop, or `None` when another round may follow.

    `disputed_ids` are the findings the agent disputed with evidence on this
    round's call: a reviewer re-raising one of them is the dispute's second
    reply, and the item is stuck - the user decides, not the loop. Budget end
    is last and only fires with a blocker or should still open, so it is never
    mistaken for approval.
    """
    if round_.verdict == "unavailable":
        return "reviewer_unavailable"
    if round_satisfied(round_):
        return "approved"
    if round_.findings and all(finding.severity == "nit" for finding in round_.findings):
        return "nits_only"
    if any(finding.id in disputed_ids for finding in round_.findings):
        return "stuck"
    if round_.round_no >= max_rounds:
        return "budget_exhausted"
    return None


def render_sol_loop_ledger(rounds: list[SolLoopRound]) -> str:
    """The rounds as the findings ledger from the sol-loop skill.

    One row per round with its scope, verdict and stop reason, then one row per
    finding with its severity and outcome. An outcome is what the agent passed
    in as a disposition on a later round; a finding nobody has answered yet
    reads `open`. Usage is not in the ledger: the review call returns only the
    review, never its token use, so it is reported as not exposed rather than
    guessed.
    """
    lines = ["## Sol-loop review", "", f"Rounds: {len(rounds)}", ""]
    lines.append("| Round | Scope | Verdict | Stop |")
    lines.append("| --- | --- | --- | --- |")
    for round_ in rounds:
        lines.append(
            f"| {round_.round_no} | {round_.scope} | {round_.verdict} | "
            f"{round_.stop_reason or '—'} |"
        )
    lines.append("")
    outcomes: dict[str, str] = {}
    for round_ in rounds:
        for finding_id, outcome in round_.dispositions.items():
            outcomes[finding_id] = outcome
    seen: dict[str, SolLoopFinding] = {}
    for round_ in rounds:
        for finding in round_.findings:
            seen.setdefault(finding.id, finding)
    if seen:
        lines.append("| Finding | Severity | File | Outcome |")
        lines.append("| --- | --- | --- | --- |")
        for finding in seen.values():
            outcome = outcomes.get(finding.id) or finding.outcome or "open"
            lines.append(
                f"| {finding.id} | {finding.severity} | {finding.file or '—'} | {outcome} |"
            )
        lines.append("")
    lines.append("Review usage: not exposed.")
    return "\n".join(lines)


ReviewFn = Callable[[str, str], Awaitable[SolLoopReview | None]]
"""What runs one reviewer's review: the work, its context.

Returns the reviewer's structured review, or `None` when the call produced
nothing usable. Raising is allowed too: the round records it as `unavailable`
rather than failing the run that asked for a review.
"""


async def run_sol_loop_round(
    reviewer: ResolvedSolLoopReviewer,
    work: str,
    context: str,
    round_no: int,
    max_rounds: int,
    scope: str,
    dispositions: dict[str, str],
    review_fn: ReviewFn,
) -> SolLoopRound:
    """Run one review round with the loop's single reviewer.

    A reviewer with no model records `unavailable` with its reason and is
    never substituted. A review that raises records `unavailable` with the
    failure's type - a budget cap skipping the call included, which is a
    reviewer that could not be reached, not a silent non-approval. A review
    with no verdict in its field or its prose records `no_verdict`, and one
    with no findings in its field takes them from its prose. The stop reason
    is a property of the returned round, read from :attr:`SolLoopRound.stop_reason`.
    """
    dispositions = {
        finding_id: outcome
        for finding_id, outcome in dispositions.items()
        if outcome in _KNOWN_OUTCOMES
    }
    if reviewer.model is None:
        return SolLoopRound(
            round_no=round_no,
            scope=scope,
            verdict="unavailable",
            model=reviewer.model_label,
            dispositions=dispositions,
            stop_reason="reviewer_unavailable",
            reason=reviewer.unavailable_reason or "No model available",
        )
    try:
        review = await review_fn(work, context)
    except Exception as exc:
        return SolLoopRound(
            round_no=round_no,
            scope=scope,
            verdict="unavailable",
            model=reviewer.model_label,
            dispositions=dispositions,
            stop_reason="reviewer_unavailable",
            reason=type(exc).__name__,
        )
    if review is None:
        round_ = SolLoopRound(
            round_no=round_no,
            scope=scope,
            verdict="no_verdict",
            model=reviewer.model_label,
            dispositions=dispositions,
        )
    else:
        verdict = review.verdict or parse_verdict(review.summary)
        findings = list(review.findings) or parse_findings(review.summary)
        round_ = SolLoopRound(
            round_no=round_no,
            scope=scope,
            verdict=verdict or "no_verdict",
            model=reviewer.model_label,
            findings=findings,
            dispositions=dispositions,
        )
    round_.stop_reason = stop_reason_for(
        round_,
        max_rounds,
        frozenset(
            finding_id
            for finding_id, outcome in dispositions.items()
            if outcome == "disagree-with-evidence"
        ),
    )
    return round_

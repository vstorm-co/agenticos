"""A council review: three delegates, one per provider, score the work.

The shape is Theo's tstack council skill, as a domain module with no database
and no service imports, so it can be tested without a run: each delegate
reviews the same work in parallel, on its own provider's model, at high
reasoning effort, and scores it out of 10. A fresh review after fixes is a new
round, and the loop runs until every delegate is satisfied.

Two rules from the skill are load-bearing here and worth stating where the code
enforces them:

- **A missing score is `no_score`, never an error and never an invention.**
  :class:`CouncilReview` carries `score` as optional, and a delegate that
  returns no score - in the field or in its prose - records as `no_score`.
- **An unavailable member is reported, never substituted.** A member with no
  model, or whose review raises, records as `unavailable` with the reason, and
  the round goes on without it. Substituting another provider would break the
  one-model-per-provider shape the scores are comparable under.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

# `(\d{1,2}) / 10`, with spaces allowed around the slash. The lookarounds keep
# `110/10` from reading as `10/10` and `7/100` from reading as `7/10`.
_SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*/\s*10(?!\d)")


class CouncilReview(BaseModel):
    """What one delegate's ambient call answers.

    The score is optional on purpose: a delegate that gives none parses as
    `no_score`, never as an error. The caller may still find one in the prose
    with :func:`parse_score`.
    """

    score: int | None = Field(default=None, ge=0, le=10)
    findings: list[str] = []
    summary: str = ""


@dataclass
class ResolvedCouncilMember:
    """One council member, with its model resolved - or why there is none."""

    name: str
    provider: str
    model_label: str
    model: Model | None
    unavailable_reason: str | None = None


CouncilMemberStatus = Literal["scored", "no_score", "unavailable", "skipped"]
"""How one delegate's review landed. `skipped` is for a delegate the run
chose not to wait for; :func:`run_council_round` never produces it."""


@dataclass
class CouncilMemberReview:
    """One delegate's review in one round, as the manifest records it."""

    name: str
    status: CouncilMemberStatus
    score: int | None = None
    findings: list[str] = field(default_factory=list)
    reason: str | None = None


@dataclass
class CouncilRound:
    """One full review pass: every member's review, in member order."""

    round_no: int
    reviews: list[CouncilMemberReview] = field(default_factory=list)

    def satisfied(self, threshold: int) -> bool:
        """Whether this round closes the loop, at `threshold`."""
        return round_satisfied(self, threshold)

    def to_record(self, threshold: int) -> dict[str, Any]:
        """The round as the run manifest stores it, JSON through and through."""
        return {
            "round": self.round_no,
            "satisfied": self.satisfied(threshold),
            "reviews": [
                {
                    "name": review.name,
                    "status": review.status,
                    "score": review.score,
                    "findings": list(review.findings),
                    "reason": review.reason,
                }
                for review in self.reviews
            ],
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> CouncilRound:
        """The inverse of :meth:`to_record`, for re-rendering recorded rounds."""
        return cls(
            round_no=int(record.get("round", 0)),
            reviews=[
                CouncilMemberReview(
                    name=str(review.get("name", "")),
                    status=review.get("status", "no_score"),
                    score=review.get("score"),
                    findings=list(review.get("findings") or []),
                    reason=review.get("reason"),
                )
                for review in record.get("reviews") or []
            ],
        )


def parse_score(text: str) -> int | None:
    """The first `N/10` in `text`, when `N` is a score out of 10.

    Spaces around the slash are allowed (`7 / 10` counts). Anything else -
    no score at all, or a first score outside 0..10 such as `11/10` - is
    `None`, so a missing score is a fact about the review rather than a
    failure to parse it.
    """
    match = _SCORE_RE.search(text or "")
    if match is None:
        return None
    score = int(match.group(1))
    return score if 0 <= score <= 10 else None


def round_satisfied(round_: CouncilRound, threshold: int) -> bool:
    """Whether every delegate scored this round at or above `threshold`.

    A round with no reviews satisfies nothing: `all` of an empty round is
    vacuously true, and a council nobody reviewed is not a council that
    agreed.
    """
    if not round_.reviews:
        return False
    return all(
        review.status == "scored" and review.score is not None and review.score >= threshold
        for review in round_.reviews
    )


def render_council_table(rounds: list[CouncilRound]) -> str:
    """The rounds as the PR-description table from the council skill.

    A delegate with no score reads `no score`, an unavailable one reads
    `unavailable`, and a score reads `7/10`. Nothing is invented: a cell is
    only ever a score a delegate actually gave.
    """
    lines = ["## Council review", "", f"Rounds: {len(rounds)}", ""]
    header = "| Delegate | " + " | ".join(f"Round {round_.round_no}" for round_ in rounds) + " |"
    lines.append(header)
    lines.append("| --- | " + " | ".join("---" for _ in rounds) + " |")
    names: list[str] = []
    for round_ in rounds:
        for review in round_.reviews:
            if review.name not in names:
                names.append(review.name)
    by_round = [{review.name: review for review in round_.reviews} for round_ in rounds]
    for name in names:
        cells = [_cell(by_round[index].get(name)) for index in range(len(rounds))]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _cell(review: CouncilMemberReview | None) -> str:
    """One table cell for one delegate's review in one round."""
    if review is None or review.status == "skipped":
        return "no score"
    if review.status == "unavailable":
        return "unavailable"
    if review.status == "scored" and review.score is not None:
        return f"{review.score}/10"
    return "no score"


ReviewFn = Callable[[ResolvedCouncilMember, str, str], Awaitable[CouncilReview | None]]
"""What runs one delegate's review: the member, the work, its context.

Returns the delegate's structured review, or `None` when the call produced
nothing usable. Raising is allowed too: the round records it as `unavailable`
rather than failing the other delegates' reviews.
"""


async def run_council_round(
    members: list[ResolvedCouncilMember],
    work: str,
    context: str,
    round_no: int,
    threshold: int,
    review_fn: ReviewFn,
) -> CouncilRound:
    """Fan one review round out to every member, in parallel.

    A member with no model records `unavailable` with its reason and is never
    substituted. A review that raises records `unavailable` with the failure's
    type, and a review that returns `None` - or a review with no score in its
    field or its prose - records `no_score`. The round's satisfaction is a
    property of the returned round, read with :func:`round_satisfied`.
    """
    results = await asyncio.gather(
        *(_review_one(member, work, context, review_fn) for member in members),
        return_exceptions=True,
    )
    reviews: list[CouncilMemberReview] = []
    for member, result in zip(members, results, strict=True):
        if isinstance(result, BaseException):
            reviews.append(
                CouncilMemberReview(
                    name=member.name,
                    status="unavailable",
                    reason=type(result).__name__,
                )
            )
        else:
            reviews.append(result)
    return CouncilRound(round_no=round_no, reviews=reviews)


async def _review_one(
    member: ResolvedCouncilMember,
    work: str,
    context: str,
    review_fn: ReviewFn,
) -> CouncilMemberReview:
    """One member's review, as a status rather than a raise."""
    if member.model is None:
        return CouncilMemberReview(
            name=member.name,
            status="unavailable",
            reason=member.unavailable_reason or "No model available",
        )
    try:
        review = await review_fn(member, work, context)
    except Exception as exc:
        return CouncilMemberReview(
            name=member.name, status="unavailable", reason=type(exc).__name__
        )
    if review is None:
        return CouncilMemberReview(name=member.name, status="no_score")
    score = review.score
    if score is None:
        score = parse_score(review.summary)
    if score is None:
        for finding in review.findings:
            score = parse_score(finding)
            if score is not None:
                break
    if score is None:
        return CouncilMemberReview(
            name=member.name, status="no_score", findings=list(review.findings)
        )
    return CouncilMemberReview(
        name=member.name, status="scored", score=score, findings=list(review.findings)
    )

"""What an eval suite holds a run to, and how a run measured against it came out.

Apart from `app.schemas.eval_suite` because an eval run's own read carries the
verdict of a check made on a suite, and the suite schemas read the run's.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.db.models.eval_suite import EvalSuiteResultStatus
from app.schemas.base import BaseSchema

ThresholdReasonCode = Literal[
    "pass_rate_below",
    "nothing_graded",
    "regressions",
    "cost_per_pass_rise",
    "p95_rise",
    "invalid_comparison",
    "ungraded",
]


class EvalSuiteThreshold(BaseSchema):
    """What a result must meet to pass. Quality first; efficiency only when asked for.

    Attributes:
        min_pass_rate: The lowest settled pass rate allowed - each case counted
            by the majority of its attempts. None asks for no minimum.
        max_confirmed_regressions: How many cases may break reproducibly
            against the baseline. Zero by default: one confirmed regression fails.
        max_cost_per_pass_rise: The largest rise in cost per passed case against
            the baseline, as a fraction (0.2 is twenty per cent). None checks none.
        max_p95_rise: The largest rise in p95 latency against the baseline, as a
            fraction. None checks none.
    """

    min_pass_rate: float | None = Field(default=None, ge=0, le=1)
    max_confirmed_regressions: int = Field(default=0, ge=0, le=10_000)
    max_cost_per_pass_rise: float | None = Field(default=None, ge=0, le=100)
    max_p95_rise: float | None = Field(default=None, ge=0, le=100)


class ThresholdReason(BaseSchema):
    """One way a result fell short, with the numbers that decided it."""

    code: ThresholdReasonCode
    value: float | None = None
    limit: float | None = None
    detail: str | None = None


class EvalSuiteCheck(BaseSchema):
    """The eval suite a check ran on, as it stood when the check started.

    Kept on the run, so renaming the suite or changing its threshold afterwards
    leaves the verdict the check reached as it was.
    """

    suite_id: UUID
    name: str
    threshold: EvalSuiteThreshold


class EvalSuiteCheckRead(BaseSchema):
    """What the suite a check ran on would have said of the run, had it been one of its own.

    A check is not one of the suite's runs: it is in no suite's history and
    notifies nobody.
    """

    suite_id: UUID
    name: str = Field(description="The suite's name when the check started")
    suite_exists: bool = Field(
        description="Whether the suite is still there, under this agent, to be opened"
    )
    status: EvalSuiteResultStatus | None = Field(
        description=(
            "`passed`, `failed` or `inconclusive` once the run completed; null while it "
            "runs or when it ended without completing"
        )
    )
    reasons: list[ThresholdReason] = Field(
        default_factory=list, description="Every way the run fell short of the threshold"
    )

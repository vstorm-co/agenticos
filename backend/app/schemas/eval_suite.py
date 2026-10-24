"""Schemas for eval suites: what a suite is, when it runs, and how each run came out."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.agents.prompt_variables import is_time_zone
from app.core.cron import cron_has_next
from app.db.models.eval_suite import EvalSuiteResultStatus, EvalSuiteTrigger
from app.schemas.base import BaseSchema
from app.schemas.eval_run import EvalRunEstimate, OverallLiteral, VerdictLiteral
from app.schemas.eval_threshold import EvalSuiteThreshold, ThresholdReason

FailingKind = Literal["regression", "failed", "ungraded", "incomplete"]
DependencyKind = Literal["skill", "knowledge_base", "context"]


class EvalSuiteSchedule(BaseSchema):
    """A cron expression read on the wall clock of a time zone."""

    cron: str = Field(min_length=1, max_length=120, examples=["0 6 * * *"])
    timezone: str = Field(default="UTC", max_length=64, examples=["Europe/Warsaw"])

    @field_validator("cron")
    @classmethod
    def _fires(cls, value: str) -> str:
        if not cron_has_next(value):
            raise ValueError("Use a five-field cron expression that fires, such as '0 6 * * *'")
        return value

    @field_validator("timezone")
    @classmethod
    def _known(cls, value: str) -> str:
        if not is_time_zone(value):
            raise ValueError("Use an IANA time zone, such as 'Europe/Warsaw'")
        return value


class EvalSuiteCreate(BaseSchema):
    """A suite as a person sets it up.

    Attributes:
        dataset_id: The dataset whose latest version is answered on every run.
        environment_id: The agent's environment whose version is checked and
            whose test connections the cases use. Null checks the agent's
            current published version, on the connections its spec binds.
        on_publish: Run on every version published, against the one before it.
        on_promotion: Run when a version is promoted onto the suite's
            environment (the default one, when none is named), against the
            version it replaced.
        on_dependency_change: Run when a skill, context file or knowledge base the checked
            version binds changes - once per burst of changes.
        schedule: Run on a cron schedule. None runs on no schedule.
        max_run_usd: Skip a run whose estimate is above this. Scheduled and
            triggered runs start with nobody watching, so this is the ceiling
            the owner agreed to instead.
    """

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    dataset_id: UUID
    environment_id: UUID | None = None
    threshold: EvalSuiteThreshold = Field(default_factory=EvalSuiteThreshold)
    on_publish: bool = False
    on_promotion: bool = False
    on_dependency_change: bool = False
    schedule: EvalSuiteSchedule | None = None
    max_run_usd: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=6)


class EvalSuiteUpdate(BaseSchema):
    """A change to a suite. Saving any of it makes the saver the suite's owner.

    `schedule: null` stops the schedule; `environment_id: null` checks the
    current published version; `is_active` pauses or resumes it.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    dataset_id: UUID | None = None
    environment_id: UUID | None = None
    threshold: EvalSuiteThreshold | None = None
    on_publish: bool | None = None
    on_promotion: bool | None = None
    on_dependency_change: bool | None = None
    schedule: EvalSuiteSchedule | None = None
    max_run_usd: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=6)
    is_active: bool | None = None


class EvalSuiteEstimateRequest(BaseSchema):
    """What a suite set up this way would cost a run, and a month of its schedule."""

    dataset_id: UUID
    environment_id: UUID | None = None
    schedule: EvalSuiteSchedule | None = None


class EvalSuiteEstimate(BaseSchema):
    """The spend a suite's runs ask for, shown before it is saved.

    `run` is one run of the checked version on its own - a scheduled run, or one
    after a dependency changed. `paired_run` is one that runs the previous
    version beside it, as a publish or a promotion does; null when there is no
    previous version yet. `monthly_usd` is `run` times the schedule's fires over
    the next thirty days.
    """

    run: EvalRunEstimate
    paired_run: EvalRunEstimate | None
    fires_per_month: int | None
    monthly_usd: Decimal | None


class FailingCase(BaseSchema):
    case_id: UUID
    input: str = Field(description="The question the case asks, cut to a line")
    kind: FailingKind = Field(
        description="`regression`: passed on the baseline and fails reproducibly now; "
        "`failed`: the first answer failed or the agent crashed on it; `ungraded`: nothing "
        "grades it; `incomplete`: the provider or a scorer failed on it"
    )


class EvalSuiteSummary(BaseSchema):
    """How the eval run behind a result came out, as the threshold read it."""

    pass_rate: float | None
    first_pass_rate: float | None
    cases: int
    baseline_pass_rate: float | None = None
    baseline_run_id: UUID | None = None
    baseline_version: int | None = None
    paired: bool = False
    verdict: VerdictLiteral | None = None
    overall: OverallLiteral | None = None
    invalid_reason: str | None = None
    regressions_confirmed: int = 0
    regressions_unconfirmed: int = 0
    fixed_confirmed: int = 0
    cost_per_pass_usd: Decimal | None = None
    baseline_cost_per_pass_usd: Decimal | None = None
    p95_ms: float | None = None
    baseline_p95_ms: float | None = None
    reasons: list[ThresholdReason] = Field(default_factory=list)
    failing_cases: list[FailingCase] = Field(default_factory=list)
    message: str | None = Field(
        default=None, description="Why a result was skipped or ended without a verdict"
    )


class EvalSuiteResultRead(BaseSchema):
    id: UUID
    suite_id: UUID
    trigger: EvalSuiteTrigger
    trigger_detail: dict[str, str] | None
    version_number: int | None
    baseline_version_number: int | None
    environment_id: UUID | None
    status: EvalSuiteResultStatus
    reason: str | None
    due_at: datetime
    eval_run_id: UUID | None
    baseline_eval_run_id: UUID | None
    run_as_user_id: UUID | None
    threshold: EvalSuiteThreshold
    summary: EvalSuiteSummary | None
    notified_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    settled_at: datetime | None


class EvalSuiteResultList(BaseSchema):
    items: list[EvalSuiteResultRead]
    total: int


class EvalSuitePin(BaseSchema):
    """What a guard checks, beside what its dataset holds now.

    A suite that guards an environment holds the dataset version and the
    scoring it was set up with; only somebody who may override promotions
    moves it onto newer ones.
    """

    dataset_version: int | None = Field(
        description=(
            "The dataset version the guard reads; null on a guard not pinned yet, which "
            "holds every promotion back until somebody who may override promotions pins it"
        )
    )
    latest_dataset_version: int | None = Field(
        default=None, description="The dataset's version now; null when the reader cannot see it"
    )
    scoring_current: bool | None = Field(
        default=None,
        description=(
            "Whether the dataset is graded now as the guard grades it; null when the reader "
            "cannot see it"
        ),
    )


class EvalSuiteRead(BaseSchema):
    """A suite, what it last came to, and what it is doing now."""

    id: UUID
    agent_id: UUID
    agent_name: str
    dataset_id: UUID
    dataset_name: str | None = Field(
        description="Null when the reader cannot see the dataset, which still runs"
    )
    dataset_has_cases: bool | None = Field(
        default=None,
        description=(
            "Whether the dataset has a version yet - a suite on one with none cannot guard an "
            "environment. A version that holds no cases still counts; a run on it is refused. "
            "Null when the reader cannot see the dataset"
        ),
    )
    environment_id: UUID | None
    environment_name: str | None
    owner_user_id: UUID | None
    owner_email: str | None
    name: str
    description: str | None
    is_active: bool
    paused_reason: str | None
    threshold: EvalSuiteThreshold
    on_publish: bool
    on_promotion: bool
    on_dependency_change: bool
    schedule: EvalSuiteSchedule | None
    next_fire_at: datetime | None
    max_run_usd: Decimal | None
    pin: EvalSuitePin | None = Field(
        default=None, description="Null on a suite that guards nothing, which reads the latest"
    )
    last_result: EvalSuiteResultRead | None
    open_result: EvalSuiteResultRead | None = Field(
        description="The result running now, or waiting to start"
    )
    created_at: datetime
    updated_at: datetime | None


class EvalSuiteList(BaseSchema):
    items: list[EvalSuiteRead]
    total: int

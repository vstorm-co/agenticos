"""The promotion gate - an environment's guarding eval suites, read for one version."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema
from app.schemas.eval_suite import EvalSuiteResultRead

GuardState = Literal[
    "passed",
    "failed",
    "inconclusive",
    "skipped",
    "error",
    "checking",
    "stale",
    "unchecked",
    "paused",
    "unpinned",
]
"""Where one guard stands on a version.

`passed` is the only state that lets the version through. `failed`,
`inconclusive`, `skipped` and `error` are its last result there; `checking` is a
run waiting or going; `stale` is a result over another dataset version or
threshold than the suite holds now; `unchecked` is no result at all; `paused` is
a suite that will not produce one until it is resumed; `unpinned` is a guard
not pinned to a dataset version yet - set up before guards were pinned, on a
dataset that had none - which holds every version back until somebody who may
override promotions pins it.
"""


class PromotionGuardRead(BaseSchema):
    suite_id: UUID
    suite_name: str
    state: GuardState
    paused_reason: str | None = None
    result: EvalSuiteResultRead | None = Field(
        default=None,
        description="The result the state was read from: the last settled one, or the open one",
    )


class PromotionGateRead(BaseSchema):
    """Whether a version may be promoted onto an environment, guard by guard."""

    environment_id: UUID
    environment_name: str
    version_id: UUID
    version: int
    guarded: bool = Field(description="Whether the environment names any guard at all")
    passing: bool = Field(description="Whether every guard passed on this version")
    can_override: bool = Field(
        description="Whether the caller may promote past the guards that did not pass"
    )
    guards: list[PromotionGuardRead]


class PromotionGateRun(BaseSchema):
    version_id: UUID = Field(description="The version to run the guards on before promoting it")


class PromotionGateRunRead(BaseSchema):
    started: list[UUID] = Field(description="The guards that started a run on the version")
    gate: PromotionGateRead


class PromotionGuardRecord(BaseSchema):
    """One guard as it stood when it was overridden."""

    suite_id: UUID
    suite_name: str
    state: GuardState
    result_id: UUID | None = None


class PromotionOverrideRead(BaseSchema):
    """A promotion made onto a guarded environment past guards that had not passed."""

    id: UUID
    environment_id: UUID | None
    environment_name: str
    user_id: UUID | None
    user_email: str | None = Field(
        default=None, description="Who overrode; null once they left the organization"
    )
    reason: str
    guards: list[PromotionGuardRecord]
    created_at: datetime

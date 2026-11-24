"""Bounded, value-free browser teaching contracts shared across trusted boundaries."""

import hashlib
import json
import re
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.browser_origins import browser_origin
from app.core.exceptions import BadRequestError, ConflictError

MAX_EVENTS = 500
MAX_EVENT_BYTES = 128 * 1024
MAX_CAPTURE_SECONDS = 30 * 60
RETENTION_SECONDS = 24 * 60 * 60
MAX_GENERATION_SECONDS = 180
PARAMETER_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"
FINGERPRINT_PATTERN = r"^sha256:[0-9a-f]{64}$"

BrowserProcedureTeachingAction = Literal[
    "navigate", "click", "select", "input_parameter", "scroll", "checkpoint"
]
BrowserProcedureTeachingRole = Literal[
    "button",
    "link",
    "textbox",
    "combobox",
    "checkbox",
    "radio",
    "tab",
    "menuitem",
    "option",
    "switch",
]


class BrowserProcedureTeachingState(StrEnum):
    RECORDING = "recording"
    PAUSED = "paused"
    REVIEW = "review"
    PROPOSED = "proposed"
    DISCARDED = "discarded"
    EXPIRED = "expired"


class BrowserProcedureTeachingGeneration(StrEnum):
    NONE = "none"
    QUEUED = "queued"
    GENERATING = "generating"
    SUCCEEDED = "succeeded"
    REFUSED = "refused"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


class BrowserProcedureTeachingReason(StrEnum):
    DISABLED = "teaching_disabled"
    UNAVAILABLE = "teaching_unavailable"
    OWNERSHIP_LOST = "browser_ownership_lost"
    PROTECTED = "credential_output_protected"
    AUTHORITY_CHANGED = "authority_changed"
    EXPIRED = "teaching_expired"
    EVENT_LIMIT = "event_limit_reached"
    BYTE_LIMIT = "event_bytes_limit_reached"
    TIME_LIMIT = "capture_time_limit_reached"
    AUTHENTICATION = "human_authentication_required"
    UNSUPPORTED_ACTION = "human_step_required"
    ORIGIN_REFUSED = "origin_not_allowed"
    NATIVE_UNAVAILABLE = "capture_unavailable"
    PAUSED_BY_OWNER = "paused_by_owner"
    STALE_REVISION = "stale_revision"
    ALREADY_ACTIVE = "teaching_already_active"
    EVENT_CONFLICT = "event_sequence_conflict"
    REVIEW_REQUIRED = "review_required"
    BUDGET_REFUSED = "generation_budget_refused"
    INVALID_DRAFT = "draft_not_usable"
    GENERATION_FAILED = "generation_failed"
    GENERATION_UNKNOWN = "generation_outcome_unknown"
    OPTED_OUT = "learning_opted_out"
    TASK_NOT_COMPLETED = "task_not_completed"


class BrowserProcedureTeachingRefused(BadRequestError):
    """Only a fixed code leaves a capture or model boundary, never its input/error."""

    def __init__(self, reason: BrowserProcedureTeachingReason) -> None:
        self.reason = reason
        super().__init__(
            message="Browser teaching unavailable", details={"reason_code": reason.value}
        )


def browser_procedure_teaching_stale_revision() -> ConflictError:
    return ConflictError(
        message="Browser teaching changed; read its current revision",
        details={"reason_code": BrowserProcedureTeachingReason.STALE_REVISION.value},
    )


class BrowserProcedureTeachingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class StructuralTarget(BrowserProcedureTeachingModel):
    role: BrowserProcedureTeachingRole
    fingerprint: str = Field(pattern=FINGERPRINT_PATTERN)


class BrowserProcedureTeachingObservation(BrowserProcedureTeachingModel):
    """An isolated-world descriptor; neither labels nor field values have a field."""

    origin: str
    target: StructuralTarget | None = None
    human_required: bool = False

    @field_validator("origin")
    @classmethod
    def _origin(cls, value: str) -> str:
        return browser_origin(value)


class BrowserProcedureTeachingCapturedAction(BrowserProcedureTeachingModel):
    """The input id is derived from the server connection and server input sequence."""

    sequence: int = Field(ge=1, le=MAX_EVENTS)
    input_id: UUID
    action: BrowserProcedureTeachingAction
    origin: str
    target: StructuralTarget | None = None
    direction: Literal["up", "down"] | None = None
    human_step: bool = False

    @field_validator("origin")
    @classmethod
    def _origin(cls, value: str) -> str:
        return browser_origin(value)

    @model_validator(mode="after")
    def _shape(self) -> BrowserProcedureTeachingCapturedAction:
        if (self.action in {"click", "select", "input_parameter"}) != (self.target is not None):
            raise ValueError("Only a control action has a structural target")
        if (self.action == "scroll") != (self.direction is not None):
            raise ValueError("Only a scroll has a direction")
        if self.human_step and self.action != "checkpoint":
            raise ValueError("A human step is a checkpoint")
        return self


class BrowserProcedureTeachingParameter(BrowserProcedureTeachingModel):
    name: str = Field(pattern=PARAMETER_PATTERN)
    description: str = Field(min_length=1, max_length=240)


class BrowserProcedureTeachingReviewedAction(BrowserProcedureTeachingModel):
    """The person supplies descriptions; structural facts still come from capture."""

    sequence: int = Field(ge=1, le=MAX_EVENTS)
    label: str = Field(min_length=1, max_length=160)
    parameter: str | None = Field(default=None, pattern=PARAMETER_PATTERN)
    path_template: str | None = Field(default=None, max_length=512)
    omit: bool = False

    @field_validator("path_template")
    @classmethod
    def _path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # Templates contain explicit review text and named parameters. Queries,
        # fragments, encoded tokens, authorities and dot traversal are refused.
        if (
            not value.startswith("/")
            or value.startswith("//")
            or any(char in value for char in "?#%\\:@")
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(part in {".", ".."} for part in value.split("/"))
        ):
            raise ValueError("Use a reviewed path template without URL tokens")
        without_parameters = re.sub(r"\{[a-z][a-z0-9_]{0,31}\}", "", value)
        if "{" in without_parameters or "}" in without_parameters:
            raise ValueError("Use named path parameters")
        return value


class BrowserProcedureTeachingReview(BrowserProcedureTeachingModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description: str = Field(min_length=1, max_length=500)
    actions: tuple[BrowserProcedureTeachingReviewedAction, ...] = Field(
        min_length=1, max_length=MAX_EVENTS
    )
    parameters: tuple[BrowserProcedureTeachingParameter, ...] = Field(default=(), max_length=50)
    prerequisites: tuple[str, ...] = Field(default=(), max_length=16)
    success_checks: tuple[str, ...] = Field(min_length=1, max_length=16)

    @field_validator("prerequisites", "success_checks")
    @classmethod
    def _short_checks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() or len(value) > 240 for value in values):
            raise ValueError("Use short, explicit review checks")
        return values

    @model_validator(mode="after")
    def _unique(self) -> BrowserProcedureTeachingReview:
        if len({item.sequence for item in self.actions}) != len(self.actions) or len(
            {item.name for item in self.parameters}
        ) != len(self.parameters):
            raise ValueError("Review each step and parameter once")
        if list(self.actions) != sorted(self.actions, key=lambda item: item.sequence):
            raise ValueError("Keep the captured order")
        names = {item.name for item in self.parameters}
        for action in self.actions:
            used = set(re.findall(r"\{([a-z][a-z0-9_]{0,31})\}", action.path_template or ""))
            if action.parameter is not None:
                used.add(action.parameter)
            if not used <= names:
                raise ValueError("Define every reviewed parameter")
        return self


class BrowserProcedureTeachingStep(BrowserProcedureTeachingModel):
    action: BrowserProcedureTeachingAction
    origin: str
    label: str = Field(min_length=1, max_length=160)
    role: BrowserProcedureTeachingRole | None = None
    parameter: str | None = Field(default=None, pattern=PARAMETER_PATTERN)
    path_template: str | None = None
    direction: Literal["up", "down"] | None = None
    human_step: bool = False

    @field_validator("origin")
    @classmethod
    def _origin(cls, value: str) -> str:
        return browser_origin(value)

    @model_validator(mode="after")
    def _shape(self) -> BrowserProcedureTeachingStep:
        controls = {"click", "select", "input_parameter"}
        if (
            (self.action in controls) != (self.role is not None)
            or (self.action in {"select", "input_parameter"}) != (self.parameter is not None)
            or (self.action == "navigate") != (self.path_template is not None)
            or (self.action == "scroll") != (self.direction is not None)
            or (self.action == "checkpoint") != self.human_step
        ):
            raise ValueError("Procedure fields must describe the reviewed action")
        BrowserProcedureTeachingReviewedAction(
            sequence=1, label=self.label, parameter=self.parameter, path_template=self.path_template
        )
        return self


class BrowserProcedureTeachingProcedure(BrowserProcedureTeachingModel):
    schema_version: Literal[1] = 1
    origins: tuple[str, ...] = Field(min_length=1, max_length=10)
    steps: tuple[BrowserProcedureTeachingStep, ...] = Field(min_length=1, max_length=MAX_EVENTS)
    parameters: tuple[BrowserProcedureTeachingParameter, ...] = Field(max_length=50)
    prerequisites: tuple[str, ...] = Field(max_length=16)
    success_checks: tuple[str, ...] = Field(min_length=1, max_length=16)
    source_session_id: UUID
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: Literal["manual", "refinement"]
    verified_success: bool = False

    @field_validator("origins")
    @classmethod
    def _origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(browser_origin(value) for value in values)

    @field_validator("prerequisites", "success_checks")
    @classmethod
    def _checks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return BrowserProcedureTeachingReview._short_checks(values)

    @model_validator(mode="after")
    def _scope(self) -> BrowserProcedureTeachingProcedure:
        names = {parameter.name for parameter in self.parameters}
        if len(names) != len(self.parameters) or len(set(self.origins)) != len(self.origins):
            raise ValueError("Procedure scopes and parameters must be unique")
        if self.source == "manual" and self.verified_success:
            raise ValueError("A manual demonstration is not verified task success")
        for step in self.steps:
            used = set(re.findall(r"\{([a-z][a-z0-9_]{0,31})\}", step.path_template or ""))
            if step.parameter is not None:
                used.add(step.parameter)
            if step.origin not in self.origins or not used <= names:
                raise ValueError("Procedure actions must stay within reviewed scopes")
        return self


def browser_procedure_canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def reviewed_browser_procedure(
    *,
    session_id: UUID,
    origins: tuple[str, ...],
    captured: tuple[BrowserProcedureTeachingCapturedAction, ...],
    review: BrowserProcedureTeachingReview,
    source: Literal["manual", "refinement"],
    verified_success: bool,
) -> BrowserProcedureTeachingProcedure:
    """Build only from captured facts and an explicit complete human review."""
    if tuple(item.sequence for item in captured) != tuple(item.sequence for item in review.actions):
        raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.REVIEW_REQUIRED)
    steps: list[BrowserProcedureTeachingStep] = []
    for event, action in zip(captured, review.actions, strict=True):
        if action.omit:
            continue
        if (
            event.origin not in origins
            or (event.action in {"input_parameter", "select"}) != (action.parameter is not None)
            or (event.action == "navigate") != (action.path_template is not None)
        ):
            raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.REVIEW_REQUIRED)
        steps.append(
            BrowserProcedureTeachingStep(
                action=event.action,
                origin=event.origin,
                label=action.label,
                role=None if event.target is None else event.target.role,
                parameter=action.parameter,
                path_template=action.path_template,
                direction=event.direction,
                human_step=event.human_step,
            )
        )
    if not steps:
        raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.REVIEW_REQUIRED)
    payload = {
        "origins": origins,
        "review": review.model_dump(mode="json"),
        "captured": [item.model_dump(mode="json") for item in captured],
        "source": source,
        "verified_success": verified_success,
    }
    encoded = browser_procedure_canonical_bytes(payload)
    if len(encoded) > MAX_EVENT_BYTES:
        raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.BYTE_LIMIT)
    return BrowserProcedureTeachingProcedure(
        origins=origins,
        steps=tuple(steps),
        parameters=review.parameters,
        prerequisites=review.prerequisites,
        success_checks=review.success_checks,
        source_session_id=session_id,
        source_hash=hashlib.sha256(encoded).hexdigest(),
        source=source,
        verified_success=verified_success,
    )

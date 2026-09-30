"""What each trigger node hands its graph, and the one handler they share.

A workflow starts from exactly one trigger: the node naming the way in - by hand
or the API (`core.input`), a chat message, a signed webhook delivery, a
schedule's tick, a new table record. The trigger's configuration lives in the
graph, and publishing a version is what switches it on
(`app.services.workflow_triggers`). The surface that admits the run stores what
it received as the run's input, already in this node's output shape, so the
handler only checks it and hands it on (`run_input_as`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.db.models.workflow_exposure import MIN_INTERVAL_SECONDS
from app.schemas.agent_trigger import MAX_INTERVAL_SECONDS, _cron_has_next
from app.schemas.virtual_table import RecordFilter
from app.schemas.virtual_table_trigger import MAX_FILTERS
from app.services.workflow_execution import context
from app.workflows.contracts.io import TableIORef
from app.workflows.contracts.results import Failed, WorkflowError
from app.workflows.nodes._tables import TABLE_FIELD


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ChatTriggerOutput(_Frozen):
    """The message a member sent in the chat, and where the answer goes."""

    prompt: str
    conversation_id: UUID
    user_id: UUID | None = None


class WebhookTriggerOutput(_Frozen):
    """One signed delivery: its JSON body and the id the sender gave it."""

    body: dict[str, Any] = Field(default_factory=dict)
    delivery_id: str


class ScheduleTriggerConfig(_Frozen):
    """How often the workflow runs, and what every run starts with."""

    schedule_kind: Literal["interval", "cron"] = "interval"
    interval_seconds: int | None = Field(
        default=3600,
        ge=MIN_INTERVAL_SECONDS,
        le=MAX_INTERVAL_SECONDS,
        description="Seconds between runs, at least a minute",
    )
    cron_expression: str | None = Field(
        default=None,
        max_length=255,
        description="Five fields, in the workflow's timezone (UTC unless its settings "
        "name another), such as 0 9 * * 1-5",
    )
    input: dict[str, Any] = Field(
        default_factory=dict, description="What every run starts with, as JSON"
    )

    @model_validator(mode="after")
    def _cadence(self) -> ScheduleTriggerConfig:
        if self.schedule_kind == "interval" and self.interval_seconds is None:
            raise ValueError("An interval schedule needs interval_seconds")
        if self.schedule_kind == "cron" and (
            self.cron_expression is None or not _cron_has_next(self.cron_expression)
        ):
            raise ValueError("A cron schedule needs a crontab expression that ever fires")
        return self


class ScheduleTriggerOutput(_Frozen):
    """When the tick fired, and the input the schedule starts every run with."""

    fired_at: datetime
    input: dict[str, Any] = Field(default_factory=dict)


class TableRecordTriggerConfig(_Frozen):
    """Which table, and which of its new records start the workflow."""

    table: TableIORef = TABLE_FIELD
    filters: list[RecordFilter] = Field(
        default_factory=list,
        max_length=MAX_FILTERS,
        description="Every one must hold on the record as it was added",
    )


class TableRecordTriggerOutput(_Frozen):
    """The record as it was added: its values by column id and by label, and who added it."""

    table_id: UUID
    record_id: UUID
    values: dict[str, Any] = Field(default_factory=dict)
    fields: dict[str, Any] = Field(default_factory=dict)
    author_id: UUID | None = None


class FailedRunError(_Frozen):
    """What the failed run ended with: the typed error its failing step recorded."""

    code: str
    message: str


class WorkflowFailedTriggerOutput(_Frozen):
    """The run that failed: which workflow, which step, and with what error."""

    run_id: UUID
    workflow_id: UUID
    workflow_name: str
    step_id: UUID | None = None
    step_name: str | None = None
    error: FailedRunError


def run_input_as[Output: BaseModel](output: type[Output]) -> Output | Failed:
    """The run's input as a trigger hands it on, or the failure when it does not fit.

    Only a test run can fail here: every live surface stores this shape.
    """
    try:
        return output.model_validate(context.current().run_input)
    except ValidationError:
        return Failed(
            error=WorkflowError(
                code="TRIGGER_INPUT_INVALID",
                message="The run's input does not have the shape this trigger hands on",
            )
        )

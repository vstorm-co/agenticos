"""The local updater's closed, administrator-only protocol."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

type UpdatePhase = Literal[
    "preparing",
    "ready",
    "scheduled",
    "draining",
    "backing_up",
    "applying",
    "checking",
    "succeeded",
    "failed",
    "cancelled",
]
type StableVersion = Annotated[str, Field(pattern=r"^1\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$")]
type OperationId = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]


class UpdateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UpdatePrepare(UpdateModel):
    version: StableVersion


class UpdateApply(UpdateModel):
    id: OperationId
    scheduled_for: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None


class UpdateCancel(UpdateModel):
    id: OperationId


class UpdateOperationRead(UpdateModel):
    id: OperationId
    version: StableVersion
    phase: UpdatePhase
    created_at: float
    updated_at: float
    scheduled_for: float | None = None
    commit: Annotated[str, Field(pattern=r"^([a-f0-9]{40})?$")] = ""
    previous_commit: Annotated[str, Field(pattern=r"^([a-f0-9]{40})?$")] = ""
    reason: Annotated[str, Field(pattern=r"^[a-z_]{1,64}$")] | None = None
    backup_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}/(prepared|final)$")] | None = None
    images: dict[str, str] = Field(default_factory=dict)
    requires_recovery: bool = False


class AgentUpdateRead(UpdateModel):
    operation: UpdateOperationRead | None


class UpdateStatusRead(AgentUpdateRead):
    configured: bool
    reachable: bool
    pipeline_url: str | None

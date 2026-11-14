"""Server-owned continuation data for a suspended code-mode feed.

Snapshots never come from a caller or enter a manifest. An interpreter upgrade
invalidates the checkpoint explicitly rather than replaying completed effects.
"""

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class CodeHostCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monty_id: int
    tool_call_id: str
    tool_name: str
    definition_hash: str = ""
    args: JsonValue
    # A settled value is encoded as tagged JSON so binary tool results survive.
    settled: bool = False
    awaiting_approval: bool = False
    value: JsonValue = None
    error: str | None = None
    delay_secs: float | None = Field(default=None, ge=0, le=30)


class CodeCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: int = 1
    parent_tool_call_id: str
    task_id: str | None = None
    runtime: str
    code_hash: str
    snapshot_hash: str
    snapshot: str = Field(repr=False, max_length=12_000_000)
    call_count: int = Field(ge=0)
    usage_calls: int = Field(default=0, ge=0)
    calls: list[CodeHostCall]
    history: list[dict[str, JsonValue]]
    content: dict[str, JsonValue]
    printed: str
    slept_secs: float = Field(default=0, ge=0)
    manifest: dict[str, JsonValue]


@dataclass
class CodeContinuations:
    """Shared by a run and its delegates; only the runner persists it."""

    checkpoints: dict[str, CodeCheckpoint] = field(default_factory=dict)
    native_tools: dict[str | None, frozenset[str]] = field(default_factory=dict)
    approval_calls: set[str] = field(default_factory=set)

    @property
    def orphan_approvals(self) -> set[str]:
        waiting = {
            call.tool_call_id
            for checkpoint in self.checkpoints.values()
            for call in checkpoint.calls
            if call.awaiting_approval and not call.settled
        }
        return self.approval_calls - waiting

    def requires_approval(self, tool_call_id: str) -> bool:
        """A changed hint cannot discard a decision already requested."""
        return any(
            call.tool_call_id == tool_call_id and call.awaiting_approval and not call.settled
            for checkpoint in self.checkpoints.values()
            for call in checkpoint.calls
        )


class CodeApprovalPause(BaseException):
    """Internal control flow, deliberately outside SDK tool-error conversion."""

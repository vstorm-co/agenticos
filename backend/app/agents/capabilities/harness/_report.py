"""What one prompt to a harness session came to, as the model reads it.

The shape is the coding agent's report with its `kind` renamed: a harness
session is the agent's working backend for a stream of prompts, not one task
handed off, and the console tells a report from a sentence by that field. The
conversion drops the coding-task-only fields - the change set, the result
archive - which a session prompt never produces.
"""

from typing import Literal

from pydantic import BaseModel

from app.agents.capabilities.coding_agent._harness import (
    Access,
    CodingReport,
    CodingStep,
    Harness,
)


class HarnessReport(BaseModel):
    """One prompt's answer, steps, and the session it continues in."""

    kind: Literal["harness"] = "harness"
    harness: Harness
    access: Access
    outcome: Literal["completed", "failed", "timed_out"]
    answer: str
    session_id: str | None = None
    steps: list[CodingStep] = []
    files_changed: list[str] = []
    refused: list[str] = []
    """Tools the harness wanted and was not allowed at this access."""


def from_coding(report: CodingReport) -> HarnessReport:
    """A coding report as a harness report, without its `kind` and task-only fields."""
    return HarnessReport.model_validate(report.model_dump(exclude={"kind"}))

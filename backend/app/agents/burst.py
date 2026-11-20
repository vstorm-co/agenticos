"""Burst mode: split one task into parallel subtasks, run them side by side,
then merge the results into one outcome.

The shape is OpenMausBot v0.1.153 Burst mode, as a domain module with no
database and no service imports, so it can be tested without a run: the
calling agent splits the task - previewing the parts to the person first,
the way `/burst` previews them - and one call fans the parts out to parallel
workers and merges what comes back. A fresh burst after fixes is a new burst,
numbered from 1.

Two rules from the concept are load-bearing here and worth stating where the
code enforces them:

- **A subtask that fails is reported as failed, never dropped.** A worker
  that raises, or returns nothing usable, records as `failed` with the
  reason, and the merge names it. A burst that quietly lost a part would
  read as a burst that finished it.
- **The merge never claims failed work as done.** The merged outcome lists
  each part under its own heading, failed parts under a `FAILED` heading
  with the reason, and a footer counting completed against attempted. The
  agent acts on the failed parts - retry them, do them itself, or narrow
  the task - rather than presenting the merge as complete.

The fan-out ceiling is the subagents ceiling, not a new one: the capability
caps subtasks at the subagents `max_fanout` default of 3 and hard max of 10,
and the workers are ambient one-shot agents on the run's own model - the
same fan-out council (#5) and sol-loop (#6) use - metered against the run's
budget, not spec'd delegate agents with their own specs.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

#: The smallest burst: one part is not a burst, it is the task itself.
MIN_SUBTASKS = 2


class BurstSubtaskAnswer(BaseModel):
    """What one burst worker answers.

    The result is the part's whole output: the code, the draft, the findings -
    whatever the subtask asked for. An empty result is not an answer, and the
    burst records it as a failed part rather than merging nothing.
    """

    result: str = ""


@dataclass
class BurstSubtask:
    """One part of a burst, as the calling agent split it."""

    id: str
    title: str
    prompt: str


BurstSubtaskStatus = Literal["completed", "failed"]
"""How one subtask landed. There is no third state: a part either produced
its result or it did not, and the merge says which."""


@dataclass
class BurstSubtaskResult:
    """One subtask's outcome in a burst, as the manifest records it."""

    id: str
    title: str
    status: BurstSubtaskStatus
    result: str = ""
    reason: str | None = None

    def to_record(self) -> dict[str, Any]:
        """The subtask's outcome as the run manifest stores it."""
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "result": self.result,
            "reason": self.reason,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> BurstSubtaskResult:
        """The inverse of :meth:`to_record`, for re-rendering recorded bursts."""
        return cls(
            id=str(record.get("id", "")),
            title=str(record.get("title", "")),
            status=record.get("status", "failed"),
            result=str(record.get("result", "") or ""),
            reason=record.get("reason"),
        )


@dataclass
class BurstOutcome:
    """One whole burst: every part's outcome, and the merge of them."""

    burst_no: int
    task: str
    results: list[BurstSubtaskResult] = field(default_factory=list)
    merged: str = ""

    @property
    def completed(self) -> list[BurstSubtaskResult]:
        """The parts that produced their result."""
        return [result for result in self.results if result.status == "completed"]

    @property
    def failed(self) -> list[BurstSubtaskResult]:
        """The parts that did not, named so the agent can act on them."""
        return [result for result in self.results if result.status == "failed"]

    def all_completed(self) -> bool:
        """Whether every part produced its result.

        A burst with no parts completes nothing: `all` of an empty burst is
        vacuously true, and a burst nobody ran is not a burst that finished.
        """
        return bool(self.results) and not self.failed

    def to_record(self) -> dict[str, Any]:
        """The burst as the run manifest stores it, JSON through and through."""
        return {
            "burst": self.burst_no,
            "task": self.task,
            "merged": self.merged,
            "results": [result.to_record() for result in self.results],
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> BurstOutcome:
        """The inverse of :meth:`to_record`, for re-rendering recorded bursts."""
        return cls(
            burst_no=int(record.get("burst", 0)),
            task=str(record.get("task", "")),
            results=[
                BurstSubtaskResult.from_record(result) for result in record.get("results") or []
            ],
            merged=str(record.get("merged", "") or ""),
        )


def validate_subtasks(subtasks: list[str], max_subtasks: int) -> list[str]:
    """What is wrong with a burst's split, as messages the model can act on.

    An empty list is a valid split of nothing, and the tool refuses it rather
    than running a burst with no parts: the caller splits first, then bursts.
    """
    errors: list[str] = []
    if len(subtasks) < MIN_SUBTASKS:
        errors.append(
            f"A burst needs at least {MIN_SUBTASKS} subtasks, so the work "
            f"actually splits - {len(subtasks)} given. Split the task into "
            "independent parts first, or do it as one task instead."
        )
    if len(subtasks) > max_subtasks:
        errors.append(
            f"A burst runs at most {max_subtasks} subtasks at once - "
            f"{len(subtasks)} given. Combine parts until they fit, or run "
            "the rest as a second burst."
        )
    seen: set[str] = set()
    for index, subtask in enumerate(subtasks, start=1):
        if not subtask.strip():
            errors.append(f"Subtask {index} is empty - every part needs its own prompt.")
        elif subtask.strip() in seen:
            errors.append(
                f"Subtask {index} repeats an earlier part - two workers "
                "doing the same part is a wasted run, not a split."
            )
        else:
            seen.add(subtask.strip())
    return errors


def make_subtasks(prompts: list[str]) -> list[BurstSubtask]:
    """The validated prompts as subtasks, numbered `B1` onwards.

    The ids are stable across the burst: the merge, the manifest record and
    the tool's answer all name the same `B1`, so a failed part is the same
    part everywhere it is mentioned.
    """
    return [
        BurstSubtask(id=f"B{index}", title=f"Part {index}", prompt=prompt)
        for index, prompt in enumerate(prompts, start=1)
    ]


def merge_burst(task: str, results: list[BurstSubtaskResult]) -> str:
    """The parts' results merged into one outcome, in subtask order.

    Each completed part gets its own heading with its result under it; each
    failed part gets a `FAILED` heading with the reason, so the merge never
    reads as though the part finished. The footer counts completed against
    attempted, so a reader can tell a burst that finished from one that
    lost a part without reading every heading.
    """
    lines = [f"# Burst: {task}", ""]
    for result in results:
        if result.status == "completed":
            lines.append(f"## {result.id} — {result.title}")
            lines.append("")
            lines.append(result.result)
        else:
            lines.append(f"## {result.id} — {result.title} — FAILED")
            lines.append("")
            lines.append(f"Not completed: {result.reason or 'no reason given'}.")
        lines.append("")
    completed = sum(1 for result in results if result.status == "completed")
    failed = [result.id for result in results if result.status == "failed"]
    lines.append(f"Completed {completed} of {len(results)} parts.")
    if failed:
        lines.append(
            f"Failed: {', '.join(failed)} - retry them, do them directly, or narrow the task."
        )
    return "\n".join(lines).rstrip() + "\n"


def render_burst_summary(outcome: BurstOutcome) -> str:
    """The burst as a short block, for the skill's PR section.

    A failed part reads `failed`, never as a part that finished. Nothing is
    invented: a cell is only ever a status a part actually reached.
    """
    lines = ["## Burst", "", f"Task: {outcome.task}", ""]
    lines.append(
        f"Parts: {len(outcome.results)} - {len(outcome.completed)} completed, {len(outcome.failed)} failed."
    )
    lines.append("")
    for result in outcome.results:
        if result.status == "completed":
            lines.append(f"| {result.id} | {result.title} | completed |")
        else:
            lines.append(
                f"| {result.id} | {result.title} | failed ({result.reason or 'no reason given'}) |"
            )
    return "\n".join(lines)


RunFn = Callable[[BurstSubtask], Awaitable[BurstSubtaskAnswer | None]]
"""What runs one subtask: the subtask, and its worker's answer.

Returns the worker's structured answer, or `None` when the call produced
nothing usable. Raising is allowed too: the burst records it as `failed`
rather than failing the other subtasks' work.
"""


async def run_burst(
    subtasks: list[BurstSubtask],
    task: str,
    burst_no: int,
    run_fn: RunFn,
) -> BurstOutcome:
    """Fan one burst out to every subtask, in parallel, then merge.

    A worker that raises records `failed` with the failure's type, and a
    worker that returns `None` - or an answer with an empty result - records
    `failed` with the reason. The merge is a property of the returned
    outcome, read with :func:`merge_burst`.
    """
    gathered = await asyncio.gather(
        *(_run_one(subtask, run_fn) for subtask in subtasks),
        return_exceptions=True,
    )
    results: list[BurstSubtaskResult] = []
    for subtask, outcome in zip(subtasks, gathered, strict=True):
        if isinstance(outcome, BaseException):
            results.append(
                BurstSubtaskResult(
                    id=subtask.id,
                    title=subtask.title,
                    status="failed",
                    reason=type(outcome).__name__,
                )
            )
        else:
            results.append(outcome)
    merged = merge_burst(task, results)
    return BurstOutcome(burst_no=burst_no, task=task, results=results, merged=merged)


async def _run_one(subtask: BurstSubtask, run_fn: RunFn) -> BurstSubtaskResult:
    """One subtask's work, as a status rather than a raise."""
    try:
        answer = await run_fn(subtask)
    except Exception as exc:
        return BurstSubtaskResult(
            id=subtask.id, title=subtask.title, status="failed", reason=type(exc).__name__
        )
    if answer is None or not answer.result.strip():
        return BurstSubtaskResult(
            id=subtask.id,
            title=subtask.title,
            status="failed",
            reason="empty result",
        )
    return BurstSubtaskResult(
        id=subtask.id, title=subtask.title, status="completed", result=answer.result
    )

"""The burst's one tool: split a task, run the parts in parallel, merge."""

import json
from typing import Any

from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.burst import (
    BurstSubtask,
    BurstSubtaskAnswer,
    make_subtasks,
    render_burst_summary,
    validate_subtasks,
)
from app.agents.burst import (
    run_burst as run_burst_parts,
)
from app.agents.capabilities._ambient import run_ambient_agent
from app.agents.manifest import MAX_RECORDED_BURSTS, RunRecorder

# Read-only, and bounded: a worker does its own part and nothing else, it
# does not edit what another part is doing, and it does not widen the task.
# The part's prompt is the whole of its brief - the task for context, the
# part itself, and the instruction to return only its own result.
_WORKER_INSTRUCTIONS = (
    "You are a burst worker doing one part of a larger task. Do only your "
    "part: read the task for context, then produce the result your part "
    "asks for, and nothing else. Do not redo another part's work and do not "
    "widen the task. Return your whole result in the result field. If you "
    "cannot do the part, return an empty result rather than guessing."
)


def build_burst_toolset(
    recorder: RunRecorder,
    max_subtasks: int,
    max_bursts: int,
) -> FunctionToolset[Any]:
    """The burst toolset: one tool, one burst per call."""
    toolset: FunctionToolset[Any] = FunctionToolset()

    @toolset.tool
    async def run_burst(ctx: RunContext[Any], task: str, subtasks: list[str]) -> str:
        """Split a task into parallel subtasks and merge the results.

        Use it when one task splits into independent parts that can run side
        by side - research in several directions at once, drafts of separate
        sections, checks over separate files. Split the task first and show
        the split to the person, then call this once per burst: the call fans
        the parts out to workers in parallel and returns the merged outcome.
        One call is one burst: after a burst, fix or retry what failed and
        call it again for a fresh burst.

        Args:
            task: The whole task, as the parts will read it for context.
            subtasks: The parts, each one a prompt for its own worker - an
                independent piece of the task, with everything its worker
                needs to do it. At least 2, at most the capability's maximum.

        Returns:
            A JSON string with the burst number, the merged outcome, how many
            parts completed and how many failed, and each part with its
            status. A part that failed reads `failed` with its reason - never
            as a part that finished, and never dropped from the merge. When
            the split is invalid, or no more bursts are allowed, a refusal
            string instead, saying so.
        """
        errors = validate_subtasks(subtasks, max_subtasks)
        if errors:
            return " ".join(errors)
        burst_no = len(recorder.burst_runs) + 1
        if burst_no > max_bursts:
            return (
                f"No more bursts: this agent allows at most {max_bursts} "
                f"bursts and {burst_no - 1} have already run. Act on the "
                "last burst's failed parts instead of asking for another burst."
            )
        parts = make_subtasks(subtasks)

        async def run_fn(subtask: BurstSubtask) -> BurstSubtaskAnswer | None:
            prompt = f"Task:\n{task}\n\nYour part:\n{subtask.prompt}"
            return await run_ambient_agent(
                ctx,
                output_type=BurstSubtaskAnswer,
                user_prompt=prompt,
                instructions=_WORKER_INSTRUCTIONS,
            )

        outcome = await run_burst_parts(parts, task, burst_no, run_fn)
        if len(recorder.burst_runs) < MAX_RECORDED_BURSTS:
            recorder.burst_runs.append(outcome.to_record())
        return json.dumps(
            {
                "burst": outcome.burst_no,
                "task": outcome.task,
                "all_completed": outcome.all_completed(),
                "completed": len(outcome.completed),
                "failed": [
                    {"id": result.id, "title": result.title, "reason": result.reason}
                    for result in outcome.failed
                ],
                "merged": outcome.merged,
                "summary": render_burst_summary(outcome),
            }
        )

    return toolset

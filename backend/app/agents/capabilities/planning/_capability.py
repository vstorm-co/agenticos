"""Planning - a checklist the agent keeps for itself, over the library that implements it.

`pydantic-ai-harness` provides the plan store, the tools and the cache-safe tail
reminder. This module wraps its `Planning` the way `subagents` wraps its library
rather than returning it bare the way `thinking` does, and the reasons are worth
stating because "just return theirs" is usually right:

*The reference docs are generated from these docstrings.* A capability whose
behaviour is only documented in another repository is one nobody here can answer a
question about - and what an agent may do is exactly the question a client asks.

*The prompt text is this repository's.* A tool's description is the strongest prompt
in the product - the model reads it before deciding to call the tool - so the nine
descriptions are declared here, once, and handed to the library through
`descriptions=`. That keeps the text the model reads, the text the Builder shows an
operator choosing what needs approval, and the text this repository's tests assert
on all the same string. The same holds for the library's `get_instructions()`
guidance - the write-plan, granular and subtask sentences it puts in the system
prompt every turn - which is declared here too and handed over through `guidance=`,
so a harness release that rewrites its default guidance cannot silently rewrite our
system prompt. It is the same bargain `sandbox` strikes with its console library.

*The plan has to survive an approval park, and the store is the runner's, not
this capability's.* The library's default `InMemoryPlanStore` is fresh per run, so a
run that parks on an approval mid-plan would resume with an empty checklist - the
same shape of bug the delegation journal had before agenticos#175. The runner owns
the store: it seeds one from `paused_state` on resume, injects it through
:data:`PLANNING_STORE_RESOURCE`, and reads it back when the run parks. This
capability only hands that store to the library. Building it needs no runner change
because the store arrives as a resource, exactly as the subagent runtime does.

What is deliberately *not* wrapped: the toolset, the plan mutation logic, the
dependency reconciliation and the tail reminder. Those are the library's job and it
does them; a second copy here would be one more thing to keep in step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic_ai_harness.planning import InMemoryPlanStore, PlanItem, Planning

from app.agents.capabilities._registry import CapabilityToolInfo
from app.agents.capabilities._tool_text import ToolText

if TYPE_CHECKING:
    from pydantic_ai_harness.planning import PlanStore

PLANNING_STORE_RESOURCE = "planning_store"
"""Resource key under which the runner injects the run's :class:`PlanStore`.

Present when the runner assembled a store for this run - which it does whenever the
spec binds `planning` - and absent for a preview, a unit test, or any build that
does not go through the runner. Absent, the library keeps a fresh in-memory plan per
run (its own default), which is the honest behaviour for a build with no run to park.
"""

WRITE_PLAN_TEXT = ToolText(
    summary="Create or replace the entire plan.",
    usage=(
        "Pass the whole ordered list every time -- including steps that are "
        "unchanged, completed, or cancelled -- so there are no indices to track. "
        "Keep exactly one step `in_progress`. Call this first for multi-step "
        "work, then again as you start and finish steps."
    ),
    returns=(
        "`Plan updated:` with the number of steps and the plan as it now stands. "
        "A plan it will not accept is not written at all: `Plan not updated:` "
        "names what was wrong -- a duplicate step id, a status or a link that "
        "needs subtasks enabled, a step marked blocked that depends on nothing -- "
        "and the previous plan is still in place."
    ),
)
READ_PLAN_TEXT = ToolText(
    summary="Read the current plan: each step's id, content, and status.",
    usage=("Use it before granular edits -- the ids come from here -- and to check what is left."),
    returns=(
        "Every step with its id, content and status, then a progress summary. "
        "`No plan yet.` before anything is written, which is an answer rather "
        "than a failure."
    ),
)
ADD_TASK_TEXT = ToolText(
    summary="Append one new `pending` step without replacing the plan.",
    usage="Prefer this over write_plan when you only need to add a single step.",
    returns="A confirmation carrying the new step's id, which the granular tools take.",
)
UPDATE_TASK_STATUS_TEXT = ToolText(
    summary="Update one step's status by id.",
    usage=(
        "Set `in_progress` when you START a step and `completed` when it is fully "
        "done -- never mark work complete while tests fail or the implementation "
        "is partial."
    ),
    returns=(
        "The step's content and the status it now holds. An id that is not in the "
        "plan says so, and a step whose prerequisites are unfinished refuses to "
        "start and says which -- read the plan and pick one that can move."
    ),
)
UPDATE_TASK_STATUSES_TEXT = ToolText(
    summary="Update several steps' statuses in one call.",
    usage="Ideal for handing off from a finished step to the next one.",
    returns=(
        "How many steps changed, and to what. The batch is validated first, so "
        "one bad entry means `No changes applied.` and the errors -- the plan is "
        "untouched and the whole call is worth sending again corrected."
    ),
)
REMOVE_TASK_TEXT = ToolText(
    summary="Permanently delete a step by id.",
    usage=(
        "Use it for steps that are no longer relevant or were created in error. "
        "To mark work done, use update_task_status instead."
    ),
    returns=(
        "The step that was removed, and what went with it -- deleting a parent "
        "takes its subtasks. An id that is not in the plan says so."
    ),
)
ADD_SUBTASK_TEXT = ToolText(
    summary="Add a `pending` subtask under an existing step.",
    usage=(
        "Break a complex step into a handful of independently completable "
        "subtasks, and complete them before completing the parent."
    ),
    returns=(
        "The new subtask's id and the parent it hangs under. A parent id that is "
        "not in the plan says so and nothing is added."
    ),
)
SET_DEPENDENCY_TEXT = ToolText(
    summary="Record that one step must wait for another to complete.",
    usage=(
        "The dependent step is automatically marked `blocked` until its "
        "prerequisite is resolved (`completed` or `cancelled`)."
    ),
    returns=(
        "Which step now waits on which, and whether that blocked it. A dependency "
        "that cannot exist is refused with the reason -- a step depending on "
        "itself, a cycle, or one already recorded -- and nothing changes."
    ),
)
GET_AVAILABLE_TASKS_TEXT = ToolText(
    summary="List the steps that can be worked on now.",
    usage=(
        "Those that are not completed, not blocked, and have no incomplete "
        "dependencies. Use it to choose the next step when dependencies are "
        "involved."
    ),
    returns=(
        "One line per workable step. `No available steps.` means every step is "
        "completed, cancelled or blocked -- so the next move is to resolve a "
        "prerequisite, not to wait."
    ),
)

WRITE_PLAN_DESCRIPTION = WRITE_PLAN_TEXT.render()
READ_PLAN_DESCRIPTION = READ_PLAN_TEXT.render()
ADD_TASK_DESCRIPTION = ADD_TASK_TEXT.render()
UPDATE_TASK_STATUS_DESCRIPTION = UPDATE_TASK_STATUS_TEXT.render()
UPDATE_TASK_STATUSES_DESCRIPTION = UPDATE_TASK_STATUSES_TEXT.render()
REMOVE_TASK_DESCRIPTION = REMOVE_TASK_TEXT.render()
ADD_SUBTASK_DESCRIPTION = ADD_SUBTASK_TEXT.render()
SET_DEPENDENCY_DESCRIPTION = SET_DEPENDENCY_TEXT.render()
GET_AVAILABLE_TASKS_DESCRIPTION = GET_AVAILABLE_TASKS_TEXT.render()

WRITE_PLAN_GUIDANCE = (
    "You have a planning tool, `write_plan`. For multi-step work, call it first to lay "
    "out the steps, then keep it current: mark exactly one step `in_progress`, and mark "
    "a step `completed` as soon as it is fully done. Pass the full plan every time you "
    "call `write_plan`."
)
GRANULAR_GUIDANCE = (
    "Use `add_task` to append a single step, `update_task_status`/`update_task_statuses` "
    "to move steps between statuses, and `read_plan` to see step ids before a granular "
    "edit."
)
SUBTASK_GUIDANCE = (
    "Break a complex step into subtasks with `add_subtask`, and record ordering with "
    "`set_dependency`: a step stays `blocked` until every step it depends on is resolved "
    "(`completed` or `cancelled`). Call `get_available_tasks` to pick the next step that "
    "has no incomplete dependencies."
)

_CORE_TEXTS: dict[str, ToolText] = {
    "write_plan": WRITE_PLAN_TEXT,
    "read_plan": READ_PLAN_TEXT,
    "add_task": ADD_TASK_TEXT,
    "update_task_status": UPDATE_TASK_STATUS_TEXT,
    "update_task_statuses": UPDATE_TASK_STATUSES_TEXT,
    "remove_task": REMOVE_TASK_TEXT,
}
_SUBTASK_TEXTS: dict[str, ToolText] = {
    "add_subtask": ADD_SUBTASK_TEXT,
    "set_dependency": SET_DEPENDENCY_TEXT,
    "get_available_tasks": GET_AVAILABLE_TASKS_TEXT,
}
_TEXTS: dict[str, ToolText] = {**_CORE_TEXTS, **_SUBTASK_TEXTS}

PLANNING_TOOLS: tuple[CapabilityToolInfo, ...] = tuple(
    # None of the nine acts on the world: every one mutates a checklist the model
    # keeps for itself, so there is nothing here for a person to approve. The three
    # subtask tools are declared alongside the six core ones - a tool absent from
    # this list can be neither gated by the approval policy nor renamed by a binding,
    # and that half of the failure is silent - and offered only when the binding sets
    # `enable_subtasks`, which the registry's drift test checks under its widest config.
    # `summary`, not the whole text: the Builder shows this beside an approval
    # checkbox, and the model reads the same sentence followed by the usage and
    # the return shape. One object, two lengths - never two copies.
    CapabilityToolInfo(id=name, description=text.summary)
    for name, text in _TEXTS.items()
)
"""Every tool the capability declares, all nine, in the order the library registers them."""


def _offered_names(*, subtasks: bool) -> list[str]:
    """The tool names the library will register for a given configuration."""
    if subtasks:
        return list(_TEXTS)
    return list(_CORE_TEXTS)


def _guidance(*, subtasks: bool) -> str:
    """The system-prompt guidance for a given configuration.

    Assembled to track the tools the configuration actually offers - the core build
    always registers `write_plan` and the granular tools, and the subtask sentence is
    added only under `enable_subtasks` - so the model is never told about a tool it
    lacks. This mirrors the library's own default assembly, but the wording is this
    repository's and pinned, so a harness release cannot silently rewrite the prompt.
    """
    parts = [WRITE_PLAN_GUIDANCE, GRANULAR_GUIDANCE]
    if subtasks:
        parts.append(SUBTASK_GUIDANCE)
    return " ".join(parts)


def build_planning(
    *,
    enable_subtasks: bool,
    cache_ttl: Literal["5m", "1h"],
    store: PlanStore | None,
) -> Planning:
    """Assemble the library capability from this binding's configuration.

    `descriptions` is handed the text for exactly the tools this configuration
    offers - the library rejects a description keyed by a tool it will not register -
    so the model reads this repository's wording rather than the library's default.
    `guidance` pins the system-prompt instructions to this repository's string for the
    same reason: left at the default, a harness release that rewrites its guidance
    would silently rewrite our system prompt every turn.

    `store` is the run's, injected by the runner so the plan survives an approval
    park; `None` lets the library keep a fresh in-memory plan per run, which is the
    right default for a build with no run behind it.
    """
    return Planning(
        enable_subtasks=enable_subtasks,
        cache_ttl=cache_ttl,
        store=store,
        descriptions={
            name: _TEXTS[name].render() for name in _offered_names(subtasks=enable_subtasks)
        },
        guidance=_guidance(subtasks=enable_subtasks),
    )


def new_plan_store() -> InMemoryPlanStore:
    """A fresh, empty in-memory store.

    The default a run holds before anything is planned, and the one a `PreparedRun`
    carries when it is built outside the runner. In-memory rather than persistent
    because a plan's lifetime here is one run - which may park and resume - not a
    record kept across conversations.
    """
    return InMemoryPlanStore()


async def open_plan_store(items: list[dict[str, Any]] | None) -> InMemoryPlanStore:
    """A store seeded with a resume's stored plan, or empty on a fresh run.

    `items` is `PausedRunState.plan` - the steps a run held when it parked, each a
    JSON dump of a `PlanItem`. `None` and `[]` both mean a run that had no plan (a
    fresh start, or a park before this capability existed), and both open an empty
    store. Seeding here, behind the resource the builder reads, is what carries the
    checklist across an approval park - the same shape as re-seeding a delegation's
    registry from its frames.
    """
    store = InMemoryPlanStore()
    await store.set_items([PlanItem.model_validate(item) for item in items or []])
    return store


async def dump_plan(store: PlanStore) -> list[dict[str, Any]]:
    """The store's steps as JSON, for `PausedRunState.plan`.

    A plain list of `PlanItem` dumps rather than the store itself: what a parked run
    needs to resume is the checklist, and the store's identity is this run's alone.
    """
    return [item.model_dump(mode="json") for item in await store.get_items()]

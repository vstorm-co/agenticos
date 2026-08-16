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

if TYPE_CHECKING:
    from pydantic_ai_harness.planning import PlanStore

PLANNING_STORE_RESOURCE = "planning_store"
"""Resource key under which the runner injects the run's :class:`PlanStore`.

Present when the runner assembled a store for this run - which it does whenever the
spec binds `planning` - and absent for a preview, a unit test, or any build that
does not go through the runner. Absent, the library keeps a fresh in-memory plan per
run (its own default), which is the honest behaviour for a build with no run to park.
"""

WRITE_PLAN_DESCRIPTION = (
    "Create or replace the entire plan. Pass the whole ordered list every time -- "
    "including steps that are unchanged, completed, or cancelled -- so there are no "
    "indices to track. Keep exactly one step `in_progress`. Call this first for "
    "multi-step work, then again as you start and finish steps."
)
READ_PLAN_DESCRIPTION = (
    "Read the current plan: each step's id, content, and status, plus a progress "
    "summary. Use it before granular edits (the ids come from here) and to check "
    "what is left."
)
ADD_TASK_DESCRIPTION = (
    "Append one new `pending` step without replacing the plan. Prefer this over "
    "write_plan when you only need to add a single step."
)
UPDATE_TASK_STATUS_DESCRIPTION = (
    "Update one step's status by id. Set `in_progress` when you START a step and "
    "`completed` when it is fully done -- never mark work complete while tests fail "
    "or the implementation is partial."
)
UPDATE_TASK_STATUSES_DESCRIPTION = (
    "Update several steps' statuses in one call -- ideal for handing off from a "
    "finished step to the next one. The whole batch is validated first: if any entry "
    "is invalid nothing is applied and the errors are returned."
)
REMOVE_TASK_DESCRIPTION = (
    "Permanently delete a step by id -- use it for steps that are no longer relevant "
    "or were created in error. To mark work done, use update_task_status instead."
)
ADD_SUBTASK_DESCRIPTION = (
    "Add a `pending` subtask under an existing step, creating a parent/child link. "
    "Break a complex step into a handful of independently completable subtasks, and "
    "complete them before completing the parent."
)
SET_DEPENDENCY_DESCRIPTION = (
    "Record that one step must wait for another to complete. The dependent step is "
    "automatically marked `blocked` until its prerequisite is resolved (`completed` "
    "or `cancelled`). Self-dependencies, cycles, and duplicates are rejected."
)
GET_AVAILABLE_TASKS_DESCRIPTION = (
    "List the steps that can be worked on now -- those that are not completed, not "
    "blocked, and have no incomplete dependencies. Use it to choose the next step "
    "when dependencies are involved."
)

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

_CORE_DESCRIPTIONS: dict[str, str] = {
    "write_plan": WRITE_PLAN_DESCRIPTION,
    "read_plan": READ_PLAN_DESCRIPTION,
    "add_task": ADD_TASK_DESCRIPTION,
    "update_task_status": UPDATE_TASK_STATUS_DESCRIPTION,
    "update_task_statuses": UPDATE_TASK_STATUSES_DESCRIPTION,
    "remove_task": REMOVE_TASK_DESCRIPTION,
}
_SUBTASK_DESCRIPTIONS: dict[str, str] = {
    "add_subtask": ADD_SUBTASK_DESCRIPTION,
    "set_dependency": SET_DEPENDENCY_DESCRIPTION,
    "get_available_tasks": GET_AVAILABLE_TASKS_DESCRIPTION,
}
_DESCRIPTIONS: dict[str, str] = {**_CORE_DESCRIPTIONS, **_SUBTASK_DESCRIPTIONS}

PLANNING_TOOLS: tuple[CapabilityToolInfo, ...] = tuple(
    # None of the nine acts on the world: every one mutates a checklist the model
    # keeps for itself, so there is nothing here for a person to approve. The three
    # subtask tools are declared alongside the six core ones - a tool absent from
    # this list can be neither gated by the approval policy nor renamed by a binding,
    # and that half of the failure is silent - and offered only when the binding sets
    # `enable_subtasks`, which the registry's drift test checks under its widest config.
    CapabilityToolInfo(id=name, description=description)
    for name, description in _DESCRIPTIONS.items()
)
"""Every tool the capability declares, all nine, in the order the library registers them."""


def _offered_names(*, subtasks: bool) -> list[str]:
    """The tool names the library will register for a given configuration."""
    if subtasks:
        return list(_DESCRIPTIONS)
    return list(_CORE_DESCRIPTIONS)


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
            name: _DESCRIPTIONS[name] for name in _offered_names(subtasks=enable_subtasks)
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

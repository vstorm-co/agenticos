"""Tests for the planning capability.

The capability wraps `pydantic_ai_harness.planning`, so what is worth pinning here
is the seam this repository owns: that it registers the tools it declares, offers
the six core ones by default and all nine under `enable_subtasks`, hands the model
this repository's tool text rather than the library's, and contributes nothing at
all to an agent that does not bind it. The plan-mutation logic and the tail reminder
are the library's and are tested there.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from pydantic_ai_harness.planning import InMemoryPlanStore, PlanItem, Planning, TaskStatus

from app.agents.capabilities import CapabilityBinding, build
from app.agents.capabilities._registry import CapabilityBuildContext, get
from app.agents.capabilities.planning import (
    PlanningConfig,
    _build,
    build_planning,
    dump_plan,
    new_plan_store,
    open_plan_store,
    still_open,
)
from app.agents.capabilities.planning._capability import (
    _TEXTS,
    PLANNING_TOOLS,
    SUBTASK_GUIDANCE,
    _guidance,
)

pytestmark = pytest.mark.anyio

CORE_TOOLS = frozenset(
    {
        "write_plan",
        "read_plan",
        "add_task",
        "update_task_status",
        "update_task_statuses",
        "remove_task",
    }
)
SUBTASK_TOOLS = frozenset({"add_subtask", "set_dependency", "get_available_tasks"})


def _offered(capability: Planning) -> frozenset[str]:
    """The tool names this capability's toolset would offer a model."""
    toolset = capability.get_toolset()
    assert toolset is not None
    return frozenset(toolset.tools)


class TestRegistration:
    def test_it_registers_under_a_stable_id(self):
        definition = get("planning")

        assert (definition.id, definition.name, definition.category) == (
            "planning",
            "Planning",
            "reasoning",
        )

    def test_it_declares_all_nine_tools(self):
        """Including the three offered only under subtasks: a tool absent from the
        declaration can be neither gated by approval nor renamed by a binding."""
        assert get("planning").tool_ids == CORE_TOOLS | SUBTASK_TOOLS

    def test_none_of_its_tools_acts_on_the_world(self):
        """They mutate a checklist the model keeps for itself; there is nothing to approve."""
        definition = get("planning")

        assert definition.side_effecting is False
        assert all(tool.side_effecting is None for tool in definition.tools)

    def test_it_needs_no_scope(self):
        """It reaches no external resource, so an organization grants nothing for it."""
        assert get("planning").scopes == frozenset()


class TestTools:
    def test_a_flat_checklist_offers_the_six_core_tools(self):
        built = build([CapabilityBinding(capability_id="planning")])

        assert _offered(built[0]) == CORE_TOOLS

    def test_enabling_subtasks_adds_the_three_dependency_tools(self):
        built = build(
            [CapabilityBinding(capability_id="planning", config={"enable_subtasks": True})]
        )

        assert _offered(built[0]) == CORE_TOOLS | SUBTASK_TOOLS


class TestDescriptions:
    def test_the_declaration_and_the_model_read_the_same_text(self):
        """One object, two lengths - never two paraphrases that drift apart.

        The Builder shows the summary beside an approval checkbox; the model
        reads that same sentence followed by the usage and the return shape.
        """
        declared = {tool.id: tool.description for tool in PLANNING_TOOLS}

        assert declared == {name: text.summary for name, text in _TEXTS.items()}

    def test_the_model_reads_this_repositorys_text_not_the_librarys_default(self):
        built = build(
            [CapabilityBinding(capability_id="planning", config={"enable_subtasks": True})]
        )
        toolset = built[0].get_toolset()
        assert toolset is not None

        offered = {name: tool.description for name, tool in toolset.tools.items()}
        assert offered == {name: text.render() for name, text in _TEXTS.items()}

    def test_every_planning_tool_says_what_it_returns(self):
        """The half a tool description usually leaves out, in the shape
        pydantic-ai gives a docstring that has a `Returns:` section."""
        built = build(
            [CapabilityBinding(capability_id="planning", config={"enable_subtasks": True})]
        )
        toolset = built[0].get_toolset()
        assert toolset is not None

        assert all("<returns>" in tool.description for tool in toolset.tools.values())


class TestGuidance:
    """The `get_instructions()` text this capability contributes to the system prompt.

    It lands in the prompt every turn, so - like the tool descriptions - it is pinned
    to this repository's string rather than left at the library default, where a
    harness release could rewrite it silently.
    """

    def test_the_model_reads_this_repositorys_guidance_not_the_librarys_default(self):
        built = build([CapabilityBinding(capability_id="planning")])

        assert built[0].guidance == _guidance(subtasks=False)
        assert built[0].get_instructions() == _guidance(subtasks=False)

    def test_a_flat_checklist_omits_the_subtask_guidance(self):
        built = build([CapabilityBinding(capability_id="planning")])

        assert SUBTASK_GUIDANCE not in _guidance(subtasks=False)
        assert built[0].get_instructions() == _guidance(subtasks=False)

    def test_enabling_subtasks_adds_the_subtask_guidance(self):
        built = build(
            [CapabilityBinding(capability_id="planning", config={"enable_subtasks": True})]
        )

        assert SUBTASK_GUIDANCE in _guidance(subtasks=True)
        assert built[0].guidance == _guidance(subtasks=True)
        assert built[0].get_instructions() == _guidance(subtasks=True)


class TestConfig:
    def test_the_defaults_are_a_flat_checklist_with_a_short_ttl(self):
        config = PlanningConfig()

        assert config.enable_subtasks is False
        assert config.cache_ttl == "5m"

    def test_the_cache_ttl_is_one_of_two_values(self):
        with pytest.raises(ValidationError):
            PlanningConfig(cache_ttl="10m")

    def test_the_builder_applies_defaults_when_the_config_is_absent(self):
        """The build path always validates a config, but the builder defends against
        `None` the way every other capability's does; this covers that branch."""
        capability = _build(
            CapabilityBuildContext(binding=CapabilityBinding(capability_id="planning"), config=None)
        )

        assert isinstance(capability, Planning)
        assert capability.enable_subtasks is False

    def test_the_builder_carries_the_configured_ttl_and_subtasks_through(self):
        built = build(
            [
                CapabilityBinding(
                    capability_id="planning", config={"enable_subtasks": True, "cache_ttl": "1h"}
                )
            ]
        )

        assert built[0].enable_subtasks is True
        assert built[0].cache_ttl == "1h"


class TestStore:
    def test_an_injected_store_is_the_one_the_capability_uses(self):
        """The runner owns the store so the plan survives a park; the capability
        hands it to the library rather than making its own."""
        store = InMemoryPlanStore()

        capability = build_planning(enable_subtasks=False, cache_ttl="5m", store=store)

        assert capability.store is store

    def test_no_injected_store_leaves_the_library_to_keep_a_fresh_one(self):
        capability = build_planning(enable_subtasks=False, cache_ttl="5m", store=None)

        assert capability.store is None


class TestContributesNothing:
    def test_an_agent_that_does_not_bind_planning_pays_nothing(self):
        """The invariant the issue asks for: no binding, no tools, no reminder."""
        assert build([]) == []

    def test_a_disabled_binding_is_not_built(self):
        assert build([CapabilityBinding(capability_id="planning", enabled=False)]) == []


class TestParkSurvival:
    """The store the runner seeds on resume and reads on a park.

    The plan is state, and a run that parks on an approval mid-plan resumes as a
    fresh run - so the runner carries the checklist through `PausedRunState`. These
    cover the store helpers that snapshot and re-seed it.
    """

    async def test_a_fresh_run_opens_an_empty_store(self):
        store = await open_plan_store(None)

        assert await store.get_items() == []

    async def test_a_resume_re_seeds_the_stored_plan(self):
        items = [PlanItem(content="Write the migration").model_dump(mode="json")]

        store = await open_plan_store(items)
        seeded = await store.get_items()

        assert [item.content for item in seeded] == ["Write the migration"]

    async def test_the_snapshot_round_trips_through_a_park(self):
        """What `finish` dumps is what `resume` can re-seed, byte for byte."""
        original = InMemoryPlanStore()
        await original.set_items(
            [
                PlanItem(content="Read the code", status=TaskStatus.completed),
                PlanItem(content="Write the fix", status=TaskStatus.in_progress),
            ]
        )

        snapshot = await dump_plan(original)
        reopened = await open_plan_store(snapshot)

        assert await dump_plan(reopened) == snapshot

    async def test_a_blocked_dependency_survives_a_park(self):
        """The fragile cell of the matrix: subtasks mode, where a `blocked` step and
        its `depends_on` edge have to reach the resumed run intact."""
        original = InMemoryPlanStore()
        await original.set_items(
            [
                PlanItem(id="a", content="Migration", status=TaskStatus.in_progress),
                PlanItem(id="b", content="Backfill", status=TaskStatus.blocked, depends_on=["a"]),
            ]
        )

        reopened = await open_plan_store(await dump_plan(original))
        seeded = {item.id: item for item in await reopened.get_items()}

        assert seeded["b"].status == TaskStatus.blocked
        assert seeded["b"].depends_on == ["a"]

    def test_a_default_store_is_empty_and_in_memory(self):
        assert isinstance(new_plan_store(), InMemoryPlanStore)


class TestAFinishedPlanIsHistory:
    """What a *new* turn is seeded with (#1221).

    `keep_plan` stores whatever the store held when the run ended, completed steps
    included, and a fresh turn seeds from it - so a thread whose three steps were
    all ticked off in August opened in November with the tail reminder calling them
    "your current plan" and `read_plan` answering with them. The agent was working
    to a checklist about a task nobody was doing.

    Filtered at the seed rather than cleared when the last step is ticked: within
    the turn that finishes a plan the store still holds it, so the agent can
    summarise what it just did and nothing contradicts the transcript. It is the
    next question that starts clean.
    """

    def test_a_plan_with_every_step_ticked_is_not_seeded(self):
        items = [
            PlanItem(content="Read the code", status=TaskStatus.completed).model_dump(mode="json"),
            PlanItem(content="Write the fix", status=TaskStatus.completed).model_dump(mode="json"),
        ]

        assert still_open(items) is None

    def test_cancelled_counts_as_finished(self):
        """A step nobody is going to do is not work outstanding."""
        items = [
            PlanItem(content="Read the code", status=TaskStatus.completed).model_dump(mode="json"),
            PlanItem(content="Ship it", status=TaskStatus.cancelled).model_dump(mode="json"),
        ]

        assert still_open(items) is None

    def test_one_step_left_seeds_the_whole_plan(self):
        """Including the finished steps: what is left only makes sense beside what
        is done, and `write_plan` takes the whole list every time."""
        items = [
            PlanItem(content="Read the code", status=TaskStatus.completed).model_dump(mode="json"),
            PlanItem(content="Write the fix", status=TaskStatus.pending).model_dump(mode="json"),
        ]

        assert still_open(items) == items

    def test_a_blocked_step_is_work_outstanding(self):
        """The one status that could read either way. Something still has to
        unblock it, so the plan is not finished."""
        items = [
            PlanItem(id="a", content="Migration", status=TaskStatus.completed).model_dump(
                mode="json"
            ),
            PlanItem(
                id="b", content="Backfill", status=TaskStatus.blocked, depends_on=["a"]
            ).model_dump(mode="json"),
        ]

        assert still_open(items) == items

    def test_no_plan_is_left_alone_either_way(self):
        """`None` and `[]` both mean no plan, and both have to survive as
        themselves - `open_plan_store` reads them the same but `keep_plan` does
        not, and turning one into the other would rewrite a row for nothing."""
        assert still_open(None) is None
        assert still_open([]) == []

    async def test_the_seeded_store_holds_what_survived(self):
        """End to end through the helper the runner actually calls."""
        finished = [
            PlanItem(content="Done", status=TaskStatus.completed).model_dump(mode="json"),
        ]

        store = await open_plan_store(still_open(finished))

        assert await store.get_items() == []

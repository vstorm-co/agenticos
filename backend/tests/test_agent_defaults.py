"""A model choice is personal; it must not pin old platform behavior."""

from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec, BudgetSpec
from app.services.agent_defaults import STARTER, baseline, legacy_defaults, merge_defaults


@pytest.mark.security
def test_model_and_budget_changes_keep_receiving_prompt_and_tool_updates() -> None:
    shipped = AgentSpec(name="AgenticOS", instructions="Old prompt", capabilities=[{"id": "clock"}])
    model = uuid4()
    personal = shipped.model_copy(
        update={"model_profile_id": model, "budget": BudgetSpec(monthly_usd=7)}
    )
    target = shipped.model_copy(
        update={
            "instructions": "New prompt",
            "capabilities": AgentSpec(
                name="Target", capabilities=[{"id": "clock"}, {"id": "memory_files"}]
            ).capabilities,
        }
    )
    updated = merge_defaults(personal, target, baseline(STARTER, shipped))
    assert updated.instructions == "New prompt"
    assert [cap.id for cap in updated.capabilities] == ["clock", "memory_files"]
    assert updated.model_profile_id == model
    assert updated.budget.monthly_usd == 7


def test_personal_prompt_and_tool_restrictions_survive_a_refresh() -> None:
    shipped = AgentSpec(
        name="AgenticOS",
        instructions="Old",
        capabilities=[{"id": "clock"}],
        mcp_servers=[{"account": "platform", "approval": "writes"}],
    )
    personal = AgentSpec(
        name="Custom",
        instructions="My policy",
        capabilities=[{"id": "memory_files"}],
        mcp_servers=[],
    )
    target = shipped.model_copy(update={"instructions": "New"})
    updated = merge_defaults(personal, target, baseline(STARTER, shipped))
    assert updated.instructions == "My policy"
    assert [cap.id for cap in updated.capabilities] == ["memory_files"]
    assert updated.mcp_servers == []
    assert updated.name == "Custom"


def test_release_history_has_both_original_templates() -> None:
    history = legacy_defaults()
    assert history[STARTER] and history["general/platform-assistant"]
    assert all(len(row.instructions) == 64 for rows in history.values() for row in rows)


def test_the_v1_20_defaults_remain_recognizable() -> None:
    # Prompt bodies shipped by the v1.20.0 tag, hashed after stripping whitespace.
    history = legacy_defaults()
    assert "13ad44c80817adc59f3d476d6e5bebde043e21d19c2da4402d6268690edb2f18" in {
        row.instructions for row in history[STARTER]
    }
    assert "edc222143f0fec6f048ce85d9eb91c6b8c87b73692f580212005c3ea412816db" in {
        row.instructions for row in history["general/platform-assistant"]
    }


def test_shipped_workflow_guidance_is_recognized_without_treating_user_edits_as_defaults() -> None:
    history = legacy_defaults()["general/platform-assistant"]
    row = next(row for row in history if row.instruction_variants)
    assert row.recognizes_prompt(row.instruction_variants[0])
    assert not row.recognizes_prompt("my custom prompt fingerprint")


def test_adding_architect_pin_upgrades_old_baselines_but_preserves_custom_delegates() -> None:
    from app.agents.spec import SubagentRef

    spec = AgentSpec(name="AgenticOS")
    previous = baseline(STARTER, spec)
    previous.pop("subagents")
    architect = SubagentRef(agent_id=uuid4(), agent_version_id=uuid4())
    target = spec.model_copy(update={"subagents": [architect]})
    assert merge_defaults(spec, target, previous).subagents == [architect]
    custom = SubagentRef(agent_id=uuid4(), agent_version_id=uuid4())
    assert merge_defaults(
        spec.model_copy(update={"subagents": [custom]}), target, previous
    ).subagents == [custom]


def test_refresh_removes_shipped_planning_without_changing_a_personal_model() -> None:
    model = uuid4()
    for key in (STARTER, "general/platform-assistant"):
        shipped = AgentSpec(
            name="Assistant", capabilities=[{"id": "planning"}, {"id": "memory_files"}]
        )
        current = shipped.model_copy(update={"model_profile_id": model})
        target = shipped.model_copy(update={"capabilities": shipped.capabilities[1:]})
        updated = merge_defaults(current, target, baseline(key, shipped))
        assert [binding.id for binding in updated.capabilities] == ["memory_files"]
        assert updated.model_profile_id == model

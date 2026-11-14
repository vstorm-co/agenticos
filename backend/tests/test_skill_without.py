"""Taking one skill out of a spec, from the agent and its inline specialists alike."""

import uuid

from app.agents.spec import AgentSpec, SkillBindingSpec
from app.services.skill_agents import without_skill

SKILL = uuid.uuid4()
OTHER = uuid.uuid4()


def _spec(config: dict[str, object]) -> AgentSpec:
    return AgentSpec(
        name="Clerk",
        skill_ids=[SKILL, OTHER],
        skill_bindings=[SkillBindingSpec(skill_id=SKILL, version=1)],
        capabilities=[{"id": "subagents", "config": config}, {"id": "web_search"}],
    )


def test_the_skill_and_its_binding_go_and_the_others_stay():
    stripped = without_skill(_spec({}), SKILL)

    assert stripped.skill_ids == [OTHER]
    assert stripped.skill_bindings == []
    assert stripped.capabilities == _spec({}).capabilities


def test_a_specialist_loses_the_skill_and_keeps_what_it_was_given():
    specialist = {
        "name": "billing",
        "description": "Bills.",
        "instructions": "Bill.",
        "skill_ids": [str(SKILL), str(OTHER)],
        "skill_bindings": [{"skill_id": str(SKILL), "version": 1}],
    }

    stripped = without_skill(_spec({"inline": [specialist], "mode": "auto"}), SKILL)

    assert stripped.capabilities[0].config == {
        "inline": [{**specialist, "skill_ids": [str(OTHER)], "skill_bindings": []}],
        "mode": "auto",
    }


def test_a_delegation_config_that_no_longer_reads_is_kept_as_it_was():
    config = {"inline": "not a list"}

    assert without_skill(_spec(config), SKILL).capabilities[0].config == config

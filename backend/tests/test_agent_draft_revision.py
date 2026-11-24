"""Content revisions cover every draft writer without depending on timestamps."""

from app.agents.spec import AgentSpec
from app.schemas.agent import agent_draft_revision


def test_stored_object_order_and_omitted_defaults_do_not_change_the_revision() -> None:
    compact = {"name": "Support", "model_settings": {"temperature": 0.2, "max_tokens": 200}}
    spec = AgentSpec.model_validate(compact)
    expanded = spec.model_dump(mode="json")
    expanded["model_settings"] = {"max_tokens": 200, "temperature": 0.2}
    assert agent_draft_revision(spec) == agent_draft_revision(AgentSpec.model_validate(expanded))


def test_changing_a_skill_binding_invalidates_the_previous_draft_revision() -> None:
    from uuid import uuid4

    from app.agents.spec import SkillBindingSpec

    skill_id = uuid4()
    base = AgentSpec(name="Support", skill_ids=[skill_id])
    changed = base.model_copy(
        update={"skill_bindings": [SkillBindingSpec(skill_id=skill_id, version=2)]}
    )
    assert agent_draft_revision(base) != agent_draft_revision(changed)

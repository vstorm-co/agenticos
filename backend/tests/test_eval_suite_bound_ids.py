"""Which resources a version reads - its own and its inline specialists'."""

import uuid

from app.agents.spec import AgentSpec
from app.services.eval_suite import binds, bound_ids


def _spec(own: list[uuid.UUID], config: object | None = None) -> AgentSpec:
    capabilities = [] if config is None else [{"id": "subagents", "config": config}]
    return AgentSpec.model_validate(
        {"name": "Clerk", "skill_ids": [str(i) for i in own], "capabilities": capabilities}
    )


def _specialist(skill_ids: list[uuid.UUID]) -> dict[str, object]:
    return {
        "name": "billing",
        "description": "Bills.",
        "instructions": "Bill.",
        "skill_ids": [str(i) for i in skill_ids],
    }


def test_a_version_reads_its_own_and_its_specialists_skills():
    own, theirs = uuid.uuid4(), uuid.uuid4()

    spec = _spec([own], {"inline": [_specialist([theirs])]})

    assert bound_ids(spec, "skill") == {own, theirs}
    assert binds(spec, "skill", theirs)


def test_without_specialists_a_version_reads_its_own():
    own = uuid.uuid4()

    assert bound_ids(_spec([own]), "skill") == {own}
    assert not binds(_spec([own]), "skill", uuid.uuid4())


def test_a_specialist_config_that_does_not_parse_adds_nothing():
    own = uuid.uuid4()

    spec = _spec([own], {"inline": "not a list"})

    assert bound_ids(spec, "skill") == {own}

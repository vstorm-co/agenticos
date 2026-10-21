"""The parts of the suite service that need no database: what a version binds, and how rows read."""

from __future__ import annotations

import uuid

from app.agents.spec import AgentSpec
from app.db.models.eval_suite import EvalSuite, EvalSuiteResult
from app.services.eval_suite import binds


def _spec(**values: object) -> AgentSpec:
    return AgentSpec.model_validate({"name": "Clerk", "instructions": "Help", **values})


def test_a_version_binds_its_own_skills_and_collections() -> None:
    skill, collection = uuid.uuid4(), uuid.uuid4()
    spec = _spec(skill_ids=[str(skill)], collection_ids=[str(collection)])

    assert binds(spec, "skill", skill)
    assert binds(spec, "knowledge_base", collection)
    assert not binds(spec, "skill", collection)


def test_a_delegation_that_does_not_parse_binds_nothing_more() -> None:
    skill = uuid.uuid4()
    spec = _spec(capabilities=[{"id": "subagents", "enabled": True, "config": {"inline": "x"}}])

    assert not binds(spec, "skill", skill)


def test_rows_say_what_they_are() -> None:
    suite = EvalSuite(id=uuid.uuid4(), agent_id=uuid.uuid4(), name="Nightly")
    result = EvalSuiteResult(
        id=uuid.uuid4(), suite_id=suite.id, trigger="schedule", status="passed"
    )

    assert "Nightly" in repr(suite)
    assert "schedule" in repr(result) and "passed" in repr(result)

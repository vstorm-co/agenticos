"""A candidate skill can bring its own files, and a check measures them."""

import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.capabilities.skills import SkillBody, SkillBodyFile, to_toolkit_skill
from app.agents.spec import AgentSpec
from app.db.models.eval_run import EvalRun
from app.db.models.skill import Skill
from app.repositories import agent_repo, eval_run_repo
from app.services.eval_run import EvalRunService, _bodies_json, skill_body_from_json, spec_hash
from app.services.skills import SkillService

SKILL_ID = uuid.uuid4()
FILE = SkillBodyFile(name="limits.md", description="Caps", content="Up to $500.")
_CTX = MagicMock()


def _stored() -> Skill:
    resource = SimpleNamespace(name="old.md", description=None, content="old")
    return cast(
        Skill,
        SimpleNamespace(
            name="refunds", description="Stored.", content="Stored body.", resources=[resource]
        ),
    )


def test_a_candidates_files_are_served_in_place_of_the_stored_ones() -> None:
    served = to_toolkit_skill(_stored(), SkillBody("New.", "New body.", resources=(FILE,)))

    assert [(item.name, item.content) for item in served.resources] == [
        ("limits.md", "Up to $500.")
    ]


def test_a_candidate_without_files_keeps_the_stored_ones() -> None:
    served = to_toolkit_skill(_stored(), SkillBody("New.", "New body."))

    assert [item.name for item in served.resources] == ["old.md"]


def test_a_stored_candidate_reads_back_with_its_files() -> None:
    body = SkillBody("New.", "New body.", resources=(FILE,), fork_id=uuid.uuid4())

    stored = _bodies_json({SKILL_ID: body})[str(SKILL_ID)]

    assert skill_body_from_json(stored) == body
    assert skill_body_from_json(_bodies_json({SKILL_ID: SkillBody("a", "b")})[str(SKILL_ID)]) == (
        SkillBody("a", "b")
    )


def test_a_stored_candidate_keeps_whether_it_is_served_over_a_pin() -> None:
    body = SkillBody("a", "b", over_pin=True)

    stored = _bodies_json({SKILL_ID: body})[str(SKILL_ID)]

    assert skill_body_from_json(stored) == body
    assert "over_pin" not in _bodies_json({SKILL_ID: SkillBody("a", "b")})[str(SKILL_ID)]


def test_two_candidates_differing_only_in_a_file_are_measured_apart() -> None:
    """The fingerprint decides whether a cached arm stands in for a run; a changed
    file is a different candidate."""
    spec = AgentSpec(name="Desk", model_profile_id=uuid.uuid4())
    other = SkillBodyFile(name="limits.md", description="Caps", content="Up to $50.")

    first = spec_hash(spec, {SKILL_ID: SkillBody("d", "c", resources=(FILE,))})
    second = spec_hash(spec, {SKILL_ID: SkillBody("d", "c", resources=(other,))})

    assert first != second


@pytest.mark.anyio
class TestServedSkillVersions:
    """What keys a cached baseline: the stored skill versions an agent is served."""

    def _skill(self, skill_id: uuid.UUID, version_id: uuid.UUID | None) -> Skill:
        return cast(Skill, SimpleNamespace(id=skill_id, latest_version_id=version_id))

    async def test_the_agents_and_its_specialists_versions_are_both_read(self, monkeypatch):
        own, specialists = uuid.uuid4(), uuid.uuid4()
        own_version, specialist_version = uuid.uuid4(), uuid.uuid4()
        served = {own: own_version, specialists: specialist_version}

        async def resolve(_self, _ctx, skill_ids, *, bindings=()):
            return [self._skill(key, served[key]) for key in skill_ids]

        monkeypatch.setattr(SkillService, "resolve_for_agent", resolve)
        spec = AgentSpec(
            name="Desk",
            model_profile_id=uuid.uuid4(),
            skill_ids=[own],
            capabilities=[
                {
                    "id": "subagents",
                    "config": {
                        "inline": [
                            {
                                "name": "reader",
                                "description": "Reads",
                                "instructions": "Read.",
                                "skill_ids": [str(specialists)],
                            }
                        ]
                    },
                }
            ],
        )

        result = await EvalRunService(MagicMock()).served_skill_versions(MagicMock(), spec)

        assert result == {
            f":{own}": str(own_version),
            f"reader:{specialists}": str(specialist_version),
        }

    async def test_an_agent_with_no_skill_is_served_none(self, monkeypatch):
        async def resolve(_self, _ctx, skill_ids, *, bindings=()):
            return [self._skill(uuid.uuid4(), None)]

        monkeypatch.setattr(SkillService, "resolve_for_agent", resolve)
        spec = AgentSpec(
            name="Desk",
            model_profile_id=uuid.uuid4(),
            capabilities=[{"id": "subagents", "config": {"inline": "not a list"}}],
        )

        assert await EvalRunService(MagicMock()).served_skill_versions(MagicMock(), spec) is None

    async def test_an_agent_that_delegates_nothing_is_read_on_its_own(self, monkeypatch):
        own, version = uuid.uuid4(), uuid.uuid4()

        async def resolve(_self, _ctx, skill_ids, *, bindings=()):
            return [self._skill(key, version) for key in skill_ids]

        monkeypatch.setattr(SkillService, "resolve_for_agent", resolve)
        spec = AgentSpec(name="Desk", model_profile_id=uuid.uuid4(), skill_ids=[own])

        result = await EvalRunService(MagicMock()).served_skill_versions(MagicMock(), spec)

        assert result == {f":{own}": str(version)}


@pytest.mark.anyio
class TestAnArmWhoseSkillsMovedStandsForNone:
    """A cached baseline stands for the skill versions it answered with; an arm whose
    skills advanced while it ran answered with a mix."""

    PLANNED = {f":{SKILL_ID}": "v1"}

    def _arm(self, **values: object) -> SimpleNamespace:
        return SimpleNamespace(
            skill_versions=values.pop("skill_versions", self.PLANNED),
            agent_version_id=values.pop("agent_version_id", None),
            spec={"name": "Desk", "model_profile_id": str(uuid.uuid4())},
        )

    async def _forget(self, monkeypatch, arms, *, served, ctx: object = _CTX, version=None):
        updated = AsyncMock()
        monkeypatch.setattr(eval_run_repo, "list_arms", AsyncMock(return_value=arms))
        monkeypatch.setattr(eval_run_repo, "update_arm", updated)
        monkeypatch.setattr(agent_repo, "get_version", AsyncMock(return_value=version))
        monkeypatch.setattr(EvalRunService, "served_skill_versions", AsyncMock(return_value=served))
        run = cast(EvalRun, SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4()))
        await EvalRunService(MagicMock()).forget_moved_skills(ctx, run)
        return [call.kwargs["arm"] for call in updated.await_args_list]

    async def test_an_arm_whose_skills_stayed_keeps_them(self, monkeypatch):
        arm = self._arm()
        assert await self._forget(monkeypatch, [arm], served=dict(self.PLANNED)) == []

    async def test_an_arm_whose_skills_moved_is_unmarked(self, monkeypatch):
        arm, plain = self._arm(), self._arm(skill_versions=None)
        moved = await self._forget(monkeypatch, [arm, plain], served={f":{SKILL_ID}": "v2"})
        assert moved == [arm]

    async def test_a_published_arm_is_read_from_its_version(self, monkeypatch):
        version = SimpleNamespace(spec={"name": "Desk", "model_profile_id": str(uuid.uuid4())})
        arm = self._arm(agent_version_id=uuid.uuid4())
        kept = await self._forget(monkeypatch, [arm], served=dict(self.PLANNED), version=version)
        assert kept == []

    async def test_a_version_gone_or_a_starter_gone_unmarks_the_arm(self, monkeypatch):
        gone = self._arm(agent_version_id=uuid.uuid4())
        assert await self._forget(monkeypatch, [gone], served=dict(self.PLANNED)) == [gone]
        arm = self._arm()
        assert await self._forget(monkeypatch, [arm], served=dict(self.PLANNED), ctx=None) == [arm]

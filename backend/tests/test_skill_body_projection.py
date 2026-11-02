"""A candidate skill can bring its own files, and a check measures them."""

import uuid
from types import SimpleNamespace
from typing import cast

from app.agents.capabilities.skills import SkillBody, SkillBodyFile, to_toolkit_skill
from app.agents.spec import AgentSpec
from app.db.models.skill import Skill
from app.services.eval_run import _bodies_json, skill_body_from_json, spec_hash

SKILL_ID = uuid.uuid4()
FILE = SkillBodyFile(name="limits.md", description="Caps", content="Up to $500.")


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
    body = SkillBody("New.", "New body.", resources=(FILE,))

    stored = _bodies_json({SKILL_ID: body})[str(SKILL_ID)]

    assert skill_body_from_json(stored) == body
    assert skill_body_from_json(_bodies_json({SKILL_ID: SkillBody("a", "b")})[str(SKILL_ID)]) == (
        SkillBody("a", "b")
    )


def test_two_candidates_differing_only_in_a_file_are_measured_apart() -> None:
    """The fingerprint decides whether a cached arm stands in for a run; a changed
    file is a different candidate."""
    spec = AgentSpec(name="Desk", model_profile_id=uuid.uuid4())
    other = SkillBodyFile(name="limits.md", description="Caps", content="Up to $50.")

    first = spec_hash(spec, {SKILL_ID: SkillBody("d", "c", resources=(FILE,))})
    second = spec_hash(spec, {SKILL_ID: SkillBody("d", "c", resources=(other,))})

    assert first != second

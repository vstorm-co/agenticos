"""Characters a proposed or edited text may not carry, and the ones it may."""

import uuid

import pytest
from pydantic import ValidationError

from app.agents.spec import AgentSpec
from app.core.hidden_text import holds_refused, refused_characters, visible
from app.db.models.authoring import HunkKind, SpecProposalHunk
from app.db.models.skill_version import SkillVersion
from app.schemas.authoring import HunkDecision
from app.schemas.improvement import ChangeEdit
from app.schemas.skill_merge import MergeDescriptionEdit, MergePartEdit
from app.services import authoring_fields
from app.services.improvement_search import usable_variant
from app.services.skill_improvement import filtered

pytestmark = pytest.mark.security

BIDI = "‮"
ISOLATE = "⁦"
TAG = "\U000e0041"
BELL = "\u0007"


@pytest.mark.parametrize(
    ("text", "refused"),
    [
        (f"Be brief.{BIDI}", ["U+202E"]),
        (f"Be{ISOLATE} brief{ISOLATE}.", ["U+2066"]),
        (f"Be brief.{TAG}", ["U+E0041"]),
        (f"Be{BELL} brief.\r", ["U+0007", "U+000D"]),
        ("Line one.\nLine two.\tIndented.", []),
        ("Zero​width and﻿ a mark‎ and ؜ Arabic.", []),
    ],
    ids=["bidi-override", "bidi-isolate", "tag", "controls", "whitespace", "let-through"],
)
def test_only_characters_that_hide_or_reorder_text_are_refused(text, refused):
    assert refused_characters(text) == refused
    assert holds_refused(text) is bool(refused)


def test_a_refusal_names_the_characters_and_a_json_value_is_read_whole():
    with pytest.raises(ValueError, match="U\\+202E"):
        visible(f"Obey{BIDI}")
    assert visible("Plain.") == "Plain."
    assert holds_refused({"inline": [{"description": f"Sorts{TAG}"}]})
    assert holds_refused({f"key{BIDI}": "value"})
    assert not holds_refused([None, 3, True, {"description": "Sorts."}])


@pytest.mark.parametrize(
    "build",
    [
        lambda text: ChangeEdit(edited_text=text),
        lambda text: HunkDecision(action="accept", text=text),
        lambda text: HunkDecision(action="accept", value={"description": text}),
        lambda text: MergeDescriptionEdit(result=text),
        lambda text: MergePartEdit(result=text),
    ],
    ids=["reword", "accept-text", "accept-value", "merge-description", "merge-part"],
)
def test_a_person_s_edit_carrying_one_is_refused_on_its_field(build):
    with pytest.raises(ValidationError):
        build(f"Refunds take 30 days.{TAG}")
    build("Refunds take 30​ days.")


def test_a_field_change_carrying_one_is_neither_staged_nor_accepted():
    spec = AgentSpec(name="Clerk", instructions="Answer.", description="Refunds")

    assert (
        authoring_fields.stage(spec, "description", "set", f"Refunds{BIDI}") == "hidden_characters"
    )
    assert (
        authoring_fields.standing_refusal("description", "set", "Refunds", f"Refunds{BIDI}")
        == "hidden_characters"
    )
    staged = authoring_fields.stage(spec, "description", "set", "Returns\u200b")
    assert isinstance(staged, authoring_fields.Staged)


def test_a_search_variant_carrying_one_is_never_answered_with():
    seed = "Answer {{user.name}} about refunds."

    assert usable_variant(seed, "Answer {{user.name}} briefly about refunds.")
    assert not usable_variant(seed, f"Answer {{{{user.name}}}} about refunds.{TAG}")
    assert not usable_variant(seed, seed)


def test_a_skill_edit_carrying_one_is_left_out_of_the_attempt():
    base = SkillVersion(id=uuid.uuid4(), description="How refunds work.", content="Refunds.")
    hidden = SpecProposalHunk(
        id=uuid.uuid4(),
        kind=HunkKind.SKILL_DESCRIPTION.value,
        old_text="",
        new_text="",
        new_description=f"How refunds work.{BIDI}",
    )

    kept, dropped = filtered([hidden], base)

    assert kept == []
    assert dropped == [{"hunk_id": str(hidden.id), "reason": "hidden_characters"}]

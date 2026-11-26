"""Characters a proposed or edited text may not carry, and the ones it may."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.agents.spec import AgentSpec
from app.core.hidden_text import (
    holds_refused,
    refused_characters,
    unix_newlines,
    unix_newlines_in,
    visible,
)
from app.db.models.authoring import HunkKind, SpecProposalHunk
from app.db.models.skill_version import SkillVersion
from app.schemas.authoring import (
    ContextImprovement,
    FieldChange,
    HunkDecision,
    InstructionChange,
    NewSkillChange,
    ProposedSkill,
    Rejection,
    SkillImprovement,
    ToolChange,
)
from app.schemas.improvement import ChangeEdit
from app.schemas.skill_check import SkillCheckRequest
from app.schemas.skill_improvement import MergeTexts, SkillBodyEdit, SkillEdits
from app.schemas.skill_merge import MergeDescriptionEdit, MergePartEdit
from app.services import authoring_fields
from app.services.authoring_worker import AuthoringRun
from app.services.improvement_search import InstructionVariant, usable_variant
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


def _check_request(**text: str) -> SkillCheckRequest:
    return SkillCheckRequest.model_validate(
        {
            "candidate": {"description": "Refunds", "content": "Refund in 30 days.", **text},
            "base_version_id": uuid.uuid4(),
        }
    )


@pytest.mark.parametrize(
    "build",
    [
        lambda text: ChangeEdit(edited_text=text),
        lambda text: HunkDecision(action="accept", text=text),
        lambda text: HunkDecision(action="accept", value={"description": text}),
        lambda text: MergeDescriptionEdit(result=text),
        lambda text: MergePartEdit(result=text),
        lambda text: ProposedSkill(name="refunds", description="Refunds", content=text),
        lambda text: _check_request(content=text),
        lambda text: _check_request(description=text),
    ],
    ids=[
        "reword",
        "accept-text",
        "accept-value",
        "merge-description",
        "merge-part",
        "skill-idea",
        "checked-text",
        "checked-description",
    ],
)
def test_a_person_s_edit_carrying_one_is_refused_on_its_field(build):
    with pytest.raises(ValidationError):
        build(f"Refunds take 30 days.{TAG}")
    build("Refunds take 30​ days.")


WINDOWS = "Refunds take 30 days.\r\nAsk for the receipt.\rThen refund."
UNIX = "Refunds take 30 days.\nAsk for the receipt.\nThen refund."


def test_windows_and_lone_carriage_return_line_breaks_are_written_as_newlines():
    assert unix_newlines(WINDOWS) == UNIX
    assert unix_newlines("\r\r\n") == "\n\n"
    assert unix_newlines_in({WINDOWS: [WINDOWS, 3, None, True]}) == {UNIX: [UNIX, 3, None, True]}
    assert visible(WINDOWS) == UNIX


@pytest.mark.parametrize(
    ("build", "read"),
    [
        (lambda text: ChangeEdit(edited_text=text), lambda made: made.edited_text),
        (lambda text: HunkDecision(action="accept", text=text), lambda made: made.text),
        (
            lambda text: HunkDecision(action="accept", value={"description": text}),
            lambda made: made.value["description"],
        ),
        (lambda text: MergeDescriptionEdit(result=text), lambda made: made.result),
        (lambda text: MergePartEdit(result=text), lambda made: made.result),
        (lambda text: _check_request(content=text), lambda made: made.candidate.content),
    ],
    ids=["reword", "accept-text", "accept-value", "merge-description", "merge-part", "checked"],
)
def test_a_person_s_edit_with_windows_line_breaks_is_kept_with_newlines(build, read):
    assert read(build(WINDOWS)) == UNIX


def test_a_person_s_wording_keeps_its_ends_and_gets_newlines():
    """Whitespace at either end is part of a passage, and a Windows line break inside it
    is still a newline."""
    typed = "  Cite the policy.\r\nAnswer briefly.\r\n"
    kept = "  Cite the policy.\nAnswer briefly.\n"

    assert ChangeEdit(edited_text=typed).edited_text == kept
    assert HunkDecision(action="accept", text=typed).text == kept


@pytest.mark.parametrize(
    ("build", "read"),
    [
        (
            lambda text: InstructionChange(old_text="", new_text=text, rationale="r"),
            lambda made: [made.new_text],
        ),
        (
            lambda text: ToolChange(
                capability_id="web", tool_id="fetch", name=text, description=text, rationale="r"
            ),
            lambda made: [made.name, made.description],
        ),
        (
            lambda text: FieldChange(
                path="description", op="set", value=[text], rationale="r", expected_effect="e"
            ),
            lambda made: made.value,
        ),
        (
            lambda text: NewSkillChange(name=text, description=text, content=text, rationale="r"),
            lambda made: [made.name, made.description, made.content],
        ),
        (
            lambda text: SkillImprovement(
                summary="s", expected_effect="e", description=text, content=text, rationale="r"
            ),
            lambda made: [made.description, made.content],
        ),
        (
            lambda text: ContextImprovement(
                summary="s", expected_effect="e", description=text, content=text, rationale="r"
            ),
            lambda made: [made.description, made.content],
        ),
        (
            lambda text: SkillEdits(
                summary="s",
                expected_effect="e",
                edits=[SkillBodyEdit(old_text="", new_text=text, rationale="r")],
                description=text,
            ),
            lambda made: [made.edits[0].new_text, made.description],
        ),
        (lambda text: MergeTexts(texts=[text]), lambda made: made.texts),
        (lambda text: InstructionVariant(instructions=text), lambda made: [made.instructions]),
    ],
    ids=[
        "instructions",
        "tool",
        "field",
        "new-skill",
        "skill",
        "context",
        "skill-edits",
        "merge",
        "search-variant",
    ],
)
def test_a_proposal_with_windows_line_breaks_is_judged_and_kept_with_newlines(build, read):
    texts = read(build(WINDOWS))

    assert texts == [UNIX] * len(texts)
    assert not holds_refused(texts)


def test_a_tool_change_carrying_one_is_not_proposed():
    change = ToolChange(
        capability_id="web", tool_id="fetch", description=f"Fetch{BIDI} pages.", rationale="r"
    )

    assert AuthoringRun._tool_refusal({("web", "fetch")}, change) is Rejection.HIDDEN_CHARACTERS


def test_a_skill_edit_or_description_carrying_one_is_not_proposed():
    rejected: list[tuple[str, Rejection]] = []
    worker = SimpleNamespace(_reject=lambda kind, reason, _change: rejected.append((kind, reason)))
    edits = SkillEdits(
        summary="s",
        expected_effect="e",
        edits=[SkillBodyEdit(old_text="Refunds.", new_text=f"Refunds{BIDI}.", rationale="r")],
        description=f"Refunds{TAG}",
    )

    hunks = AuthoringRun._skill_hunks(worker, "Refunds.", "Refunds", MagicMock(), edits)

    assert hunks == []
    assert rejected == [
        (HunkKind.SKILL_BODY, Rejection.HIDDEN_CHARACTERS),
        (HunkKind.SKILL_DESCRIPTION, Rejection.HIDDEN_CHARACTERS),
    ]


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

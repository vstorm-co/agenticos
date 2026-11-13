"""The parts of a skill session that decide without a database: the candidate text, its
hash, which proposed edits are offered, and whether the person acting may go on."""

import uuid
from typing import Any

import pytest

from app.db.models.authoring import HunkKind, SpecProposalHunk
from app.db.models.skill_improvement import SkillImprovementIteration, SkillImprovementRun
from app.db.models.skill_version import SkillVersion
from app.schemas.authoring import InstructionChange
from app.services import authoring_hunks
from app.services.skill_improvement import (
    SkillStanding,
    _starter,
    candidate_hash,
    candidate_text,
    filtered,
)

_BODY = "Refunds take 14 days.\nAlways ask for the order number.\nBe polite."


def _base() -> SkillVersion:
    return SkillVersion(id=uuid.uuid4(), description="How refunds work.", content=_BODY)


def _edit(old: str, new: str, **values: Any) -> SpecProposalHunk:
    columns = authoring_hunks.anchor_change(
        _BODY, InstructionChange(old_text=old, new_text=new, rationale="")
    )
    assert isinstance(columns, dict)
    return SpecProposalHunk(
        id=uuid.uuid4(), kind=HunkKind.SKILL_BODY.value, **{**columns, **values}
    )


def _description(new: str, **values: Any) -> SpecProposalHunk:
    return SpecProposalHunk(
        id=uuid.uuid4(),
        kind=HunkKind.SKILL_DESCRIPTION.value,
        old_text="",
        new_text="",
        new_description=new,
        **values,
    )


class TestCandidate:
    def test_edits_apply_in_order_and_a_rewording_wins_over_the_proposal(self):
        hunks = [
            _edit("Refunds take 14 days.", "Refunds take 30 days.", edited_text="Within 30 days."),
            _edit("Be polite.", "Be kind."),
            _description("How refunds and returns work.", edited_text="Refunds and returns."),
        ]

        description, content = candidate_text(_base(), hunks) or ("", "")

        assert description == "Refunds and returns."
        assert content == "Within 30 days.\nAlways ask for the order number.\nBe kind."

    def test_an_edit_whose_passage_is_gone_makes_no_candidate(self):
        first = _edit("Refunds take 14 days.", "Refunds take 30 days.")
        again = _edit("Refunds take 14 days.", "Refunds take 60 days.")

        assert candidate_text(_base(), [first, again]) is None

    def test_the_hash_is_the_text_and_only_the_text(self):
        assert candidate_hash("a", "b") == candidate_hash("a", "b")
        assert candidate_hash("a", "b") != candidate_hash("b", "a")


class TestFilter:
    def test_repeats_overlaps_and_a_second_description_are_dropped_with_why(self):
        kept_edit = _edit("Refunds take 14 days.", "Refunds take 30 days.")
        repeated = _edit("Refunds take 14 days.", "Refunds take 30 days.")
        overlapping = _edit("Refunds take 14 days.", "Refunds take 60 days.")
        description, second = _description("New."), _description("Newer.")

        kept, dropped = filtered([kept_edit, repeated, description, overlapping, second], _base())

        assert kept == [kept_edit, description]
        assert dropped == [
            {"hunk_id": str(repeated.id), "reason": "repeated"},
            {"hunk_id": str(overlapping.id), "reason": "overlaps"},
            {"hunk_id": str(second.id), "reason": "repeated"},
        ]


@pytest.mark.parametrize(
    ("edits", "runs", "allowed"),
    [(True, True, True), (False, True, False), (True, False, False)],
)
def test_a_person_goes_on_only_with_edit_access_and_runs_view(edits, runs, allowed):
    standing = SkillStanding(edits_skill=edits, views_runs=runs)

    assert standing.allowed is allowed


def test_rows_name_themselves():
    run = SkillImprovementRun(id=uuid.uuid4(), skill_id=uuid.uuid4(), status="queued")
    attempt = SkillImprovementIteration(id=uuid.uuid4(), run_id=run.id, number=2)

    assert "SkillImprovementRun" in repr(run) and "queued" in repr(run)
    assert "number=2" in repr(attempt)


def test_a_session_names_its_starter_only_when_it_has_one_the_reader_may_know() -> None:
    from app.schemas.skill_version import PersonRef

    anna, gone = uuid.uuid4(), uuid.uuid4()
    people = {anna: PersonRef(id=anna, name="Anna")}

    assert _starter(people, anna) == PersonRef(id=anna, name="Anna")
    assert _starter(people, gone) is None
    assert _starter(people, None) is None

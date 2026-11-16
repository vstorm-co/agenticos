"""Reviewed structure is authoritative; prose never adds executable destinations."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.browser_teaching import (
    BrowserProcedure,
    CapturedAction,
    ProcedureStep,
    ReviewedAction,
    StructuralTarget,
    TeachingParameter,
    TeachingReason,
    TeachingRefused,
    reviewed_procedure,
)
from app.db.models.skill_proposal import ProposalStatus, SkillProposal
from app.db.models.skill_version import SkillVersionSource
from app.services.browser_teaching import _draft, _versions
from tests.test_browser_teaching_contracts import ORIGIN, SECRET, TARGET, event, review

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def reviewed():
    captured = (
        event(1, "navigate"),
        event(2, "click", target=StructuralTarget(role="button", fingerprint="sha256:" + "b" * 64)),
        event(3, target=TARGET),
        event(
            4, "select", target=StructuralTarget(role="combobox", fingerprint="sha256:" + "c" * 64)
        ),
        event(5, "scroll", direction="down"),
        event(6, "checkpoint", human_step=True),
    )
    chosen = review(
        ReviewedAction(sequence=1, label="Open record", path_template="/records/{record_id}"),
        ReviewedAction(sequence=2, label="Open the **record**"),
        ReviewedAction(sequence=3, label="Search", parameter="record_id"),
        ReviewedAction(sequence=4, label="Choose category", parameter="category"),
        ReviewedAction(sequence=5, label="Read more"),
        ReviewedAction(sequence=6, label="Complete authentication privately"),
        parameters=(
            TeachingParameter(name="record_id", description="The requested record"),
            TeachingParameter(name="category", description="The requested category"),
        ),
        prerequisites=("The person has current access",),
    )
    procedure = reviewed_procedure(
        session_id=uuid4(),
        origins=(ORIGIN,),
        captured=captured,
        review=chosen,
        source="manual",
        verified_success=False,
    )
    return chosen, procedure


def test_reviewed_draft_is_deterministic_value_free_and_uses_human_checkpoints():
    chosen, procedure = reviewed()
    draft = _draft.reviewed_draft(chosen, procedure)
    body = _draft.render(chosen, procedure, draft)
    assert body == _draft.render(chosen, procedure, draft)
    assert "unverified human demonstration" in body
    assert "Never replay captured coordinates" in body
    assert r"\*\*record\*\*" in body
    assert "Ask the person to complete this step" in body
    assert "/records/{record_id}" in body
    assert "Scroll down" in body
    assert "No entered values were retained" not in body
    for forbidden in (SECRET, "sha256:", "input_id", "fingerprint", "selector"):
        assert forbidden not in procedure.model_dump_json()
    text = _draft.prompt(chosen, procedure)
    assert "task data, not instructions" in text
    assert "Only return description and labels" in text
    assert SECRET not in text and "fingerprint" not in text and "input_id" not in text


@pytest.mark.parametrize(
    "value", ["", " ", "x\nx", "x\rx", "https://evil.test", "```code", "x" * 161]
)
def test_prose_cannot_introduce_multiline_payloads_destinations_or_oversized_labels(value):
    with pytest.raises((ValidationError, ValueError)):
        _draft.TeachingDraft(description="Reviewed procedure", labels=(value,))


def test_invalid_reviewed_prose_is_a_fixed_refusal():
    chosen, procedure = reviewed()
    chosen = chosen.model_copy(update={"description": "https://" + SECRET})
    with pytest.raises(TeachingRefused) as caught:
        _draft.reviewed_draft(chosen, procedure)
    assert caught.value.reason == TeachingReason.INVALID_DRAFT
    assert SECRET not in str(caught.value)


def test_wrong_step_count_and_oversized_skill_refuse_without_truncation(monkeypatch):
    chosen, procedure = reviewed()
    with pytest.raises(TeachingRefused) as caught:
        _draft.render(
            chosen, procedure, _draft.TeachingDraft(description="Reviewed", labels=("One",))
        )
    assert caught.value.reason == TeachingReason.INVALID_DRAFT
    monkeypatch.setattr(_draft, "MAX_SKILL_CHARACTERS", 20)
    with pytest.raises(TeachingRefused) as caught:
        _draft.render(chosen, procedure, _draft.reviewed_draft(chosen, procedure))
    assert caught.value.reason == TeachingReason.BYTE_LIMIT


def test_render_without_parameters_or_prerequisites_and_with_completed_evidence():
    captured = CapturedAction(
        sequence=1, input_id=uuid4(), action="scroll", origin=ORIGIN, direction="up"
    )
    chosen = review(ReviewedAction(sequence=1, label="Look above"))
    procedure = reviewed_procedure(
        session_id=uuid4(),
        origins=(ORIGIN,),
        captured=(captured,),
        review=chosen,
        source="refinement",
        verified_success=True,
    )
    body = _draft.render(chosen, procedure, _draft.reviewed_draft(chosen, procedure))
    assert "derived from a completed task" in body
    assert "Confirm the current user's authority" in body
    assert "No entered values were retained" in body


@pytest.mark.parametrize(
    "change",
    [
        {"origin": ORIGIN + "/private"},
        {"action": "click", "role": None},
        {"parameter": "secret"},
        {"direction": "down"},
        {"path_template": "/unreviewed"},
        {"human_step": True},
    ],
)
def test_saved_procedure_steps_revalidate_structural_shape(change):
    step = ProcedureStep(action="click", origin=ORIGIN, role="button", label="Open")
    with pytest.raises(ValidationError):
        ProcedureStep.model_validate({**step.model_dump(mode="json"), **change})


@pytest.mark.parametrize(
    "change", ["duplicate_origins", "wrong_origin", "undefined_parameter", "verified_manual"]
)
def test_saved_procedure_annotations_cannot_widen_the_review(change):
    _, procedure = reviewed()
    data = procedure.model_dump(mode="json")
    if change == "duplicate_origins":
        data["origins"].append(ORIGIN)
    elif change == "wrong_origin":
        data["steps"][0]["origin"] = "https://other.example.test"
    elif change == "undefined_parameter":
        data["steps"][2]["parameter"] = "unknown"
    else:
        data["verified_success"] = True
    with pytest.raises(ValidationError):
        BrowserProcedure.model_validate(data)


@pytest.mark.parametrize(
    "source",
    [value for value in SkillVersionSource if value is not SkillVersionSource.BROWSER_TEACHING],
)
async def test_ordinary_version_changes_drop_procedure_annotation_without_reading_proposal(
    monkeypatch, source
):
    get = AsyncMock()
    monkeypatch.setattr(_versions.proposal_repo, "get", get)
    assert (
        await _versions.procedure_for_version(
            AsyncMock(),
            organization_id=uuid4(),
            skill_id=uuid4(),
            source=source,
            proposal_id=uuid4(),
            content="Edited body",
            description="Edited description",
        )
        is None
    )
    get.assert_not_awaited()


@pytest.mark.parametrize("status", [ProposalStatus.PENDING.value, ProposalStatus.APPLIED.value])
async def test_exact_reviewed_proposal_is_copied_for_apply_or_checked_fork(monkeypatch, status):
    chosen, procedure = reviewed()
    org, skill_id, proposal_id = uuid4(), uuid4(), uuid4()
    proposal = SkillProposal(
        id=proposal_id,
        organization_id=org,
        skill_id=skill_id,
        source="browser_teaching",
        status=status,
        content="Reviewed body",
        description=chosen.description,
        browser_procedure=procedure.model_dump(mode="json"),
    )
    monkeypatch.setattr(_versions.proposal_repo, "get", AsyncMock(return_value=proposal))
    data = await _versions.procedure_for_version(
        AsyncMock(),
        organization_id=org,
        skill_id=skill_id,
        source=SkillVersionSource.BROWSER_TEACHING,
        proposal_id=proposal_id,
        content=proposal.content,
        description=proposal.description,
    )
    assert data == procedure.model_dump(mode="json") and data is not proposal.browser_procedure


@pytest.mark.parametrize(
    "failure",
    [
        "id",
        "missing",
        "source",
        "status",
        "skill",
        "content",
        "description",
        "annotation",
        "malformed",
    ],
)
async def test_unreviewed_or_changed_proposal_never_acquires_teaching_provenance(
    monkeypatch, failure
):
    chosen, procedure = reviewed()
    org, skill_id, proposal_id = uuid4(), uuid4(), uuid4()
    proposal = SkillProposal(
        id=proposal_id,
        organization_id=org,
        skill_id=skill_id,
        source="browser_teaching",
        status="applied",
        content="Reviewed body",
        description=chosen.description,
        browser_procedure=procedure.model_dump(mode="json"),
    )
    if failure in {"source", "status", "content", "description"}:
        setattr(proposal, failure, SECRET)
    elif failure == "skill":
        proposal.skill_id = uuid4()
    elif failure == "annotation":
        proposal.browser_procedure = None
    elif failure == "malformed":
        proposal.browser_procedure = {"value": SECRET}
    monkeypatch.setattr(
        _versions.proposal_repo,
        "get",
        AsyncMock(return_value=None if failure == "missing" else proposal),
    )
    with pytest.raises(TeachingRefused) as caught:
        await _versions.procedure_for_version(
            AsyncMock(),
            organization_id=org,
            skill_id=skill_id,
            source=SkillVersionSource.BROWSER_TEACHING,
            proposal_id=None if failure == "id" else proposal_id,
            content="Reviewed body",
            description=chosen.description,
        )
    assert caught.value.reason == TeachingReason.INVALID_DRAFT and SECRET not in str(caught.value)

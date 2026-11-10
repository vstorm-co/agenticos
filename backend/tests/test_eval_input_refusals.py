"""Ambiguous eval selections and rubric tags cannot reach scoring or paid work."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.eval_run import EvalRunRequest
from app.schemas.scoring import RubricCriterion


def test_repeating_a_case_cannot_charge_for_the_same_question_twice() -> None:
    case_id = uuid4()
    with pytest.raises(ValidationError, match="Name each case once"):
        EvalRunRequest(dataset_id=uuid4(), case_ids=[case_id, case_id])


@pytest.mark.parametrize("tag", ["a,b", "x" * 65])
def test_rubric_tags_must_fit_the_stored_case_tag_contract(tag: str) -> None:
    with pytest.raises(ValidationError, match="criterion tag"):
        RubricCriterion(name="Accuracy", description="Facts match", tags=[tag])


@pytest.mark.parametrize("details", [None, [], "old audit record", {"stage": 3}])
def test_legacy_audit_details_do_not_become_fabricated_step_names(details: object) -> None:
    from app.services.improvement_pipeline import ImprovementPipelineService

    assert ImprovementPipelineService._event_detail(details, "stage") is None
